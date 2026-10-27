"""Automatic updates from a shared folder: latest.json + installer, verified by SHA-256."""
import hashlib
import json

import pytest

from qrlabel.domain.errors import ValidationError
from qrlabel.services import updater
from qrlabel.services.updater import (
    UpdateInfo,
    install_mode,
    check_for_update,
    download,
    installer_command,
    is_newer,
    parse_manifest,
    read_manifest,
)

PAYLOAD = b"fake installer bytes"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _publish(folder, version="1.0.1", file="NCR-Print-Label-Setup-1.0.1.exe", sha=SHA, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_bytes(PAYLOAD)
    (folder / "latest.json").write_text(json.dumps({"version": version, "file": file, "sha256": sha, **extra}),
                                        encoding="utf-8")
    return folder


def test_versions():
    assert is_newer("1.0.1", "0.9.0") and is_newer("0.10.0", "0.9.9") and is_newer("1.0.0.1", "1.0")
    assert not is_newer("0.9.0", "0.9.0") and not is_newer("0.8.9", "0.9.0")
    with pytest.raises(ValidationError):
        is_newer("1.0-beta", "0.9.0")


@pytest.mark.parametrize("bad", [
    {"file": "x.exe", "sha256": SHA},  # no version
    {"version": "1.0.1", "file": "..\\..\\evil.exe", "sha256": SHA},  # path in the file name
    {"version": "1.0.1", "file": "C:\\evil.exe", "sha256": SHA},
    {"version": "1.0.1", "file": "setup.bat", "sha256": SHA},  # only .exe
    {"version": "1.0.1", "file": "setup.exe", "sha256": "abc"},  # bad hash
    {"version": "latest", "file": "setup.exe", "sha256": SHA},
])
def test_bad_manifest_rejected(bad):
    with pytest.raises(ValidationError):
        parse_manifest(bad)


def test_manifest_fields():
    info = parse_manifest({"version": " 1.0.1 ", "file": "NCR-Print-Label-Setup-1.0.1.exe", "sha256": SHA.upper(),
                           "notes": "Fix", "required": True, "published": "x", "by": "y"})
    assert info == UpdateInfo("1.0.1", "NCR-Print-Label-Setup-1.0.1.exe", SHA, "Fix", True)


def test_check_for_update(tmp_path):
    folder = _publish(tmp_path / "share", notes="Grade box")
    info = check_for_update(str(folder), "0.9.0")
    assert info.version == "1.0.1" and info.notes == "Grade box" and not info.required
    assert check_for_update(str(folder), "1.0.1") is None  # up to date
    assert check_for_update(str(folder), "2.0.0") is None  # never offers an older version
    assert check_for_update("", "0.9.0") is None  # no folder set


def test_missing_or_broken_folder(tmp_path):
    with pytest.raises(ValidationError, match="No latest.json"):
        read_manifest(str(tmp_path))
    (tmp_path / "latest.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(ValidationError, match="not valid JSON"):
        read_manifest(str(tmp_path))
    with pytest.raises(ValidationError):
        read_manifest(str(tmp_path / "nope" / "deeper"))


def test_manifest_with_bom(tmp_path):  # PowerShell / Notepad may add a BOM
    (tmp_path / "latest.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"version": "1.0.1", "file": "a.exe", "sha256": SHA}).encode())
    assert read_manifest(str(tmp_path)).version == "1.0.1"


def test_download_verifies_hash(tmp_path):
    folder = _publish(tmp_path / "share")
    info = read_manifest(str(folder))
    dest = download(info, str(folder), tmp_path / "updates")
    assert dest.read_bytes() == PAYLOAD and dest.parent == tmp_path / "updates"
    assert not list((tmp_path / "updates").glob("*.part"))


def test_download_refuses_changed_file(tmp_path):
    folder = _publish(tmp_path / "share")
    info = read_manifest(str(folder))
    (folder / info.file).write_bytes(b"something else")  # replaced after publishing
    with pytest.raises(ValidationError, match="SHA-256"):
        download(info, str(folder), tmp_path / "updates")
    assert not list((tmp_path / "updates").iterdir())  # nothing left to run


def test_download_missing_installer(tmp_path):
    folder = _publish(tmp_path / "share")
    info = read_manifest(str(folder))
    (folder / info.file).unlink()
    with pytest.raises(ValidationError, match="Cannot copy"):
        download(info, str(folder), tmp_path / "updates")


def test_install_mode(tmp_path, monkeypatch):
    mode, why = install_mode()  # tests run from source
    assert mode is None and "source" in why
    exe = tmp_path / "NCRPrintLabel.exe"
    exe.write_bytes(b"")
    assert install_mode(exe) == ("user", "")  # "for me only": the user can write the folder
    real_write = updater.Path.write_text

    def denied(self, *a, **kw):
        if self.name == ".update-write-test":
            raise PermissionError("Program Files")
        return real_write(self, *a, **kw)

    monkeypatch.setattr(updater.Path, "write_text", denied)
    mode, why = install_mode(exe)  # "for all users": Windows asks for an administrator
    assert mode == "admin" and "administrator" in why


def test_installer_command(tmp_path):
    user = installer_command(tmp_path / "Setup.exe")
    assert user[0].endswith("Setup.exe")
    assert {"/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER"} <= set(user)
    assert "/RELAUNCH=1" not in user  # the helper script opens the program again, as the user
    assert "/ALLUSERS" in installer_command(tmp_path / "Setup.exe", "admin")


def test_updater_script_for_me_only(tmp_path):
    script = updater.updater_script(tmp_path / "it's Setup.exe", 4321, tmp_path / "NCRPrintLabel.exe")
    assert script.startswith("Wait-Process -Id 4321")
    assert "it''s Setup.exe" in script  # quoted for PowerShell
    assert "RunAs" not in script and "-Wait" in script
    assert script.rstrip().endswith("NCRPrintLabel.exe'")  # program opened again afterwards


def test_updater_script_for_all_users(tmp_path):
    script = updater.updater_script(tmp_path / "Setup.exe", 1, tmp_path / "NCRPrintLabel.exe", "admin")
    assert "-Verb RunAs -Wait" in script and "'/ALLUSERS'" in script
    assert "catch" in script  # UAC cancelled: the old version opens again
    install, reopen = script.split("catch", 1)
    assert "RunAs" not in reopen  # the program is not started as the administrator


def test_start_installer_runs_hidden(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    updater.start_installer_after_exit(tmp_path / "Setup.exe", 4321, tmp_path / "app.exe", "admin")
    args, kw = calls[0]
    assert args[0] == "powershell.exe" and "Hidden" in args and "Wait-Process -Id 4321" in args[-1]


def test_config_default_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("QRLABEL_DATA_DIR", str(tmp_path))
    from qrlabel.app.context import AppContext

    u = AppContext().config["update"]
    assert u["folder"] == r"\\ncr230\RY_File\_Free-OSS\NCRPrintLabel" and u["check_on_start"] is True
