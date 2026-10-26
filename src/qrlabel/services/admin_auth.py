"""Admin password for protected settings pages.

Only a salted PBKDF2 hash is stored (config.json -> admin.password_hash).
This is a UI gate for operators; real data protection comes from the read-only
SQL login and Windows permissions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from collections.abc import Callable
from typing import Any

from ..domain.errors import ValidationError

ITERATIONS = 200_000
MIN_LENGTH = 8
MAX_FAILURES = 5
LOCKOUT_SECONDS = 30

# Hash of the initial admin password given by the business. Change it after installation.
DEFAULT_ADMIN_HASH = "pbkdf2_sha256$200000$2/Jzur2cw01D/MfuDeL2UQ==$0GP5zvVeaeQHPMPTzJhHVYz1nEfMTL4ywGuw4lSgqJU="


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


class AdminAuth:
    def __init__(
        self,
        get_config: Callable[[], dict[str, Any]],
        save_config: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._get_config = get_config
        self._save_config = save_config
        self._clock = clock
        self._failures = 0
        self._blocked_until = 0.0

    def _stored_hash(self) -> str:
        return self._get_config().get("admin", {}).get("password_hash") or DEFAULT_ADMIN_HASH

    def seconds_blocked(self) -> int:
        return max(0, int(self._blocked_until - self._clock() + 0.999))

    def verify(self, password: str) -> bool:
        """Check the admin password. Raises ValidationError while temporarily blocked."""
        wait = self.seconds_blocked()
        if wait:
            raise ValidationError(f"Too many wrong attempts. Try again in {wait} seconds.")
        if verify_password(password, self._stored_hash()):
            self._failures = 0
            return True
        self._failures += 1
        if self._failures >= MAX_FAILURES:
            self._failures = 0
            self._blocked_until = self._clock() + LOCKOUT_SECONDS
        return False

    def change(self, current: str, new: str, confirm: str) -> None:
        if not verify_password(current, self._stored_hash()):
            raise ValidationError("The current admin password is wrong.")
        if new != confirm:
            raise ValidationError("The new passwords do not match.")
        if len(new) < MIN_LENGTH:
            raise ValidationError(f"The new password must be at least {MIN_LENGTH} characters.")
        if new == current:
            raise ValidationError("The new password must be different.")
        cfg = self._get_config()
        cfg.setdefault("admin", {})["password_hash"] = hash_password(new)
        self._save_config()
