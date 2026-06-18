"""Pure data builders behind the read-only reporting dashboard.

``mureo.web.reports`` reads STATE.json (via the active ``StateStore``
resolved from the runtime context) and shapes a JSON-safe, secret-free
summary the future dashboard renders. These tests cover:

  - platform-agnostic enumeration: built-in AND ``plugin:<dist>`` keys
    all appear, each with the right display name;
  - a plugin platform WITHOUT metrics still appears (totals empty), so a
    bridge shows up as advisory / no synced metrics;
  - ``recent_actions`` + ``reports`` are surfaced (no secrets);
  - empty / missing STATE.json → an empty-but-valid summary (never raises);
  - ``list_report_clients`` returns exactly one client for the default
    single workspace, and delegates to the Agency ``list_clients`` seam
    when the store advertises it.

The runtime context is reset around every test so a custom state store
injected here never leaks into another test.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.models import (
    ActionLogEntry,
    CampaignSnapshot,
    PlatformState,
    StateDocument,
)
from mureo.core.runtime_context import (
    default_runtime_context,
    get_runtime_context,
    reset_runtime_context,
)
from mureo.web.reports import build_report_summary, list_report_clients

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


def _write_state(workspace: Path, doc: StateDocument) -> None:
    """Persist ``doc`` to ``<workspace>/STATE.json`` via the active store."""
    from mureo.context.state import write_state_file

    write_state_file(workspace / "STATE.json", doc)


def _use_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    """Point the cached default runtime context at ``workspace``.

    Mirrors how production resolves STATE.json: through the active
    ``StateStore``'s ``state_path``. We seed the cache directly (no
    entry-point factory) so the builders read the temp workspace.
    """
    ctx = default_runtime_context(workspace=workspace)
    monkeypatch.setattr(
        "mureo.web.reports.get_runtime_context",
        lambda: ctx,
    )


# ---------------------------------------------------------------------------
# build_report_summary — platform-agnostic enumeration
# ---------------------------------------------------------------------------


def _mixed_state() -> StateDocument:
    """google_ads + meta_ads (both with metrics) + a plugin bridge."""
    google = PlatformState(
        account_id="123-456-7890",
        campaigns=(
            CampaignSnapshot(
                campaign_id="g1",
                campaign_name="Brand Search",
                status="ENABLED",
                metrics={"spend": 1000.0, "clicks": 200, "conversions": 10},
            ),
        ),
        totals={"spend": 1000.0, "clicks": 200, "conversions": 10},
        metrics_period="LAST_30_DAYS",
    )
    meta = PlatformState(
        account_id="act_999",
        campaigns=(
            CampaignSnapshot(
                campaign_id="m1",
                campaign_name="Retargeting",
                status="ACTIVE",
                metrics={"spend": 500.0, "result_indicator": "link_click"},
            ),
        ),
        totals={"spend": 500.0, "impressions": 9000},
        metrics_period="LAST_7_DAYS",
    )
    # A plugin/bridge platform WITH metrics.
    logly = PlatformState(
        account_id="logly-acct-1",
        campaigns=(
            CampaignSnapshot(
                campaign_id="l1",
                campaign_name="Logly Native",
                status="RUNNING",
                metrics={"spend": 250.0, "impressions": 4000},
            ),
        ),
        totals={"spend": 250.0, "impressions": 4000},
        metrics_period="LAST_30_DAYS",
    )
    # A plugin/bridge platform WITHOUT metrics (advisory only).
    advisory = PlatformState(account_id="adv-1")
    return StateDocument(
        version="2",
        last_synced_at="2026-06-17T09:00:00+00:00",
        platforms={
            "google_ads": google,
            "meta_ads": meta,
            "plugin:mureo-logly-bridge": logly,
            "plugin:acme-ads": advisory,
        },
        action_log=(
            ActionLogEntry(
                timestamp="2026-06-16T10:00:00+00:00",
                action="budget_update",
                platform="google_ads",
                campaign_id="g1",
                summary="raised daily budget",
                observation_due="2026-06-23",
                # A secret-shaped field that must NEVER surface.
                command="google_ads_budget_update --token=SECRET123",
            ),
        ),
        reports={"daily": {"verdict": "Healthy", "note": "all good"}},
    )


@pytest.mark.unit
def test_summary_lists_every_platform_with_display_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _mixed_state())

    summary = build_report_summary()
    by_key = {p["key"]: p for p in summary["platforms"]}

    assert set(by_key) == {
        "google_ads",
        "meta_ads",
        "plugin:mureo-logly-bridge",
        "plugin:acme-ads",
    }
    assert by_key["google_ads"]["display_name"] == "Google Ads"
    assert by_key["meta_ads"]["display_name"] == "Meta Ads"
    # plugin:<dist> → humanized label dropping the mureo- prefix.
    assert by_key["plugin:mureo-logly-bridge"]["display_name"] == "Logly (plugin)"
    assert by_key["plugin:acme-ads"]["display_name"] == "Acme Ads (plugin)"


@pytest.mark.unit
def test_summary_carries_totals_period_and_campaign_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _mixed_state())

    by_key = {p["key"]: p for p in build_report_summary()["platforms"]}
    google = by_key["google_ads"]
    assert google["totals"] == {"spend": 1000.0, "clicks": 200, "conversions": 10}
    assert google["metrics_period"] == "LAST_30_DAYS"
    assert google["campaign_count"] == 1


@pytest.mark.unit
def test_plugin_platform_without_metrics_still_appears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _mixed_state())

    by_key = {p["key"]: p for p in build_report_summary()["platforms"]}
    advisory = by_key["plugin:acme-ads"]
    # Totals null/empty + no period → the frontend renders "advisory /
    # no synced metrics". The platform is NOT dropped.
    assert advisory["totals"] in (None, {})
    assert advisory["metrics_period"] is None
    assert advisory["campaign_count"] == 0


@pytest.mark.unit
def test_summary_surfaces_recent_actions_and_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _mixed_state())

    summary = build_report_summary()
    assert summary["last_synced_at"] == "2026-06-17T09:00:00+00:00"
    assert summary["reports"] == {"daily": {"verdict": "Healthy", "note": "all good"}}

    assert len(summary["recent_actions"]) == 1
    action = summary["recent_actions"][0]
    assert action["action"] == "budget_update"
    assert action["platform"] == "google_ads"
    assert action["campaign_id"] == "g1"
    assert action["summary"] == "raised daily budget"
    assert action["observation_due"] == "2026-06-23"


@pytest.mark.unit
def test_summary_never_leaks_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    _write_state(tmp_path, _mixed_state())

    import json

    blob = json.dumps(build_report_summary())
    # The action's ``command`` carried a token; it must not be relayed.
    assert "SECRET123" not in blob
    assert "--token" not in blob
    assert "command" not in blob
    # Per-platform ``account_id`` is never surfaced.
    assert "123-456-7890" not in blob
    assert "act_999" not in blob
    assert "logly-acct-1" not in blob


@pytest.mark.unit
def test_totals_whitelist_strips_non_canonical_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stray/secret-shaped key in ``totals`` must not reach the dashboard —
    only the canonical metric vocabulary survives."""
    _use_workspace(monkeypatch, tmp_path)
    state = StateDocument(
        version="2",
        platforms={
            "google_ads": PlatformState(
                account_id="acct-x",
                totals={
                    "spend": 100.0,
                    "conversions": 5,
                    "api_token": "SHOULD_NOT_LEAK",
                    "account_id": "acct-x",
                },
            )
        },
    )
    _write_state(tmp_path, state)

    summary = build_report_summary()
    totals = summary["platforms"][0]["totals"]
    assert totals == {"spend": 100.0, "conversions": 5}
    import json

    assert "SHOULD_NOT_LEAK" not in json.dumps(summary)


@pytest.mark.unit
def test_recent_actions_limited_to_last_n(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    entries = tuple(
        ActionLogEntry(
            timestamp=f"2026-06-{i:02d}T00:00:00+00:00",
            action=f"action_{i}",
            platform="google_ads",
        )
        for i in range(1, 31)
    )
    _write_state(tmp_path, StateDocument(version="2", action_log=entries))

    actions = build_report_summary()["recent_actions"]
    # Capped, and the LAST entries (most recent) are kept.
    assert len(actions) <= 20
    assert actions[-1]["action"] == "action_30"


# ---------------------------------------------------------------------------
# build_report_summary — empty / missing STATE.json
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_summary_empty_when_state_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    # No STATE.json written at all.
    summary = build_report_summary()
    assert summary["platforms"] == []
    assert summary["recent_actions"] == []
    assert summary["reports"] in (None, {})
    assert summary["last_synced_at"] is None
    # The client field reflects the active workspace, never raises.
    assert "client" in summary


@pytest.mark.unit
def test_summary_does_not_raise_on_broken_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    (tmp_path / "STATE.json").write_text("{ this is not valid json", encoding="utf-8")
    # Malformed STATE.json must degrade to an empty-but-valid summary.
    summary = build_report_summary()
    assert summary["platforms"] == []
    assert summary["recent_actions"] == []


# ---------------------------------------------------------------------------
# list_report_clients
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_clients_single_for_default_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    clients = list_report_clients()
    assert len(clients) == 1
    only = clients[0]
    assert only["active"] is True
    assert only["slug"]  # non-empty
    assert "name" in only


@pytest.mark.unit
def test_list_clients_delegates_to_agency_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the active state store advertises ``list_clients`` (an Agency
    backend), the builder delegates to it instead of synthesizing one."""

    class _AgencyStore:
        workspace_id = "agency"

        def list_clients(self) -> list[dict[str, Any]]:
            return [
                {"slug": "acme", "name": "Acme Co", "active": True},
                {"slug": "globex", "name": "Globex", "active": False},
            ]

    ctx = dataclasses.replace(default_runtime_context(), state_store=_AgencyStore())
    monkeypatch.setattr("mureo.web.reports.get_runtime_context", lambda: ctx)

    clients = list_report_clients()
    assert [c["slug"] for c in clients] == ["acme", "globex"]
    assert clients[0]["active"] is True


@pytest.mark.unit
def test_get_runtime_context_importable() -> None:
    """Smoke: the resolver is reachable (used by the builders)."""
    assert get_runtime_context() is not None
