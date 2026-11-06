from condo.passwords import hash_password, verify_password


def test_roundtrip():
    stored = hash_password("segredo", iterations=1000)
    assert verify_password("segredo", stored)
    assert not verify_password("errado", stored)


def test_salted():
    assert hash_password("x", iterations=1000) != hash_password("x", iterations=1000)


def test_malformed_hash_is_rejected():
    assert not verify_password("x", "")
    assert not verify_password("x", "pbkdf2_sha256$abc$!!$!!")
    assert not verify_password("x", "md5$1$a$b")
