"""Tests for ``mureo.core.state_store.FilesystemStateStore`` — the
default in-process implementation that persists ``STATE.json`` /
``STRATEGY.md`` to a workspace directory (today: CWD).

The default delegates to the existing helpers in
``mureo.context.state`` and ``mureo.context.strategy`` so call-site
behaviour is preserved once the consumers are refactored in a follow-up
commit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mureo.context.models import ActionLogEntry, StateDocument, StrategyEntry
from mureo.core.state_store import FilesystemStateStore, StateStore


@pytest.mark.unit
def test_satisfies_protocol(tmp_path: Path) -> None:
    store = FilesystemStateStore(workspace=tmp_path)
    assert isinstance(store, StateStore)


@pytest.mark.unit
def test_read_state_missing_returns_empty_document(tmp_path: Path) -> None:
    """Mirrors ``read_state_file`` — a missing file is not an error."""
    store = FilesystemStateStore(workspace=tmp_path)
    assert store.read_state() == StateDocument()


@pytest.mark.unit
def test_write_then_read_state_round_trip(tmp_path: Path) -> None:
    store = FilesystemStateStore(workspace=tmp_path)
    doc = StateDocument(version="2", customer_id="123-456-7890")
    store.write_state(doc)
    assert (tmp_path / "STATE.json").exists()
    assert store.read_state() == doc


@pytest.mark.unit
def test_read_strategy_missing_returns_empty_list(tmp_path: Path) -> None:
    store = FilesystemStateStore(workspace=tmp_path)
    assert store.read_strategy() == []


@pytest.mark.unit
def test_write_then_read_strategy_round_trip(tmp_path: Path) -> None:
    store = FilesystemStateStore(workspace=tmp_path)
    entries = [
        StrategyEntry(context_type="persona", title="Persona", content="x"),
        StrategyEntry(context_type="usp", title="USP", content="y"),
    ]
    store.write_strategy(entries)
    assert (tmp_path / "STRATEGY.md").exists()
    assert store.read_strategy() == entries


@pytest.mark.unit
def test_read_strategy_returns_isolated_snapshot(tmp_path: Path) -> None:
    store = FilesystemStateStore(workspace=tmp_path)
    store.write_strategy([StrategyEntry(context_type="persona", title="T", content="x")])
    snap = store.read_strategy()
    snap.append(StrategyEntry(context_type="usp", title="U", content="y"))
    assert len(store.read_strategy()) == 1


@pytest.mark.unit
def test_append_action_log_accumulates(tmp_path: Path) -> None:
    store = FilesystemStateStore(workspace=tmp_path)
    e1 = ActionLogEntry(timestamp="2026-01-01T00:00:00Z", action="a", platform="g")
    e2 = ActionLogEntry(timestamp="2026-01-02T00:00:00Z", action="b", platform="m")
    store.append_action_log(e1)
    store.append_action_log(e2)
    assert store.read_state().action_log == (e1, e2)


@pytest.mark.unit
def test_append_action_log_creates_state_file_when_missing(tmp_path: Path) -> None:
    """``append_action_log`` against a workspace with no STATE.json must
    transparently create the file with a default StateDocument shell."""
    store = FilesystemStateStore(workspace=tmp_path)
    entry = ActionLogEntry(timestamp="2026-01-01T00:00:00Z", action="a", platform="g")
    store.append_action_log(entry)
    assert (tmp_path / "STATE.json").exists()
    assert store.read_state().action_log == (entry,)


@pytest.mark.unit
def test_workspace_paths_resolve_under_workspace_dir(tmp_path: Path) -> None:
    """Both files must sit alongside each other under the workspace dir so
    operator assets (creatives, briefs) can co-locate."""
    store = FilesystemStateStore(workspace=tmp_path)
    assert store.state_path == tmp_path / "STATE.json"
    assert store.strategy_path == tmp_path / "STRATEGY.md"


@pytest.mark.unit
def test_default_workspace_is_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    store = FilesystemStateStore()
    assert store.state_path == tmp_path / "STATE.json"
