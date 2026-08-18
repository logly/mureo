"""#610 — the supported way out of a platform key mureo cannot resolve.

#609 stops a new bad key being written. This is the other half: an operator
whose ``platforms`` map ALREADY carries one had no move except opening
STATE.json and editing it by hand, which on a non-engineer's machine is the
more dangerous option, not the safer one.

What these tests pin:

  - the reported shape end to end — LOGLY snapshots filed under ``logly_ads``
    beside the bridge's real provider name ``logly_ads_context``, one ad
    account, two entries — is repaired, and the repaired document no longer
    produces a ``duplicate_account`` conflict from ``mureo.web.reports``;
  - **planning changes nothing** (the dry run the CLI defaults to);
  - a backup of the pre-repair document exists before anything is written;
  - a duplicate whose two keys BOTH name real platforms is left alone — that
    is the case ``mureo/web/reports.py`` deliberately refuses to decide, and
    this repair does not widen into a general duplicate merger;
  - **unresolvable alone is not enough to offer removal** (#616). "mureo
    cannot resolve this key" is a fact about the machine running the repair,
    not about the entry — the plugin that registers the key may simply not be
    installed here. Removal is offered only when the DOCUMENT shows the entry
    is wrong: it duplicates a key mureo CAN resolve holding the same ad
    account, or it is an empty stub;
  - an entry carrying ``conversion_action_types`` is never dropped (#617).
    That allow-list is operator-declared, so no sync restores it;
  - a duplicate whose two keys BOTH resolve is repaired only when the losing
    key is named EXPLICITLY (#636). Naming it is the operator recording the
    decision mureo refuses to make for them; without that the plan is silent
    and the document is untouched, and no explicit naming overrides #617;
  - the write goes through a path ``guard_platform_entry_write`` does not
    refuse — verified against a document the create guard would reject;
  - nothing is summed, moved or re-stamped: the surviving entry is byte-for
    -byte what it was, and ``last_synced_at`` is not touched (a repair is not
    a sync).

Every test pins the installed-plugin set. This machine has real bridges
installed, so a test leaning on the ambient environment would pass for a
reason it never asserted.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context import platform_guards
from mureo.context.platform_repair import (
    DROP_CHOSEN_DUPLICATE,
    DROP_DUPLICATE,
    DROP_EMPTY_STUB,
    KEEP_CARRIES_FIGURES,
    KEEP_CONVERSION_OVERRIDE,
    KEEP_NOT_A_DUPLICATE,
    apply_state_file_repairs,
    drop_platform_entries,
    is_unresolvable_platform_key,
    plan_platform_key_repairs,
    plan_platform_keys,
)
from mureo.context.state import read_state_file
from mureo.core.runtime_context import default_runtime_context, reset_runtime_context

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


def _pin_installed_platforms(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Pin which plugin platforms the environment reports as installed.

    Same pin the #609 guard tests use, and for the same reason: the machine
    that reported both issues has ``logly_ads_context`` and the LINE/Yahoo
    bridge installed, so an unpinned test would assert nothing.
    """
    entries = tuple(SimpleNamespace(name=name) for name in names)
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: entries)


def _logly_totals(spend: float, fetched_at: str) -> dict[str, Any]:
    return {
        "spend": spend,
        "conversions": 12,
        "period": "LAST_30_DAYS",
        "fetched_at": fetched_at,
    }


def _reported_document() -> dict[str, Any]:
    """The incident: one ad account, two keys, only one of them resolvable."""
    return {
        "version": "2",
        "last_synced_at": "2026-08-12T01:00:00+00:00",
        "platforms": {
            "logly_ads": {
                "account_id": "1234567890",
                "campaigns": [
                    {
                        "campaign_id": "c-1",
                        "campaign_name": "Brand",
                        "status": "ENABLED",
                    }
                ],
                "totals": _logly_totals(9000.0, "2026-08-01T03:00:00+00:00"),
                "metrics_period": "LAST_30_DAYS",
                "periods": {
                    "LAST_30_DAYS": _logly_totals(9000.0, "2026-08-01T03:00:00+00:00")
                },
            },
            "logly_ads_context": {
                "account_id": "1234567890",
                "campaigns": [
                    {
                        "campaign_id": "c-1",
                        "campaign_name": "Brand",
                        "status": "ENABLED",
                    }
                ],
                "totals": _logly_totals(4500.0, "2026-08-12T03:00:00+00:00"),
                "metrics_period": "LAST_30_DAYS",
                "periods": {
                    "LAST_30_DAYS": _logly_totals(4500.0, "2026-08-12T03:00:00+00:00")
                },
            },
        },
        "action_log": [
            {
                "timestamp": "2026-08-11T09:00:00+00:00",
                "action": "update_budget",
                "platform": "logly_ads_context",
            }
        ],
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak.*"))


# ---------------------------------------------------------------------------
# Which keys the repair is even willing to look at
# ---------------------------------------------------------------------------


class TestUnresolvableKeyDefinition:
    """What counts as resolvable is #609's answer, reused — never a second one.

    A second definition that can drift from the first is the bug this pair of
    issues is about, so this asks ``reject_unknown_platform_key`` and reports
    what it said.
    """

    def test_a_builtin_is_resolvable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _pin_installed_platforms(monkeypatch)
        assert not is_unresolvable_platform_key("google_ads")

    def test_an_installed_providers_name_is_resolvable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        assert not is_unresolvable_platform_key("logly_ads_context")

    def test_a_canonical_plugin_key_is_resolvable_uninstalled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The escape hatch #609 kept open: a snapshot whose bridge lives on
        another machine names its own distribution, so it needs no registry —
        and must never be offered up for deletion here."""
        _pin_installed_platforms(monkeypatch)
        assert not is_unresolvable_platform_key(
            "plugin:mureo-logly-bridge:logly_ads_context"
        )

    def test_the_invented_key_is_unresolvable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        assert is_unresolvable_platform_key("logly_ads")

    def test_an_unreadable_environment_resolves_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_provider_entry_points`` returning ``None`` means "could not
        enumerate". #609 fails OPEN on it, and inheriting that here is what
        stops a broken install from proposing to delete every plugin entry."""
        monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: None)
        assert not is_unresolvable_platform_key("logly_ads")


# ---------------------------------------------------------------------------
# The reported incident, end to end
# ---------------------------------------------------------------------------


class TestTheLoglyIncident:
    def test_the_document_is_repaired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())
        before = read_state_file(path).platforms["logly_ads_context"]

        outcome = apply_state_file_repairs(path)

        assert outcome.changed is True
        assert [r.entry.key for r in outcome.repairs] == ["logly_ads"]
        doc = read_state_file(path)
        assert set(doc.platforms) == {"logly_ads_context"}
        # Nothing summed, nothing moved: the surviving entry is what it was.
        assert doc.platforms["logly_ads_context"] == before

    def test_the_repaired_document_reports_no_duplicate_account(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The finding the operator was stuck on is gone from the read side,
        asked of ``mureo.web.reports`` itself rather than re-derived here."""
        from mureo.web.reports import CONFLICT_DUPLICATE_ACCOUNT, build_report_summary

        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())
        ctx = default_runtime_context(workspace=tmp_path)
        monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)

        kinds_before = [
            row["kind"] for row in build_report_summary()["platform_conflicts"]
        ]
        assert CONFLICT_DUPLICATE_ACCOUNT in kinds_before

        apply_state_file_repairs(path)

        kinds_after = [
            row["kind"] for row in build_report_summary()["platform_conflicts"]
        ]
        assert CONFLICT_DUPLICATE_ACCOUNT not in kinds_after

    def test_the_rest_of_the_document_is_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Including ``last_synced_at``: a repair is not a sync, and
        re-stamping it would make every other platform's stale figures read
        as just-synced (the #535 trap)."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())

        apply_state_file_repairs(path)

        doc = read_state_file(path)
        assert doc.last_synced_at == "2026-08-12T01:00:00+00:00"
        assert len(doc.action_log) == 1
        assert doc.action_log[0].platform == "logly_ads_context"

    def test_the_repair_is_not_recorded_in_the_action_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deliberate. ``action_log`` records changes made to an AD PLATFORM
        — every entry names a ``platform`` and is fed to ``plan_rollback``,
        whose allow-list is MCP tool operations. A local-file repair has no
        platform operation to name and none to reverse, and the entry would
        have to carry the very key just removed, putting it back on the
        dashboard's activity feed and in every ``--platform`` filter.
        Reversibility is the timestamped backup, which restores the exact
        prior document — strictly more than a rollback plan could offer."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())

        apply_state_file_repairs(path)

        assert [e.action for e in read_state_file(path).action_log] == ["update_budget"]


# ---------------------------------------------------------------------------
# Show before doing
# ---------------------------------------------------------------------------


class TestPlanningChangesNothing:
    def test_planning_leaves_the_file_byte_identical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())
        before = path.read_bytes()

        repairs = plan_platform_key_repairs(read_state_file(path))

        assert [r.entry.key for r in repairs] == ["logly_ads"]
        assert path.read_bytes() == before
        assert _backups(path) == []

    def test_the_plan_names_what_each_entry_holds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The operator cannot read JSON, so the plan has to carry the facts
        they would otherwise have to open the file to see."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())

        (repair,) = plan_platform_key_repairs(read_state_file(path))

        entry = repair.entry
        assert entry.key == "logly_ads"
        assert entry.resolvable is False
        assert entry.account_id == "1234567890"
        assert entry.campaign_count == 1
        assert entry.has_totals is True
        assert entry.metrics_period == "LAST_30_DAYS"
        assert entry.totals_fetched_at == "2026-08-01T03:00:00+00:00"
        assert [(r.period, r.fetched_at) for r in entry.rollups] == [
            ("LAST_30_DAYS", "2026-08-01T03:00:00+00:00")
        ]
        # And the entry the account is really stored under, so the operator
        # can see what survives.
        (other,) = repair.same_account
        assert other.key == "logly_ads_context"
        assert other.resolvable is True
        assert other.totals_fetched_at == "2026-08-12T03:00:00+00:00"

    def test_drop_platform_entries_is_pure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())
        doc = read_state_file(path)

        repaired = drop_platform_entries(doc, ("logly_ads",))

        assert set(repaired.platforms) == {"logly_ads_context"}
        assert set(doc.platforms) == {"logly_ads", "logly_ads_context"}


# ---------------------------------------------------------------------------
# Back up first
# ---------------------------------------------------------------------------


class TestBackup:
    def test_a_backup_of_the_pre_repair_document_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())

        outcome = apply_state_file_repairs(path)

        assert outcome.backup is not None
        assert outcome.backup.exists()
        assert _backups(path) == [outcome.backup]
        restored = json.loads(outcome.backup.read_text(encoding="utf-8"))
        assert set(restored["platforms"]) == {"logly_ads", "logly_ads_context"}

    def test_a_second_repair_does_not_clobber_the_first_backup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Timestamped, not a single rolling ``.bak``: a second run would
        otherwise overwrite the only copy of the pre-repair document with the
        already-repaired one."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())
        first = apply_state_file_repairs(path)

        # Re-introduce a second bad key and repair again.
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["platforms"]["logly_ads_v2"] = {"account_id": "1234567890"}
        _write(path, payload)
        second = apply_state_file_repairs(path)

        assert second.backup is not None
        assert first.backup is not None
        assert second.backup != first.backup
        assert first.backup.exists()

    def test_no_backup_is_taken_when_there_is_nothing_to_repair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {"logly_ads_context": {"account_id": "1234567890"}},
            },
        )
        before = path.read_bytes()

        outcome = apply_state_file_repairs(path)

        assert outcome.changed is False
        assert outcome.backup is None
        assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# Scope: the unresolvable-key case only
# ---------------------------------------------------------------------------


class TestScope:
    def test_a_duplicate_of_two_real_platforms_is_left_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``mureo/web/reports.py`` refuses to decide this one and is right:
        both keys name a platform, so which entry holds the true figures is a
        question about money that only the operator can answer. This repair
        does not widen into a general duplicate merger."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "google_ads": {"account_id": "1234567890"},
                    "logly_ads_context": {"account_id": "1234567890"},
                },
            },
        )
        before = path.read_bytes()

        assert plan_platform_key_repairs(read_state_file(path)) == ()
        outcome = apply_state_file_repairs(path)

        assert outcome.changed is False
        assert path.read_bytes() == before

    def test_a_lone_unresolvable_key_with_figures_is_out_of_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reversed by #616, deliberately.

        It used to be IN scope, on the reasoning that the reported shape
        carries ``account_id: ""`` on the bad entry so the account join cannot
        see the pair. But an entry that joins with nothing and carries figures
        is indistinguishable from a legitimate solitary entry whose bridge is
        not installed on THIS machine — and deleting that one loses the only
        record of real spend. An entry with an unknown account id and nothing
        stored is still offered (it is an empty stub); one carrying figures is
        reported for the operator instead.
        """
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_context": {"account_id": "1234567890"},
                    "logly_ads": {
                        "account_id": "",
                        "totals": {"spend": 10.0, "fetched_at": "2026-08-01T00:00:00Z"},
                    },
                },
            },
        )
        before = path.read_bytes()

        plan = plan_platform_keys(read_state_file(path))
        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.entry.key == "logly_ads"
        assert finding.entry.account_id == ""
        assert finding.reason == KEEP_CARRIES_FIGURES
        # The join cannot connect the two, so the finding claims no context.
        assert finding.same_account == ()

        assert apply_state_file_repairs(path).changed is False
        assert path.read_bytes() == before

    def test_only_the_named_key_is_repaired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {"account_id": "1"},
                    "logly_adz": {"account_id": "2"},
                },
            },
        )

        apply_state_file_repairs(path, keys=("logly_ads",))

        assert set(read_state_file(path).platforms) == {"logly_adz"}

    def test_a_named_key_that_resolves_is_never_repaired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {"version": "2", "platforms": {"google_ads": {"account_id": "1"}}},
        )

        assert (
            plan_platform_key_repairs(read_state_file(path), keys=("google_ads",)) == ()
        )
        assert apply_state_file_repairs(path, keys=("google_ads",)).changed is False

    def test_an_unreadable_environment_repairs_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: None)
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())
        before = path.read_bytes()

        assert apply_state_file_repairs(path).changed is False
        assert path.read_bytes() == before

    def test_a_missing_file_repairs_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"

        outcome = apply_state_file_repairs(path)

        assert outcome.changed is False
        assert not path.exists()


# ---------------------------------------------------------------------------
# What the document has to SAY before an entry is offered (#616)
# ---------------------------------------------------------------------------


class TestWhatIsOfferedForRemoval:
    """Unresolvable alone selects nothing. The document has to show it is wrong.

    ``is_unresolvable_platform_key`` answers a question about the machine
    running the repair — which plugins are importable right now — not about
    the entry. On a machine where a bridge is not installed, that machine's
    legitimate solitary entry looks exactly like an invented key. So the plan
    asks the DOCUMENT instead: is this a duplicate of a key mureo can resolve
    holding the same ad account, or is it an empty stub?
    """

    def test_a_solitary_entry_with_figures_is_not_offered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The #616 case: a real platform, real figures, duplicating nothing —
        on a machine that simply does not have the bridge installed."""
        _pin_installed_platforms(monkeypatch)  # no plugin installed HERE
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_context": {
                        "account_id": "1234567890",
                        "campaigns": [
                            {
                                "campaign_id": "c-1",
                                "campaign_name": "Always-on prospecting",
                                "status": "ENABLED",
                            }
                        ],
                        "totals": _logly_totals(128000.0, "2026-08-13T23:10:00Z"),
                        "metrics_period": "LAST_30_DAYS",
                    }
                },
            },
        )
        before = path.read_bytes()

        plan = plan_platform_keys(read_state_file(path))

        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.entry.key == "logly_ads_context"
        assert finding.reason == KEEP_CARRIES_FIGURES
        assert apply_state_file_repairs(path).changed is False
        assert path.read_bytes() == before

    def test_a_duplicate_of_a_resolvable_key_is_offered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The incident's own shape: same ad account, one key that resolves."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _reported_document())

        plan = plan_platform_keys(read_state_file(path))

        (repair,) = plan.repairs
        assert repair.entry.key == "logly_ads"
        assert repair.reason == DROP_DUPLICATE
        assert plan.kept == ()

    def test_a_duplicate_of_another_UNRESOLVABLE_key_is_not_offered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two entries neither of which mureo can vouch for are not evidence
        against each other: dropping one still loses figures nothing refills."""
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "totals": _logly_totals(9000.0, "2026-08-01T03:00:00+00:00"),
                    },
                    "logly_ads_context": {
                        "account_id": "1234567890",
                        "totals": _logly_totals(4500.0, "2026-08-12T03:00:00+00:00"),
                    },
                },
            },
        )

        plan = plan_platform_keys(read_state_file(path))

        assert plan.repairs == ()
        assert [f.reason for f in plan.kept] == [
            KEEP_CARRIES_FIGURES,
            KEEP_CARRIES_FIGURES,
        ]

    def test_an_empty_stub_is_offered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No campaigns, no totals, no periods, no declared settings — there
        is nothing in it to lose, whoever the key belongs to."""
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {"version": "2", "platforms": {"logly_ads": {"account_id": "1234567890"}}},
        )

        plan = plan_platform_keys(read_state_file(path))

        (repair,) = plan.repairs
        assert repair.entry.key == "logly_ads"
        assert repair.reason == DROP_EMPTY_STUB
        apply_state_file_repairs(path)
        assert read_state_file(path).platforms == {}

    def test_an_id_less_empty_stub_is_offered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty ``account_id`` is not what makes a stub — an entry with an
        unknown id and real figures is NOT one — but it does not save an entry
        that stores nothing either."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_context": {"account_id": "1234567890"},
                    "logly_ads": {"account_id": ""},
                },
            },
        )

        plan = plan_platform_keys(read_state_file(path))

        (repair,) = plan.repairs
        assert repair.entry.key == "logly_ads"
        assert repair.reason == DROP_EMPTY_STUB

    def test_an_entry_that_only_carries_periods_is_not_a_stub(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "",
                        "periods": {
                            "YESTERDAY": {
                                "spend": 100.0,
                                "fetched_at": "2026-08-13T00:00:00Z",
                            }
                        },
                    }
                },
            },
        )

        plan = plan_platform_keys(read_state_file(path))

        assert plan.repairs == ()
        assert [f.reason for f in plan.kept] == [KEEP_CARRIES_FIGURES]


# ---------------------------------------------------------------------------
# The one field no sync brings back (#617)
# ---------------------------------------------------------------------------


class TestOperatorDeclaredSettings:
    """``conversion_action_types`` is declared by a person, not fetched (#342).

    Every other thing a ``platforms`` entry holds — the ad account, campaigns,
    ``totals``, ``periods``, ``metrics_period`` — is re-fetchable, which is
    what makes "drop it, the next sync refills the real key" a safe repair.
    This one is not: nothing on the platform side knows it, so dropping the
    entry loses it for good. mureo refuses rather than asking the operator to
    confirm a loss it can avoid.
    """

    def test_an_entry_carrying_an_override_is_never_dropped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "conversion_action_types": ["offsite_conversion.custom.90210"],
                    },
                    "logly_ads_context": {"account_id": "1234567890"},
                },
            },
        )
        before = path.read_bytes()

        plan = plan_platform_keys(read_state_file(path))

        # It IS a duplicate of a resolvable key — the only thing holding it
        # back is the setting no sync restores.
        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.entry.key == "logly_ads"
        assert finding.reason == KEEP_CONVERSION_OVERRIDE
        assert apply_state_file_repairs(path).changed is False
        assert path.read_bytes() == before

    def test_the_override_is_carried_into_the_facts_an_operator_reads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``PlatformEntryFacts`` is what the preview can print, so a field
        that is invisible there cannot be named before a confirmation."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "conversion_action_types": [
                            "offsite_conversion.custom.90210",
                            "offsite_conversion.custom.90211",
                        ],
                    },
                },
            },
        )

        (finding,) = plan_platform_keys(read_state_file(path)).kept

        assert finding.entry.conversion_action_types == (
            "offsite_conversion.custom.90210",
            "offsite_conversion.custom.90211",
        )

    def test_an_override_survives_a_repair_of_a_sibling_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal is per entry, not per document: a stub beside it is
        still removed, and the declared allow-list is still there afterwards."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {"account_id": "1234567890"},
                    "logly_ads_context": {
                        "account_id": "1234567890",
                        "conversion_action_types": ["offsite_conversion.custom.90210"],
                    },
                },
            },
        )

        outcome = apply_state_file_repairs(path)

        assert [r.entry.key for r in outcome.repairs] == ["logly_ads"]
        doc = read_state_file(path)
        assert doc.platforms["logly_ads_context"].conversion_action_types == (
            "offsite_conversion.custom.90210",
        )


# ---------------------------------------------------------------------------
# The other thing no sync brings back: a collection-failure note (#643)
# ---------------------------------------------------------------------------


class TestACollectionFailureNote:
    """An entry whose only content is ``not_collected`` is not an empty stub.

    ``is_empty_stub`` asks one question — does this entry store nothing a
    removal could lose? — and a note is something a removal loses. It records
    that a collection failed at a stated time, and nothing re-derives that: a
    later run either succeeds, retiring the note, or fails again and writes a
    new note about a new attempt. That puts it on the
    ``conversion_action_types`` side of the line this module already draws
    (#617), not the re-fetchable side.

    A platform that failed on its FIRST collection has no campaigns, no
    ``totals`` and no ``periods``, so the note is all there is — and both
    writers create exactly that entry on purpose, because it is the case an
    operator can least diagnose. Being unresolvable is a fact about the
    MACHINE (#609/#631), so without this the note is dropped as "empty"
    precisely on the machines where the operator cannot see the platform
    either.
    """

    def test_a_note_only_entry_is_not_an_empty_stub(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "not_collected": {
                            "attempted_at": "2026-08-13T04:00:00+00:00",
                            "reason": "the access token expired",
                        },
                    }
                },
            },
        )

        (finding,) = plan_platform_keys(read_state_file(path)).kept

        assert finding.entry.is_empty_stub is False

    def test_an_entry_with_nothing_at_all_still_is(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The note is what saves it, not the entry merely existing."""
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {"version": "2", "platforms": {"logly_ads": {"account_id": "1234567890"}}},
        )

        (repair,) = plan_platform_keys(read_state_file(path)).repairs

        assert repair.entry.is_empty_stub is True
        assert repair.reason == DROP_EMPTY_STUB

    def test_a_note_only_entry_is_reported_and_handed_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Under a key mureo cannot resolve — the only way DROP_EMPTY_STUB is
        reached at all, and the case where the note is the one record of why
        this platform has no figures."""
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "not_collected": {
                            "attempted_at": "2026-08-13T04:00:00+00:00",
                            "reason": "the access token expired",
                        },
                    }
                },
            },
        )
        before = path.read_bytes()

        plan = plan_platform_keys(read_state_file(path))

        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.entry.key == "logly_ads"
        assert finding.reason == KEEP_CARRIES_FIGURES
        assert apply_state_file_repairs(path).changed is False
        assert path.read_bytes() == before

    def test_the_note_is_carried_into_the_facts_an_operator_reads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``PlatformEntryFacts`` is what the preview can print, so a field
        that is invisible there cannot be named before a confirmation — the
        same reason ``conversion_action_types`` had to be carried (#617)."""
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "not_collected": {
                            "attempted_at": "2026-08-13T04:00:00+00:00",
                            "reason": "the access token expired",
                        },
                    }
                },
            },
        )

        (finding,) = plan_platform_keys(read_state_file(path)).kept

        assert finding.entry.not_collected_reason == "the access token expired"
        assert finding.entry.not_collected_attempted_at == "2026-08-13T04:00:00+00:00"

    def test_an_entry_with_figures_and_no_note_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The field is optional and additive: every entry written before
        #638 carries none, and reads back as none."""
        _pin_installed_platforms(monkeypatch)
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "totals": _logly_totals(9000.0, "2026-08-01T03:00:00+00:00"),
                    }
                },
            },
        )

        (finding,) = plan_platform_keys(read_state_file(path)).kept

        assert finding.entry.not_collected_reason is None
        assert finding.entry.not_collected_attempted_at is None

    def test_a_note_only_duplicate_of_a_resolvable_key_is_still_offered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The note changes what "empty" means, not what a duplicate is: the
        record survives under the key the account is really stored under, and
        DROP_DUPLICATE never asked whether the entry was empty."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "not_collected": {
                            "attempted_at": "2026-08-13T04:00:00+00:00",
                            "reason": "the access token expired",
                        },
                    },
                    "logly_ads_context": {
                        "account_id": "1234567890",
                        "totals": _logly_totals(4500.0, "2026-08-12T03:00:00+00:00"),
                    },
                },
            },
        )

        (repair,) = plan_platform_keys(read_state_file(path)).repairs

        assert repair.entry.key == "logly_ads"
        assert repair.reason == DROP_DUPLICATE


# ---------------------------------------------------------------------------
# Repair must stay possible (#609 left whole-document writes permissive)
# ---------------------------------------------------------------------------


class TestTheWritePathIsNotRefused:
    def test_the_repair_writes_a_document_the_create_guard_would_reject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verified, not assumed. The repaired document still carries a
        duplicate of two REAL keys — a shape ``guard_platform_entry_write``
        refuses to create — and the write still lands, because the repair
        goes through the whole-document funnel #609 deliberately left
        permissive."""
        from mureo.context.state import set_platform_metrics

        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {"account_id": "1234567890"},
                    "google_ads": {"account_id": "1234567890"},
                    "logly_ads_context": {"account_id": "1234567890"},
                },
            },
        )

        # The targeted create path refuses this document's shape outright.
        with pytest.raises(ValueError):
            set_platform_metrics(path, "meta_ads", "1234567890", totals={"spend": 1.0})

        outcome = apply_state_file_repairs(path)

        assert outcome.changed is True
        assert set(read_state_file(path).platforms) == {
            "google_ads",
            "logly_ads_context",
        }


# ---------------------------------------------------------------------------
# The operator's own decision, recorded explicitly (#636)
# ---------------------------------------------------------------------------


def _both_keys_resolve_document() -> dict[str, Any]:
    """#636: one ad account under two keys mureo CAN resolve.

    The reported pair — the bridge's own provider name and the legacy
    ``plugin:<distribution>`` spelling of the same platform. Neither is
    unresolvable, so nothing in the #616 plan reaches either of them.
    """
    return {
        "version": "2",
        "platforms": {
            "plugin:mureo-logly-bridge": {
                "account_id": "1234567890",
                "totals": _logly_totals(9000.0, "2026-08-01T03:00:00+00:00"),
                "metrics_period": "LAST_30_DAYS",
            },
            "logly_ads_context": {
                "account_id": "1234567890",
                "totals": _logly_totals(4500.0, "2026-08-12T03:00:00+00:00"),
                "metrics_period": "LAST_30_DAYS",
            },
        },
    }


class TestAnExplicitlyChosenDuplicate:
    """The operator answers the question mureo says is theirs (#636).

    Both keys resolve, so ``plan_platform_keys`` proposes nothing and the
    dashboard withholds the client's totals for good: mureo would not choose
    and the operator had no way to record having chosen. Naming the losing key
    explicitly is that way — and it is the ONLY thing that widens the plan.
    mureo still never picks a side.
    """

    def test_the_named_duplicate_is_offered_and_repaired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _both_keys_resolve_document())

        plan = plan_platform_keys(
            read_state_file(path),
            keys=("plugin:mureo-logly-bridge",),
            drop_duplicates=("plugin:mureo-logly-bridge",),
        )

        (repair,) = plan.repairs
        assert repair.entry.key == "plugin:mureo-logly-bridge"
        assert repair.entry.resolvable is True
        assert repair.reason == DROP_CHOSEN_DUPLICATE
        # The evidence is the document's, not the machine's: the sibling that
        # holds the same ad account is named.
        assert [facts.key for facts in repair.same_account] == ["logly_ads_context"]

        outcome = apply_state_file_repairs(
            path,
            keys=("plugin:mureo-logly-bridge",),
            drop_duplicates=("plugin:mureo-logly-bridge",),
        )

        assert outcome.changed is True
        assert set(read_state_file(path).platforms) == {"logly_ads_context"}
        # The backup still comes first.
        assert outcome.backup is not None
        assert _backups(path)

    def test_the_conflict_the_dashboard_reported_is_gone_afterwards(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asked of ``mureo.web.reports`` itself: the card recovers."""
        from mureo.web.reports import CONFLICT_DUPLICATE_ACCOUNT, build_report_summary

        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _both_keys_resolve_document())
        ctx = default_runtime_context(workspace=tmp_path)
        monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)

        kinds_before = [
            row["kind"] for row in build_report_summary()["platform_conflicts"]
        ]
        assert CONFLICT_DUPLICATE_ACCOUNT in kinds_before

        apply_state_file_repairs(
            path,
            keys=("plugin:mureo-logly-bridge",),
            drop_duplicates=("plugin:mureo-logly-bridge",),
        )

        kinds_after = [
            row["kind"] for row in build_report_summary()["platform_conflicts"]
        ]
        assert CONFLICT_DUPLICATE_ACCOUNT not in kinds_after

    def test_the_survivor_is_byte_for_byte_what_it_was(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drop, never merge — the same contract the #616 path has. Nothing is
        summed into the entry that stays."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _both_keys_resolve_document())
        before = read_state_file(path).platforms["logly_ads_context"]

        apply_state_file_repairs(
            path,
            keys=("plugin:mureo-logly-bridge",),
            drop_duplicates=("plugin:mureo-logly-bridge",),
        )

        assert read_state_file(path).platforms["logly_ads_context"] == before

    def test_without_the_explicit_choice_nothing_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Naming the key alone is not deciding: ``keys`` narrows the plan, it
        does not widen it. Silence here is what keeps mureo out of the
        operator's money question."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _both_keys_resolve_document())
        before = path.read_bytes()

        assert plan_platform_keys(read_state_file(path)).repairs == ()
        assert (
            plan_platform_keys(
                read_state_file(path), keys=("plugin:mureo-logly-bridge",)
            ).repairs
            == ()
        )
        assert apply_state_file_repairs(path).changed is False
        assert (
            apply_state_file_repairs(path, keys=("plugin:mureo-logly-bridge",)).changed
            is False
        )
        assert path.read_bytes() == before
        assert _backups(path) == []

    def test_planning_a_chosen_drop_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dry run the CLI defaults to: same file, same mtime, no backup."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(path, _both_keys_resolve_document())
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns

        plan_platform_keys(
            read_state_file(path),
            keys=("plugin:mureo-logly-bridge",),
            drop_duplicates=("plugin:mureo-logly-bridge",),
        )

        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime
        assert _backups(path) == []

    def test_an_entry_that_duplicates_nothing_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit is not carte blanche. This is not a general "delete a key"
        command: without a sibling holding the same ad account, the document
        does not show the entry to be a duplicate at all, and the operator may
        simply have mistyped the key they meant."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_context": {
                        "account_id": "1234567890",
                        "totals": _logly_totals(9000.0, "2026-08-01T03:00:00+00:00"),
                    },
                    "google_ads": {"account_id": "999"},
                },
            },
        )
        before = path.read_bytes()

        plan = plan_platform_keys(
            read_state_file(path),
            keys=("logly_ads_context",),
            drop_duplicates=("logly_ads_context",),
        )

        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.entry.key == "logly_ads_context"
        assert finding.reason == KEEP_NOT_A_DUPLICATE
        assert (
            apply_state_file_repairs(
                path,
                keys=("logly_ads_context",),
                drop_duplicates=("logly_ads_context",),
            ).changed
            is False
        )
        assert path.read_bytes() == before

    def test_an_entry_carrying_a_conversion_override_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#617 stands, named explicitly or not: no sync restores that
        allow-list, so dropping the entry loses it for good."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        payload = _both_keys_resolve_document()
        payload["platforms"]["plugin:mureo-logly-bridge"]["conversion_action_types"] = [
            "offsite_conversion.custom.90210"
        ]
        _write(path, payload)
        before = path.read_bytes()

        plan = plan_platform_keys(
            read_state_file(path),
            keys=("plugin:mureo-logly-bridge",),
            drop_duplicates=("plugin:mureo-logly-bridge",),
        )

        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.reason == KEEP_CONVERSION_OVERRIDE
        assert (
            apply_state_file_repairs(
                path,
                keys=("plugin:mureo-logly-bridge",),
                drop_duplicates=("plugin:mureo-logly-bridge",),
            ).changed
            is False
        )
        assert path.read_bytes() == before

    def test_only_the_named_key_is_widened(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of the duplicate stays, and so does every entry the
        operator said nothing about."""
        _pin_installed_platforms(monkeypatch, "logly_ads_context")
        path = tmp_path / "STATE.json"
        payload = _both_keys_resolve_document()
        payload["platforms"]["google_ads"] = {"account_id": "999"}
        _write(path, payload)

        apply_state_file_repairs(
            path,
            keys=("plugin:mureo-logly-bridge",),
            drop_duplicates=("plugin:mureo-logly-bridge",),
        )

        assert set(read_state_file(path).platforms) == {
            "logly_ads_context",
            "google_ads",
        }
