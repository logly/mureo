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
from mureo.change_import.builtin.google_ads import (
    _CRITERION_RESOURCE_TYPES,
    GoogleAdsChangeFeed,
    _row_to_change,
)
from mureo.google_ads._extensions_targeting import CHANGE_HISTORY_ROW_LIMIT
from mureo.mcp import server as mcp_server
from mureo.mcp._handlers_change_import import handle_external_changes_import

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "resource_name": "customers/1/changeEvents/2026-08-05~1~2",
        "change_date_time": "2026-08-05 09:14:00",
        "change_resource_type": "CAMPAIGN_CRITERION",
        "change_resource_name": "customers/1/campaignCriteria/111~99",
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
    def test_a_row_with_only_an_ad_group_names_the_ad_group(self) -> None:
        change = _row_to_change(
            _row(change_resource_type="AD_GROUP", change_resource_name="")
        )
        assert change is not None
        assert change.campaign_id == "111"
        assert change.entity_type == "ad_group"
        assert change.entity_id == "222"

    def test_resource_name_segments_match_the_sdk_path_builders(self) -> None:
        """Every path segment this adapter parses must be one the SDK mints.

        The segments are the other half of the fabricated-field class of bug:
        a wrong one silently yields "no identity" rather than raising, so the
        adapter would keep working and simply stop recognising its targets.
        Asserted against the SDK's own ``*_path`` builders rather than
        hardcoded strings, so a rename in a future API version fails here.
        """
        from google.ads.googleads.v23.services.services.ad_group_ad_service import (
            AdGroupAdServiceClient,
        )
        from google.ads.googleads.v23.services.services.ad_group_bid_modifier_service import (  # noqa: E501
            AdGroupBidModifierServiceClient,
        )
        from google.ads.googleads.v23.services.services.ad_group_criterion_service import (  # noqa: E501
            AdGroupCriterionServiceClient,
        )
        from google.ads.googleads.v23.services.services.ad_service import (
            AdServiceClient,
        )
        from google.ads.googleads.v23.services.services.campaign_criterion_service import (  # noqa: E501
            CampaignCriterionServiceClient,
        )

        def segment(resource_name: str) -> str:
            return resource_name.split("/")[-2]

        assert segment(AdServiceClient.ad_path("1", "999")) == "ads"
        assert (
            segment(AdGroupAdServiceClient.ad_group_ad_path("1", "222", "999"))
            == "adGroupAds"
        )
        expected = {
            "AD_GROUP_CRITERION": segment(
                AdGroupCriterionServiceClient.ad_group_criterion_path("1", "222", "777")
            ),
            "CAMPAIGN_CRITERION": segment(
                CampaignCriterionServiceClient.campaign_criterion_path(
                    "1", "111", "777"
                )
            ),
            "AD_GROUP_BID_MODIFIER": segment(
                AdGroupBidModifierServiceClient.ad_group_bid_modifier_path(
                    "1", "222", "777"
                )
            ),
        }
        assert {
            key: value[0] for key, value in _CRITERION_RESOURCE_TYPES.items()
        } == expected

    @pytest.mark.parametrize(
        ("resource_type", "change_resource_name", "entity_type"),
        [
            (
                "AD_GROUP_CRITERION",
                "customers/1/adGroupCriteria/222~777",
                "ad_group_criterion",
            ),
            (
                "CAMPAIGN_CRITERION",
                "customers/1/campaignCriteria/111~777",
                "campaign_criterion",
            ),
            # Not reachable through mureo's own tools (device bids go through
            # CampaignCriterionService), but an operator's UI edit reaches the
            # feed — and this is a feed of changes mureo did not make.
            (
                "AD_GROUP_BID_MODIFIER",
                "customers/1/adGroupBidModifiers/222~777",
                "ad_group_bid_modifier",
            ),
        ],
        ids=["ad_group_criterion", "campaign_criterion", "ad_group_bid_modifier"],
    )
    def test_a_criterion_row_names_the_CRITERION_not_its_parent(
        self, resource_type: str, change_resource_name: str, entity_type: str
    ) -> None:
        """Two keywords in one ad group are two different things to edit.

        Collapsing them onto the shared ad group is what let an operator's
        edit to one keyword read as mureo's edit to a sibling keyword, so the
        criterion — not its parent — is the canonical target.
        """
        change = _row_to_change(
            _row(
                change_resource_type=resource_type,
                change_resource_name=change_resource_name,
            )
        )
        assert change is not None
        assert change.campaign_id == "111"
        assert change.entity_type == entity_type
        assert change.entity_id == "777"

    def test_an_unresolvable_criterion_row_claims_no_sub_campaign_target(self) -> None:
        change = _row_to_change(
            _row(change_resource_type="AD_GROUP_CRITERION", change_resource_name="odd")
        )
        assert change is not None
        assert change.entity_id is None
        assert change.campaign_id == "111"

    @pytest.mark.parametrize(
        ("resource_type", "change_resource_name"),
        [
            # AdGroupAdService — a status toggle.
            ("AD_GROUP_AD", "customers/1/adGroupAds/222~999"),
            # AdService — ``google_ads_ads_update``, i.e. every creative edit.
            # No ad-group segment and no "~", so a parser that only knows the
            # composite shape leaves these rows with nothing below the
            # campaign and re-imports every creative edit as external.
            ("AD", "customers/1/ads/999"),
        ],
        ids=["ad_group_ad", "ad"],
    )
    def test_an_ad_level_row_names_the_AD_not_its_ad_group(
        self, resource_type: str, change_resource_name: str
    ) -> None:
        """One canonical target per row, matching mureo's own convention.

        Reporting both the ad and its parent ad group would make the feed row
        look strictly more specific than mureo's own record of the same
        change, and attribution requires equal specificity — so mureo's
        ad-level work would re-import as external on every run.
        """
        change = _row_to_change(
            _row(
                change_resource_type=resource_type,
                change_resource_name=change_resource_name,
            )
        )
        assert change is not None
        assert change.ad_id == "999"
        assert change.entity_id is None
        assert change.campaign_id == "111"

    def test_an_unresolvable_ad_row_claims_no_sub_campaign_target(self) -> None:
        """Falling back to the ad group would claim specificity it lacks."""
        change = _row_to_change(
            _row(change_resource_type="AD_GROUP_AD", change_resource_name="weird")
        )
        assert change is not None
        assert change.ad_id is None
        assert change.entity_id is None
        assert change.campaign_id == "111"

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
        change = _row_to_change(
            _row(
                change_resource_type="AD_GROUP",
                campaign="something/else",
                ad_group="",
                change_resource_name="",
            )
        )
        assert change is not None
        assert change.campaign_id is None
        assert change.entity_id is None

    def test_a_row_without_a_change_time_is_dropped(self) -> None:
        """Dating it 'now' would review it on the wrong schedule and would
        move the watermark past changes never seen."""
        assert _row_to_change(_row(change_date_time="")) is None

    def test_a_real_change_event_row_classifies_end_to_end(self) -> None:
        """The whole path, from the row the API returns to the kind (#588).

        Every test above starts from a hand-written row dict, which is where
        this feed's worst defect hid: the mapper emitted a bare ``str()`` of
        the enum field, and mureo builds its Google Ads client with the SDK
        default ``use_proto_plus=False``, so that field is a plain ``int`` and
        the string was "2" — while every consumer keys on "AD". Classification
        missed every time and each imported change fell through to kind ``""``
        with nothing raised and nothing logged.

        So this drives ``map_change_event`` with the RAW PROTOBUF the search
        interceptor hands back — ``convert_proto_plus_to_protobuf`` is exactly
        what the SDK does — and asserts the kind at the far end. Building the
        proto-plus object and passing it straight in would test a shape
        production never produces, which is how the first attempt at this fix
        passed while changing nothing.
        """
        from google.ads.googleads import util
        from google.ads.googleads.v23.resources.types.change_event import ChangeEvent

        from mureo.change_import.dedupe import (
            _OPERATION_ALIASES,
            KIND_AD,
            change_kind,
        )
        from mureo.google_ads.mappers import map_change_event

        event = ChangeEvent(
            resource_name="customers/1/changeEvents/2026-08-05~1~2",
            change_date_time="2026-08-05 09:14:00",
            change_resource_name="customers/1/ads/999",
            campaign="customers/1/campaigns/111",
            ad_group="customers/1/adGroups/222",
        )
        event.change_resource_type = 2  # AD
        event.resource_change_operation = 3  # UPDATE
        event.changed_fields.paths.append("ad.final_urls")
        raw = util.convert_proto_plus_to_protobuf(event)
        assert isinstance(raw.change_resource_type, int)  # the production shape

        change = _row_to_change(map_change_event(raw))

        assert change is not None
        assert change.resource_type == "AD"
        # The point of the fix: the kind resolves instead of being "".
        assert change_kind(change) == KIND_AD
        assert _OPERATION_ALIASES.get(change.operation) == "update"
        # And the ad-level identity, which is keyed on the same string.
        assert change.ad_id == "999"


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
        """BYOD has no change history, so nothing was LOOKED at.

        The assertion is on ``unavailable_reason``, not on ``notes``: notes
        are prose an operator may or may not read, while
        ``unavailable_reason`` is what routes the platform to
        ``ChangeImportStatus.UNAVAILABLE`` and into ``blind_spots``. An
        earlier version of this test checked only the note and passed while
        the platform was still being reported as checked.
        """
        feed = GoogleAdsChangeFeed()
        monkeypatch.setattr(feed, "_open_client", lambda _account: None)

        result = await feed.fetch_change_events("123", since=NOW, until=NOW)

        assert result.changes == ()
        assert "BYOD" in result.unavailable_reason

    @pytest.mark.asyncio
    async def test_byod_reaches_the_blind_spots_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end: the BYOD signal must survive all the way to the tool.

        ``/daily-check`` step 2b tells the agent that a platform absent from
        ``blind_spots`` was looked at, so this is the assertion that matters.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "STATE.json").write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {"google_ads": {"account_id": "123", "campaigns": []}},
                    "action_log": [],
                }
            ),
            encoding="utf-8",
        )
        feed = GoogleAdsChangeFeed()
        monkeypatch.setattr(feed, "_open_client", lambda _account: None)
        register_change_feed(feed)

        payload = json.loads((await handle_external_changes_import({}))[0].text)

        assert payload["blind_spots"] == ["google_ads"]
        assert payload["platforms"][0]["status"] == "unavailable"


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
