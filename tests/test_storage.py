from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from condo import loader, storage

DOCS = Path(__file__).resolve().parent.parent / "docs"
OCT = "extrato_01487_2026-10-01_2026-11-01.xlsx"


def test_filename_for_matches_existing_files():
    assert storage.filename_for(pd.Period("2026-10", "M")) == OCT
    assert storage.filename_for(pd.Period("2026-12", "M")).endswith("2026-12-01_2027-01-01.xlsx")


def test_local_save_read_and_signature(tmp_path):
    store = storage.LocalStorage(tmp_path)
    before = store.signature()
    store.save(OCT, (DOCS / OCT).read_bytes(), author="Síndico")

    assert store.names() == [OCT]
    assert store.signature() != before
    assert loader.load_statement(BytesIO(store.read(OCT))).month == pd.Period("2026-10", "M")
    assert not list(tmp_path.glob("*.tmp"))


def test_from_config_defaults_to_local_docs():
    store = storage.from_config(None)
    assert isinstance(store, storage.LocalStorage)
    assert OCT in store.names()


def test_from_config_directory(tmp_path):
    store = storage.from_config({"directory": str(tmp_path)})
    assert store.directory == tmp_path


def test_local_doc_versioning(tmp_path):
    store = storage.LocalStorage(tmp_path)
    assert store.read_doc("u.json") == (None, None)
    store.write_doc("u.json", b"1", None, "create")
    data, v1 = store.read_doc("u.json")
    assert data == b"1"
    with pytest.raises(storage.ConflictError):
        store.write_doc("u.json", b"2", None, "create again")  # already exists
    store.write_doc("u.json", b"2", v1, "update")
    with pytest.raises(storage.ConflictError):
        store.write_doc("u.json", b"3", v1, "stale")  # v1 is outdated


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture
def supabase(monkeypatch):
    """In-memory stand-in for the PostgREST endpoints SupabaseStorage uses."""
    store = storage.from_config({"backend": "supabase", "url": "https://x.supabase.co/", "key": "sb_secret_k"})
    rows = {}  # nome -> row

    def match(params):
        def ok(row):
            return all(str(row[k]) == v[3:] for k, v in params.items() if k != "select")
        return [r for r in rows.values() if ok(r)]

    def pick(row, params):
        return {k: row[k] for k in params["select"].split(",")}

    def get(url, params=None, timeout=None):
        assert url == "https://x.supabase.co/rest/v1/arquivos"
        return FakeResponse(payload=[pick(r, params) for r in match(params)])

    def post(url, json=None, headers=None, timeout=None):
        if json["nome"] in rows:
            return FakeResponse(409)
        rows[json["nome"]] = dict(json)
        return FakeResponse(201)

    def patch(url, params=None, json=None, headers=None, timeout=None):
        hits = match(params)
        for row in hits:
            row.update(json)
        return FakeResponse(payload=[pick(r, params) for r in hits])

    for name, fn in [("get", get), ("post", post), ("patch", patch)]:
        monkeypatch.setattr(store.session, name, fn)
    return store, rows


def test_supabase_uses_secret_key_header_only():
    store = storage.from_config({"backend": "supabase", "url": "https://x.supabase.co", "key": "sb_secret_k"})
    assert store.session.headers["apikey"] == "sb_secret_k"
    assert "Authorization" not in store.session.headers
    legacy = storage.SupabaseStorage("https://x.supabase.co", "eyJhbGci.legacy")
    assert legacy.session.headers["Authorization"] == "Bearer eyJhbGci.legacy"


def test_supabase_statements_roundtrip_and_replace(supabase):
    store, rows = supabase
    data = (DOCS / OCT).read_bytes()
    assert store.names() == [] and store.signature() == ()

    store.save(OCT, data, author="Síndico")
    store.write_doc("usuarios.xlsx", b"x", None, "conta")  # not a statement
    first = store.signature()
    assert store.names() == [OCT]
    assert loader.load_statement(BytesIO(store.read(OCT))).month == pd.Period("2026-10", "M")

    store.save(OCT, data, author="Síndico")  # replace bumps the version
    assert store.signature() != first
    assert rows[OCT]["versao"] == 2 and "Síndico" in rows[OCT]["atualizado_por"]


def test_supabase_doc_conflicts(supabase):
    store, _ = supabase
    assert store.read_doc("u.xlsx") == (None, None)
    store.write_doc("u.xlsx", b"1", None, "create")
    with pytest.raises(storage.ConflictError):
        store.write_doc("u.xlsx", b"2", None, "create again")
    _, v1 = store.read_doc("u.xlsx")
    store.write_doc("u.xlsx", b"2", v1, "update")
    with pytest.raises(storage.ConflictError):
        store.write_doc("u.xlsx", b"3", v1, "stale")
    assert store.read_doc("u.xlsx")[0] == b"2"


def test_account_store_on_supabase(supabase, monkeypatch):
    from condo import accounts, passwords

    monkeypatch.setattr(accounts, "hash_password", lambda pw: passwords.hash_password(pw, iterations=1000))
    store = accounts.AccountStore(supabase[0])
    store.update(lambda d: accounts.signup(d, "Ap 102", "Maria", "51999998888", "segredo123", "segredo123", ["Ap 102"]), "signup")
    store.update(lambda d: accounts.approve_signup(d, "ap102", "Síndico"), "approve")
    assert store.load()[0]["users"]["ap102"]["status"] == accounts.ACTIVE
