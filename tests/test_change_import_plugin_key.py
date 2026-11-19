"""A provider-served platform's change feed joins on its canonical key (#998).

A feed registers under its plain registry name (``widgets``), but the
platform's STATE.json key is ``plugin:<distribution>:<name>``. The importer
has to find the feed from that key, and everything it writes has to land
under that key, or the dedupe against mureo's own entries and the repeated
poll stop joining.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from mureo.change_import import (
    ChangeFeedResult,
    ChangeImportStatus,
    ExternalChange,
    change_feed_platform_keys,
    clear_change_feed_registry,
    default_change_feed_registry,
    import_external_changes,
    plugin_source,
    register_change_feed,
    resolve_change_feed,
)
from mureo.change_import.registry import ChangeFeedRegistry
from mureo.context.models import EXTERNAL_ORIGIN, ActionLogEntry
from mureo.context.state import append_action_log, read_state_file
from mureo.mcp._handlers_change_import import handle_external_changes_import

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
KEY = "plugin:dist-a:widgets"


def _change(**overrides: Any) -> ExternalChange:
    base: dict[str, Any] = {
        "platform": "widgets",
        "occurred_at": (NOW - timedelta(hours=2)).isoformat(),
        "resource_type": "CAMPAIGN_CRITERION",
        "operation": "CREATE",
        "change_id": "w-1",
        "changed_fields": ("campaign_criterion.negative",),
        "actor": "operator@example.com",
        "client_type": "WEB",
        "campaign_id": "111",
    }
    base.update(overrides)
    return ExternalChange(**base)


class _StubFeed:
    def __init__(self, platform: str, result: ChangeFeedResult) -> None:
        self.platform = platform
        self._result = result
        self.since_calls: list[datetime] = []

    async def fetch_change_events(
        self, account_id: str, *, since: datetime, until: datetime
    ) -> ChangeFeedResult:
        self.since_calls.append(since)
        return self._result


def _discover_feed(distribution: str, platform: str, result: ChangeFeedResult) -> Any:
    """Register a feed through entry-point discovery, the path a plugin takes."""

    class _Feed(_StubFeed):
        def __init__(self) -> None:
            super().__init__(platform, result)

    class _Dist:
        name = distribution

    class _EntryPoint:
        name = platform
        dist = _Dist()

        def load(self) -> Any:
            return _Feed

    default_change_feed_registry().discover(
        refresh=True, loader=lambda group: [_EntryPoint()]
    )
    return default_change_feed_registry().get(platform)


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

    The bootstrap fires once and the instance is then emptied, so the
    built-in feeds stay unregistered: registration is first-wins on the
    registry name, and a stub registered under a built-in name would
    otherwise be dropped in favour of the live feed.
    """
    clear_change_feed_registry()
    default_change_feed_registry().clear()
    yield
    clear_change_feed_registry()


@pytest.mark.unit
class TestResolveChangeFeed:
    def test_canonical_key_resolves_by_distribution_and_name(self) -> None:
        feed = _StubFeed("widgets", ChangeFeedResult(changes=()))
        register_change_feed(feed, source_distribution="dist-a")

        assert resolve_change_feed("plugin:dist-a:widgets") is feed
        assert resolve_change_feed("plugin:dist-b:widgets") is None
        assert resolve_change_feed("plugin:dist-a:other") is None
        # A bare registry name keeps using the direct lookup.
        assert resolve_change_feed("widgets") is feed

    def test_legacy_short_form_resolves_a_single_feed(self) -> None:
        feed = _StubFeed("widgets", ChangeFeedResult(changes=()))
        register_change_feed(feed, source_distribution="dist-a")

        assert resolve_change_feed("plugin:dist-a") is feed

    def test_legacy_short_form_refuses_to_pick_between_two_feeds(self) -> None:
        register_change_feed(
            _StubFeed("widgets", ChangeFeedResult(changes=())),
            source_distribution="dist-a",
        )
        register_change_feed(
            _StubFeed("gadgets", ChangeFeedResult(changes=())),
            source_distribution="dist-a",
        )

        assert resolve_change_feed("plugin:dist-a") is None
        assert resolve_change_feed("plugin:dist-a:gadgets") is not None

    def test_a_feed_without_a_distribution_never_answers_a_plugin_key(self) -> None:
        register_change_feed(_StubFeed("widgets", ChangeFeedResult(changes=())))

        assert resolve_change_feed("plugin:dist-a:widgets") is None
        assert resolve_change_feed("plugin:dist-a") is None
        assert resolve_change_feed("widgets") is not None

    def test_a_discovered_feed_does_not_answer_another_distributions_key(
        self,
    ) -> None:
        feed = _discover_feed("dist-a", "widgets", ChangeFeedResult(changes=()))

        assert plugin_source(feed) == "dist-a"
        assert resolve_change_feed("plugin:dist-a:widgets") is feed
        assert resolve_change_feed("plugin:dist-b:widgets") is None

    def test_a_dropped_duplicate_is_not_stamped(self) -> None:
        registry = ChangeFeedRegistry()
        first = _StubFeed("widgets", ChangeFeedResult(changes=()))
        second = _StubFeed("widgets", ChangeFeedResult(changes=()))
        registry.register(first, source_distribution="dist-a")
        registry.register(second, source_distribution="dist-b")

        assert registry.get("widgets") is first
        assert plugin_source(first) == "dist-a"
        assert plugin_source(second) == ""

        registry.clear()
        assert plugin_source(first) == ""

    def test_feeds_lists_registered_pairs(self) -> None:
        registry = ChangeFeedRegistry()
        feed = _StubFeed("widgets", ChangeFeedResult(changes=()))
        registry.register(feed)

        assert registry.feeds() == (("widgets", feed),)


@pytest.mark.unit
class TestImportUnderCanonicalKey:
    @pytest.mark.asyncio
    async def test_entries_are_filed_under_the_canonical_key(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {KEY: "acct-1"})
        feed = _discover_feed(
            "dist-a", "widgets", ChangeFeedResult(changes=(_change(),))
        )

        first = await import_external_changes(path, now=NOW)

        assert [o.status for o in first] == [ChangeImportStatus.IMPORTED]
        assert first[0].platform == KEY
        entries = read_state_file(path).action_log
        assert len(entries) == 1
        entry = entries[0]
        assert entry.platform == KEY
        assert entry.origin == EXTERNAL_ORIGIN
        assert entry.external_id is not None
        assert entry.external_id.startswith(f"{KEY}|")

        second = await import_external_changes(path, now=NOW)

        # The second window starts at the first change's ``occurred_at``:
        # the watermark is read from entries filed under the STATE key.
        assert feed.since_calls[1] == datetime.fromisoformat(_change().occurred_at)
        assert second[0].status is ChangeImportStatus.IMPORTED
        assert second[0].imported == ()
        assert second[0].already_imported == 1
        assert len(read_state_file(path).action_log) == 1

    @pytest.mark.asyncio
    async def test_mureos_own_entry_under_the_canonical_key_is_attributed(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {KEY: "acct-1"})
        append_action_log(
            path,
            ActionLogEntry(
                timestamp=(NOW - timedelta(minutes=1)).isoformat(),
                action="widgets_campaigns_update_status",
                platform=KEY,
                campaign_id="111",
            ),
        )
        echo = _change(
            occurred_at=NOW.isoformat(),
            resource_type="CAMPAIGN",
            changed_fields=("status",),
            operation="UPDATE",
        )
        _discover_feed("dist-a", "widgets", ChangeFeedResult(changes=(echo,)))

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].attributed_to_mureo == 1
        assert outcomes[0].imported == ()
        assert len(read_state_file(path).action_log) == 1

    @pytest.mark.asyncio
    async def test_a_change_labelled_for_another_platform_is_dropped(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {KEY: "acct-1"})
        _discover_feed(
            "dist-a",
            "widgets",
            ChangeFeedResult(
                changes=(_change(), _change(platform="gadgets", change_id="w-2"))
            ),
        )

        outcomes = await import_external_changes(path, now=NOW)

        assert len(outcomes[0].imported) == 1
        assert any("'gadgets'" in note for note in outcomes[0].notes)
        assert [e.platform for e in read_state_file(path).action_log] == [KEY]

    @pytest.mark.asyncio
    async def test_another_distributions_key_is_unavailable(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"plugin:dist-b:widgets": "acct-1"})
        _discover_feed("dist-a", "widgets", ChangeFeedResult(changes=(_change(),)))

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].status is ChangeImportStatus.UNAVAILABLE
        assert outcomes[0].reason == (
            "change_import_unavailable_for_plugin:dist-b:widgets"
        )
        assert read_state_file(path).action_log == ()


@pytest.mark.unit
class TestBuiltinPlatformUnchanged:
    @pytest.mark.asyncio
    async def test_builtin_external_id_is_byte_identical(self, tmp_path: Path) -> None:
        """The relabel is the identity when the feed name is the STATE key, so
        ids already written for a built-in platform keep deduplicating."""
        path = _write_state(tmp_path, {"google_ads": "123"})
        native = _change(
            platform="google_ads", change_id="customers/1/changeEvents/aaa"
        )
        derived = _change(
            platform="google_ads",
            change_id="",
            client_type="GOOGLE_ADS_WEB_CLIENT",
        )
        register_change_feed(
            _StubFeed("google_ads", ChangeFeedResult(changes=(native, derived)))
        )

        await import_external_changes(path, now=NOW)

        ids = [e.external_id for e in read_state_file(path).action_log]
        assert ids == [
            "google_ads|customers/1/changeEvents/aaa",
            "google_ads|sha256:6d967136c49ac0690c5766e0fd9eb92d",
        ]


_SHORT_FORM_NOTE = "names a distribution rather than a platform"


@pytest.mark.unit
class TestLegacyShortFormImport:
    @pytest.mark.asyncio
    async def test_a_single_feed_imports_under_the_short_form(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"plugin:dist-a": "acct-1"})
        _discover_feed("dist-a", "widgets", ChangeFeedResult(changes=(_change(),)))

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].status is ChangeImportStatus.IMPORTED
        entry = read_state_file(path).action_log[0]
        assert entry.platform == "plugin:dist-a"
        assert entry.external_id is not None
        assert entry.external_id.startswith("plugin:dist-a|")

    @pytest.mark.asyncio
    async def test_an_ambiguous_short_form_says_why_it_is_unavailable(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {"plugin:dist-a": "acct-1"})
        for name in ("widgets", "gadgets"):
            register_change_feed(
                _StubFeed(name, ChangeFeedResult(changes=(_change(platform=name),))),
                source_distribution="dist-a",
            )

        outcomes = await import_external_changes(path, now=NOW)

        outcome = outcomes[0]
        assert outcome.status is ChangeImportStatus.UNAVAILABLE
        assert outcome.reason == "change_import_unavailable_for_plugin:dist-a"
        assert len(outcome.notes) == 2
        assert outcome.notes[0].startswith("mureo has no change feed for")
        assert _SHORT_FORM_NOTE in outcome.notes[1]
        assert "plugin:dist-a:<name>" in outcome.notes[1]
        assert read_state_file(path).action_log == ()

    @pytest.mark.asyncio
    async def test_a_canonical_key_without_a_feed_gets_no_short_form_note(
        self, tmp_path: Path
    ) -> None:
        path = _write_state(tmp_path, {KEY: "acct-1"})

        outcomes = await import_external_changes(path, now=NOW)

        assert outcomes[0].status is ChangeImportStatus.UNAVAILABLE
        assert len(outcomes[0].notes) == 1
        assert not any(_SHORT_FORM_NOTE in note for note in outcomes[0].notes)


@pytest.mark.unit
class TestFeedPlatformKeys:
    def test_keys_are_state_keys(self) -> None:
        register_change_feed(_StubFeed("google_ads", ChangeFeedResult(changes=())))
        _discover_feed("dist-a", "widgets", ChangeFeedResult(changes=()))

        assert change_feed_platform_keys() == ("google_ads", KEY)

    @pytest.mark.asyncio
    async def test_the_tool_lists_the_canonical_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _write_state(tmp_path, {KEY: "acct-1"})
        _discover_feed("dist-a", "widgets", ChangeFeedResult(changes=()))

        payload = json.loads((await handle_external_changes_import({}))[0].text)

        assert payload["feeds_available_for"] == [KEY]
        assert [p["platform"] for p in payload["platforms"]] == [KEY]
        assert payload["blind_spots"] == []
