import pytest

from qrlabel.domain.errors import ValidationError
from qrlabel.services.admin_auth import (
    DEFAULT_ADMIN_HASH,
    LOCKOUT_SECONDS,
    MAX_FAILURES,
    AdminAuth,
    hash_password,
    verify_password,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(config=None, clock=None):
    cfg = config if config is not None else {"admin": {"password_hash": hash_password("Correct-Horse-1")}}
    saved = []
    return AdminAuth(lambda: cfg, lambda: saved.append(True), clock or Clock()), cfg, saved


def test_hash_roundtrip_and_salt():
    a, b = hash_password("secret-123"), hash_password("secret-123")
    assert a != b  # random salt
    assert verify_password("secret-123", a) and not verify_password("secret-124", a)
    assert not verify_password("x", "garbage") and not verify_password("x", "md5$1$a$b")


def test_default_hash_is_well_formed():
    algo, iterations, salt, digest = DEFAULT_ADMIN_HASH.split("$")
    assert algo == "pbkdf2_sha256" and int(iterations) >= 100_000 and salt and digest


def test_empty_config_uses_default_hash():
    auth, _, _ = make(config={"admin": {"password_hash": ""}})
    assert auth._stored_hash() == DEFAULT_ADMIN_HASH


def test_verify_and_lockout():
    clock = Clock()
    auth, _, _ = make(clock=clock)
    for _ in range(MAX_FAILURES):
        assert auth.verify("wrong") is False
    with pytest.raises(ValidationError):
        auth.verify("Correct-Horse-1")  # blocked even with the right password
    clock.t += LOCKOUT_SECONDS + 1
    assert auth.verify("Correct-Horse-1") is True


def test_change_password():
    auth, cfg, saved = make()
    with pytest.raises(ValidationError):
        auth.change("bad", "New-Pass-99", "New-Pass-99")
    with pytest.raises(ValidationError):
        auth.change("Correct-Horse-1", "New-Pass-99", "New-Pass-98")
    with pytest.raises(ValidationError):
        auth.change("Correct-Horse-1", "short", "short")
    auth.change("Correct-Horse-1", "New-Pass-99", "New-Pass-99")
    assert saved and verify_password("New-Pass-99", cfg["admin"]["password_hash"])
    assert "New-Pass-99" not in str(cfg)
    assert auth.verify("New-Pass-99") and not auth.verify("Correct-Horse-1")
