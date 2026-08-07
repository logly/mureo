"""The built-in Google Ads change feed and the MCP tool around it (#545).

Two things are pinned here that the platform-agnostic tests cannot reach:
the mapping from Google's ``change_event`` rows onto ``ExternalChange``
(without which mureo has no target identity and double-counts its own work),
and the honesty of the MCP tool's response when a platform cannot be polled.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.change_import import (
    ChangeFeedResult,
    clear_change_feed_registry,
    default_change_feed_registry,
    register_change_feed,
)
from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed, _row_to_change
from mureo.google_ads._extensions_targeting import CHANGE_HISTORY_ROW_LIMIT
from mureo.mcp import server as mcp_server
from mureo.mcp._handlers_change_import import handle_external_changes_import

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "resource_name": "customers/1/changeEvents/2026-08-05~1~2",
        "change_date_time": "2026-08-05 09:14:00",
        "change_resource_type": "CAMPAIGN_CRITERION",
        "changed_resource_name": "customers/1/campaignCriteria/111~99",
        "resource_change_operation": "CREATE",
        "changed_fields": ["campaign_criterion.negative"],
        "client_type": "GOOGLE_ADS_WEB_CLIENT",
        "user_email": "operator@example.com",
        "campaign": "customers/1/campaigns/111",
        "ad_group": "customers/1/adGroups/222",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    clear_change_feed_registry()
    default_change_feed_registry().clear()
    yield
    clear_change_feed_registry()


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache() -> Any:
    """Reset the workspace resolver cache around every test.

    ``resolve_workspace_path`` reads the cached RuntimeContext, so without
    this a host-installed ``mureo.runtime_context_factory`` (or an earlier
    test's cwd) decides which STATE.json the handler writes.
    """
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.mark.unit
class TestRowMapping:
    def test_identity_is_extracted_from_resource_names(self) -> None:
        change = _row_to_change(_row())
        assert change is not None
        assert change.campaign_id == "111"
        assert change.entity_type == "ad_group"
        assert change.entity_id == "222"

    def test_timestamp_is_normalised_to_parseable_iso(self) -> None:
        change = _row_to_change(_row())
        assert change is not None
        assert datetime.fromisoformat(change.occurred_at)

    def test_the_event_resource_name_becomes_the_dedup_id(self) -> None:
        change = _row_to_change(_row())
        assert change is not None
        assert change.change_id == "customers/1/changeEvents/2026-08-05~1~2"

    def test_an_unexpected_resource_path_yields_no_identity(self) -> None:
        """Better no id than a fabricated one — a wrong id mis-attributes."""
        change = _row_to_change(_row(campaign="something/else", ad_group=""))
        assert change is not None
        assert change.campaign_id is None
        assert change.entity_id is None

    def test_a_row_without_a_change_time_is_dropped(self) -> None:
        """Dating it 'now' would review it on the wrong schedule and would
        move the watermark past changes never seen."""
        assert _row_to_change(_row(change_date_time="")) is None


@pytest.mark.unit
class TestGoogleFeed:
    @pytest.mark.asyncio
    async def test_a_capped_response_is_reported_as_truncated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        feed = GoogleAdsChangeFeed()
        client = AsyncMock()
        client.list_change_history.return_value = [
            _row(resource_name=f"customers/1/changeEvents/{i}")
            for i in range(CHANGE_HISTORY_ROW_LIMIT)
        ]
        monkeypatch.setattr(feed, "_open_client", lambda _account: client)

        result = await feed.fetch_change_events("123", since=NOW, until=NOW)

        assert result.truncated is True
        assert any("unreachable" in note for note in result.notes)

    @pytest.mark.asyncio
    async def test_coverage_limits_are_always_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty window must still say what the feed cannot see."""
        feed = GoogleAdsChangeFeed()
        client = AsyncMock()
        client.list_change_history.return_value = []
        monkeypatch.setattr(feed, "_open_client", lambda _account: client)

        result = await feed.fetch_change_events("123", since=NOW, until=NOW)

        assert result.changes == ()
        assert result.truncated is False
        joined = " ".join(result.notes)
        assert "30 days" in joined
        assert "automated" in joined

    @pytest.mark.asyncio
    async def test_byod_says_so_rather_than_returning_a_quiet_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        feed = GoogleAdsChangeFeed()
        monkeypatch.setattr(feed, "_open_client", lambda _account: None)

        result = await feed.fetch_change_events("123", since=NOW, until=NOW)

        assert result.changes == ()
        assert any("BYOD" in note for note in result.notes)


class _StubFeed:
    platform = "google_ads"

    async def fetch_change_events(
        self, account_id: str, *, since: datetime, until: datetime
    ) -> ChangeFeedResult:
        return ChangeFeedResult(changes=())


@pytest.mark.unit
class TestMcpTool:
    @pytest.fixture()
    def state_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.chdir(tmp_path)
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        "google_ads": {"account_id": "123", "campaigns": []},
                        "meta_ads": {"account_id": "act_9", "campaigns": []},
                    },
                    "action_log": [],
                }
            ),
            encoding="utf-8",
        )
        return path

    @pytest.mark.asyncio
    async def test_the_tool_is_registered(self) -> None:
        tools = await mcp_server.handle_list_tools()
        assert "mureo_external_changes_import" in {t.name for t in tools}

    @pytest.mark.asyncio
    async def test_blind_spots_are_named_in_the_response(
        self, state_file: Path
    ) -> None:
        register_change_feed(_StubFeed())

        result = await handle_external_changes_import({})
        payload = json.loads(result[0].text)

        assert payload["blind_spots"] == ["meta_ads"]
        by_platform = {p["platform"]: p for p in payload["platforms"]}
        assert by_platform["google_ads"]["status"] == "imported"
        assert by_platform["meta_ads"]["status"] == "unavailable"
        assert (
            by_platform["meta_ads"]["reason"]
            == "change_import_unavailable_for_meta_ads"
        )
        assert payload["feeds_available_for"] == ["google_ads"]

    @pytest.mark.asyncio
    async def test_an_unparseable_since_is_refused_not_defaulted(
        self, state_file: Path
    ) -> None:
        """Falling back silently would report a window the caller never got."""
        register_change_feed(_StubFeed())
        with pytest.raises(ValueError, match="ISO 8601"):
            await handle_external_changes_import({"since": "last tuesday"})

    @pytest.mark.asyncio
    async def test_an_empty_platform_filter_is_refused(self, state_file: Path) -> None:
        with pytest.raises(ValueError, match="at least one"):
            await handle_external_changes_import({"platforms": []})
