"""A targeted write must change what it declares and nothing else.

Every STATE.json mutator rebuilt its document — and its platform entry — by
enumerating fields. That works until a field is added, at which point every
mutator that forgot it silently resets it, and a reset field is
indistinguishable downstream from one that was never set. The bug therefore
does not announce itself; it is found later, from the damage.

It has been found five times in this project now:

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
- ``preflight_tracking_consistency`` here — found while rebasing onto the
  commit that introduced it (#570). All five fields of
  ``TrackingConsistencyReport`` were enumerated, so nothing is dropped today;
  the sixth field added to that model would be. Two functions beside it in the
  same file already used ``replace``.

Finding it four times did not prevent the fifth, because the defect is an
omission and omissions are invisible in review. So these tests are driven off
``dataclasses.fields(...)`` rather than a hand-written list: each states only
the fields its mutator DECLARES it changes, and asserts everything else
survived. A field added to :class:`StateDocument`, :class:`PlatformState`,
:class:`CampaignMetrics` or ``TrackingConsistencyReport`` is checked by every
one of them without any test being edited — and the value maps below fail
loudly if the new field has no distinctive value to check.

Two subtleties, both of which produced a test that looked like a guard and was
not. They are the reason this file is longer than it first appears it needs to
be.

**1. Where every field already has a declared role, behaviour cannot tell an
enumerated rebuild from a ``replace``.** That is why the ``CampaignMetrics``
instance sat unnoticed: the two fields it dropped are the two a merge clears
anyway, so the old code and the fixed code produce identical output today. The
guard there has to be STRUCTURAL —
``test_a_field_the_merge_does_not_know_about_survives`` subclasses the model to
supply a field the function has never heard of, which ``replace`` carries and
an enumerated constructor discards.

**2. Every fixture value must be NON-DEFAULT.** A field the codec declares but
wires into neither half comes back at its default; if the fixture also left it
at its default, the comparison passes and the loss is invisible. Naming a field
in ``state_codec._CODEC_COVERAGE`` satisfies the import-time check — which
asserts declaration — while still dropping the data on every write. Only a
distinctive value in the maps below turns that into a failure, which is why
``_assert_map_covers`` runs over EVERY model the codec touches
(:data:`_CODEC_MODELS`), nested ones included, rather than just the two at the
top.

Division of labour, stated once: the import-time check in ``state_codec``
asserts a field is DECLARED; the round-trip tests here assert it SURVIVES.
Neither substitutes for the other.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.anomaly_detector import CampaignMetrics
from mureo.analytics.builtin._live_clients import _merge_campaign_metrics
from mureo.context.models import (
    EXTERNAL_ORIGIN,
    ActionLogEntry,
    AdState,
    BatchRecord,
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
    set_platform_daily,
    set_platform_metrics,
    set_platform_not_collected,
    set_report,
    set_workspace_not_collected,
    upsert_campaign,
    write_state_file,
)

_ACCOUNT = "123-456-7890"
_PLATFORM = "google_ads"


# Every value below must be NON-DEFAULT and distinctive. That is the whole
# mechanism: a codec that declares a field but wires neither half leaves it at
# its default on the way back, so a fixture that also left it at its default
# would compare equal and the loss would be invisible. Every nested model gets
# the same treatment for the same reason — a gap in any one of them is a gap in
# the round trip.

#: One distinctive value per :class:`AdState` field.
_AD_STATE_FIELD_VALUES: dict[str, Any] = {
    "ad_id": "A-1",
    "name": "RSA — spring",
    "status": "ENABLED",
    "effective_status": "DISAPPROVED",
    "as_of": "2026-08-08T08:00:00+09:00",
}

#: One distinctive value per :class:`ActionLogEntry` field.
_ACTION_LOG_FIELD_VALUES: dict[str, Any] = {
    "timestamp": "2026-08-08T09:30:00+09:00",
    "action": "google_ads_budget_update",
    "platform": _PLATFORM,
    "campaign_id": "C-1",
    "ad_id": "A-1",
    "summary": "raised daily budget",
    "command": "/budget-rebalance",
    "metrics_at_action": {"cpa": 5200, "conversions": 45},
    "observation_due": "2026-08-22",
    "reversible_params": {
        "operation": "google_ads_budget_update",
        "params": {"budget_id": "B1", "amount": 10000},
    },
    "rollback_of": 3,
    "evaluation_of": 4,
    "entity_type": "ad_group",
    "entity_id": "G-1",
    "batch_id": "B-20260808-093000-a1b2",
    "origin": EXTERNAL_ORIGIN,
    "external_id": "google_ads|customers/1/changeEvents/abc",
    "occurred_at": "2026-08-05T09:14:00+09:00",
}

#: One distinctive value per :class:`BatchRecord` field (#549).
_BATCH_FIELD_VALUES: dict[str, Any] = {
    "batch_id": "B-20260808-093000-a1b2",
    "label": "pause the losing ad groups",
    "started_at": "2026-08-08T09:30:00+09:00",
    "ended_at": "2026-08-08T09:41:00+09:00",
}

#: One distinctive value per :class:`CampaignSnapshot` field, minus the id the
#: caller varies.
_CAMPAIGN_FIELD_VALUES: dict[str, Any] = {
    "campaign_id": "C-1",
    "campaign_name": "Brand Search",
    "status": "ENABLED",
    "bidding_strategy_type": "TARGET_CPA",
    "bidding_details": {"target_cpa": 5000},
    "daily_budget": 12000.0,
    "monthly_budget": 360000.0,
    "device_targeting": ({"device": "MOBILE", "modifier": 1.2},),
    "campaign_goal": "leads",
    "notes": "do not pause",
    "metrics": {"spend": 4200.0, "clicks": 310},
    "ads": (AdState(**_AD_STATE_FIELD_VALUES),),
}


def _campaign(campaign_id: str = "C-1") -> CampaignSnapshot:
    return CampaignSnapshot(**{**_CAMPAIGN_FIELD_VALUES, "campaign_id": campaign_id})


#: One distinctive value per :class:`PlatformState` field.
_PLATFORM_FIELD_VALUES: dict[str, Any] = {
    "account_id": _ACCOUNT,
    "campaigns": (_campaign(),),
    "totals": {"spend": 4200.0, "conversions": 12},
    "metrics_period": "LAST_30_DAYS",
    "periods": {"LAST_30_DAYS": {"spend": 4200.0}},
    "daily": {"2026-08-07": {"spend": 140.0, "clicks": 11}},
    "conversion_action_types": ("offsite_conversion.custom.42",),
    "not_collected": {
        "attempted_at": "2026-08-08T09:00:00+09:00",
        "reason": "the Meta access token expired",
    },
}

#: One distinctive value per :class:`StateDocument` field.
_DOCUMENT_FIELD_VALUES: dict[str, Any] = {
    "version": "2",
    "last_synced_at": "2026-08-08T09:00:00+09:00",
    "customer_id": _ACCOUNT,
    "campaigns": (_campaign(),),
    "platforms": {_PLATFORM: PlatformState(**_PLATFORM_FIELD_VALUES)},
    "action_log": (ActionLogEntry(**_ACTION_LOG_FIELD_VALUES),),
    "reports": {"daily": {"narrative": "healthy"}},
    "workspace_not_collected": {
        "attempted_at": "2026-08-08T08:00:00+09:00",
        "reason": "the credentials file could not be read",
    },
    "batches": (BatchRecord(**_BATCH_FIELD_VALUES),),
}

#: Every model the STATE.json codec maps, with the map that must cover it.
#: Checked as one table so a model cannot be added to the codec and quietly
#: left out of the round trip.
_CODEC_MODELS: tuple[tuple[type, dict[str, Any]], ...] = (
    (StateDocument, _DOCUMENT_FIELD_VALUES),
    (PlatformState, _PLATFORM_FIELD_VALUES),
    (ActionLogEntry, _ACTION_LOG_FIELD_VALUES),
    (CampaignSnapshot, _CAMPAIGN_FIELD_VALUES),
    (AdState, _AD_STATE_FIELD_VALUES),
    (BatchRecord, _BATCH_FIELD_VALUES),
)


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


def _assert_every_codec_model_covered() -> None:
    """Every model the codec maps has a fully-populated, non-default fixture."""
    for model, values in _CODEC_MODELS:
        _assert_map_covers(model, values)


def _seed(path: Path) -> StateDocument:
    """Write a STATE.json with every field of every model populated."""
    _assert_every_codec_model_covered()
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

    def test_set_platform_daily(self, seeded: tuple[Path, StateDocument]) -> None:
        path, before = seeded
        after = set_platform_daily(
            path, _PLATFORM, _ACCOUNT, days={"2026-08-06": {"spend": 100.0}}
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

    def test_set_platform_not_collected(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        path, before = seeded
        after = set_platform_not_collected(
            path, _PLATFORM, _ACCOUNT, reason="the sync did not run"
        )
        # ``last_synced_at`` is NOT in `changed`: a collection that failed is
        # not a sync, and re-stamping it would report the document as
        # just-synced on the strength of nothing having been collected.
        _assert_document_preserved(before, after, changed={"platforms"})
        assert after.last_synced_at == before.last_synced_at

    def test_set_workspace_not_collected(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        path, before = seeded
        after = set_workspace_not_collected(path, reason="the collection never ran")
        # One field, and ``last_synced_at`` is not among them for the same
        # reason as above: a collection that failed is not a sync. The
        # PER-PLATFORM notes are not among them either — the two record
        # different failures and neither implies the other.
        _assert_document_preserved(before, after, changed={"workspace_not_collected"})
        assert after.last_synced_at == before.last_synced_at
        assert after.workspace_not_collected is not None
        assert after.workspace_not_collected["reason"] == "the collection never ran"


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
        # …and the window this call did NOT name is byte-for-byte what it
        # was, down to the absent fetched_at: the #637 stamp lands only on
        # the rollups a write actually supplies.
        assert merged["LAST_30_DAYS"] == {"spend": 4200.0}
        assert merged["YESTERDAY"]["spend"] == 100.0
        # A None argument means "leave as it was", not "clear it".
        assert self._platform(after).totals == _PLATFORM_FIELD_VALUES["totals"]

    def test_daily_write_keeps_every_window_rollup(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        path, before = seeded
        after = set_platform_daily(
            path, _PLATFORM, _ACCOUNT, days={"2026-08-06": {"spend": 100.0}}
        )
        _assert_platform_preserved(
            self._platform(before), self._platform(after), changed={"daily"}
        )
        # ``daily`` merges per DATE key, so the day already stored survives —
        # down to its absent fetched_at, since the stamp lands only on the
        # buckets a write actually supplies.
        merged = self._platform(after).daily
        assert merged is not None
        assert merged["2026-08-07"] == {"spend": 140.0, "clicks": 11}
        assert merged["2026-08-06"]["spend"] == 100.0

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

    def test_the_not_collected_note_write_keeps_every_figure(
        self, seeded: tuple[Path, StateDocument]
    ) -> None:
        """It says the numbers were not UPDATED — never that they are wrong,
        and never by touching them."""
        path, before = seeded
        after = set_platform_not_collected(
            path, _PLATFORM, _ACCOUNT, reason="the sync did not run"
        )
        _assert_platform_preserved(
            self._platform(before),
            self._platform(after),
            changed={"not_collected"},
        )
        note = self._platform(after).not_collected
        assert note is not None and note["reason"] == "the sync did not run"

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
class TestTrackingReportNarrowing:
    """Narrowing a tracking report to the planned ads keeps the rest.

    Fifth instance, found while rebasing onto the commit that introduced it
    (#570). ``preflight_tracking_consistency`` runs the account-wide detector
    and then narrows the result to the ads being uploaded. It rebuilt
    :class:`TrackingConsistencyReport` field-by-field, enumerating all five —
    complete today, and silently resetting whatever is added tomorrow.

    Every field being enumerated correctly is exactly why a behavioural
    assertion proves nothing here, the same trap as ``CampaignMetrics``. The
    report is built inside the function, so the subclass has to arrive through
    the seam: patching the detector makes it return a model carrying a field
    the narrowing step has never heard of. ``replace`` reconstructs
    ``type(obj)`` and keeps it; naming ``TrackingConsistencyReport(...)``
    returns the base class and drops it.
    """

    def test_narrowing_preserves_a_field_it_does_not_know_about(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.analysis.tracking import checks as tracking_checks
        from mureo.analysis.tracking.models import TrackingConsistencyReport

        @dataclass(frozen=True)
        class ExtendedReport(TrackingConsistencyReport):
            scan_id: str | None = None

        monkeypatch.setattr(
            tracking_checks,
            "check_tracking_consistency",
            lambda *a, **k: ExtendedReport(
                ads_examined=7,
                campaigns_examined=2,
                notes=("delivery data absent",),
                scan_id="SCAN-1",
            ),
        )
        narrowed = tracking_checks.preflight_tracking_consistency([], [])

        assert isinstance(narrowed, ExtendedReport), (
            "preflight_tracking_consistency rebuilt the report as a bare "
            "TrackingConsistencyReport. Use dataclasses.replace so fields it "
            "does not own survive."
        )
        assert narrowed.scan_id == "SCAN-1"

    def test_narrowing_preserves_every_field_it_does_not_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two fields it DOES own change; the rest are carried across."""
        from mureo.analysis.tracking import checks as tracking_checks
        from mureo.analysis.tracking.models import TrackingConsistencyReport

        source = TrackingConsistencyReport(
            ads_examined=7,
            campaigns_examined=2,
            ads_without_readable_url=("ad-9",),
            notes=("delivery data absent — severities capped at HIGH",),
        )
        monkeypatch.setattr(
            tracking_checks, "check_tracking_consistency", lambda *a, **k: source
        )
        narrowed = tracking_checks.preflight_tracking_consistency([], [])

        owned = {"findings", "ads_without_readable_url"}
        for field in fields(TrackingConsistencyReport):
            if field.name in owned:
                continue
            assert getattr(narrowed, field.name) == getattr(source, field.name), (
                f"{field.name!r} was reset while narrowing the report to the "
                "planned ads."
            )


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
        _assert_every_codec_model_covered()
        doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
        restored = parse_state(render_state(doc))
        for field in fields(StateDocument):
            assert getattr(restored, field.name) == getattr(doc, field.name), (
                f"{field.name!r} did not survive the STATE.json round trip — "
                "check BOTH halves of state_codec."
            )

    def test_every_platform_field_survives_render_and_parse(self) -> None:
        _assert_every_codec_model_covered()
        doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
        restored = parse_state(render_state(doc))
        assert restored.platforms is not None
        for field in fields(PlatformState):
            assert getattr(restored.platforms[_PLATFORM], field.name) == getattr(
                doc.platforms[_PLATFORM], field.name  # type: ignore[index]
            ), f"platform field {field.name!r} did not survive the round trip"

    def test_every_action_log_field_survives_render_and_parse(self) -> None:
        """#545 adds three fields to this codec pair — the gap closes first.

        Declaring a field in ``_CODEC_COVERAGE`` while wiring neither half of
        ``_parse_action_log_entry`` / ``_action_log_entry_to_dict`` passes the
        import-time check, because that check asserts declaration only. It is
        this assertion that catches the loss — but only because every field in
        the fixture carries a distinctive NON-DEFAULT value, so a dropped one
        comes back different rather than coincidentally equal.
        """
        _assert_every_codec_model_covered()
        doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
        restored = parse_state(render_state(doc))
        original_entry = doc.action_log[0]
        restored_entry = restored.action_log[0]
        for field in fields(ActionLogEntry):
            assert getattr(restored_entry, field.name) == getattr(
                original_entry, field.name
            ), (
                f"action_log field {field.name!r} did not survive the round "
                "trip — naming it in _CODEC_COVERAGE is not enough, BOTH "
                "_parse_action_log_entry and _action_log_entry_to_dict must "
                "handle it."
            )

    def test_every_ad_state_field_survives_render_and_parse(self) -> None:
        """``AdState`` is nested two deep and had the same blind spot."""
        _assert_every_codec_model_covered()
        doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
        restored = parse_state(render_state(doc))
        original_ads = doc.campaigns[0].ads
        restored_ads = restored.campaigns[0].ads
        assert original_ads is not None and restored_ads is not None
        for field in fields(AdState):
            assert getattr(restored_ads[0], field.name) == getattr(
                original_ads[0], field.name
            ), (
                f"ads[] field {field.name!r} did not survive the round trip — "
                "check BOTH _parse_ad and _ad_state_to_dict."
            )

    def test_every_campaign_field_survives_render_and_parse(self) -> None:
        _assert_every_codec_model_covered()
        doc = StateDocument(**_DOCUMENT_FIELD_VALUES)
        restored = parse_state(render_state(doc))
        for field in fields(CampaignSnapshot):
            assert getattr(restored.campaigns[0], field.name) == getattr(
                doc.campaigns[0], field.name
            ), (
                f"campaign field {field.name!r} did not survive the round trip "
                "— check BOTH _parse_campaign and _snapshot_to_dict."
            )

    def test_round_trip_through_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        doc = _seed(path)
        restored = read_state_file(path)
        for field in fields(StateDocument):
            assert getattr(restored, field.name) == getattr(doc, field.name)
