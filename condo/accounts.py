"""Resident accounts: signup, password reset and síndico approval.

One account per unit; the login is derived from the unit ("Ap 102" -> "ap102").
Everything here works on a plain dict so it is testable; the AccountStore at the
bottom loads/saves it as an .xlsx workbook (one row per account / reset request)
through the storage backend.

Document shape:
    {"users": {login: {name, unidade, phone, password_hash, status, created_at,
                       approved_at?, approved_by?}},
     "resets": {login: {password_hash, code, requested_at}}}
status is "pending" (awaiting the síndico) or "active". Rejected signups are deleted.
"""
from __future__ import annotations

from io import BytesIO
import re
import secrets
from datetime import datetime
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from condo.passwords import hash_password, verify_password

PENDING = "pending"
ACTIVE = "active"
MIN_PASSWORD = 8
DOC_NAME = "usuarios.xlsx"
TZ = ZoneInfo("America/Sao_Paulo")
UNIT_RE = re.compile(r"\b(Ap|Lj Loja) (\d+)\b")


class AccountError(ValueError):
    """A user-facing validation error (message in Portuguese)."""


# --- Units -----------------------------------------------------------------
def units_in(descriptions: Iterable[str]) -> list[str]:
    """Units as written in the statements, e.g. 'Ap 01', 'Lj Loja 174'."""
    found = {f"{m.group(1)} {m.group(2)}" for d in descriptions for m in UNIT_RE.finditer(d)}
    return sort_units(found)


def sort_units(units: Iterable[str]) -> list[str]:
    return sorted(set(units), key=lambda u: (not u.startswith("Ap "), int(u.split()[-1])))


def username_for(unit: str) -> str:
    kind, number = unit.rsplit(" ", 1)
    return ("ap" if kind == "Ap" else "loja") + number


def display_name(unit: str) -> str:
    return unit.replace("Lj Loja", "Loja")


# --- Validation ------------------------------------------------------------
def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) not in (10, 11):
        raise AccountError("Informe o telefone com DDD, por exemplo (51) 99999-9999.")
    return digits


def format_phone(digits: str) -> str:
    return f"({digits[:2]}) {digits[2:-4]}-{digits[-4:]}"


def _check_password(password: str, confirm: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres.")
    if password != confirm:
        raise AccountError("As senhas não conferem.")


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="minutes")


def empty_doc() -> dict:
    return {"users": {}, "resets": {}}


# --- Operations on the document --------------------------------------------
def signup(doc: dict, unit: str, name: str, phone: str, password: str, confirm: str,
           known_units: Iterable[str]) -> str:
    """Create a pending account; returns the login."""
    if unit not in set(known_units):
        raise AccountError("Escolha uma unidade da lista.")
    name = " ".join(name.split())
    if len(name) < 3:
        raise AccountError("Informe seu nome.")
    phone = normalize_phone(phone)
    _check_password(password, confirm)

    login = username_for(unit)
    existing = doc["users"].get(login)
    if existing and existing["status"] == ACTIVE:
        raise AccountError(
            f"O {display_name(unit)} já tem cadastro. Se você esqueceu a senha, use "
            "“Esqueci minha senha”. Se não foi você quem se cadastrou, fale com o síndico."
        )
    if existing and existing["status"] == PENDING:
        raise AccountError(
            f"Já existe um cadastro do {display_name(unit)} aguardando aprovação do síndico."
        )
    doc["users"][login] = {
        "name": name,
        "unidade": unit,
        "phone": phone,
        "password_hash": hash_password(password),
        "status": PENDING,
        "created_at": _now(),
    }
    return login


def request_reset(doc: dict, login: str, password: str, confirm: str) -> str:
    """Store the new password until the síndico approves; returns the code the
    resident must tell the síndico when contacted at the phone on file."""
    user = doc["users"].get(login)
    if not user or user["status"] != ACTIVE:
        raise AccountError("Não encontramos um cadastro aprovado para essa unidade.")
    _check_password(password, confirm)
    code = f"{secrets.randbelow(10**6):06d}"
    doc["resets"][login] = {
        "password_hash": hash_password(password),
        "code": code,
        "requested_at": _now(),
    }
    return code


def approve_signup(doc: dict, login: str, by: str) -> None:
    user = doc["users"].get(login)
    if not user or user["status"] != PENDING:
        raise AccountError("Esse cadastro não está mais pendente.")
    user.update(status=ACTIVE, approved_at=_now(), approved_by=by)


def reject_signup(doc: dict, login: str) -> None:
    user = doc["users"].get(login)
    if user and user["status"] == PENDING:
        del doc["users"][login]


def approve_reset(doc: dict, login: str, by: str) -> None:
    request = doc["resets"].pop(login, None)
    user = doc["users"].get(login)
    if not request or not user:
        raise AccountError("Esse pedido não está mais pendente.")
    user.update(password_hash=request["password_hash"], password_changed_at=_now(),
                password_changed_by=by)


def reject_reset(doc: dict, login: str) -> None:
    doc["resets"].pop(login, None)


def remove_access(doc: dict, login: str) -> None:
    """E.g. the resident moved out; the unit can sign up again afterwards."""
    doc["users"].pop(login, None)
    doc["resets"].pop(login, None)


def check_login(doc: dict, login: str, password: str) -> tuple[dict | None, str | None]:
    """(user, None) on success, else (None, message)."""
    user = doc["users"].get(login)
    if not user or not verify_password(password, user["password_hash"]):
        return None, "Usuário ou senha incorretos."
    if user["status"] != ACTIVE:
        return None, "Seu cadastro ainda está aguardando a aprovação do síndico."
    return user, None


# --- Persistence -------------------------------------------------------------
# Workbook layout: sheet -> (doc key, columns). The first column is the login.
SHEETS = {
    "usuarios": ("users", ["login", "unidade", "name", "phone", "status", "created_at",
                           "approved_at", "approved_by", "password_hash"]),
    "pedidos_senha": ("resets", ["login", "code", "requested_at", "password_hash"]),
}


def to_xlsx(doc: dict) -> bytes:
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for sheet, (key, columns) in SHEETS.items():
            rows = [{"login": login, **fields} for login, fields in sorted(doc[key].items())]
            pd.DataFrame(rows, columns=columns).to_excel(writer, sheet_name=sheet, index=False)
    return out.getvalue()


def from_xlsx(data: bytes) -> dict:
    # dtype=str keeps phones and codes as text (no lost leading zeros).
    frames = pd.read_excel(BytesIO(data), sheet_name=None, dtype=str)
    doc = empty_doc()
    for sheet, (key, columns) in SHEETS.items():
        frame = frames.get(sheet, pd.DataFrame(columns=columns)).fillna("")
        for row in frame.to_dict("records"):
            login = row.pop("login")
            doc[key][login] = {k: v for k, v in row.items() if v != ""}  # blank = absent
    return doc


class AccountStore:
    """Loads/saves the document through a storage backend with optimistic
    concurrency: if someone else saved in between, re-read and re-apply."""

    def __init__(self, backend):
        self.backend = backend

    def load(self) -> tuple[dict, str | None]:
        data, version = self.backend.read_doc(DOC_NAME)
        return (from_xlsx(data) if data else empty_doc()), version

    def update(self, change: Callable[[dict], object], message: str):
        from condo.storage import ConflictError

        for _ in range(3):
            doc, version = self.load()
            result = change(doc)  # AccountError propagates: nothing is saved
            data = to_xlsx(doc)
            try:
                self.backend.write_doc(DOC_NAME, data, version, message)
                return result
            except ConflictError:
                continue
        raise AccountError("O sistema está ocupado. Tente novamente em instantes.")
