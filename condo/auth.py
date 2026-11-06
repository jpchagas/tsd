"""Login. Two sources of users:

1. .streamlit/secrets.toml, for the síndico (and any other fixed account):

    [auth.users.sindico]
    name = "Síndico"
    role = "admin"            # can upload statements and approve residents
    password_hash = "pbkdf2_sha256$..."   # python -m condo.passwords

2. The account store (condo/accounts.py): residents who signed up and were
   approved by the síndico. They always get role "morador".
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from condo import accounts
from condo.data import get_account_store
from condo.passwords import verify_password

ROLE_ADMIN = "admin"
ROLE_RESIDENT = "morador"
_SESSION_KEY = "user"
WRONG = "Usuário ou senha incorretos."


@dataclass(frozen=True)
class User:
    username: str
    name: str
    role: str
    unidade: str | None = None  # e.g. "Ap 102"; None for the síndico

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def _configured_users() -> dict:
    try:
        return dict(st.secrets["auth"]["users"])
    except (KeyError, FileNotFoundError):
        return {}


def authenticate(username: str, password: str) -> tuple[User | None, str | None]:
    """(user, None) on success, else (None, message to show)."""
    login = username.strip().lower()
    entry = _configured_users().get(login)
    if entry:
        if not verify_password(password, entry.get("password_hash", "")):
            return None, WRONG
        return User(
            username=login,
            name=entry.get("name", login),
            role=entry.get("role", ROLE_RESIDENT),
            unidade=entry.get("unidade"),
        ), None

    doc, _ = get_account_store().load()
    found, message = accounts.check_login(doc, login, password)
    if not found:
        return None, message
    return User(username=login, name=found["name"], role=ROLE_RESIDENT, unidade=found["unidade"]), None


def current_user() -> User | None:
    return st.session_state.get(_SESSION_KEY)


def sign_in(user: User) -> None:
    st.session_state[_SESSION_KEY] = user


def logout() -> None:
    st.session_state.pop(_SESSION_KEY, None)


def require_admin() -> User:
    """Guard for admin-only pages, in addition to hiding them from navigation."""
    user = current_user()
    if user is None or not user.is_admin:
        st.error("Esta página é restrita ao síndico.")
        st.stop()
    return user
