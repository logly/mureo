"""A whole-document STATE.json write may not silently shorten the log.

``action_log`` is the curated record of what mureo did to an ad account,
and it is append-only by contract. Every targeted mutator in this tree
honours that — :func:`mureo.context.state.append_action_log` reads,
appends and writes inside one lock.

The whole-document writers cannot be held to it the same way. A host
restoring a backup, an agency sync assembling its own
:class:`~mureo.context.models.StateDocument`,
:meth:`mureo.core.state_store.FilesystemStateStore.write_state` and
:func:`mureo.context.platform_repair.apply_state_file_repairs` all hand
:func:`~mureo.context.state.write_state_file` a complete document, and a
stale or partial one shortens the record with no trace that it did.

**Advisory, not enforcement** — the same reasoning as
:func:`mureo.context.platform_guards.warn_on_duplicate_accounts`: a
document that cannot be written is a workspace an operator can neither
sync nor repair, and this layer has no way to tell a restore (legitimate,
and shorter) from a bug. So the write proceeds and the previous document
survives beside it as ``STATE.json.bak.<unix_ns>``, with a WARNING naming
both lengths and where the copy went.

One thing it does refuse: a shortening write whose backup FAILED. Fail
closed, exactly like ``apply_state_file_repairs`` — overwriting the only
copy of a record because the copy could not be made is the outcome this
module exists to prevent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mureo.context.state_codec import _action_log_entry_to_dict
from mureo.fsutil import backup_file

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import ActionLogEntry, StateDocument

logger = logging.getLogger(__name__)


def _rendered(entries: tuple[ActionLogEntry, ...]) -> list[dict[str, object]]:
    """The entries as they are stored, so a rewrite is visible.

    Compared through the codec rather than by identity or length: an
    entry whose reason, metrics or observation window was replaced is the
    same count of entries and a different record.
    """
    return [_action_log_entry_to_dict(entry) for entry in entries]


def _previous_document(path: Path) -> StateDocument | None:
    """What is on disk at ``path``, or ``None`` if that cannot be read.

    A document nobody can read is not evidence that anything was
    shortened, so an unreadable or absent file leaves the write
    unguarded. ``strict=False``: a nonconforming campaign entry must not
    cost the backup of the ``action_log`` beside it.
    """
    if not path.exists():
        return None
    from mureo.context.state import read_state_file

    try:
        return read_state_file(path, strict=False)
    except Exception:  # noqa: BLE001 — a guard may not break the write
        logger.debug("action_log guard: %s could not be read", path, exc_info=True)
        return None


def _is_shrink(previous: StateDocument, new_doc: StateDocument) -> bool:
    """Whether ``new_doc``'s log drops or rewrites part of ``previous``'s."""
    old = _rendered(previous.action_log)
    new = _rendered(new_doc.action_log)
    if len(new) < len(old):
        return True
    return new[: len(old)] != old


def guard_action_log_shrink(
    path: Path, new_doc: StateDocument, *, previous: StateDocument | None
) -> Path | None:
    """Back ``path`` up when ``new_doc`` shortens its ``action_log``.

    Args:
        path: STATE.json location, as it is about to be overwritten.
        new_doc: The document the caller is about to write.
        previous: The on-disk document, when the caller has already read
            it under the same lock — the ordinary mutators do, and pass
            it so this guard costs them no second read. ``None`` makes
            the guard read ``path`` itself.

    Returns:
        The backup path, or ``None`` when nothing was shortened (or
        there was nothing on disk to shorten).

    Raises:
        OSError: The backup could not be written. The caller must not
            proceed with the write — see the module docstring.
    """
    known = previous if previous is not None else _previous_document(path)
    if known is None or not _is_shrink(known, new_doc):
        return None
    backup = backup_file(path, timestamped=True)
    if backup is None:  # the file went away under us: nothing to preserve
        return None
    logger.warning(
        "STATE.json action_log shortened from %d to %d entries by a "
        "whole-document write; previous copy kept at %s",
        len(known.action_log),
        len(new_doc.action_log),
        backup,
    )
    return backup


__all__ = ["guard_action_log_shrink"]
