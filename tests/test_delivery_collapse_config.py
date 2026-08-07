"""STRATEGY.md -> CollapseThresholds resolution (#546).

This module's entire job is one promise: **a broken STRATEGY.md must not
silently disable outage detection.** Every way the file can fail — absent,
unreadable, unparseable, full of nonsense — has to land on the built-in
defaults rather than on "no thresholds, no detection", so every one of
those paths is exercised here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mureo.analysis.delivery_collapse import CollapseThresholds
from mureo.analysis.delivery_collapse_config import (
    SOURCE_DEFAULTS,
    SOURCE_GUARDRAILS,
    load_collapse_thresholds,
    resolve_strategy_path,
)

pytestmark = pytest.mark.unit


GUARDRAILS = (
    "# Strategy\n\n"
    "## Guardrails\n"
    "- max_daily_budget_per_campaign: 50000\n"
    "- delivery_collapse_drop_pct: 70\n"
    "- delivery_collapse_consecutive_days: 2\n"
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the runtime context's state store at ``tmp_path``."""
    monkeypatch.chdir(tmp_path)

    class _Store:
        strategy_path = tmp_path / "STRATEGY.md"

    class _Context:
        state_store = _Store()

    monkeypatch.setattr(
        "mureo.core.runtime_context.get_runtime_context", lambda: _Context()
    )
    return tmp_path


def test_absent_strategy_file_yields_defaults(workspace: Path) -> None:
    thresholds, source = load_collapse_thresholds()

    assert thresholds == CollapseThresholds()
    assert source == SOURCE_DEFAULTS


def test_guardrails_are_read_and_reported_as_the_source(workspace: Path) -> None:
    (workspace / "STRATEGY.md").write_text(GUARDRAILS, encoding="utf-8")

    thresholds, source = load_collapse_thresholds()

    assert thresholds.drop_pct == pytest.approx(70.0)
    assert thresholds.consecutive_days == 2
    assert source == SOURCE_GUARDRAILS


def test_strategy_without_collapse_guardrails_reports_defaults(
    workspace: Path,
) -> None:
    """Only budget caps declared — the source must not claim otherwise."""
    (workspace / "STRATEGY.md").write_text(
        "## Guardrails\n- max_daily_budget_per_campaign: 50000\n", encoding="utf-8"
    )

    thresholds, source = load_collapse_thresholds()

    assert thresholds == CollapseThresholds()
    assert source == SOURCE_DEFAULTS


def test_unreadable_strategy_file_falls_open_to_defaults(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A permissions problem must not take outage detection offline."""
    path = workspace / "STRATEGY.md"
    path.write_text(GUARDRAILS, encoding="utf-8")

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _boom)

    thresholds, source = load_collapse_thresholds()

    assert thresholds == CollapseThresholds()
    assert source == SOURCE_DEFAULTS


def test_unparseable_strategy_file_falls_open_to_defaults(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (workspace / "STRATEGY.md").write_text(GUARDRAILS, encoding="utf-8")

    def _boom(_text: str) -> CollapseThresholds:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(
        "mureo.analysis.delivery_collapse_config."
        "collapse_thresholds_from_strategy_text",
        _boom,
    )

    thresholds, source = load_collapse_thresholds()

    assert thresholds == CollapseThresholds()
    assert source == SOURCE_DEFAULTS


def test_garbage_guardrail_values_do_not_disable_detection(workspace: Path) -> None:
    """One typo'd bullet drops that rule, never the whole section."""
    (workspace / "STRATEGY.md").write_text(
        "## Guardrails\n"
        "- delivery_collapse_drop_pct: quite a lot\n"
        "- delivery_collapse_consecutive_days: 3\n",
        encoding="utf-8",
    )

    thresholds, source = load_collapse_thresholds()

    assert thresholds.drop_pct == CollapseThresholds().drop_pct
    assert thresholds.consecutive_days == 3
    assert source == SOURCE_GUARDRAILS


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_path_comes_from_the_state_store_when_it_declares_one(
    workspace: Path,
) -> None:
    assert resolve_strategy_path() == workspace / "STRATEGY.md"


def test_path_falls_back_to_the_store_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Store:
        workspace = tmp_path / "ws"

    class _Context:
        state_store = _Store()

    monkeypatch.setattr(
        "mureo.core.runtime_context.get_runtime_context", lambda: _Context()
    )

    assert resolve_strategy_path() == tmp_path / "ws" / "STRATEGY.md"


def test_path_falls_back_to_cwd_when_the_context_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken runtime context must not break threshold resolution."""
    monkeypatch.chdir(tmp_path)

    def _boom() -> object:
        raise RuntimeError("no runtime context")

    monkeypatch.setattr("mureo.core.runtime_context.get_runtime_context", _boom)

    assert resolve_strategy_path() == Path.cwd() / "STRATEGY.md"


def test_thresholds_still_resolve_when_the_context_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "STRATEGY.md").write_text(GUARDRAILS, encoding="utf-8")

    def _boom() -> object:
        raise RuntimeError("no runtime context")

    monkeypatch.setattr("mureo.core.runtime_context.get_runtime_context", _boom)

    thresholds, source = load_collapse_thresholds()

    assert thresholds.consecutive_days == 2
    assert source == SOURCE_GUARDRAILS
