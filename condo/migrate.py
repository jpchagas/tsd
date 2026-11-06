"""Copy the local docs/ files to the storage configured in .streamlit/secrets.toml.

    poetry run python -m condo.migrate

Uploads every statement plus usuarios.xlsx and categorias.xlsx. Files that already
exist in the destination are left alone, so it is safe to run more than once.
"""
from __future__ import annotations

import sys

import toml

from condo import accounts, categories, storage

SECRETS = storage.PROJECT_ROOT / ".streamlit" / "secrets.toml"


def main() -> None:
    config = toml.load(SECRETS).get("storage", {}) if SECRETS.exists() else {}
    destination = storage.from_config(config)
    if isinstance(destination, storage.LocalStorage):
        sys.exit("Configure [storage] backend = \"supabase\" in .streamlit/secrets.toml first.")
    source = storage.LocalStorage(storage.PROJECT_ROOT / "docs")
    names = source.names() + [n for n in (accounts.DOC_NAME, categories.DOC_NAME) if source.read_doc(n)[0]]
    for name in names:
        try:
            destination.write_doc(name, source.read_doc(name)[0], None, "Migração inicial")
        except storage.ConflictError:
            print(f"já existe, mantido: {name}")
        else:
            print(f"enviado: {name}")


if __name__ == "__main__":
    main()
