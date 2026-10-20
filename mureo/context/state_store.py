"""``FilesystemStateStore`` — the default :class:`~mureo.core.state_store.StateStore`.

It composes the existing helpers in ``mureo.context.state`` and
``mureo.context.strategy`` so call-site behaviour is preserved
verbatim — only the access shape changes.

It lives here, not in ``mureo.core``, because it is built on the file-format
layer: ``mureo.core`` sits below ``mureo.context`` and never imports it at load
time (#863). :func:`mureo.core.runtime_context.default_runtime_context` reaches
this class by object reference, and ``mureo.core`` still exports the name.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mureo.context.state import (
    _state_lock_path,
    read_state_file,
    write_state_file,
)
from mureo.context.state import (
    append_action_log as _legacy_append_action_log,
)
from mureo.context.strategy import (
    read_strategy_file,
    write_strategy_file,
)
from mureo.fsutil import file_lock

if TYPE_CHECKING:
    from mureo.context.models import ActionLogEntry, StateDocument, StrategyEntry


# ---------------------------------------------------------------------------
# Default implementation — STATE.json + STRATEGY.md under a workspace dir
# ---------------------------------------------------------------------------


class FilesystemStateStore:
    """Persist state in ``STATE.json`` and ``STRATEGY.md`` under a workspace
    directory (default CWD).

    All file I/O routes through the existing legacy helpers so behaviour
    matches the today's CWD-relative call sites byte-for-byte for
    callers that do not inject a custom store.
    """

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace if workspace is not None else Path.cwd()
        self.state_path = self.workspace / "STATE.json"
        self.strategy_path = self.workspace / "STRATEGY.md"

    def read_state(self) -> StateDocument:
        return read_state_file(self.state_path)

    def write_state(self, doc: StateDocument) -> None:
        # Take the same cross-process lock every STATE.json mutator holds
        # (``_locked_state_mutation``) so a blind full-document write cannot
        # interleave with a concurrent read-modify-write and resurrect the #115
        # lost-update race. This store's own read/modify/write callers go
        # through ``append_action_log`` (already locked); guarding the plain
        # ``write_state`` too closes the design trap of a naive future caller.
        # The write stays atomic via ``write_state_file``.
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(_state_lock_path(self.state_path)):
            write_state_file(self.state_path, doc)

    def read_strategy(self) -> list[StrategyEntry]:
        # ``read_strategy_file`` already returns a fresh list from
        # ``parse_strategy``; copy defensively so future refactors of the
        # legacy helper cannot weaken the snapshot-isolation contract.
        return list(read_strategy_file(self.strategy_path))

    def write_strategy(self, entries: list[StrategyEntry]) -> None:
        # Defensive copy so callers can keep mutating their input.
        write_strategy_file(self.strategy_path, list(entries))

    def append_action_log(self, entry: ActionLogEntry) -> None:
        _legacy_append_action_log(self.state_path, entry)
