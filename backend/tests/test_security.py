import pytest

from app.core.security import hash_password, hash_token, needs_rehash, new_session_token, verify_password


def test_password_roundtrip_and_uniqueness():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2  # salted
    assert verify_password("correct horse battery", h1)
    assert not verify_password("Correct horse battery", h1)
    assert not verify_password("", h1)


def test_verify_handles_missing_or_corrupt_hash():
    assert not verify_password("anything", None)
    assert not verify_password("anything", "")
    assert not verify_password("anything", "garbage")
    assert not verify_password("anything", "md5$1$a$b")


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("short")


def test_needs_rehash_detects_weak_iterations():
    assert needs_rehash("pbkdf2_sha256$1000$c2FsdA==$aGFzaA==")
    assert not needs_rehash(hash_password("a-long-enough-password"))
    assert needs_rehash(None)


def test_session_tokens_are_random_and_hashed():
    a, b = new_session_token(), new_session_token()
    assert a != b and len(a) > 30
    assert hash_token(a) == hash_token(a) and hash_token(a) != hash_token(b)
    assert a not in hash_token(a)  # the raw token is never recoverable from storage
