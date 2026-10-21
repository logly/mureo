"""``StateStore`` Protocol.

The Protocol abstracts what today is hard-wired CWD-relative file I/O
in ``mureo.context.state`` and ``mureo.context.strategy``. Alternate
backends (tests, SQLite, S3, a hosted Files API) can swap the
underlying storage without touching the rest of mureo.

The default implementation, ``FilesystemStateStore``, lives in
:mod:`mureo.context.state_store`: ``mureo.core`` sits below
``mureo.context`` and never imports it at load time (#863). The three
models named in the signatures below are imported for type checking only.
The old ``mureo.core.state_store.FilesystemStateStore`` path still resolves,
on access, for callers outside this repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mureo.context.models import ActionLogEntry, StateDocument, StrategyEntry
    from mureo.context.state_store import (
        FilesystemStateStore as FilesystemStateStore,
    )


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


def __getattr__(name: str) -> Any:
    if name == "FilesystemStateStore":
        # ABI re-export of a higher layer, resolved on access (#863).
        from mureo.context.state_store import (  # noqa: PLC0415 — PEP 562 re-export (#863)
            FilesystemStateStore,
        )

        return FilesystemStateStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
