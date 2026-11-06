"""Cached access to storage and the dataset for the Streamlit pages."""
from __future__ import annotations

from io import BytesIO

import streamlit as st

from condo import accounts, categories, loader, storage

ACCOUNT_LABELS = {
    "PRI": "Conta principal (dia a dia)",
    "FO": "Fundo de obras",
    "FR": "Fundo de reserva",
}


@st.cache_resource
def get_storage() -> storage.Storage:
    try:
        config = st.secrets.get("storage")
    except FileNotFoundError:  # no secrets file at all
        config = None
    return storage.from_config(config)


@st.cache_data(ttl=60, show_spinner=False)
def _signature() -> tuple:
    # File mtimes, rechecked at most once a minute (picks up files copied into docs/
    # by hand); an upload clears the cache and is visible immediately.
    return get_storage().signature()


@st.cache_data(show_spinner="Carregando extratos…")
def _load(signature: tuple) -> loader.Dataset:
    store = get_storage()
    return loader.load_all(BytesIO(store.read(name)) for name in store.names())


def get_dataset() -> loader.Dataset:
    return _load(_signature())


@st.cache_data(show_spinner=False)
def _category_map(version: str | None) -> dict[str, str]:
    data, _ = get_storage().read_doc(categories.DOC_NAME)
    return categories.merged(categories.mapping_from_xlsx(data) if data else {})


def get_category_map() -> dict[str, str]:
    """Expense code -> category: defaults plus the síndico's edits. Keyed on the
    file's content hash, so a save (or a hand edit of the file) shows up at once."""
    return _category_map(get_storage().read_doc(categories.DOC_NAME)[1])


def save_category_map(mapping: dict[str, str], author: str) -> None:
    store = get_storage()
    _, version = store.read_doc(categories.DOC_NAME)  # last save wins: only the síndico edits
    store.write_doc(categories.DOC_NAME, categories.mapping_to_xlsx(mapping), version,
                    message=f"Categorias alteradas por {author}")


def get_account_store() -> accounts.AccountStore:
    # Not cached: approvals and new signups must be visible immediately.
    return accounts.AccountStore(get_storage())


def known_units() -> list[str]:
    """Units seen in the statements, plus `[condo] extra_units` from the secrets
    (for a unit that never appears in a statement, e.g. ["Ap 22"])."""
    try:
        extra = list(st.secrets.get("condo", {}).get("extra_units", []))
    except FileNotFoundError:
        extra = []
    found = accounts.units_in(get_dataset().transactions["descricao"]) if get_dataset().months else []
    return accounts.sort_units([*found, *extra])


def save_statements(items: list[tuple[bytes, loader.Statement]], author: str) -> None:
    store = get_storage()
    for data, stmt in items:
        store.save(storage.filename_for(stmt.month), data, author=author)
    st.cache_data.clear()


def brl(value: float) -> str:
    """Format as Brazilian currency: R$ 1.234,56"""
    text = f"{abs(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"-R$ {text}" if value < 0 else f"R$ {text}"


def month_label(month) -> str:
    names = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return f"{names[month.month - 1]}/{month.year}"


def brl_signed(value: float) -> str:
    """Change amounts: always signed, e.g. +R$ 1.234,56 / -R$ 80,00."""
    return brl(value) if value < 0 else "+" + brl(value)


def pct(value: float) -> str:
    return f"{value * 100:.0f}%".replace(".", ",")


def month_short(month) -> str:
    return month_label(month)[:4] + str(month.year)[2:]


def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:
        return "light"


def brl_compact(value: float) -> str:
    """Short label for chart annotations: R$ 226,7 mil (full value below 1.000)."""
    if abs(value) < 1000:
        return brl(value)
    sign = "-" if value < 0 else ""
    return f"{sign}R$ {abs(value) / 1000:.1f} mil".replace(".", ",")
