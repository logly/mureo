"""The ChatGPT Ads change feed: the audit log as external changes (#994).

Requests go feed → client → ``httpx.MockTransport``, checked against the
contract fixture. Rows are mapped by the pure ``_row_to_change``; the
attribution matrix runs mureo's own deduper against the identity each change
tool declares, so the feed and the tools cannot drift apart unnoticed.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from mureo.bundled_providers import register_bundled_providers
from mureo.change_import import (
    ChangeImportStatus,
    ImportVerdict,
    classify_change,
    clear_change_feed_registry,
    default_change_feed_registry,
    import_external_changes,
    plugin_source,
    resolve_change_feed,
)
from mureo.change_import.registry import ChangeFeedWarning
from mureo.chatgpt_ads import change_feed, handlers
from mureo.chatgpt_ads._api import (
    CHANGE_FEED_ROW_CAP,
    MAX_CHANGED_FIELDS,
    MAX_PAGES_PER_CALL,
    PAGE_MAX_AUDIT_LOGS,
)
from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError
from mureo.chatgpt_ads.change_feed import (
    ChatGPTAdsChangeFeed,
    _row_to_change,
    _token,
)
from mureo.chatgpt_ads.provider import (
    CHATGPT_ADS_SOURCE_DISTRIBUTION,
    ChatGPTAdsProvider,
    register_chatgpt_ads_provider,
)
from mureo.context.models import EXTERNAL_ORIGIN, ActionLogEntry
from mureo.context.state import append_action_log, read_state_file
from mureo.core.auth_failure import AUTH_CAUSE_NO_CREDENTIALS, PlatformAuthError
from mureo.core.providers.registry import ProviderEntry, default_registry
from mureo.mcp.plugin_semantics import derive_semantics, extract_mutation_identity
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI, page

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

KEY = "plugin:mureo-chatgpt-ads:chatgpt_ads"
#: The documented example row's timestamp: 2026-03-02 00:00:00 UTC.
TS = 1772409600
SINCE = datetime(2026, 3, 1, tzinfo=timezone.utc)
UNTIL = datetime(2026, 3, 2, 12, tzinfo=timezone.utc)
START = int(SINCE.timestamp())
END = int(UNTIL.timestamp())
ACCOUNT = "adacct_1"

#: The API reference's example audit-log row.
DOCUMENTED_ROW: dict[str, Any] = {
    "id": "alog_123",
    "audit_log_type": "update_campaign",
    "obj_type": "Campaign",
    "obj_id": "cmpn_123",
    "item_name": "Spring sale",
    "actor_type": "user",
    "actor_id": "user_123",
    "campaign_id": "cmpn_123",
    "ad_group_id": None,
    "changes": {
        "obj_type": "Campaign",
        "name": {"before": "Spring", "after": "Spring sale"},
    },
    "hierarchy_info": {},
    "ts": TS,
}


def _row(**overrides: Any) -> dict[str, Any]:
    return {**DOCUMENTED_ROW, **overrides}


def _map(row: object) -> Any:
    return _row_to_change(row, START, END)


def _rows(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [_row(id=f"alog_{i}", ts=TS + i) for i in range(start, start + count)]


@pytest.fixture()
def _clean_feeds() -> Iterator[None]:
    """An empty change-feed registry (built-ins included), restored after."""
    clear_change_feed_registry()
    default_change_feed_registry().clear()
    yield
    clear_change_feed_registry()


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI()
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: fake.client())
    fake.add("/ad_account", body={"id": ACCOUNT, "timezone": "UTC"})
    return fake


async def _fetch(account_id: str = ACCOUNT) -> Any:
    return await ChatGPTAdsChangeFeed().fetch_change_events(
        account_id, since=SINCE, until=UNTIL
    )


def _audit_params(api: FakeAPI, index: int = -1) -> dict[str, str]:
    requests = [r for r in api.requests if r.url.path == "/v1/audit_logs"]
    return dict(requests[index].url.params.multi_items())


class TestRequest:
    async def test_window_order_page_size_and_cursor(self, api: FakeAPI) -> None:
        api.add("/audit_logs", body=page(_rows(100), has_more=True))
        api.add("/audit_logs", body=page(_rows(2, 100), has_more=False))

        result = await _fetch()

        assert len(result.changes) == 102
        assert [r.url.path for r in api.requests] == [
            "/v1/ad_account",
            "/v1/audit_logs",
            "/v1/audit_logs",
        ]
        first = _audit_params(api, 0)
        assert first["start_time"] == str(int(SINCE.timestamp()))
        assert first["end_time"] == str(int(UNTIL.timestamp()))
        assert first["order"] == "asc"
        assert first["limit"] == "100"
        assert "after" not in first
        second = _audit_params(api, 1)
        assert second["after"] == "alog_99"
        assert second["limit"] == "100"
        assert second["order"] == "asc"

    def test_the_platform_is_the_registry_name(self) -> None:
        assert ChatGPTAdsChangeFeed.platform == "chatgpt_ads"


class TestRowMapping:
    def test_documented_row_field_by_field(self) -> None:
        change = _map(DOCUMENTED_ROW)
        assert change is not None
        assert change.platform == "chatgpt_ads"
        assert change.occurred_at == "2026-03-02T00:00:00+00:00"
        assert change.resource_type == "CAMPAIGN"
        assert change.operation == "UPDATE"
        assert change.change_id == "alog_123"
        assert change.changed_fields == ("name",)
        assert change.actor == "user_123"
        assert change.client_type == ""
        assert change.campaign_id == "cmpn_123"
        assert change.ad_id is None
        assert change.entity_type is None
        assert change.entity_id is None

    def test_ad_group_row(self) -> None:
        change = _map(_row(obj_type="AdGroup", obj_id="adgrp_1", campaign_id="cmpn_9"))
        assert change is not None
        assert change.resource_type == "AD_GROUP"
        assert (change.entity_type, change.entity_id) == ("ad_group", "adgrp_1")
        assert change.campaign_id == "cmpn_9"
        assert change.ad_id is None

    def test_ad_row_names_the_ad_not_its_ad_group(self) -> None:
        change = _map(
            _row(
                obj_type="Ad",
                obj_id="ad_1",
                campaign_id="cmpn_9",
                ad_group_id="adgrp_1",
            )
        )
        assert change is not None
        assert change.resource_type == "AD"
        assert change.ad_id == "ad_1"
        assert change.campaign_id == "cmpn_9"
        assert change.entity_id is None
        assert change.entity_type is None

    def test_parent_campaign_is_optional(self) -> None:
        change = _map(_row(obj_type="ad_group", obj_id="g", campaign_id=None))
        assert change is not None
        assert change.resource_type == "AD_GROUP"
        assert change.entity_id == "g"
        assert change.campaign_id is None

    @pytest.mark.parametrize("obj_type", ["Campaign", "AdGroup", "Ad"])
    def test_a_row_without_a_target_id_names_nothing(self, obj_type: str) -> None:
        change = _map(_row(obj_type=obj_type, obj_id=None))
        assert change is not None
        assert (change.campaign_id, change.ad_id, change.entity_id) == (
            None,
            None,
            None,
        )

    @pytest.mark.parametrize(
        ("obj_type", "expected"),
        [("AdAccount", "AD_ACCOUNT"), ("spend_limit", "SPEND_LIMIT")],
    )
    def test_unknown_type_has_no_identity(self, obj_type: str, expected: str) -> None:
        change = _map(_row(obj_type=obj_type, obj_id="x_1"))
        assert change is not None
        assert change.resource_type == expected
        assert (
            change.campaign_id,
            change.ad_id,
            change.entity_type,
            change.entity_id,
        ) == (None, None, None, None)

    @pytest.mark.parametrize("obj_type", [None, "", "Ad Group", 7])
    def test_missing_type_is_unknown(self, obj_type: Any) -> None:
        change = _map(_row(obj_type=obj_type))
        assert change is not None
        assert change.resource_type == "UNKNOWN"
        assert change.campaign_id is None

    @pytest.mark.parametrize("audit_log_type", [None, "", "_x", "bad type"])
    def test_unusable_log_type_is_unknown(self, audit_log_type: Any) -> None:
        change = _map(_row(audit_log_type=audit_log_type))
        assert change is not None
        assert change.operation == "UNKNOWN"

    def test_a_log_type_without_underscore_is_its_own_verb(self) -> None:
        change = _map(_row(audit_log_type="pause"))
        assert change is not None
        assert change.operation == "PAUSE"

    def test_free_text_name_is_never_carried(self) -> None:
        change = _map(_row(item_name="evil\nname"))
        assert change is not None
        assert "evil" not in repr(change)


class TestToken:
    @pytest.mark.parametrize(
        "value",
        [
            "a b",
            "a\nb",
            "ab\n",
            "café",
            "",
            None,
            7,
            pytest.param("a" * 201, id="201-chars"),
        ],
    )
    def test_dropped(self, value: Any) -> None:
        assert _token(value) == ""
        assert _token(value, "fallback") == "fallback"

    @pytest.mark.parametrize(
        "value", ["alog_123", "a.b:c@d-e", pytest.param("a" * 200, id="200-chars")]
    )
    def test_kept(self, value: str) -> None:
        assert _token(value) == value

    def test_unsafe_strings_are_dropped_from_every_field(self) -> None:
        bad = "x y"
        change = _map(_row(id=bad, actor_id=bad, obj_id=bad, campaign_id=bad))
        assert change is not None
        assert change.change_id == ""
        assert change.actor == ""
        assert change.campaign_id is None

    @pytest.mark.parametrize("actor_type", ["user", "api_key", "x y", None, 3])
    def test_client_type_is_never_filled(self, actor_type: Any) -> None:
        change = _map(_row(actor_type=actor_type))
        assert change is not None
        assert change.client_type == ""

    @pytest.mark.parametrize("changes", [["name"], "name", None, 3])
    def test_changes_that_are_not_an_object(self, changes: Any) -> None:
        change = _map(_row(changes=changes))
        assert change is not None
        assert change.changed_fields == ()

    def test_change_keys_are_filtered(self) -> None:
        change = _map(
            _row(
                changes={
                    1: {},
                    "bad key": {},
                    "a:b": {},
                    "f" * 65: {},
                    "obj_type": "Campaign",
                    "status": {},
                    "bidding_config.max_bid_micros": {},
                    "g" * 64: {},
                }
            )
        )
        assert change is not None
        assert change.changed_fields == (
            "status",
            "bidding_config.max_bid_micros",
            "g" * 64,
        )

    def test_at_most_twenty_fields_in_row_order(self) -> None:
        keys = ["obj_type", *(f"field_{i}" for i in range(25))]
        change = _map(_row(changes={key: {} for key in keys}))
        assert change is not None
        assert MAX_CHANGED_FIELDS == 20
        assert change.changed_fields == tuple(f"field_{i}" for i in range(20))

    def test_a_huge_changes_object_yields_twenty(self) -> None:
        change = _map(_row(changes={f"k{i}": {} for i in range(20_000)}))
        assert change is not None
        assert change.changed_fields == tuple(f"k{i}" for i in range(20))


class TestTimestamp:
    @pytest.mark.parametrize(
        "ts",
        [None, "1772409600", True, 1772409600.0, START - 1, END + 1, 4102444000],
        ids=[
            "null",
            "string",
            "bool",
            "float",
            "before-start",
            "after-end",
            "far-future",
        ],
    )
    def test_row_without_usable_ts_is_skipped(self, ts: Any) -> None:
        assert _map(_row(ts=ts)) is None

    @pytest.mark.parametrize("ts", [START, END])
    def test_window_bounds_are_inclusive(self, ts: int) -> None:
        change = _map(_row(ts=ts))
        assert change is not None
        assert (
            change.occurred_at == datetime.fromtimestamp(ts, timezone.utc).isoformat()
        )

    def test_non_object_row_is_skipped(self) -> None:
        assert _map(["alog_1"]) is None

    async def test_skipped_rows_are_counted_in_a_note(self, api: FakeAPI) -> None:
        served = [
            *_rows(2),
            _row(id="n1", ts=None),
            _row(id="n2", ts="x"),
            _row(id="n3", ts=END + 1),
            _row(id="n4", ts=4102444000),
            "junk",
        ]
        api.add("/audit_logs", body={"data": served, "has_more": False})

        result = await _fetch()

        assert [c.change_id for c in result.changes] == ["alog_0", "alog_1"]
        assert any(
            "5 audit-log entries had no usable timestamp inside the window" in note
            for note in result.notes
        )

    async def test_no_skip_note_when_every_row_is_usable(self, api: FakeAPI) -> None:
        api.add("/audit_logs", body=page(_rows(2), has_more=False))
        result = await _fetch()
        assert not any("no usable timestamp" in note for note in result.notes)

    @pytest.mark.parametrize(
        ("since", "until"),
        [
            (datetime(2026, 3, 1), UNTIL),
            (SINCE, datetime(2026, 3, 2)),
        ],
        ids=["naive-since", "naive-until"],
    )
    async def test_a_naive_bound_is_refused_before_any_request(
        self, api: FakeAPI, since: datetime, until: datetime
    ) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            await ChatGPTAdsChangeFeed().fetch_change_events(
                ACCOUNT, since=since, until=until
            )
        assert api.requests == []


class TestNotesAndCap:
    async def test_coverage_note_is_always_present(self, api: FakeAPI) -> None:
        api.add("/audit_logs", body=page([], has_more=False))
        result = await _fetch()
        assert result.changes == ()
        assert result.truncated is False
        assert result.unavailable_reason == ""
        assert result.notes == (change_feed._COVERAGE_NOTE,)

    async def test_more_than_the_cap_is_truncated(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        api.add("/audit_logs", body=page(_rows(4), has_more=True))

        result = await _fetch()

        assert _audit_params(api, 0)["limit"] == "4"
        assert [c.change_id for c in result.changes] == ["alog_0", "alog_1", "alog_2"]
        assert result.truncated is True
        third = datetime.fromtimestamp(TS + 2, timezone.utc).isoformat()
        fourth = datetime.fromtimestamp(TS + 3, timezone.utc).isoformat()
        note = change_feed._truncation_note(third)
        assert note in result.notes
        assert f"through {third}" in note
        assert f"since={third}" in note
        assert fourth not in " ".join(result.notes)

    async def test_exactly_the_cap_is_not_truncated(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        api.add("/audit_logs", body=page(_rows(3), has_more=False))

        result = await _fetch()

        assert len(result.changes) == 3
        assert result.truncated is False
        assert not any("stopped at" in note for note in result.notes)

    async def test_a_capped_pass_read_newest_first_is_refused(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        api.add("/audit_logs", body=page(_rows(4)[::-1], has_more=True))

        with pytest.raises(ChatGPTAdsAPIError) as info:
            await _fetch()

        assert info.value.status == 0
        assert "oldest first" in str(info.value)
        assert "nothing was imported" in str(info.value)
        assert "since" in str(info.value)

    async def test_the_extra_row_counts_in_the_order_check(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        served = [*_rows(3, 1), _row(id="early", ts=TS)]
        api.add("/audit_logs", body=page(served, has_more=True))

        with pytest.raises(ChatGPTAdsAPIError, match="oldest first"):
            await _fetch()

    async def test_undatable_rows_do_not_break_the_order_check(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        served = [_rows(1)[0], _row(id="n", ts=None), *_rows(2, 1)]
        api.add("/audit_logs", body=page(served, has_more=True))

        result = await _fetch()

        assert result.truncated is True
        assert [c.change_id for c in result.changes] == ["alog_0", "alog_1"]

    async def test_an_uncapped_pass_does_not_check_order(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        api.add("/audit_logs", body=page(_rows(3)[::-1], has_more=False))

        result = await _fetch()

        assert [c.change_id for c in result.changes] == ["alog_2", "alog_1", "alog_0"]

    async def test_a_capped_pass_with_no_datable_row_is_refused(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        served = [_row(id=f"n{i}", ts=None) for i in range(3)] + _rows(1)
        api.add("/audit_logs", body=page(served, has_more=True))

        with pytest.raises(ChatGPTAdsAPIError) as info:
            await _fetch()

        assert info.value.status == 0
        assert "could not be dated" in str(info.value)

    def test_the_cap_fits_the_page_budget(self) -> None:
        assert CHANGE_FEED_ROW_CAP == 1000
        pages = -(-(CHANGE_FEED_ROW_CAP + 1) // PAGE_MAX_AUDIT_LOGS)
        assert pages <= MAX_PAGES_PER_CALL


def _audit_requests(api: FakeAPI) -> list[Any]:
    return [r for r in api.requests if r.url.path == "/v1/audit_logs"]


class TestAccountCheck:
    async def test_matching_account_reads_the_audit_log(self, api: FakeAPI) -> None:
        api.add("/audit_logs", body=page(_rows(1), has_more=False))

        result = await _fetch()

        assert api.requests[0].url.path == "/v1/ad_account"
        assert len(_audit_requests(api)) == 1
        assert len(result.changes) == 1
        assert not any("names no ChatGPT Ads account" in n for n in result.notes)

    async def test_another_account_is_unavailable_without_reading(
        self, api: FakeAPI
    ) -> None:
        api.routes["/v1/ad_account"] = [(200, {"id": "adacct_other"}, {})]
        api.add("/audit_logs", body=page(_rows(1), has_more=False))

        result = await _fetch()

        assert _audit_requests(api) == []
        assert result.changes == ()
        assert "different ad account" in result.unavailable_reason
        assert "adacct_other" not in result.unavailable_reason
        assert ACCOUNT not in result.unavailable_reason
        assert result.notes == (change_feed._COVERAGE_NOTE,)

    @pytest.mark.parametrize(
        "answer",
        [["adacct_1"], {"id": ""}, {"id": 7}, {"name": "x"}],
        ids=["list", "empty-id", "int-id", "no-id"],
    )
    async def test_an_unusable_account_answer_is_an_error(
        self, api: FakeAPI, answer: Any
    ) -> None:
        api.routes["/v1/ad_account"] = [(200, answer, {})]

        with pytest.raises(ChatGPTAdsAPIError) as info:
            await _fetch()

        assert info.value.status == 0
        assert "no usable id" in str(info.value)
        assert _audit_requests(api) == []

    async def test_no_account_id_skips_the_check_and_says_so(
        self, api: FakeAPI
    ) -> None:
        api.add("/audit_logs", body=page(_rows(1), has_more=False))

        result = await _fetch("")

        assert [r.url.path for r in api.requests] == ["/v1/audit_logs"]
        assert len(result.changes) == 1
        assert change_feed._NO_ACCOUNT_NOTE in result.notes


class TestFailures:
    async def test_no_key_raises_before_any_request(
        self, api: FakeAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CHATGPT_ADS_API_KEY")
        with pytest.raises(PlatformAuthError) as info:
            await _fetch()
        assert info.value.cause == AUTH_CAUSE_NO_CREDENTIALS
        assert "CHATGPT_ADS_API_KEY" in str(info.value)
        assert api.requests == []

    async def test_401_is_an_auth_error(self, api: FakeAPI) -> None:
        api.add("/audit_logs", 401, {"error": {"message": "Invalid key"}})
        with pytest.raises(PlatformAuthError):
            await _fetch()

    async def test_500_after_retries_is_an_api_error(self, api: FakeAPI) -> None:
        api.add("/audit_logs", 500, "boom")
        with pytest.raises(ChatGPTAdsAPIError):
            await _fetch()
        assert len(_audit_requests(api)) == 3


def _entry(tool: str, arguments: dict[str, Any], *, minutes: int = 1) -> ActionLogEntry:
    """mureo's own record of ``tool``, from the identity the tool declares."""
    by_name = {t.name: t for t in ChatGPTAdsProvider().mcp_tools()}
    declaration = derive_semantics(by_name[tool]).identity
    campaign_id, ad_id, entity_type, entity_id = extract_mutation_identity(
        arguments, declaration
    )
    occurred = datetime.fromtimestamp(TS, tz=timezone.utc)
    return ActionLogEntry(
        timestamp=(occurred - timedelta(minutes=minutes)).isoformat(),
        action=tool,
        platform=KEY,
        campaign_id=campaign_id,
        ad_id=ad_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def _state(tmp_path: Path) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(
        json.dumps(
            {
                "version": "2",
                "platforms": {KEY: {"account_id": "adacct_1", "campaigns": []}},
                "action_log": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _verdict(tmp_path: Path, entry: ActionLogEntry, row: dict[str, Any]) -> Any:
    path = _state(tmp_path)
    append_action_log(path, entry)
    change = _map(row)
    assert change is not None
    # The importer files the feed's changes under the STATE key before the
    # deduper reads them.
    return classify_change(replace(change, platform=KEY), read_state_file(path))


_CAMPAIGN_ROW = _row(obj_type="Campaign", obj_id="cmpn_1", campaign_id="cmpn_1")
_AD_GROUP_ROW = _row(obj_type="AdGroup", obj_id="adgrp_1", campaign_id="cmpn_1")
_AD_ROW = _row(obj_type="Ad", obj_id="ad_1", campaign_id="cmpn_1")


class TestAttribution:
    @pytest.mark.parametrize(
        ("tool", "arguments", "row"),
        [
            (
                "chatgpt_ads_campaigns_pause",
                {"campaign_id": "cmpn_1"},
                {**_CAMPAIGN_ROW, "changes": {"status": {}}},
            ),
            (
                "chatgpt_ads_campaigns_update_budget",
                {"campaign_id": "cmpn_1"},
                {**_CAMPAIGN_ROW, "changes": {"budget": {}}},
            ),
            (
                "chatgpt_ads_campaigns_update",
                {"campaign_id": "cmpn_123"},
                DOCUMENTED_ROW,
            ),
            (
                "chatgpt_ads_ad_groups_update_bid",
                {"ad_group_id": "adgrp_1"},
                {**_AD_GROUP_ROW, "changes": {"bidding_config": {}}},
            ),
            (
                "chatgpt_ads_ad_groups_pause",
                {"ad_group_id": "adgrp_1"},
                {**_AD_GROUP_ROW, "changes": {"status": {}}},
            ),
            (
                "chatgpt_ads_ads_pause",
                {"ad_id": "ad_1"},
                {**_AD_ROW, "changes": {"status": {}}},
            ),
        ],
        ids=[
            "campaign-pause",
            "campaign-budget",
            "campaign-rename",
            "ad-group-bid",
            "ad-group-pause",
            "ad-pause",
        ],
    )
    def test_mureos_own_change_is_attributed(
        self, tmp_path: Path, tool: str, arguments: dict[str, Any], row: dict[str, Any]
    ) -> None:
        verdict = _verdict(tmp_path, _entry(tool, arguments), row)
        assert verdict is ImportVerdict.ATTRIBUTED_TO_MUREO

    @pytest.mark.parametrize(
        ("tool", "arguments", "row"),
        [
            (
                "chatgpt_ads_campaigns_pause",
                {"campaign_id": "cmpn_2"},
                {**_CAMPAIGN_ROW, "changes": {"status": {}}},
            ),
            (
                "chatgpt_ads_ad_groups_update_bid",
                {"ad_group_id": "adgrp_2"},
                {**_AD_GROUP_ROW, "changes": {"bidding_config": {}}},
            ),
            (
                "chatgpt_ads_ads_pause",
                {"ad_id": "ad_2"},
                {**_AD_ROW, "changes": {"status": {}}},
            ),
        ],
        ids=["other-campaign", "other-ad-group", "other-ad"],
    )
    def test_another_target_is_imported(
        self, tmp_path: Path, tool: str, arguments: dict[str, Any], row: dict[str, Any]
    ) -> None:
        verdict = _verdict(tmp_path, _entry(tool, arguments), row)
        assert verdict is ImportVerdict.IMPORT

    def test_another_kind_is_imported(self, tmp_path: Path) -> None:
        entry = _entry("chatgpt_ads_campaigns_pause", {"campaign_id": "cmpn_123"})
        assert _verdict(tmp_path, entry, DOCUMENTED_ROW) is ImportVerdict.IMPORT

    def test_an_account_level_change_is_imported(self, tmp_path: Path) -> None:
        entry = ActionLogEntry(
            timestamp=datetime.fromtimestamp(TS - 60, tz=timezone.utc).isoformat(),
            action="chatgpt_ads_account_daily_spend_limit_set",
            platform=KEY,
        )
        row = _row(
            obj_type="AdAccount",
            obj_id="adacct_1",
            campaign_id=None,
            changes={"daily_spend_limit": {}},
        )
        assert _verdict(tmp_path, entry, row) is ImportVerdict.IMPORT

    def test_an_ad_group_row_does_not_match_a_campaign_change(
        self, tmp_path: Path
    ) -> None:
        entry = _entry("chatgpt_ads_campaigns_pause", {"campaign_id": "cmpn_1"})
        row = {**_AD_GROUP_ROW, "changes": {"status": {}}}
        assert _verdict(tmp_path, entry, row) is ImportVerdict.IMPORT

    def test_an_ad_row_does_not_match_a_campaign_change(self, tmp_path: Path) -> None:
        entry = _entry("chatgpt_ads_campaigns_pause", {"campaign_id": "cmpn_1"})
        row = {**_AD_ROW, "changes": {"status": {}}}
        assert _verdict(tmp_path, entry, row) is ImportVerdict.IMPORT

    def test_an_ad_row_does_not_match_an_ad_group_change(self, tmp_path: Path) -> None:
        entry = _entry("chatgpt_ads_ad_groups_pause", {"ad_group_id": "adgrp_1"})
        row = {**_AD_ROW, "changes": {"status": {}}}
        assert _verdict(tmp_path, entry, row) is ImportVerdict.IMPORT


@pytest.fixture()
def _isolated_provider_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(default_registry, "_entries", {})


@pytest.mark.usefixtures("_clean_feeds", "_isolated_provider_registry")
class TestRegistration:
    def test_registering_the_provider_registers_the_feed(self) -> None:
        register_chatgpt_ads_provider()
        feed = resolve_change_feed(KEY)
        assert isinstance(feed, ChatGPTAdsChangeFeed)
        assert plugin_source(feed) == CHATGPT_ADS_SOURCE_DISTRIBUTION
        assert resolve_change_feed("plugin:other-dist:chatgpt_ads") is None

    def test_the_disable_switch_registers_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUREO_DISABLE_CHATGPT_ADS", "1")
        register_bundled_providers()
        assert "chatgpt_ads" not in default_registry
        assert resolve_change_feed(KEY) is None
        assert default_change_feed_registry().get("chatgpt_ads") is None

    def test_a_foreign_provider_entry_gets_no_feed(self) -> None:
        class _Other:
            name = "chatgpt_ads"

        default_registry.register(
            ProviderEntry(
                name="chatgpt_ads",
                display_name="Other",
                capabilities=frozenset(),
                provider_class=_Other,
                source_distribution="third-party",
            )
        )
        register_chatgpt_ads_provider()
        assert default_change_feed_registry().get("chatgpt_ads") is None

    def test_a_second_call_is_silent(self) -> None:
        register_chatgpt_ads_provider()
        first = default_change_feed_registry().get("chatgpt_ads")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            register_chatgpt_ads_provider()
        assert default_change_feed_registry().get("chatgpt_ads") is first
        assert not [w for w in captured if issubclass(w.category, ChangeFeedWarning)]
        assert captured == []


@pytest.mark.usefixtures("_clean_feeds", "_isolated_provider_registry")
class TestEndToEnd:
    async def test_import_then_nothing_new(self, api: FakeAPI, tmp_path: Path) -> None:
        register_chatgpt_ads_provider()
        path = _state(tmp_path)
        api.add("/audit_logs", body=page([DOCUMENTED_ROW], has_more=False))
        now = datetime.fromtimestamp(TS, tz=timezone.utc) + timedelta(hours=1)

        first = await import_external_changes(path, now=now)

        assert [o.status for o in first] == [ChangeImportStatus.IMPORTED]
        assert first[0].platform == KEY
        assert len(first[0].imported) == 1
        entries = read_state_file(path).action_log
        assert len(entries) == 1
        entry = entries[0]
        assert entry.platform == KEY
        assert entry.origin == EXTERNAL_ORIGIN
        assert entry.action == "external_change:CAMPAIGN"
        assert entry.campaign_id == "cmpn_123"
        assert entry.external_id == f"{KEY}|alog_123"

        second = await import_external_changes(path, now=now)

        assert second[0].status is ChangeImportStatus.IMPORTED
        assert second[0].imported == ()
        assert second[0].already_imported == 1
        assert len(read_state_file(path).action_log) == 1
        # The second window starts at the imported change's own time.
        assert _audit_params(api)["start_time"] == str(TS)

    async def test_a_failed_read_is_an_error_outcome(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        register_chatgpt_ads_provider()
        path = _state(tmp_path)
        api.add("/audit_logs", 401, {"error": {"message": "Invalid key"}})

        outcomes = await import_external_changes(path)

        assert outcomes[0].status is ChangeImportStatus.ERROR
        assert outcomes[0].reason.startswith("PlatformAuthError: ")
        assert read_state_file(path).action_log == ()

    async def test_another_account_is_an_unavailable_outcome(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        register_chatgpt_ads_provider()
        path = _state(tmp_path)
        api.routes["/v1/ad_account"] = [(200, {"id": "adacct_other"}, {})]
        api.add("/audit_logs", body=page([DOCUMENTED_ROW], has_more=False))

        outcomes = await import_external_changes(path)

        assert outcomes[0].status is ChangeImportStatus.UNAVAILABLE
        assert any("different ad account" in n for n in outcomes[0].notes)
        assert _audit_requests(api) == []
        assert read_state_file(path).action_log == ()

    async def test_an_unusable_account_answer_is_an_error_outcome(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        register_chatgpt_ads_provider()
        path = _state(tmp_path)
        api.routes["/v1/ad_account"] = [(200, ["adacct_1"], {})]

        outcomes = await import_external_changes(path)

        assert outcomes[0].status is ChangeImportStatus.ERROR
        assert "no usable id" in outcomes[0].reason
        assert read_state_file(path).action_log == ()

    async def test_a_window_opening_with_mureos_own_changes_can_be_continued(
        self, api: FakeAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Rows mureo made are never stored, so they do not move the watermark;
        # the note's point is what lets the next pass get past them.
        monkeypatch.setattr(change_feed, "CHANGE_FEED_ROW_CAP", 3)
        register_chatgpt_ads_provider()
        path = _state(tmp_path)
        own = [
            {
                **_row(id=f"alog_{i}", ts=TS + i),
                "obj_type": "Campaign",
                "obj_id": f"cmpn_{i}",
                "campaign_id": f"cmpn_{i}",
                "changes": {"status": {}},
            }
            for i in range(3)
        ]
        for i in range(3):
            append_action_log(
                path,
                _entry("chatgpt_ads_campaigns_pause", {"campaign_id": f"cmpn_{i}"}),
            )
        external = {
            **_row(id="alog_ext", ts=TS + 3),
            "obj_type": "Campaign",
            "obj_id": "cmpn_9",
            "campaign_id": "cmpn_9",
            "changes": {"status": {}},
        }
        api.add("/audit_logs", body=page([*own, external], has_more=True))
        api.add("/audit_logs", body=page([own[2], external], has_more=False))
        now = datetime.fromtimestamp(TS, tz=timezone.utc) + timedelta(hours=1)

        first = await import_external_changes(path, now=now)

        read_through = datetime.fromtimestamp(TS + 2, timezone.utc).isoformat()
        assert first[0].truncated is True
        assert first[0].imported == ()
        assert change_feed._truncation_note(read_through) in first[0].notes

        second = await import_external_changes(
            path, now=now, since=datetime.fromisoformat(read_through)
        )

        assert _audit_params(api)["start_time"] == str(TS + 2)
        assert second[0].truncated is False
        assert len(second[0].imported) == 1
        externals = [
            e for e in read_state_file(path).action_log if e.origin == EXTERNAL_ORIGIN
        ]
        assert [e.external_id for e in externals] == [f"{KEY}|alog_ext"]
