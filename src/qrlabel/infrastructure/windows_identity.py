"""Who is using the application: the Windows user and their Active Directory groups.

The groups come from the Windows logon token, so no password, no LDAP query and no network
are needed (it also works with a cached domain logon). Nested groups are included by Windows.
Group changes in AD take effect after the user signs in to Windows again.
"""
from __future__ import annotations

import getpass
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowsIdentity:
    user: str  # DOMAIN\\name, or just the name when it cannot be read
    groups: tuple[str, ...] = field(default_factory=tuple)  # DOMAIN\\group names


def current_identity() -> WindowsIdentity:
    try:
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        name, domain, _ = win32security.LookupAccountSid(None, sid)
        user = f"{domain}\\{name}" if domain else name
        groups: list[str] = []
        for gsid, _attrs in win32security.GetTokenInformation(token, win32security.TokenGroups):
            try:
                gname, gdomain, _ = win32security.LookupAccountSid(None, gsid)
            except Exception:  # SIDs without a name (logon session, capabilities, offline lookups)
                continue
            groups.append(f"{gdomain}\\{gname}" if gdomain else gname)
        return WindowsIdentity(user, tuple(groups))
    except Exception as e:
        log.warning("Could not read the Windows groups (%s); using user name only", e)
        try:
            return WindowsIdentity(getpass.getuser(), ())
        except Exception:
            return WindowsIdentity("", ())
