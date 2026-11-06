import pandas as pd
import pytest

from condo import accounts, storage

UNITS = ["Ap 01", "Ap 102", "Lj Loja 174"]


@pytest.fixture(autouse=True)
def fast_hash(monkeypatch):
    # Real PBKDF2 takes ~0.4s per hash; use few iterations in tests (still a real hash).
    from condo import passwords

    monkeypatch.setattr(accounts, "hash_password", lambda pw: passwords.hash_password(pw, iterations=1000))


def _signup(doc, unit="Ap 102", password="segredo123"):
    return accounts.signup(doc, unit, "Maria Silva", "(51) 99999-8888", password, password, UNITS)


# --- units -----------------------------------------------------------------
def test_units_in_descriptions():
    descs = [
        "Condominio Ap 102 (principal)-10/2026",
        "Multa Ap 13 (principal)-08/2026",
        "Fundo Lj Loja 174 (principal)-fundo De Reserva-10/2026",
        "Condominio Ap 01 (principal)-10/2026",
        "Energia Eletrica Nr. Doc: 4520653 10/2026 Ceee Equatorial",
    ]
    assert accounts.units_in(descs) == ["Ap 01", "Ap 13", "Ap 102", "Lj Loja 174"]


@pytest.mark.parametrize(
    "unit, login, name",
    [("Ap 01", "ap01", "Ap 01"), ("Ap 102", "ap102", "Ap 102"), ("Lj Loja 174", "loja174", "Loja 174")],
)
def test_naming(unit, login, name):
    assert accounts.username_for(unit) == login
    assert accounts.display_name(unit) == name


@pytest.mark.parametrize("raw", ["(51) 99999-8888", "51999998888", "+55 51 99999-8888"])
def test_phone_normalized(raw):
    assert accounts.normalize_phone(raw) == "51999998888"
    assert accounts.format_phone("51999998888") == "(51) 99999-8888"


def test_phone_without_area_code_rejected():
    with pytest.raises(accounts.AccountError):
        accounts.normalize_phone("99999-8888")


# --- signup & approval -------------------------------------------------------
def test_signup_is_pending_until_approved():
    doc = accounts.empty_doc()
    assert _signup(doc) == "ap102"

    user, msg = accounts.check_login(doc, "ap102", "segredo123")
    assert user is None and "aguardando" in msg

    accounts.approve_signup(doc, "ap102", by="Síndico")
    user, msg = accounts.check_login(doc, "ap102", "segredo123")
    assert msg is None and user["unidade"] == "Ap 102" and user["approved_by"] == "Síndico"


def test_pending_status_not_revealed_with_wrong_password():
    doc = accounts.empty_doc()
    _signup(doc)
    assert accounts.check_login(doc, "ap102", "errada123") == (None, "Usuário ou senha incorretos.")


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        (dict(unit="Ap 999"), "unidade"),
        (dict(name=" "), "nome"),
        (dict(phone="123"), "DDD"),
        (dict(password="curta", confirm="curta"), "8 caracteres"),
        (dict(confirm="outra-senha"), "não conferem"),
    ],
)
def test_signup_validation(kwargs, fragment):
    args = dict(unit="Ap 102", name="Maria", phone="51999998888", password="segredo123", confirm="segredo123")
    args.update(kwargs)
    doc = accounts.empty_doc()
    with pytest.raises(accounts.AccountError, match=fragment):
        accounts.signup(doc, known_units=UNITS, **args)
    assert doc["users"] == {}


def test_one_account_per_unit():
    doc = accounts.empty_doc()
    _signup(doc)
    with pytest.raises(accounts.AccountError, match="aguardando"):
        _signup(doc)
    accounts.approve_signup(doc, "ap102", by="Síndico")
    with pytest.raises(accounts.AccountError, match="já tem cadastro"):
        _signup(doc)


def test_rejected_signup_frees_the_unit():
    doc = accounts.empty_doc()
    _signup(doc)
    accounts.reject_signup(doc, "ap102")
    assert doc["users"] == {}
    _signup(doc)  # can try again


# --- password reset ----------------------------------------------------------
def test_reset_needs_approval_and_keeps_old_password_meanwhile():
    doc = accounts.empty_doc()
    _signup(doc)
    accounts.approve_signup(doc, "ap102", by="Síndico")

    code = accounts.request_reset(doc, "ap102", "nova-senha-1", "nova-senha-1")
    assert len(code) == 6 and code.isdigit()
    assert accounts.check_login(doc, "ap102", "segredo123")[0] is not None
    assert accounts.check_login(doc, "ap102", "nova-senha-1")[0] is None

    accounts.approve_reset(doc, "ap102", by="Síndico")
    assert accounts.check_login(doc, "ap102", "nova-senha-1")[0] is not None
    assert accounts.check_login(doc, "ap102", "segredo123")[0] is None
    assert doc["resets"] == {}


def test_rejected_reset_keeps_old_password():
    doc = accounts.empty_doc()
    _signup(doc)
    accounts.approve_signup(doc, "ap102", by="Síndico")
    accounts.request_reset(doc, "ap102", "nova-senha-1", "nova-senha-1")
    accounts.reject_reset(doc, "ap102")
    assert accounts.check_login(doc, "ap102", "segredo123")[0] is not None


def test_reset_only_for_approved_accounts():
    doc = accounts.empty_doc()
    with pytest.raises(accounts.AccountError):
        accounts.request_reset(doc, "ap102", "nova-senha-1", "nova-senha-1")
    _signup(doc)  # pending
    with pytest.raises(accounts.AccountError):
        accounts.request_reset(doc, "ap102", "nova-senha-1", "nova-senha-1")


def test_remove_access():
    doc = accounts.empty_doc()
    _signup(doc)
    accounts.approve_signup(doc, "ap102", by="Síndico")
    accounts.request_reset(doc, "ap102", "nova-senha-1", "nova-senha-1")
    accounts.remove_access(doc, "ap102")
    assert doc == accounts.empty_doc()


# --- persistence -------------------------------------------------------------
def test_store_roundtrip_with_local_storage(tmp_path):
    store = accounts.AccountStore(storage.LocalStorage(tmp_path))
    assert store.load()[0] == accounts.empty_doc()
    store.update(_signup, "signup")
    store.update(lambda d: accounts.approve_signup(d, "ap102", "Síndico"), "approve")
    doc, _ = store.load()
    assert doc["users"]["ap102"]["status"] == accounts.ACTIVE
    assert doc["users"]["ap102"]["name"] == "Maria Silva"
    sheets = pd.read_excel(tmp_path / accounts.DOC_NAME, sheet_name=None)
    assert set(sheets) == {"usuarios", "pedidos_senha"}


def test_xlsx_roundtrip_keeps_text_fields():
    doc = accounts.empty_doc()
    _signup(doc)
    accounts.approve_signup(doc, "ap102", by="Síndico")
    _signup(doc, unit="Ap 01")  # pending: no approved_* fields
    accounts.request_reset(doc, "ap102", "nova-senha-1", "nova-senha-1")
    doc["resets"]["ap102"]["code"] = "012345"  # leading zero must survive
    assert accounts.from_xlsx(accounts.to_xlsx(doc)) == doc


def test_validation_error_saves_nothing(tmp_path):
    store = accounts.AccountStore(storage.LocalStorage(tmp_path))
    with pytest.raises(accounts.AccountError):
        store.update(lambda d: _signup(d, unit="Ap 999"), "signup")
    assert not (tmp_path / accounts.DOC_NAME).exists()


def test_concurrent_change_is_retried_not_lost(tmp_path):
    backend = storage.LocalStorage(tmp_path)
    store = accounts.AccountStore(backend)
    store.update(_signup, "first")

    calls = {"n": 0}

    def change(doc):
        calls["n"] += 1
        if calls["n"] == 1:
            # Someone else saves between our read and our write.
            accounts.AccountStore(backend).update(lambda d: _signup(d, unit="Ap 01"), "other")
        accounts.approve_signup(doc, "ap102", "Síndico")

    store.update(change, "approve")
    doc, _ = store.load()
    assert calls["n"] == 2
    assert set(doc["users"]) == {"ap102", "ap01"}  # the other save survived
    assert doc["users"]["ap102"]["status"] == accounts.ACTIVE
