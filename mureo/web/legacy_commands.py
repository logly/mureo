"""Detect and remove legacy mureo slash-command files.

Early mureo releases installed workflow operations as ``.md`` files
under ``~/.claude/commands/``. Phase-1 packaging promoted those to
skills under ``~/.claude/skills/`` instead. The configure UI surfaces
a one-shot cleanup so re-running setup does not leave stale command
files behind.

Safety: closed allow-list of basenames. The cleanup loop iterates the
allow-list only, never the directory contents — a user-owned
``~/.claude/commands/my-custom.md`` cannot be removed. No subprocess.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# Closed allow-list of mureo's historical command filenames.
LEGACY_COMMAND_NAMES: tuple[str, ...] = (
    "onboard.md",
    "daily-check.md",
    "rescue.md",
    "search-term-cleanup.md",
    "creative-refresh.md",
    "budget-rebalance.md",
    "competitive-scan.md",
    "goal-review.md",
    "weekly-report.md",
    "sync-state.md",
    "learn.md",
)


def detect_legacy_commands(commands_dir: Path) -> list[str]:
    """Return the basenames present under ``commands_dir`` that match the
    closed allow-list. Empty list when the directory does not exist or
    no files match — read-only check.
    """
    if not commands_dir.exists() or not commands_dir.is_dir():
        return []
    present: list[str] = []
    for name in LEGACY_COMMAND_NAMES:
        candidate = commands_dir / name
        try:
            if candidate.is_file():
                present.append(name)
        except OSError:
            # Permission-denied / dangling-symlink: defensively skip.
            logger.debug("Could not stat legacy candidate %s", candidate)
    return present


def remove_legacy_commands(commands_dir: Path) -> list[str]:
    """Delete every allow-listed file present under ``commands_dir``.

    Returns the basenames that were actually removed. Files outside the
    allow-list are never touched.
    """
    if not commands_dir.exists() or not commands_dir.is_dir():
        return []
    removed: list[str] = []
    for name in LEGACY_COMMAND_NAMES:
        candidate = commands_dir / name
        try:
            if candidate.is_file():
                candidate.unlink()
                removed.append(name)
        except OSError:
            logger.warning("Could not remove legacy command %s", candidate)
    return removed
