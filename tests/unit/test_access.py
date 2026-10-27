"""Menus by Active Directory group: ICT-RY sees everything, others see Search & Print, History, Printer."""
import pytest

from qrlabel.infrastructure.windows_identity import WindowsIdentity, current_identity
from qrlabel.services.access import MENUS, Access, group_matches

ADMIN = ("FACTORY\\Domain Users", "FACTORY\\ICT-RY", "FACTORY\\WSS_RY_User")
USER = ("FACTORY\\Domain Users", "FACTORY\\WSS_RY_User", "FACTORY\\ICT-RY-Dev")  # ICT-RY-Dev is not ICT-RY
DEFAULTS = {"admin_groups": ["ICT-RY"], "user_menus": ["search", "history", "printer"]}


def test_group_matching():
    assert group_matches("ICT-RY", ADMIN)
    assert group_matches("ict-ry", ADMIN)  # case-insensitive
    assert group_matches("FACTORY\\ICT-RY", ADMIN)
    assert not group_matches("OTHER\\ICT-RY", ADMIN)  # a domain given must match
    assert not group_matches("ICT-RY", USER)  # no partial names
    assert not group_matches("", ADMIN)


def test_ict_ry_sees_everything():
    a = Access("FACTORY\\it", ADMIN, DEFAULTS)
    assert a.is_ad_admin and a.full_access and a.matched_admin_group == "ICT-RY"
    assert a.visible_menus() == list(MENUS)
    assert "ICT-RY" in a.describe()


def test_others_see_three_menus():
    a = Access("FACTORY\\store1", USER, DEFAULTS)
    assert not a.full_access
    assert a.visible_menus() == ["search", "history", "printer"]
    assert not a.can_see("designer") and not a.can_see("settings") and not a.can_see("profiles")


def test_admin_password_unlocks_for_the_session():
    a = Access("FACTORY\\store1", USER, DEFAULTS)
    a.unlocked = True
    assert a.visible_menus() == list(MENUS) and a.describe() == "Administrator (admin password)"
    a.unlocked = False
    assert a.visible_menus() == ["search", "history", "printer"]


def test_search_is_always_visible_and_unknown_menus_ignored():
    a = Access("x", (), {"admin_groups": [], "user_menus": ["nope"]})
    assert a.visible_menus() == ["search"]


def test_no_groups_means_user():  # not a domain account, or the groups could not be read
    assert Access("pc\\local", (), DEFAULTS).visible_menus() == ["search", "history", "printer"]


def test_defaults_when_settings_missing():
    assert Access("x", ADMIN, None).is_ad_admin
    assert Access("x", USER, {}).visible_menus() == ["search", "history", "printer"]


def test_current_identity_reads_windows():
    ident = current_identity()
    assert isinstance(ident, WindowsIdentity) and ident.user


def test_config_has_access_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from qrlabel.app.context import AppContext

    ctx = AppContext()
    assert ctx.config["access"] == DEFAULTS
    ctx.config["access"] = {"admin_groups": ["NOBODY"], "user_menus": ["search", "history"]}
    ctx.save_config()
    again = AppContext()
    assert again.config["access"]["admin_groups"] == ["NOBODY"]


@pytest.fixture
def window_for(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import qrlabel.app.context as context

    def make(groups):
        monkeypatch.setattr(context, "current_identity", lambda: WindowsIdentity("FACTORY\\tester", groups))
        from qrlabel.ui.main_window import MainWindow

        w = MainWindow(context.AppContext())
        app.processEvents()
        return w

    return make


def _visible_menus(w):
    return [k for k, item in w._menu_items.items() if not item.isHidden()]


def test_window_for_normal_user(window_for):
    w = window_for(USER)
    assert _visible_menus(w) == ["search", "history", "printer"]
    headers = {head.text().strip(): head.isHidden() for head, _ in w._sections}
    assert headers == {"OPERATIONS": False, "LABEL SETUP": True, "SYSTEM": False}
    assert w.admin_btn.isEnabled() and "Admin" in w.admin_btn.text()


def test_window_for_ict_ry(window_for):
    w = window_for(ADMIN)
    assert _visible_menus(w) == list(MENUS)
    assert not w.admin_btn.isEnabled() and "ICT-RY" in w.admin_btn.text()
    from qrlabel.ui.admin_gate import AdminGate

    gates = [p for _, p in w.pages if isinstance(p, AdminGate)]
    assert gates and all(g.unlocked for g in gates)  # no password page for ICT-RY
    gates[0].lock()  # leaving the page must not ask for the password again
    assert gates[0].unlocked


def test_unlock_and_lock_with_password(window_for):
    from qrlabel.ui.admin_gate import AdminGate

    w = window_for(USER)
    w.ctx.access.unlocked = True  # what the Admin dialog does after a correct password
    w.apply_access()
    assert _visible_menus(w) == list(MENUS)
    w.show_page("Label Designer")
    w._admin_clicked()  # "Admin unlocked · Lock"
    assert _visible_menus(w) == ["search", "history", "printer"]
    assert w.nav.currentItem() is w._menu_items["search"]  # moved off the hidden page
    assert not any(p.unlocked for _, p in w.pages if isinstance(p, AdminGate))


def test_password_dialog(window_for):
    from qrlabel.ui.main_window import AdminPasswordDialog

    w = window_for(USER)
    dlg = AdminPasswordDialog(w, w.ctx)
    dlg.password.setText("wrong-password")
    dlg._accept()
    assert dlg.result() == 0 and "Wrong password" in dlg.error.text()
