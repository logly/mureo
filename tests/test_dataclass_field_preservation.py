"""A targeted write must change what it declares and nothing else.

Every STATE.json mutator rebuilt its document — and its platform entry — by
enumerating fields. That works until a field is added, at which point every
mutator that forgot it silently resets it, and a reset field is
indistinguishable downstream from one that was never set. The bug therefore
does not announce itself; it is found later, from the damage.

It has been found four times in this project now:

- agency #193 — ``update()`` rebuilt a registry entry field-by-field and
  dropped ``archived``, silently resuming collection on a renamed client.
- #549 — ``stamp_batch`` rebuilt an ``ActionLogEntry`` and dropped the
  provenance fields, so an imported entry lost ``is_external`` and a forged
  ``reversible_params`` planned as a real reversal.
- the STATE.json mutators here — adding ``batches`` in #549 had to be
  hand-threaded through five of them; missing one would have silently closed
  an open batch on the next campaign upsert.
- ``_merge_campaign_metrics`` here — five of :class:`CampaignMetrics`'s seven
  fields were enumerated, dropping ``cpa`` / ``ctr``. Inert only because
  nothing populates them yet, which is the state the other three were in
  before a field was added.

Finding it three times did not prevent the fourth, because the defect is an
omission and omissions are invisible in review. So these tests are driven off
``dataclasses.fields(...)`` rather than a hand-written list: each states only
the fields its mutator DECLARES it changes, and asserts everything else
survived. A field added to :class:`StateDocument`, :class:`PlatformState` or
:class:`CampaignMetrics` is checked by every one of them without any test
being edited — and the value maps below fail loudly if the new field has no
distinctive value to check.

One caveat worth stating, because it is why the fourth instance sat unnoticed:
where every current field already has a declared role, an enumerated rebuild
and a ``replace`` behave IDENTICALLY, so no behavioural assertion can tell
them apart. That case needs the structural guard —
``test_a_field_the_merge_does_not_know_about_survives``, which subclasses the
model to supply a field the function has never heard of.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.anomaly_detector import CampaignMetrics
from mureo.analytics.builtin._live_clients import _merge_campaign_metrics
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


#: One distinctive value per :class:`CampaignMetrics` field, and which of the
#: three roles each plays when two rows for the same campaign are folded
#: together. The roles are what make the check meaningful: a counter must be
#: SUMMED, a ratio must be CLEARED (it cannot be summed, and carrying one row's
#: value would report it as the total's), and anything else must be PRESERVED.
_METRICS_IDENTITY = {"campaign_id"}
_METRICS_SUMMED = {"cost", "impressions", "clicks", "conversions"}
_METRICS_CLEARED = {"cpa", "ctr"}
_METRICS_FIELD_VALUES: dict[str, Any] = {
    "campaign_id": "C-1",
    "cost": 1000.0,
    "impressions": 500,
    "clicks": 50,
    "conversions": 5.0,
    "cpa": 200.0,
    "ctr": 0.1,
}


@pytest.mark.unit
class TestCampaignMetricsMerge:
    """Folding two rows for one campaign must not drop fields (fourth instance).

    ``_index_google_rows_by_campaign`` / ``_index_meta_rows_by_campaign``
    rebuilt :class:`CampaignMetrics` by enumerating five of its seven fields,
    so ``cpa`` / ``ctr`` were dropped. Inert today only because nothing in
    ``_live_clients`` populates them — precisely the state the other three
    instances were in before a field was added.
    """

    def test_every_field_has_a_declared_role(self) -> None:
        """A new field forces a decision: summed, cleared, or preserved."""
        declared = {f.name for f in fields(CampaignMetrics)}
        classified = _METRICS_IDENTITY | _METRICS_SUMMED | _METRICS_CLEARED
        unclassified = declared - classified
        assert not unclassified or unclassified == declared - set(
            _METRICS_FIELD_VALUES
        ), (
            f"CampaignMetrics gained field(s) {sorted(unclassified)}. Decide "
            "whether a merge should sum it, clear it (ratios and averages "
            "cannot be summed), or carry it over, then update "
            "_merge_campaign_metrics and this test."
        )
        _assert_map_covers(CampaignMetrics, _METRICS_FIELD_VALUES)

    def test_counters_are_summed_and_ratios_cleared(self) -> None:
        first = CampaignMetrics(**_METRICS_FIELD_VALUES)
        second = CampaignMetrics(**_METRICS_FIELD_VALUES)
        merged = _merge_campaign_metrics(first, second)

        for name in _METRICS_SUMMED:
            assert getattr(merged, name) == getattr(first, name) * 2, name
        for name in _METRICS_CLEARED:
            assert getattr(merged, name) is None, (
                f"{name!r} is a ratio: carrying one row's value across a merge "
                "would report it as the total's."
            )
        for name in _METRICS_IDENTITY:
            assert getattr(merged, name) == getattr(first, name)

    def test_unclassified_fields_survive_a_merge(self) -> None:
        """Anything that is not a counter or a ratio is carried over.

        Driven off the field list, so a field added to
        :class:`CampaignMetrics` is checked here without this test being
        edited.
        """
        first = CampaignMetrics(**_METRICS_FIELD_VALUES)
        merged = _merge_campaign_metrics(first, CampaignMetrics(campaign_id="C-1"))
        for field in fields(CampaignMetrics):
            if field.name in _METRICS_SUMMED | _METRICS_CLEARED:
                continue
            assert getattr(merged, field.name) == getattr(first, field.name), (
                f"{field.name!r} was dropped by a merge. _merge_campaign_metrics "
                "must use dataclasses.replace and name only the fields it owns."
            )

    def test_a_field_the_merge_does_not_know_about_survives(self) -> None:
        """The structural guard — and the only one that fails TODAY.

        Every field of :class:`CampaignMetrics` currently has a declared role,
        so an enumerated rebuild and a ``replace`` are behaviourally identical
        right now: the two fields it drops are the two a merge clears anyway.
        A behavioural assertion therefore cannot tell them apart, which is
        exactly why this instance sat inert and unnoticed.

        Subclassing supplies the field the merge has never heard of.
        ``dataclasses.replace`` reconstructs ``type(obj)`` and carries it;
        naming ``CampaignMetrics(...)`` explicitly returns the base class and
        drops it. That difference is the property under test, and it holds for
        any future field without this test being edited.
        """

        @dataclass(frozen=True)
        class ExtendedMetrics(CampaignMetrics):
            source_report: str | None = None

        first = ExtendedMetrics(
            campaign_id="C-1", cost=100.0, clicks=10, source_report="weekly"
        )
        second = ExtendedMetrics(
            campaign_id="C-1", cost=50.0, clicks=5, source_report="weekly"
        )
        merged = _merge_campaign_metrics(first, second)

        assert isinstance(merged, ExtendedMetrics), (
            "_merge_campaign_metrics rebuilt the record as a bare "
            "CampaignMetrics. Use dataclasses.replace, which reconstructs the "
            "actual type and carries fields the function does not name."
        )
        assert merged.source_report == "weekly"
        assert merged.cost == 150.0

    def test_cleared_ratios_recompute_from_the_summed_counters(self) -> None:
        """Clearing is not data loss — the derived accessors do the right sum."""
        first = CampaignMetrics(
            campaign_id="C-1",
            cost=1000.0,
            impressions=1000,
            clicks=50,
            conversions=5.0,
            cpa=200.0,
            ctr=0.05,
        )
        merged = _merge_campaign_metrics(first, first)
        assert merged.derived_cpa() == pytest.approx(2000.0 / 10.0)
        assert merged.derived_ctr() == pytest.approx(100 / 2000)


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
