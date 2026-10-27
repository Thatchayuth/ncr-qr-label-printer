"""Parts (modules) of the application chosen when installing: Asset labels and/or Stock labels.

The installer writes install-options.json next to the exe ({"modules": ["asset", "journal"]}).
On start the app copies a *new* choice into the settings (config "modules"); an admin can change it
later in Application Settings. Re-installing with the same choice does not undo that change.

A module only decides which built-in data profile is offered on Search & Print. Profiles an admin
made himself are always offered. Menus are decided by AD groups (services.access), not by modules.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from .defaults import DEFAULT_PROFILE_ID, JOURNAL_PROFILE_ID, JOURNAL_SOURCES, default_journal_profile

log = logging.getLogger(__name__)

MODULES: dict[str, str] = {
    "asset": "Asset labels (fixed assets)",
    "journal": "Stock labels (inventory transfer journal)",
}
MODULE_PROFILES: dict[str, str] = {"asset": DEFAULT_PROFILE_ID, "journal": JOURNAL_PROFILE_ID}
INSTALL_OPTIONS_FILE = "install-options.json"


def install_options_path() -> Path | None:
    """install-options.json beside the installed exe; None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / INSTALL_OPTIONS_FILE
    return None


def clean_modules(modules) -> list[str]:
    out = [m for m in MODULES if m in set(modules or [])]
    return out or list(MODULES)  # never none: an empty choice means everything


def read_install_options(path: Path | None) -> list[str] | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return clean_modules(data.get("modules"))
    except Exception:
        log.exception("Cannot read %s; keeping the current modules", path)
        return None


def apply_install_options(ctx, path: Path | None = None) -> bool:
    """Take over a new installer choice. Returns True when the settings changed."""
    chosen = read_install_options(path if path is not None else install_options_path())
    if chosen is None or chosen == ctx.config.get("install_modules"):
        return False  # nothing new from the installer: keep what an admin may have changed
    ctx.config["install_modules"] = chosen
    ctx.config["modules"] = chosen
    ctx.save_config()
    log.info("Modules from the installer: %s", ", ".join(chosen))
    return True


def enabled_modules(ctx) -> list[str]:
    return clean_modules(ctx.config.get("modules"))


def hidden_profile_ids(ctx) -> set[str]:
    on = set(enabled_modules(ctx))
    return {pid for module, pid in MODULE_PROFILES.items() if module not in on}


def ensure_modules(ctx) -> None:
    """Create what an enabled module needs (never changes something that already exists)."""
    if "journal" in enabled_modules(ctx):
        template_id = install_journal_template(ctx)
        install_journal_profile(ctx, [template_id] if template_id else None)


def install_journal_template(ctx) -> str:
    """The bundled STOCK label; returns its id ('' when it is not bundled)."""
    from .defaults import bundled_templates, bundled_template_id

    tid = bundled_template_id("journal")
    if not tid:
        return ""
    if ctx.templates.get(tid) is None:
        templates, _ = bundled_templates()
        t = next((t for t in templates if t.id == tid), None)
        if t is None:
            return ""
        ctx.templates.save(t)
        log.info("Installed bundled label template '%s'", t.name)
    return tid


def install_journal_profile(ctx, template_ids: list[str] | None = None) -> bool:
    """Approve the journal tables and add the 'Inventory transfer journal' profile.

    Does nothing to an existing profile (it may have been edited). Returns True when it was added.
    """
    sources = ctx.config["approved_sources"]
    known = {s.upper() for s in sources}
    added = [t for t in JOURNAL_SOURCES if t.upper() not in known]
    if added:
        sources.extend(added)
        ctx.save_config()
        log.info("Approved journal tables: %s", ", ".join(added))
    if ctx.profiles.get(JOURNAL_PROFILE_ID) is not None:
        return False
    ctx.profiles.save(default_journal_profile(template_ids))
    log.info("Added the inventory transfer journal profile")
    return True
