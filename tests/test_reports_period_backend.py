"""Period-toggle backend for the read-only reporting dashboard.

These tests cover the ``periods`` extension layered onto the single-rollup
reporting model (``PlatformState.totals`` / ``metrics_period``):

  - ``PlatformState.periods`` model field: defensive copy + round-trip
    through ``STATE.json`` (emitted only when non-empty → legacy files stay
    byte-stable), and preservation across a campaign upsert;
  - ``build_report_summary(period=...)`` window selection:
      * ``period is None`` → backward-compatible passthrough (no regression);
      * a set ``period`` → totals resolved for that window from ``periods``;
      * legacy fallback ONLY when ``metrics_period`` matches the window
        (never mislabels a different window's totals);
      * an explicit ``periods`` key is authoritative over the legacy rollup;
      * secret-shaped keys inside a period bucket are whitelisted away;
  - ``summary["periods"]``: union of windows present anywhere, in canonical
    toggle order.

The runtime context is reset around every test so an injected state store
never leaks into another test.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.context.models import (
    CampaignSnapshot,
    PlatformState,
    StateDocument,
)
from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
)
from mureo.web.reports import build_report_summary

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


def _write_state(workspace: Path, doc: StateDocument) -> None:
    from mureo.context.state import write_state_file

    write_state_file(workspace / "STATE.json", doc)


def _use_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    ctx = default_runtime_context(workspace=workspace)
    monkeypatch.setattr("mureo.web.reports.get_runtime_context", lambda: ctx)


def _row(summary: dict, key: str) -> dict:
    return next(p for p in summary["platforms"] if p["key"] == key)


# ---------------------------------------------------------------------------
# Model: defensive copy + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_periods_defensive_copy_on_construct() -> None:
    """Mutating the dict passed in must not mutate the stored periods."""
    src = {"YESTERDAY": {"spend": 10.0}}
    state = PlatformState(account_id="x", periods=src)
    src["YESTERDAY"]["spend"] = 999.0
    src["LAST_30_DAYS"] = {"spend": 1.0}
    assert state.periods == {"YESTERDAY": {"spend": 10.0}}


@pytest.mark.unit
def test_periods_round_trip_through_state_file(tmp_path: Path) -> None:
    """periods survive a write→read cycle unchanged."""
    from mureo.context.state import read_state_file

    doc = StateDocument(
        version="2",
        platforms={
            "google_ads": PlatformState(
                account_id="123",
                periods={
                    "YESTERDAY": {"spend": 100.0, "conversions": 2},
                    "LAST_30_DAYS": {"spend": 3000.0, "conversions": 60},
                },
            )
        },
    )
    _write_state(tmp_path, doc)
    reloaded = read_state_file(tmp_path / "STATE.json")
    assert reloaded.platforms is not None
    assert reloaded.platforms["google_ads"].periods == {
        "YESTERDAY": {"spend": 100.0, "conversions": 2},
        "LAST_30_DAYS": {"spend": 3000.0, "conversions": 60},
    }


@pytest.mark.unit
def test_periods_omitted_from_json_when_absent(tmp_path: Path) -> None:
    """A platform with no periods emits no ``periods`` key (legacy-stable)."""
    doc = StateDocument(
        version="2",
        platforms={
            "google_ads": PlatformState(
                account_id="123",
                totals={"spend": 5.0},
                metrics_period="LAST_30_DAYS",
            )
        },
    )
    _write_state(tmp_path, doc)
    raw = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
    assert "periods" not in raw["platforms"]["google_ads"]


@pytest.mark.unit
def test_periods_preserved_across_campaign_upsert(tmp_path: Path) -> None:
    """A campaign upsert must not wipe the per-period rollups."""
    from mureo.context.state import read_state_file, upsert_campaign

    path = tmp_path / "STATE.json"
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    periods={"YESTERDAY": {"spend": 7.0}},
                )
            },
        ),
    )
    upsert_campaign(
        path,
        CampaignSnapshot(campaign_id="g1", campaign_name="New", status="ENABLED"),
        platform="google_ads",
        account_id="123",
    )
    reloaded = read_state_file(path)
    assert reloaded.platforms is not None
    assert reloaded.platforms["google_ads"].periods == {"YESTERDAY": {"spend": 7.0}}


# ---------------------------------------------------------------------------
# build_report_summary — window selection
# ---------------------------------------------------------------------------


def _periods_state() -> StateDocument:
    """google_ads with both windows; meta_ads with only the legacy rollup."""
    google = PlatformState(
        account_id="123",
        campaigns=(
            CampaignSnapshot(campaign_id="g1", campaign_name="Brand", status="ENABLED"),
        ),
        periods={
            "YESTERDAY": {"spend": 100.0, "conversions": 2},
            "LAST_30_DAYS": {"spend": 3000.0, "conversions": 60},
        },
    )
    # Legacy single-rollup platform: no periods, only totals/metrics_period.
    meta = PlatformState(
        account_id="act_9",
        totals={"spend": 500.0, "impressions": 9000},
        metrics_period="LAST_30_DAYS",
    )
    return StateDocument(
        version="2",
        last_synced_at="2026-06-17T09:00:00+00:00",
        platforms={"google_ads": google, "meta_ads": meta},
    )


@pytest.mark.unit
def test_period_none_is_backward_compatible_passthrough(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No period → stored single rollup returned as-is (no regression)."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _periods_state())

    summary = build_report_summary()  # period defaults to None
    meta = _row(summary, "meta_ads")
    assert meta["totals"] == {"spend": 500.0, "impressions": 9000}
    assert meta["metrics_period"] == "LAST_30_DAYS"


@pytest.mark.unit
def test_period_selects_from_periods_dict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _periods_state())

    yesterday = _row(build_report_summary(period="YESTERDAY"), "google_ads")
    assert yesterday["totals"] == {"spend": 100.0, "conversions": 2}
    assert yesterday["metrics_period"] == "YESTERDAY"

    last30 = _row(build_report_summary(period="LAST_30_DAYS"), "google_ads")
    assert last30["totals"] == {"spend": 3000.0, "conversions": 60}
    assert last30["metrics_period"] == "LAST_30_DAYS"


@pytest.mark.unit
def test_legacy_rollup_used_only_when_window_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Legacy totals fill a window iff metrics_period equals it."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _periods_state())

    # meta_ads has metrics_period=LAST_30_DAYS → request matches → totals shown.
    matched = _row(build_report_summary(period="LAST_30_DAYS"), "meta_ads")
    assert matched["totals"] == {"spend": 500.0, "impressions": 9000}
    assert matched["metrics_period"] == "LAST_30_DAYS"

    # Request YESTERDAY → no match, never mislabel → no totals for the window.
    mismatched = _row(build_report_summary(period="YESTERDAY"), "meta_ads")
    assert mismatched["totals"] is None
    assert mismatched["metrics_period"] is None


@pytest.mark.unit
def test_explicit_period_bucket_is_authoritative_over_legacy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A present periods key wins over the legacy rollup for that window."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    totals={"spend": 999.0},  # legacy says 999...
                    metrics_period="LAST_30_DAYS",
                    periods={"LAST_30_DAYS": {"spend": 42.0}},  # ...periods says 42
                )
            },
        ),
    )
    row = _row(build_report_summary(period="LAST_30_DAYS"), "google_ads")
    assert row["totals"] == {"spend": 42.0}


@pytest.mark.unit
def test_legacy_fills_window_periods_does_not_cover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """periods present but missing the window → matching legacy rollup fills it."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    totals={"spend": 3000.0},
                    metrics_period="LAST_30_DAYS",
                    # periods only covers YESTERDAY; LAST_30_DAYS must fall back.
                    periods={"YESTERDAY": {"spend": 100.0}},
                )
            },
        ),
    )
    row = _row(build_report_summary(period="LAST_30_DAYS"), "google_ads")
    assert row["totals"] == {"spend": 3000.0}
    assert row["metrics_period"] == "LAST_30_DAYS"


@pytest.mark.unit
@pytest.mark.parametrize("bucket", [None, "not-a-dict", 42, ["spend", 1]])
def test_malformed_period_bucket_degrades_to_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bucket: object
) -> None:
    """A non-dict period bucket yields None totals, never raises."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    periods={"YESTERDAY": bucket},  # type: ignore[dict-item]
                )
            },
        ),
    )
    row = _row(build_report_summary(period="YESTERDAY"), "google_ads")
    assert row["totals"] is None
    assert row["metrics_period"] is None


@pytest.mark.unit
def test_available_periods_ignores_non_str_and_empty_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only non-empty string window tokens are advertised in periods."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    periods={"YESTERDAY": {"spend": 1.0}, "": {"spend": 2.0}},
                )
            },
        ),
    )
    assert build_report_summary()["periods"] == ["YESTERDAY"]


@pytest.mark.unit
def test_period_bucket_whitelists_secret_shaped_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stray/secret-shaped key inside a period bucket never surfaces."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    periods={
                        "YESTERDAY": {
                            "spend": 10.0,
                            "refresh_token": "SECRET",
                            "account_id": "123-456",
                        }
                    },
                )
            },
        ),
    )
    row = _row(build_report_summary(period="YESTERDAY"), "google_ads")
    assert row["totals"] == {"spend": 10.0}
    assert "refresh_token" not in row["totals"]
    assert "account_id" not in row["totals"]


@pytest.mark.unit
def test_summary_periods_union_in_canonical_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """periods lists every window present anywhere, canonical order first."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _periods_state())

    # google_ads → {YESTERDAY, LAST_30_DAYS}; meta_ads legacy → {LAST_30_DAYS}.
    assert build_report_summary()["periods"] == ["YESTERDAY", "LAST_30_DAYS"]


@pytest.mark.unit
def test_summary_periods_unknown_window_sorts_after_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    periods={
                        "LAST_30_DAYS": {"spend": 1.0},
                        "THIS_MONTH": {"spend": 2.0},
                        "YESTERDAY": {"spend": 3.0},
                    },
                )
            },
        ),
    )
    # Known order (YESTERDAY, LAST_30_DAYS) first; unknown (THIS_MONTH) last.
    assert build_report_summary()["periods"] == [
        "YESTERDAY",
        "LAST_30_DAYS",
        "THIS_MONTH",
    ]


@pytest.mark.unit
def test_summary_periods_empty_when_no_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No rollups anywhere → empty periods so the toggle stays hidden."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={"google_ads": PlatformState(account_id="123")},
        ),
    )
    assert build_report_summary()["periods"] == []
