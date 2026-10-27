"""Automatic updates from a shared network folder (no database, no internet).

The folder (Application Settings) holds:
    latest.json                       {"version": "1.0.1", "file": "NCR-Print-Label-Setup-1.0.1.exe",
                                       "sha256": "...", "notes": "...", "required": false}
    NCR-Print-Label-Setup-1.0.1.exe

ICT publishes with scripts/publish_update.ps1. The app reads latest.json on start; when the version is
newer it offers the update, copies the installer to the local data folder, checks its SHA-256 and runs it
silently after the app has closed. Settings, history and designs are kept by the installer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import ValidationError

log = logging.getLogger(__name__)

MANIFEST = "latest.json"
_VERSION_RE = re.compile(r"^\d+(\.\d+){1,3}$")
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}\.exe$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    file: str
    sha256: str
    notes: str = ""
    required: bool = False


def parse_version(text: str) -> tuple[int, ...]:
    text = (text or "").strip()
    if not _VERSION_RE.match(text):
        raise ValidationError(f"'{text}' is not a version number like 1.0.2.")
    parts = tuple(int(p) for p in text.split("."))
    return parts + (0,) * (4 - len(parts))


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def parse_manifest(data: dict) -> UpdateInfo:
    """Validate latest.json. The file name may not contain a path, so nothing outside the folder is read."""
    try:
        info = UpdateInfo(
            version=str(data["version"]).strip(),
            file=str(data["file"]).strip(),
            sha256=str(data["sha256"]).strip().lower(),
            notes=str(data.get("notes", "")).strip()[:2000],
            required=bool(data.get("required", False)),
        )
    except (KeyError, TypeError, AttributeError) as e:
        raise ValidationError(f"{MANIFEST} is missing {e}.") from None
    parse_version(info.version)
    if not _FILE_RE.match(info.file) or ".." in info.file:
        raise ValidationError(f"{MANIFEST}: '{info.file}' is not a plain installer file name.")
    if not _SHA_RE.match(info.sha256):
        raise ValidationError(f"{MANIFEST}: sha256 must be 64 hex characters.")
    return info


def read_manifest(folder: str) -> UpdateInfo:
    path = Path(folder) / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ValidationError(f"No {MANIFEST} in {folder}.") from None
    except OSError as e:
        raise ValidationError(f"Cannot open the update folder {folder}: {e.strerror or e}.") from None
    except json.JSONDecodeError as e:
        raise ValidationError(f"{MANIFEST} is not valid JSON: {e}.") from None
    if not isinstance(data, dict):
        raise ValidationError(f"{MANIFEST} must contain a JSON object.")
    return parse_manifest(data)


def check_for_update(folder: str, current: str) -> UpdateInfo | None:
    """The newer version offered in the folder, or None when this one is up to date."""
    if not (folder or "").strip():
        return None
    info = read_manifest(folder.strip())
    return info if is_newer(info.version, current) else None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(info: UpdateInfo, folder: str, dest_dir: Path) -> Path:
    """Copy the installer to the local data folder and check it is exactly the published file."""
    src = Path(folder.strip()) / info.file
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("*.exe"):  # keep only the latest download
        try:
            old.unlink()
        except OSError:
            pass
    dest = dest_dir / info.file
    part = dest.with_suffix(".part")
    try:
        shutil.copyfile(src, part)
    except OSError as e:
        part.unlink(missing_ok=True)
        raise ValidationError(f"Cannot copy {info.file} from the update folder: {e.strerror or e}.") from None
    actual = sha256_of(part)
    if actual != info.sha256:
        part.unlink(missing_ok=True)
        raise ValidationError(
            f"{info.file} does not match {MANIFEST} (SHA-256 differs). The file may be damaged or replaced; "
            "the update was not installed. Tell ICT."
        )
    os.replace(part, dest)
    log.info("Update %s copied and verified (%s)", info.version, actual[:12])
    return dest


def can_install_here() -> tuple[bool, str]:
    """Only the installed program updates itself, and only when this user may write to its folder."""
    if not getattr(sys, "frozen", False):
        return False, "Updates install only into the installed program, not when running from source."
    folder = Path(sys.executable).resolve().parent
    probe = folder / ".update-write-test"
    try:
        probe.write_text("x", encoding="ascii")
        probe.unlink()
    except OSError:
        return False, (f"The program is installed for all users in {folder}; this Windows account cannot "
                       "update it. Ask ICT to run the new installer.")
    return True, ""


def installer_command(installer: Path) -> list[str]:
    # /RELAUNCH=1 makes the installer start the program again (see installer/NCRPrintLabel.iss).
    return [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1",
            f"/LOG={installer.with_suffix('.log')}"]


def start_installer_after_exit(installer: Path, pid: int) -> None:
    """Run the installer once this process (pid) has exited, so no file of the program is in use."""
    def ps_quote(text: str) -> str:
        return "'" + text.replace("'", "''") + "'"

    exe, *args = installer_command(installer)
    script = (
        f"Wait-Process -Id {int(pid)} -Timeout 120 -ErrorAction SilentlyContinue; "
        f"Start-Process -FilePath {ps_quote(exe)} -ArgumentList {', '.join(ps_quote(a) for a in args)}"
    )
    # no console window; own process group so it keeps running after this program exits
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-Command", script],
        creationflags=flags, close_fds=True,
    )
    log.info("Installer %s will start after the program closes", installer.name)
