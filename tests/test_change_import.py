"""Import externally-made changes into ``action_log`` (#545).

The gap: mureo cannot tell "nothing happened" from "something happened that
I cannot see". These tests pin the five properties that make the difference
worth anything:

1. An external change reaches ``action_log`` and is *identifiable* as external.
2. mureo's own change is NOT double-counted when it comes back through the feed.
3. Importing twice does not duplicate.
4. A platform with no change feed says so — it never reports "no changes".
5. Rollback never claims it can reverse a change mureo did not make.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from mureo.change_import import (
    ATTRIBUTION_WINDOW_MINUTES,
    CHANGE_FEED_ENTRY_POINT_GROUP,
    ChangeFeedProvider,
    ChangeFeedResult,
    ChangeFeedWarning,
    ChangeImportStatus,
    ExternalChange,
    ImportVerdict,
    classify_change,
    clear_change_feed_registry,
    default_change_feed_registry,
    discover_change_feeds,
    external_change_id,
    get_change_feed,
    import_external_changes,
    list_change_feed_platforms,
    register_change_feed,
    to_action_log_entry,
)
from mureo.context.models import EXTERNAL_ORIGIN, ActionLogEntry
from mureo.context.state import append_action_log, read_state_file, write_state_file
from mureo.context.state_codec import parse_state, render_state
from mureo.rollback import RollbackStatus, plan_batch_rollback, plan_rollback

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _change(**overrides: Any) -> ExternalChange:
    base: dict[str, Any] = {
        "platform": "google_ads",
        "occurred_at": (NOW - timedelta(hours=2)).isoformat(),
        "resource_type": "CAMPAIGN_CRITERION",
        "operation": "CREATE",
        "change_id": "customers/1/changeEvents/aaa",
        "changed_fields": ("campaign_criterion.negative",),
        "actor": "operator@example.com",
        "client_type": "GOOGLE_ADS_WEB_CLIENT",
        "campaign_id": "111",
    }
    base.update(overrides)
    return ExternalChange(**base)


class _StubFeed:
    """Minimal in-tree change feed used to drive the importer."""

    def __init__(self, platform: str, result: ChangeFeedResult) -> None:
        self.platform = platform
        self._result = result
        self.calls: list[tuple[str, datetime, datetime]] = []

    async def fetch_change_events(
        self, account_id: str, *, since: datetime, until: datetime
    ) -> ChangeFeedResult:
        self.calls.append((account_id, since, until))
        return self._result


class _ExplodingFeed:
    platform = "google_ads"

    async def fetch_change_events(
        self, account_id: str, *, since: datetime, until: datetime
    ) -> ChangeFeedResult:
        raise RuntimeError("token expired")


def _write_state(tmp_path: Path, platforms: dict[str, str]) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(
        json.dumps(
            {
                "version": "2",
                "platforms": {
                    key: {"account_id": account, "campaigns": []}
                    for key, account in platforms.items()
                },
                "action_log": [],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    """Run each test against an EMPTY registry.

    The bootstrap is fired once and then the instance is emptied, so the
    built-in Google Ads feed does not win the first-wins race against a stub
    and no test silently exercises the live client.
    """
    clear_change_feed_registry()
    default_change_feed_registry().clear()
    yield
    clear_change_feed_registry()


# ---------------------------------------------------------------------------
# 1. An external change is imported, and is identifiable as external
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExternalOriginIsRecorded:
    @pytest.mark.asyncio
    async def test_change_reaches_action_log_marked_external(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        register_change_feed(
            _StubFeed("google_ads", ChangeFeedResult(changes=(_change(),)))
        )

        outcomes = await import_external_changes(path, now=NOW)

        assert [o.status for o in outcomes] == [ChangeImportStatus.IMPORTED]
        entries = read_state_file(path).action_log
        assert len(entries) == 1
        entry = entries[0]
        assert entry.origin == EXTERNAL_ORIGIN
        assert entry.platform == "google_ads"
        assert entry.campaign_id == "111"
        # The change's own time, not the import time.
        assert entry.occurred_at == (NOW - timedelta(hours=2)).isoformat()
        assert entry.external_id == external_change_id(_change())

    @pytest.mark.asyncio
    async def test_observation_window_anchors_on_the_change_not_the_import(
        self, tmp_path: Path
    ) -> None:
        """A change made 20 days ago is already past due, not due in 14 days."""
        path = _write_state(tmp_path, {"google_ads": "123"})
        old = _change(occurred_at=(NOW - timedelta(days=20)).isoformat())
        register_change_feed(_StubFeed("google_ads", ChangeFeedResult(changes=(old,))))

        await import_external_changes(path, now=NOW)

        entry = read_state_file(path).action_log[0]
        assert entry.observation_due is not None
        assert entry.observation_due < NOW.date().isoformat()

    def test_no_metrics_baseline_is_claimed(self) -> None:
        """mureo was not there when the change was made — no `before` metrics."""
        entry = to_action_log_entry(_change(), recorded_at=NOW)
        assert entry.metrics_at_action is None

    def test_action_names_the_change_as_external(self) -> None:
        entry = to_action_log_entry(_change(), recorded_at=NOW)
        assert entry.action.startswith("external_change:")
        assert "operator@example.com" in (entry.summary or "")

    def test_mureo_originated_entries_carry_no_origin(self) -> None:
        """Every pre-#545 entry, and every mureo write, stays origin-free."""
        entry = ActionLogEntry(
            timestamp="2026-08-07T00:00:00+00:00", action="x", platform="google_ads"
        )
        assert entry.origin is None
        assert entry.external_id is None
        assert entry.occurred_at is None


# ---------------------------------------------------------------------------
# 2. mureo's own change is not double-counted
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoDoubleCounting:
    @pytest.mark.asyncio
    async def test_mureos_own_change_is_attributed_not_imported(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        # mureo paused campaign 111 a minute before the feed reports it.
        append_action_log(
            path,
            ActionLogEntry(
                timestamp=(NOW - timedelta(minutes=1)).isoformat(),
                action="google_ads_campaigns_update_status",
                platform="google_ads",
                campaign_id="111",
            ),
        )
        feed_echo = _change(
            occurred_at=NOW.isoformat(),
            resource_type="CAMPAIGN",
            operation="UPDATE",
            campaign_id="111",
            client_type="GOOGLE_ADS_API",
        )
        register_change_feed(
            _StubFeed("google_ads", ChangeFeedResult(changes=(feed_echo,)))
        )

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].attributed_to_mureo == 1
        assert outcomes[0].imported == ()
        log = read_state_file(path).action_log
        assert len(log) == 1
        assert log[0].origin is None

    def test_attribution_needs_matching_identity(self) -> None:
        """A same-minute change on a DIFFERENT campaign is still external."""
        doc = parse_state(
            json.dumps(
                {
                    "action_log": [
                        {
                            "timestamp": NOW.isoformat(),
                            "action": "google_ads_campaigns_update_status",
                            "platform": "google_ads",
                            "campaign_id": "999",
                        }
                    ]
                }
            )
        )
        assert classify_change(_change(occurred_at=NOW.isoformat()), doc) is (
            ImportVerdict.IMPORT
        )

    def test_attribution_needs_matching_platform(self) -> None:
        doc = parse_state(
            json.dumps(
                {
                    "action_log": [
                        {
                            "timestamp": NOW.isoformat(),
                            "action": "meta_ads_campaigns_pause",
                            "platform": "meta_ads",
                            "campaign_id": "111",
                        }
                    ]
                }
            )
        )
        assert classify_change(_change(occurred_at=NOW.isoformat()), doc) is (
            ImportVerdict.IMPORT
        )

    def test_attribution_window_is_bounded(self) -> None:
        """A mureo action from LAST WEEK does not absorb today's UI edit."""
        stale = NOW - timedelta(minutes=ATTRIBUTION_WINDOW_MINUTES + 1)
        doc = parse_state(
            json.dumps(
                {
                    "action_log": [
                        {
                            "timestamp": stale.isoformat(),
                            "action": "google_ads_campaigns_update_status",
                            "platform": "google_ads",
                            "campaign_id": "111",
                        }
                    ]
                }
            )
        )
        assert classify_change(_change(occurred_at=NOW.isoformat()), doc) is (
            ImportVerdict.IMPORT
        )

    def test_an_imported_external_entry_never_absorbs_a_later_change(self) -> None:
        """Attribution matches mureo-originated entries ONLY."""
        doc = parse_state(
            json.dumps(
                {
                    "action_log": [
                        {
                            "timestamp": NOW.isoformat(),
                            "action": "external_change:CAMPAIGN",
                            "platform": "google_ads",
                            "campaign_id": "111",
                            "origin": EXTERNAL_ORIGIN,
                            "external_id": "google_ads|other",
                        }
                    ]
                }
            )
        )
        assert classify_change(_change(occurred_at=NOW.isoformat()), doc) is (
            ImportVerdict.IMPORT
        )


# ---------------------------------------------------------------------------
# 3. Importing twice does not duplicate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIdempotentImport:
    @pytest.mark.asyncio
    async def test_second_import_of_the_same_change_is_a_no_op(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        register_change_feed(
            _StubFeed("google_ads", ChangeFeedResult(changes=(_change(),)))
        )

        first = await import_external_changes(path, now=NOW)
        second = await import_external_changes(path, now=NOW)

        assert len(first[0].imported) == 1
        assert second[0].imported == ()
        assert second[0].already_imported == 1
        assert len(read_state_file(path).action_log) == 1

    @pytest.mark.asyncio
    async def test_two_distinct_changes_in_one_batch_both_land(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        a = _change(change_id="customers/1/changeEvents/aaa")
        b = _change(change_id="customers/1/changeEvents/bbb", campaign_id="222")
        register_change_feed(_StubFeed("google_ads", ChangeFeedResult(changes=(a, b))))

        outcomes = await import_external_changes(path, now=NOW)

        assert len(outcomes[0].imported) == 2
        assert len(read_state_file(path).action_log) == 2

    def test_id_is_derived_when_the_feed_has_none(self) -> None:
        """A feed with no native id still dedupes on the change's content."""
        bare = _change(change_id="")
        assert external_change_id(bare) == external_change_id(_change(change_id=""))
        other = _change(change_id="", campaign_id="222")
        assert external_change_id(bare) != external_change_id(other)

    def test_id_is_namespaced_by_platform(self) -> None:
        google = _change(change_id="1")
        other = _change(change_id="1", platform="meta_ads")
        assert external_change_id(google) != external_change_id(other)

    @pytest.mark.asyncio
    async def test_the_same_change_twice_in_one_page_lands_once(
        self, tmp_path: Path
    ) -> None:
        """Dedup must see what this pass already wrote, not only the file."""
        path = _write_state(tmp_path, {"google_ads": "123"})
        register_change_feed(
            _StubFeed("google_ads", ChangeFeedResult(changes=(_change(), _change())))
        )

        outcomes = await import_external_changes(path, now=NOW)

        assert len(outcomes[0].imported) == 1
        assert outcomes[0].already_imported == 1
        assert len(read_state_file(path).action_log) == 1


# ---------------------------------------------------------------------------
# A feed answers only for its own platform
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFeedCannotWriteAnotherPlatform:
    @pytest.mark.asyncio
    async def test_a_change_labelled_for_another_platform_is_dropped(
        self, tmp_path: Path
    ) -> None:
        """Otherwise one distribution's feed could file entries against another
        platform's account, silently — every surface joins on that key."""
        path = _write_state(tmp_path, {"google_ads": "123"})
        register_change_feed(
            _StubFeed(
                "google_ads",
                ChangeFeedResult(
                    changes=(_change(), _change(platform="meta_ads", change_id="x"))
                ),
            )
        )

        outcomes = await import_external_changes(path, now=NOW)

        assert len(outcomes[0].imported) == 1
        assert any("dropped" in note for note in outcomes[0].notes)
        entries = read_state_file(path).action_log
        assert [e.platform for e in entries] == ["google_ads"]


# ---------------------------------------------------------------------------
# 4. A platform with no change feed says so
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHonestUnavailability:
    @pytest.mark.asyncio
    async def test_platform_without_a_feed_reports_unavailable(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"meta_ads": "act_9"})

        outcomes = await import_external_changes(path, now=NOW)

        assert len(outcomes) == 1
        assert outcomes[0].status is ChangeImportStatus.UNAVAILABLE
        assert outcomes[0].reason == "change_import_unavailable_for_meta_ads"
        # And critically: it did NOT come back as a clean, empty success.
        assert outcomes[0].status is not ChangeImportStatus.IMPORTED

    @pytest.mark.asyncio
    async def test_a_feed_that_ran_and_found_nothing_is_not_unavailable(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        register_change_feed(_StubFeed("google_ads", ChangeFeedResult(changes=())))

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].status is ChangeImportStatus.IMPORTED
        assert outcomes[0].imported == ()
        assert outcomes[0].reason == ""

    @pytest.mark.asyncio
    async def test_a_failing_feed_is_an_error_not_silence(self, tmp_path: Path) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        register_change_feed(_ExplodingFeed())

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].status is ChangeImportStatus.ERROR
        assert "token expired" in outcomes[0].reason

    @pytest.mark.asyncio
    async def test_one_platform_failing_does_not_stop_the_others(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"google_ads": "123", "meta_ads": "act_9"})
        register_change_feed(_ExplodingFeed())

        outcomes = {o.platform: o for o in await import_external_changes(path, now=NOW)}

        assert outcomes["google_ads"].status is ChangeImportStatus.ERROR
        assert outcomes["meta_ads"].status is ChangeImportStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_truncated_feed_says_history_was_lost(self, tmp_path: Path) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        register_change_feed(
            _StubFeed(
                "google_ads",
                ChangeFeedResult(
                    changes=(_change(),),
                    truncated=True,
                    notes=("row cap reached",),
                ),
            )
        )

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].truncated is True
        assert any("row cap" in note for note in outcomes[0].notes)


# ---------------------------------------------------------------------------
# 5. Rollback does not claim it can reverse an external change
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRollbackRefusesExternal:
    def test_external_entry_is_not_supported(self) -> None:
        entry = to_action_log_entry(_change(), recorded_at=NOW)
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status is RollbackStatus.NOT_SUPPORTED
        assert "outside mureo" in plan.notes

    def test_a_forged_reversal_hint_does_not_make_it_reversible(self) -> None:
        """An external entry carrying an allow-listed hint is STILL refused."""
        entry = ActionLogEntry(
            timestamp=NOW.isoformat(),
            action="external_change:CAMPAIGN",
            platform="google_ads",
            campaign_id="111",
            origin=EXTERNAL_ORIGIN,
            external_id="google_ads|x",
            reversible_params={
                "operation": "google_ads_campaigns_update_status",
                "params": {"campaign_id": "111", "status": "ENABLED"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status is RollbackStatus.NOT_SUPPORTED

    def test_batch_coverage_counts_an_external_member_as_a_gap(self) -> None:
        doc = parse_state(
            json.dumps(
                {
                    "batches": [
                        {
                            "batch_id": "batch-1",
                            "label": "monday",
                            "started_at": NOW.isoformat(),
                        }
                    ],
                    "action_log": [
                        {
                            "timestamp": NOW.isoformat(),
                            "action": "google_ads_campaigns_update_status",
                            "platform": "google_ads",
                            "campaign_id": "111",
                            "batch_id": "batch-1",
                            "reversible_params": {
                                "operation": "google_ads_campaigns_update_status",
                                "params": {"campaign_id": "111", "status": "ENABLED"},
                            },
                        },
                        {
                            "timestamp": NOW.isoformat(),
                            "action": "external_change:CAMPAIGN",
                            "platform": "google_ads",
                            "campaign_id": "222",
                            "batch_id": "batch-1",
                            "origin": EXTERNAL_ORIGIN,
                            "external_id": "google_ads|x",
                        },
                    ],
                }
            )
        )
        plan = plan_batch_rollback(doc, "batch-1")
        assert plan.coverage.value == "partial"
        assert plan.apply_order == (0,)


# ---------------------------------------------------------------------------
# Persistence: the new fields round-trip and old files are untouched
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPersistence:
    def test_new_fields_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        entry = to_action_log_entry(_change(), recorded_at=NOW)
        write_state_file(path, parse_state(json.dumps({})))
        append_action_log(path, entry)
        reloaded = read_state_file(path).action_log[0]
        assert reloaded.origin == entry.origin
        assert reloaded.external_id == entry.external_id
        assert reloaded.occurred_at == entry.occurred_at

    def test_a_mureo_entry_gains_no_new_keys(self) -> None:
        doc = parse_state(
            json.dumps(
                {
                    "action_log": [
                        {
                            "timestamp": NOW.isoformat(),
                            "action": "x",
                            "platform": "google_ads",
                        }
                    ]
                }
            )
        )
        rendered = json.loads(render_state(doc))["action_log"][0]
        assert "origin" not in rendered
        assert "external_id" not in rendered
        assert "occurred_at" not in rendered

    def test_external_id_without_external_origin_is_refused(self) -> None:
        with pytest.raises(ValueError, match="origin"):
            ActionLogEntry(
                timestamp=NOW.isoformat(),
                action="x",
                platform="google_ads",
                external_id="google_ads|x",
            )


# ---------------------------------------------------------------------------
# ABI: the hook is additive and cannot de-register an existing plugin
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChangeFeedAbi:
    def test_the_group_is_its_own(self) -> None:
        assert CHANGE_FEED_ENTRY_POINT_GROUP == "mureo.change_feeds"

    def test_protocol_is_structural(self) -> None:
        feed = _StubFeed("google_ads", ChangeFeedResult(changes=()))
        assert isinstance(feed, ChangeFeedProvider)

    def test_an_existing_analytics_plugin_is_not_a_change_feed(self) -> None:
        """The hook is opt-in: a plugin that never heard of it is simply absent.

        The #546 lesson — adding a member to a runtime_checkable Protocol
        de-registers every published implementation — is avoided by putting
        the hook in a NEW Protocol and a NEW entry-point group.
        """

        class LegacyAnalyticsPlugin:
            platform = "acme_ads"

            def capabilities(self) -> frozenset[str]:
                return frozenset()

        assert not isinstance(LegacyAnalyticsPlugin(), ChangeFeedProvider)
        register_change_feed(LegacyAnalyticsPlugin())  # type: ignore[arg-type]
        assert get_change_feed("acme_ads") is None

    def test_registry_is_first_wins(self) -> None:
        first = _StubFeed("google_ads", ChangeFeedResult(changes=()))
        second = _StubFeed("google_ads", ChangeFeedResult(changes=(_change(),)))
        register_change_feed(first)
        register_change_feed(second)
        assert get_change_feed("google_ads") is first

    def test_broken_plugin_is_skipped_not_fatal(self) -> None:
        class _Boom:
            name = "boom"

            def load(self) -> Any:
                raise ImportError("no")

        with pytest.warns(ChangeFeedWarning):
            registered = default_change_feed_registry().discover(
                refresh=True, loader=lambda group: [_Boom()]
            )
        assert registered == ()

    def test_platform_listing_is_sorted(self) -> None:
        register_change_feed(_StubFeed("z_ads", ChangeFeedResult(changes=())))
        register_change_feed(_StubFeed("a_ads", ChangeFeedResult(changes=())))
        assert list_change_feed_platforms() == ("a_ads", "z_ads")

    def test_discovery_never_raises_on_a_broken_group(self) -> None:
        def _boom(group: str) -> Any:
            raise RuntimeError("metadata is corrupt")

        with pytest.warns(ChangeFeedWarning):
            assert discover_change_feeds(refresh=True, loader=_boom) == ()


# ---------------------------------------------------------------------------
# Watermark: where the next poll starts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWatermark:
    @pytest.mark.asyncio
    async def test_first_import_uses_the_default_lookback(self, tmp_path: Path) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        feed = _StubFeed("google_ads", ChangeFeedResult(changes=()))
        register_change_feed(feed)

        await import_external_changes(path, now=NOW)

        _, since, until = feed.calls[0]
        assert until == NOW
        assert since < NOW

    @pytest.mark.asyncio
    async def test_next_import_resumes_from_the_newest_imported_change(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        newest = NOW - timedelta(hours=1)
        register_change_feed(
            _StubFeed(
                "google_ads",
                ChangeFeedResult(changes=(_change(occurred_at=newest.isoformat()),)),
            )
        )
        await import_external_changes(path, now=NOW)

        default_change_feed_registry().clear()
        feed = _StubFeed("google_ads", ChangeFeedResult(changes=()))
        register_change_feed(feed)
        await import_external_changes(path, now=NOW)

        _, since, _until = feed.calls[0]
        assert since == newest

    @pytest.mark.asyncio
    async def test_an_explicit_since_wins(self, tmp_path: Path) -> None:
        path = _write_state(tmp_path, {"google_ads": "123"})
        feed = _StubFeed("google_ads", ChangeFeedResult(changes=()))
        register_change_feed(feed)
        asked = NOW - timedelta(days=3)

        await import_external_changes(path, since=asked, now=NOW)

        assert feed.calls[0][1] == asked
