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
  - a lone unresolvable key that is NOT part of a duplicate is IN scope. It
    has to be: the shape actually reported from the field carries
    ``account_id: ""`` on one of the two entries, and an unknown id is never
    a join key, so the account join cannot see that pair at all;
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
    apply_state_file_repairs,
    drop_platform_entries,
    is_unresolvable_platform_key,
    plan_platform_key_repairs,
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

    def test_a_lone_unresolvable_key_is_in_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """IN scope, and it has to be: the shape actually reported from the
        field has ``account_id: ""`` on the bad entry, and an unknown id is
        never a join key — so ``duplicate_account_entries`` cannot see that
        pair, and a duplicate-only repair would miss the very incident this
        issue was filed for."""
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

        (repair,) = plan_platform_key_repairs(read_state_file(path))
        assert repair.entry.key == "logly_ads"
        assert repair.entry.account_id == ""
        # The join cannot connect the two, so the plan claims no context.
        assert repair.same_account == ()

        apply_state_file_repairs(path)
        assert set(read_state_file(path).platforms) == {"logly_ads_context"}

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
