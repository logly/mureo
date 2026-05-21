"""Tests for ``mureo.core.state_store`` — structural Protocol contract.

RED-phase tests for the new ``StateStore`` Protocol that abstracts
STATE.json / STRATEGY.md / action-log persistence. Default callers
continue to use the existing helpers in ``mureo.context.state`` and
``mureo.context.strategy``; this Protocol exists so alternate backends
(in-memory fakes for tests, SQLite, S3, Anthropic Files API, etc.) can
be swapped in without touching call sites.

This commit pins the Protocol shape only — concrete default
implementations land in a separate commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mureo.context.models import ActionLogEntry, StateDocument, StrategyEntry
from mureo.core.state_store import StateStore


@dataclass
class _FakeStateStore:
    """Minimal in-memory implementation used to exercise the Protocol shape."""

    state: StateDocument = field(default_factory=StateDocument)
    strategy: list[StrategyEntry] = field(default_factory=list)
    log: list[ActionLogEntry] = field(default_factory=list)

    def read_state(self) -> StateDocument:
        return self.state

    def write_state(self, doc: StateDocument) -> None:
        self.state = doc

    def read_strategy(self) -> list[StrategyEntry]:
        return list(self.strategy)

    def write_strategy(self, entries: list[StrategyEntry]) -> None:
        self.strategy = list(entries)

    def append_action_log(self, entry: ActionLogEntry) -> None:
        self.log.append(entry)


@pytest.mark.unit
def test_protocol_is_runtime_checkable() -> None:
    assert isinstance(_FakeStateStore(), StateStore)


@pytest.mark.unit
def test_incomplete_implementation_is_rejected() -> None:
    class _MissingAppend:
        def read_state(self) -> StateDocument:
            return StateDocument()

        def write_state(self, doc: StateDocument) -> None:
            pass

        def read_strategy(self) -> list[StrategyEntry]:
            return []

        def write_strategy(self, entries: list[StrategyEntry]) -> None:
            pass

    assert not isinstance(_MissingAppend(), StateStore)


@pytest.mark.unit
def test_fake_state_round_trip() -> None:
    store = _FakeStateStore()
    doc = StateDocument(version="2", customer_id="123-456-7890")
    store.write_state(doc)
    assert store.read_state() == doc


@pytest.mark.unit
def test_fake_strategy_round_trip() -> None:
    store = _FakeStateStore()
    entries = [StrategyEntry(context_type="persona", title="P", content="x")]
    store.write_strategy(entries)
    assert store.read_strategy() == entries


@pytest.mark.unit
def test_append_action_log_accumulates() -> None:
    store = _FakeStateStore()
    e1 = ActionLogEntry(timestamp="2026-01-01T00:00:00Z", action="a", platform="g")
    e2 = ActionLogEntry(timestamp="2026-01-02T00:00:00Z", action="b", platform="m")
    store.append_action_log(e1)
    store.append_action_log(e2)
    assert store.log == [e1, e2]


@pytest.mark.unit
def test_read_strategy_returns_isolated_snapshot() -> None:
    """``read_strategy`` must return a fresh list — caller mutations of the
    returned value must not leak back into the store. This is part of the
    Protocol contract, not a recommendation, so alternate backends that
    hand back an internal reference are caught here."""
    store = _FakeStateStore()
    store.write_strategy([StrategyEntry(context_type="persona", title="T", content="x")])
    snap = store.read_strategy()
    snap.append(StrategyEntry(context_type="usp", title="U", content="y"))
    assert len(store.read_strategy()) == 1
