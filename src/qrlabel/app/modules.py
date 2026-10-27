"""Optional parts of the application that can be added to an installation."""
from __future__ import annotations

import logging

from .defaults import JOURNAL_PROFILE_ID, JOURNAL_SOURCES, default_journal_profile

log = logging.getLogger(__name__)


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
