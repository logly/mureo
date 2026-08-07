"""A targeted write must change what it declares and nothing else.

Every STATE.json mutator rebuilt its document — and its platform entry — by
enumerating fields. That works until a field is added, at which point every
mutator that forgot it silently resets it, and a reset field is
indistinguishable downstream from one that was never set. The bug therefore
does not announce itself; it is found later, from the damage.

It has been found three times in this project now:

- agency #193 — ``update()`` rebuilt a registry entry field-by-field and
  dropped ``archived``, silently resuming collection on a renamed client.
- #549 — ``stamp_batch`` rebuilt an ``ActionLogEntry`` and dropped the
  provenance fields, so an imported entry lost ``is_external`` and a forged
  ``reversible_params`` planned as a real reversal.
- here — adding ``batches`` in #549 had to be hand-threaded through five
  mutators; missing one would have silently closed an open batch on the next
  campaign upsert.

Finding it twice did not prevent the third, because the defect is an omission
and omissions are invisible in review. So these tests are driven off
``dataclasses.fields(...)`` rather than a hand-written list: each states only
the fields its mutator DECLARES it changes, and asserts everything else
survived. A field added to :class:`StateDocument` or :class:`PlatformState` is
checked by every one of them without any test being edited — and the value
maps below fail loudly if the new field has no distinctive value to check.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from mureo.context.models import (
    ActionLogEntry,
    AdState,
    CampaignSnapshot,
    PlatformState,
    StateDocument,
)
from mureo.context.state import (
    append_action_log,
    parse_state,
    read_state_file,
    render_state,
    set_conversion_action_types,
    set_platform_metrics,
    set_report,
    upsert_campaign,
    write_state_file,
)

_ACCOUNT = "123-456-7890"
_PLATFORM = "google_ads"


def _campaign(campaign_id: str = "C-1") -> CampaignSnapshot:
    return CampaignSnapshot(
        campaign_id=campaign_id,
        campaign_name="Brand Search",
        status="ENABLED",
        bidding_strategy_type="TARGET_CPA",
        bidding_details={"target_cpa": 5000},
        daily_budget=12000.0,
        device_targeting=({"device": "MOBILE", "modifier": 1.2},),
        campaign_goal="leads",
        notes="do not pause",
        metrics={"spend": 4200.0, "clicks": 310},
        ads=(AdState(ad_id="A-1", name="RSA", status="ENABLED"),),
    )


#: One distinctive value per :class:`PlatformState` field.
_PLATFORM_FIELD_VALUES: dict[str, Any] = {
    "account_id": _ACCOUNT,
    "campaigns": (_campaign(),),
    "totals": {"spend": 4200.0, "conversions": 12},
    "metrics_period": "LAST_30_DAYS",
    "periods": {"LAST_30_DAYS": {"spend": 4200.0}},
    "conversion_action_types": ("offsite_conversion.custom.42",),
}

#: One distinctive value per :class:`StateDocument` field.
_DOCUMENT_FIELD_VALUES: dict[str, Any] = {
    "version": "2",
    "last_synced_at": "2026-08-08T09:00:00+09:00",
    "customer_id": _ACCOUNT,
    "campaigns": (_campaign(),),
    "platforms": {_PLATFORM: PlatformState(**_PLATFORM_FIELD_VALUES)},
    "action_log": (
        ActionLogEntry(
            timestamp="2026-08-08T09:30:00+09:00",
            action="google_ads_budget_update",
            platform=_PLATFORM,
            campaign_id="C-1",
            summary="raised daily budget",
            observation_due="2026-08-22",
        ),
    ),
    "reports": {"daily": {"narrative": "healthy"}},
}


def _assert_map_covers(cls: type, values: dict[str, Any]) -> None:
    """Fail loudly when the dataclass has grown a field the map does not know.

    This is what stops the test rotting the way the code did: a new field with
    no distinctive value here would be "preserved" trivially (its default
    compares equal to itself) and the guard would quietly stop guarding.
    """
    declared = {f.name for f in fields(cls)}
    missing = declared - set(values)
    assert not missing, (
        f"{cls.__name__} gained field(s) {sorted(missing)} with no value in this "
        "test's map. Add one, then confirm every mutator preserves it — a field "
        "silently reset by a targeted write is exactly what this guards."
    )
    stale = set(values) - declared
    assert not stale, f"{cls.__name__} map names removed field(s) {sorted(stale)}"


def _seed(path: Path) -> StateDocument:
    """Write a STATE.json with every field of every model populated."""
    _assert_map_covers(PlatformState, _PLATFORM_FIELD_VALUES)
    _assert_map_covers(StateDocument, _DOCUMENT_FIELD_VALUES)
    doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
    write_state_file(path, doc)
    return doc


def _assert_document_preserved(
    before: StateDocument, after: StateDocument, *, changed: set[str]
) -> None:
    """Every :class:`StateDocument` field outside ``changed`` is untouched."""
    for field in fields(StateDocument):
        if field.name in changed:
            continue
        assert getattr(after, field.name) == getattr(before, field.name), (
            f"{field.name!r} was reset by a write that does not declare it. "
            "Use dataclasses.replace and change only the fields the call owns."
        )


def _assert_platform_preserved(
    before: PlatformState, after: PlatformState, *, changed: set[str]
) -> None:
    """Every :class:`PlatformState` field outside ``changed`` is untouched."""
    for field in fields(PlatformState):
        if field.name in changed:
            continue
        assert getattr(after, field.name) == getattr(before, field.name), (
            f"platform field {field.name!r} was reset by a write that does not "
            "declare it."
        )


@pytest.fixture
def seeded(tmp_path: Path) -> tuple[Path, StateDocument]:
    path = tmp_path / "STATE.json"
    return path, _seed(path)


@pytest.mark.unit
class TestDocumentLevelPreservation:
    """Each mutator changes the document fields it owns, and no others."""

    def test_upsert_campaign(self, seeded: tuple[Path, StateDocument]) -> None:
        path, before = seeded
        after = upsert_campaign(
            path, _campaign("C-2"), platform=_PLATFORM, account_id=_ACCOUNT
        )
        _assert_document_preserved(
            before, after, changed={"last_synced_at", "campaigns", "platforms"}
        )

    def test_append_action_log(self, seeded: tuple[Path, StateDocument]) -> None:
        path, before = seeded
        after = append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-08-08T10:00:00+09:00",
                action="google_ads_keywords_add",
                platform=_PLATFORM,
            ),
        )
        # last_synced_at is deliberately NOT re-stamped: appending an action is
        # not a sync, and the dashboard's freshness must keep reflecting the
        # last real one.
        _assert_document_preserved(before, after, changed={"action_log"})
        assert after.last_synced_at == before.last_synced_at

    def test_set_report(self, seeded: tuple[Path, StateDocument]) -> None:
        path, before = seeded
        after = set_report(path, "weekly", {"narrative": "steady"})
        _assert_document_preserved(before, after, changed={"last_synced_at", "reports"})
        # Sibling report kinds survive too.
        assert after.reports is not None
        assert after.reports["daily"] == {"narrative": "healthy"}

    def test_set_platform_metrics(self, seeded: tuple[Path, StateDocument]) -> None:
        path, before = seeded
        after = set_platform_metrics(
            path, _PLATFORM, _ACCOUNT, periods={"YESTERDAY": {"spend": 100.0}}
        )
        _assert_document_preserved(
            before, after, changed={"last_synced_at", "platforms"}
        )

    def test_set_conversion_action_types(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        path, before = seeded
        after = set_conversion_action_types(path, _PLATFORM, _ACCOUNT, ["lead"])
        _assert_document_preserved(
            before, after, changed={"last_synced_at", "platforms"}
        )


@pytest.mark.unit
class TestPlatformLevelPreservation:
    """The three mutators that write ``platforms`` touch only their own fields.

    This is where the real regressions landed: a campaign upsert wiped the
    dashboard rollups, and a metrics write wiped the #342 conversion override.
    """

    def _platform(self, doc: StateDocument) -> PlatformState:
        assert doc.platforms is not None
        return doc.platforms[_PLATFORM]

    def test_upsert_campaign_keeps_rollups_and_conversion_override(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        path, before = seeded
        after = upsert_campaign(
            path, _campaign("C-2"), platform=_PLATFORM, account_id=_ACCOUNT
        )
        _assert_platform_preserved(
            self._platform(before), self._platform(after), changed={"campaigns"}
        )

    def test_metrics_write_keeps_campaigns_and_conversion_override(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        path, before = seeded
        after = set_platform_metrics(
            path, _PLATFORM, _ACCOUNT, periods={"YESTERDAY": {"spend": 100.0}}
        )
        _assert_platform_preserved(
            self._platform(before),
            self._platform(after),
            changed={"totals", "metrics_period", "periods"},
        )
        # ``periods`` merges per window rather than replacing the map.
        merged = self._platform(after).periods
        assert merged is not None
        assert merged["LAST_30_DAYS"] == {"spend": 4200.0}
        assert merged["YESTERDAY"] == {"spend": 100.0}
        # A None argument means "leave as it was", not "clear it".
        assert self._platform(after).totals == _PLATFORM_FIELD_VALUES["totals"]

    def test_conversion_override_write_keeps_everything_else(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        path, before = seeded
        after = set_conversion_action_types(path, _PLATFORM, _ACCOUNT, ["lead"])
        _assert_platform_preserved(
            self._platform(before),
            self._platform(after),
            changed={"conversion_action_types"},
        )
        assert self._platform(after).conversion_action_types == ("lead",)

    def test_a_new_platform_entry_takes_the_dataclass_defaults(
        self, tmp_path: Path
    ) -> None:
        """Creating an entry must not hand-copy the model's own defaults."""
        path = tmp_path / "STATE.json"
        write_state_file(path, StateDocument(version="2"))
        after = set_conversion_action_types(path, "meta_ads", "act_1", ["purchase"])
        assert after.platforms is not None
        created = after.platforms["meta_ads"]
        fresh = PlatformState(account_id="act_1")
        for field in fields(PlatformState):
            if field.name in {"account_id", "conversion_action_types"}:
                continue
            assert getattr(created, field.name) == getattr(fresh, field.name)


@pytest.mark.unit
class TestCodecRoundTrip:
    """The codec MUST enumerate — so it gets the same guard from outside.

    ``state_codec`` maps to an external JSON schema, so ``replace`` cannot
    help it: both halves list every field by hand. A field missing from either
    half is lost on the way to disk, silently. Driving the check off
    ``dataclasses.fields`` catches that without the codec having to change
    shape.
    """

    def test_every_document_field_survives_render_and_parse(self) -> None:
        _assert_map_covers(StateDocument, _DOCUMENT_FIELD_VALUES)
        doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
        restored = parse_state(render_state(doc))
        for field in fields(StateDocument):
            assert getattr(restored, field.name) == getattr(doc, field.name), (
                f"{field.name!r} did not survive the STATE.json round trip — "
                "check BOTH halves of state_codec."
            )

    def test_every_platform_field_survives_render_and_parse(self) -> None:
        _assert_map_covers(PlatformState, _PLATFORM_FIELD_VALUES)
        doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
        restored = parse_state(render_state(doc))
        assert restored.platforms is not None
        for field in fields(PlatformState):
            assert getattr(restored.platforms[_PLATFORM], field.name) == getattr(
                doc.platforms[_PLATFORM], field.name  # type: ignore[index]
            ), f"platform field {field.name!r} did not survive the round trip"

    def test_round_trip_through_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        doc = _seed(path)
        restored = read_state_file(path)
        for field in fields(StateDocument):
            assert getattr(restored, field.name) == getattr(doc, field.name)
