"""Windows DPAPI wrapper: secrets are encrypted for the current Windows user."""
from __future__ import annotations

import base64

_DESCRIPTION = "NCR QR Label Printer"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def protect(plaintext: str) -> str:
    import win32crypt

    blob = win32crypt.CryptProtectData(
        plaintext.encode("utf-8"), _DESCRIPTION, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN
    )
    return base64.b64encode(blob).decode("ascii")


def unprotect(token: str) -> str:
    import win32crypt

    if not token:
        return ""
    _, data = win32crypt.CryptUnprotectData(
        base64.b64decode(token), None, None, None, _CRYPTPROTECT_UI_FORBIDDEN
    )
    return data.decode("utf-8")
