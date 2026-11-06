"""Where the data lives. Everything is an .xlsx file: one statement workbook per
month, saved under a canonical name so re-uploading a month replaces it, plus the
accounts (usuarios.xlsx) and category (categorias.xlsx) workbooks.

Two backends with the same interface:
- LocalStorage: a folder (docs/ by default, gitignored). For development.
- SupabaseStorage: rows of a table in a Supabase Postgres database, for hosts whose
  disk is wiped on restart (Render's free plan). A table rather than Supabase
  Storage buckets because buckets have no conditional writes and the free plan's
  CDN can serve a stale copy after an overwrite.
"""
from __future__ import annotations

import base64
import hashlib
import os
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Protocol

import pandas as pd
import requests

ACCOUNT_ID = "01487"
PREFIX = f"extrato_{ACCOUNT_ID}_"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def filename_for(month: pd.Period) -> str:
    start = month.start_time.date()
    end = (month + 1).start_time.date()
    return f"{PREFIX}{start}_{end}.xlsx"


class ConflictError(RuntimeError):
    """The document changed since it was read; re-read and try again."""


class Storage(Protocol):
    def names(self) -> list[str]: ...
    def signature(self) -> tuple: ...  # changes whenever any file is added or replaced
    def read(self, name: str) -> bytes: ...
    def save(self, name: str, data: bytes, author: str) -> None: ...
    # Small documents (e.g. accounts) with optimistic concurrency: write_doc raises
    # ConflictError if the stored version is no longer `version` (None = must not exist).
    def read_doc(self, name: str) -> tuple[bytes | None, str | None]: ...
    def write_doc(self, name: str, data: bytes, version: str | None, message: str) -> None: ...


_WRITE_LOCK = threading.Lock()


class LocalStorage:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def names(self) -> list[str]:
        return sorted(p.name for p in self.directory.glob(f"{PREFIX}*.xlsx"))

    def signature(self) -> tuple:
        return tuple((n, (self.directory / n).stat().st_mtime) for n in self.names())

    def read(self, name: str) -> bytes:
        return (self.directory / name).read_bytes()

    def save(self, name: str, data: bytes, author: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / name
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)  # atomic: readers never see a half-written file

    def read_doc(self, name: str) -> tuple[bytes | None, str | None]:
        path = self.directory / name
        if not path.exists():
            return None, None
        data = path.read_bytes()
        return data, hashlib.sha256(data).hexdigest()

    def write_doc(self, name: str, data: bytes, version: str | None, message: str) -> None:
        with _WRITE_LOCK:  # Streamlit sessions are threads of one process
            if self.read_doc(name)[1] != version:
                raise ConflictError(name)
            self.save(name, data, author=message)


class SupabaseStorage:
    """Files as rows of one table, through Supabase's REST API (PostgREST). Table
    (SQL in the README): nome (primary key), conteudo (base64), versao, atualizado_em,
    atualizado_por. Writes are conditional on `versao`, so concurrent saves never
    silently overwrite each other."""

    def __init__(self, url: str, key: str, table: str = "arquivos"):
        self.endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
        self.session = requests.Session()
        self.session.headers["apikey"] = key
        if key.startswith("eyJ"):  # legacy service_role JWT; new sb_secret_ keys go in apikey only
            self.session.headers["Authorization"] = f"Bearer {key}"

    def _rows(self, **params) -> list[dict]:
        r = self.session.get(self.endpoint, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _versions(self) -> dict[str, int]:
        return {row["nome"]: row["versao"] for row in self._rows(select="nome,versao")}

    def names(self) -> list[str]:
        return sorted(n for n in self._versions() if n.startswith(PREFIX) and n.endswith(".xlsx"))

    def signature(self) -> tuple:
        return tuple(sorted((n, v) for n, v in self._versions().items() if n.startswith(PREFIX)))

    def read(self, name: str) -> bytes:
        data, _ = self.read_doc(name)
        if data is None:
            raise FileNotFoundError(name)
        return data

    def save(self, name: str, data: bytes, author: str) -> None:
        for _ in range(3):  # unconditional replace = conditional write on the current version
            try:
                return self.write_doc(name, data, self.read_doc(name)[1], f"Enviado por {author}")
            except ConflictError:
                continue
        raise ConflictError(name)

    def read_doc(self, name: str) -> tuple[bytes | None, str | None]:
        rows = self._rows(select="conteudo,versao", nome=f"eq.{name}")
        if not rows:
            return None, None
        return base64.b64decode(rows[0]["conteudo"]), str(rows[0]["versao"])

    def write_doc(self, name: str, data: bytes, version: str | None, message: str) -> None:
        body = {
            "conteudo": base64.b64encode(data).decode(),
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "atualizado_por": message,
        }
        if version is None:  # must not exist yet: a duplicate primary key is a 409
            r = self.session.post(self.endpoint, json={"nome": name, "versao": 1, **body},
                                  headers={"Prefer": "return=minimal"}, timeout=30)
            if r.status_code == 409:
                raise ConflictError(name)
            r.raise_for_status()
            return
        r = self.session.patch(
            self.endpoint,
            params={"nome": f"eq.{name}", "versao": f"eq.{version}", "select": "nome"},
            json={**body, "versao": int(version) + 1},
            headers={"Prefer": "return=representation"},
            timeout=30,
        )
        r.raise_for_status()
        if not r.json():  # no row matched: someone else saved since we read
            raise ConflictError(name)


def from_config(config: dict | None) -> Storage:
    """Build the storage from the optional [storage] secrets table. Without
    `backend = "supabase"` it is the local folder: `directory`, else
    CONDO_DATA_DIR, else docs/."""
    config = dict(config or {})
    backend = config.get("backend", "local")
    if backend == "supabase":
        return SupabaseStorage(url=config["url"], key=config["key"], table=config.get("table", "arquivos"))
    if backend == "local":
        default = os.environ.get("CONDO_DATA_DIR", PROJECT_ROOT / "docs")
        return LocalStorage(Path(config.get("directory", default)))
    raise ValueError(f"Unknown storage backend: {backend!r}")
