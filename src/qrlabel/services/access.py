"""Which menus a user sees, from their Active Directory groups.

- Members of an admin group (default ICT-RY) see every menu and need no admin password.
- Everyone else sees the "user menus" (default Search & Print, Print History, Printer Settings).
- The admin password unlocks every menu for the rest of the session (or until locked again).
"""
from __future__ import annotations

from collections.abc import Iterable

# menu key -> name in the sidebar (order = sidebar order)
MENUS: dict[str, str] = {
    "search": "Search & Print",
    "history": "Print History",
    "profiles": "Data Profiles",
    "qr": "QR Configuration",
    "designer": "Label Designer",
    "printer": "Printer Settings",
    "settings": "Application Settings",
    "diagnostics": "Diagnostics",
}
DEFAULT_ADMIN_GROUPS = ["ICT-RY"]
DEFAULT_USER_MENUS = ["search", "history", "printer"]
ALWAYS_VISIBLE = "search"  # nobody may end up with an empty window


def group_matches(entry: str, groups: Iterable[str]) -> bool:
    """'ICT-RY' matches FACTORY\\ICT-RY in any domain; 'FACTORY\\ICT-RY' must match exactly. Case-insensitive."""
    entry = (entry or "").strip().lower()
    if not entry:
        return False
    for g in groups:
        g = g.strip().lower()
        if g == entry or ("\\" not in entry and g.rsplit("\\", 1)[-1] == entry):
            return True
    return False


class Access:
    def __init__(self, user: str, groups: Iterable[str], settings: dict | None = None) -> None:
        settings = settings or {}
        self.user = user
        self.groups = tuple(groups)
        self.admin_groups = [g for g in settings.get("admin_groups", DEFAULT_ADMIN_GROUPS) if str(g).strip()]
        menus = settings.get("user_menus", DEFAULT_USER_MENUS)
        self.user_menus = {m for m in menus if m in MENUS} | {ALWAYS_VISIBLE}
        self.unlocked = False  # admin password entered in this session

    @property
    def is_ad_admin(self) -> bool:
        return any(group_matches(e, self.groups) for e in self.admin_groups)

    @property
    def matched_admin_group(self) -> str:
        return next((e for e in self.admin_groups if group_matches(e, self.groups)), "")

    @property
    def full_access(self) -> bool:
        return self.is_ad_admin or self.unlocked

    def can_see(self, menu: str) -> bool:
        return self.full_access or menu in self.user_menus

    def visible_menus(self) -> list[str]:
        return [m for m in MENUS if self.can_see(m)]

    def describe(self) -> str:
        if self.is_ad_admin:
            return f"Administrator (AD group {self.matched_admin_group})"
        if self.unlocked:
            return "Administrator (admin password)"
        return "User"
