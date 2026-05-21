"""``StateStore`` Protocol — pluggable persistence for STATE.json,
STRATEGY.md, and the action log.

Abstracts what today is hard-wired CWD-relative file I/O in
``mureo.context.state`` and ``mureo.context.strategy``. The OSS default
implementation (added in a follow-up commit) wraps the existing helpers
so call-site behaviour is behaviourally equivalent for users that do
not inject a custom store.

Designed so callers (tests, alternate backends such as SQLite, S3, or
a hosted-agent Files API) can swap the underlying storage without
touching the rest of mureo.

Foundation-rule waiver
----------------------
This module imports ``StateDocument`` / ``StrategyEntry`` /
``ActionLogEntry`` from ``mureo.context.models``. ``mureo.core`` modules
normally avoid reaching outwards into other top-level packages
(see :mod:`mureo.core.providers.base` for the same rule applied to the
provider Protocols). The exception is intentional here: the three
models are immutable, behaviour-free frozen dataclasses that pre-date
this Protocol, and re-homing them into ``mureo.core`` would be a
separate refactor with its own re-export and back-compat concerns.
Tracked for a follow-up commit.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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
