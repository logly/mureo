"""Tests for ``mureo.core.runtime_context`` — frozen dataclass aggregating
the four core extension Protocols plus a workspace identifier.

RED-phase tests pin the dataclass shape, immutability, and the
non-empty ``workspace_id`` validator. Default construction (the factory
that returns a sensible context for single-workspace callers) lands in
a separate commit.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from typing import Any

import pytest

from mureo.context.models import ActionLogEntry, StateDocument, StrategyEntry
from mureo.core.runtime_context import RuntimeContext


# ---------------------------------------------------------------------------
# Minimal in-process fakes — kept here (not shared) so this test stays
# self-contained and the contract is visible at a glance.
# ---------------------------------------------------------------------------


@dataclass
class _S:
    def load(self, key: str) -> dict[str, Any]:
        return {}

    def save(self, key: str, value: dict[str, Any]) -> None: ...
    def delete(self, key: str) -> None: ...


@dataclass
class _St:
    def read_state(self) -> StateDocument:
        return StateDocument()

    def write_state(self, doc: StateDocument) -> None: ...
    def read_strategy(self) -> list[StrategyEntry]:
        return []

    def write_strategy(self, entries: list[StrategyEntry]) -> None: ...
    def append_action_log(self, entry: ActionLogEntry) -> None: ...


@dataclass
class _K:
    def read_operator_knowledge(self) -> str:
        return ""

    def read_workspace_knowledge(self) -> str | None:
        return None

    def append_operator_knowledge(self, insight: str) -> None: ...
    def append_workspace_knowledge(self, insight: str) -> None: ...


@dataclass
class _T:
    async def acquire(self, key: str) -> None: ...


def _ctx(workspace_id: str = "default") -> RuntimeContext:
    return RuntimeContext(
        secret_store=_S(),
        state_store=_St(),
        knowledge_store=_K(),
        throttle_store=_T(),
        workspace_id=workspace_id,
    )


# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_construct_with_all_protocols() -> None:
    ctx = _ctx()
    assert ctx.workspace_id == "default"


@pytest.mark.unit
def test_all_fields_round_trip_by_identity() -> None:
    """The dataclass must store the passed stores by identity — no eager
    wrapping or copying. Catches a future bug where someone introduces
    validation that swaps the referenced object."""
    s, st, k, t = _S(), _St(), _K(), _T()
    ctx = RuntimeContext(
        secret_store=s,
        state_store=st,
        knowledge_store=k,
        throttle_store=t,
        workspace_id="default",
    )
    assert ctx.secret_store is s
    assert ctx.state_store is st
    assert ctx.knowledge_store is k
    assert ctx.throttle_store is t


@pytest.mark.unit
def test_is_frozen() -> None:
    ctx = _ctx()
    with pytest.raises(FrozenInstanceError):
        ctx.workspace_id = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_workspace_id_required() -> None:
    """``workspace_id`` is mandatory — no implicit default — so callers must
    be explicit about whether they are in single-workspace ('default') or
    another mode. The canonical sentinel for single-workspace is the
    literal ``"default"``."""
    with pytest.raises(TypeError):
        RuntimeContext(  # type: ignore[call-arg]
            secret_store=_S(),
            state_store=_St(),
            knowledge_store=_K(),
            throttle_store=_T(),
        )


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", " ", "\t", "\n"])
def test_workspace_id_rejects_empty_or_whitespace(bad: str) -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        _ctx(workspace_id=bad)
