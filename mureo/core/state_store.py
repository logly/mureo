"""``StateStore`` Protocol and default in-process implementation.

The Protocol abstracts what today is hard-wired CWD-relative file I/O
in ``mureo.context.state`` and ``mureo.context.strategy``. Alternate
backends (tests, SQLite, S3, a hosted Files API) can swap the
underlying storage without touching the rest of mureo.

``FilesystemStateStore`` is the default implementation. It composes the
existing helpers in ``mureo.context.state`` and
``mureo.context.strategy`` so call-site behaviour is preserved
verbatim — only the access shape changes.

Foundation-rule waiver
----------------------
This module imports ``StateDocument`` / ``StrategyEntry`` /
``ActionLogEntry`` from ``mureo.context.models`` and the default
implementation reaches further into ``mureo.context.state`` and
``mureo.context.strategy``. ``mureo.core`` modules normally avoid
reaching outwards into other top-level packages (see
:mod:`mureo.core.providers.base` for the same rule applied to the
provider Protocols). The exception is intentional here: the three
models are immutable, behaviour-free frozen dataclasses and the helper
functions are pure file-format adapters that pre-date this Protocol;
re-homing them into ``mureo.core`` would be a separate refactor with
its own re-export and back-compat concerns. Tracked for a follow-up
commit.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

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


@runtime_checkable
class StateStore(Protocol):
    """Pluggable persistence for the workspace's mureo state.

    Contract:
    - ``read_state`` / ``write_state`` round-trip the full
      ``StateDocument``. ``StateDocument`` is itself a frozen dataclass,
      so callers cannot mutate the returned value's top-level fields.
    - ``read_strategy`` must return a fresh list per call — callers
      append/sort/clear the returned list freely and the store remains
      unaffected. Implementations that hand back an internal reference
      violate the contract.
    - ``write_strategy`` accepts any iterable copied into the store;
      callers may continue mutating their input after the call returns.
    - ``append_action_log`` is the only mutator for the action log.
      Implementations must append (not overwrite) and should be safe to
      call concurrently from a single workspace.
    """

    def read_state(self) -> StateDocument: ...

    def write_state(self, doc: StateDocument) -> None: ...

    def read_strategy(self) -> list[StrategyEntry]: ...

    def write_strategy(self, entries: list[StrategyEntry]) -> None: ...

    def append_action_log(self, entry: ActionLogEntry) -> None: ...


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
