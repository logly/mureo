"""``mureo repair platform-key`` — the operator-facing half of #610.

The person who hits this cannot read JSON and cannot judge which of two
entries is right, so the command has to do the judging it CAN do safely and
show its work for the rest:

  - a dry run is what happens by default, not what a flag asks for;
  - it names the keys, the ad account and what each entry holds before it
    states what would change;
  - ``--apply`` still asks, and with no TTY it declines rather than proceeds;
  - a duplicate whose two keys both name real platforms is reported and
    handed back to the operator, exactly as the dashboard does today.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mureo.cli.main import app
from mureo.context import platform_guards

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache() -> Iterator[None]:
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture(autouse=True)
def _pin_logly_bridge_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """One installed provider, ``logly_ads_context`` — the reported machine.

    Pinned for every test here: this machine really does have that bridge
    installed, so an unpinned test would pass without asserting anything.
    """
    entries = (SimpleNamespace(name="logly_ads_context"),)
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: entries)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _reported_state(path: Path) -> None:
    _write(
        path,
        {
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
                    "totals": {
                        "spend": 9000.0,
                        "period": "LAST_30_DAYS",
                        "fetched_at": "2026-08-01T03:00:00+00:00",
                    },
                    "metrics_period": "LAST_30_DAYS",
                    "periods": {
                        "LAST_30_DAYS": {
                            "spend": 9000.0,
                            "fetched_at": "2026-08-01T03:00:00+00:00",
                        }
                    },
                },
                "logly_ads_context": {
                    "account_id": "1234567890",
                    "totals": {
                        "spend": 4500.0,
                        "fetched_at": "2026-08-12T03:00:00+00:00",
                    },
                },
            },
        },
    )


def _run(*args: str) -> Any:
    return runner.invoke(app, ["repair", "platform-key", *args])


# ---------------------------------------------------------------------------
# Show before doing
# ---------------------------------------------------------------------------


class TestDryRunIsTheDefault:
    def test_it_shows_the_keys_the_account_and_what_each_entry_holds(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "logly_ads" in out
        assert "logly_ads_context" in out
        assert "1234567890" in out  # the ad account
        assert "2026-08-01T03:00:00+00:00" in out  # the bad entry's fetched_at
        assert "2026-08-12T03:00:00+00:00" in out  # the good entry's fetched_at
        assert "LAST_30_DAYS" in out
        # And exactly what would change.
        assert "--apply" in out

    def test_it_changes_nothing(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)
        before = state.read_bytes()

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        assert state.read_bytes() == before
        assert list(tmp_path.glob("STATE.json.bak*")) == []

    def test_a_healthy_document_says_so_and_exits_clean(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {"logly_ads_context": {"account_id": "1234567890"}},
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        assert "Nothing to repair" in result.output

    def test_a_missing_state_file_is_an_error(self, tmp_path: Path) -> None:
        result = _run("--state-file", str(tmp_path / "STATE.json"))

        assert result.exit_code == 1
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# A document mureo cannot read is an error, never a traceback (#618)
# ---------------------------------------------------------------------------


class TestAnUnreadableDocument:
    """The person this command is for cannot read a traceback.

    ``read_state_file`` wraps ``json.JSONDecodeError`` only. Strict parsing
    also raises a bare ``ValueError`` for a document that is valid JSON but
    invalid against the schema, and nothing on this path caught it — so a
    campaign missing ``campaign_name`` ended in a full Python traceback while
    ``--all`` reported the same file as "Could not be read".
    """

    def test_a_schema_invalid_document_is_an_error_not_a_traceback(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "campaigns": [{"campaign_id": "c-1"}],
                    }
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "Traceback" not in result.output
        assert "Error:" in result.output
        assert str(state) in result.output
        assert "Campaign is missing required field" in result.output

    def test_apply_on_a_schema_invalid_document_is_an_error_too(
        self, tmp_path: Path
    ) -> None:
        """Same file, the destructive flags. It must not crash there either,
        and nothing may be written or backed up."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "campaigns": [{"campaign_id": "c-1"}],
                    }
                },
            },
        )
        before = state.read_bytes()

        result = _run("--state-file", str(state), "--apply", "--yes")

        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "Error:" in result.output
        assert state.read_bytes() == before
        assert list(tmp_path.glob("STATE.json.bak.*")) == []

    def test_a_document_that_breaks_between_preview_and_lock_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The apply path re-reads under the lock, so a concurrent writer can
        hand it a document the preview never saw. That is the same
        ``ValueError``, and it must not surface as a traceback either."""
        from mureo.cli import repair_cmd

        state = tmp_path / "STATE.json"
        _reported_state(state)

        def _explode(*_args: Any, **_kwargs: Any) -> None:
            raise ValueError("Campaign is missing required field 'campaign_name': {}")

        monkeypatch.setattr(repair_cmd, "apply_state_file_repairs", _explode)

        result = _run("--state-file", str(state), "--apply", "--yes")

        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "Error: mureo cannot read STATE.json" in result.output
        assert "Campaign is missing required field" in result.output

    def test_control_characters_in_the_parse_error_are_scrubbed(
        self, tmp_path: Path
    ) -> None:
        """The failing text comes out of STATE.json, so the exception carries
        agent-writable content straight to a terminal."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {
                        "account_id": "1234567890",
                        "campaigns": [{"campaign_id": "c-1\x1b[2J\x07"}],
                    }
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 1
        assert "\x1b" not in result.output
        assert "\x07" not in result.output


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


class TestApply:
    def test_apply_with_yes_removes_the_entry_and_leaves_a_backup(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)

        result = _run("--state-file", str(state), "--apply", "--yes")

        assert result.exit_code == 0, result.output
        payload = json.loads(state.read_text(encoding="utf-8"))
        assert set(payload["platforms"]) == {"logly_ads_context"}
        backups = list(tmp_path.glob("STATE.json.bak.*"))
        assert len(backups) == 1
        assert str(backups[0]) in result.output
        restored = json.loads(backups[0].read_text(encoding="utf-8"))
        assert set(restored["platforms"]) == {"logly_ads", "logly_ads_context"}

    def test_apply_declines_when_the_answer_is_no(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)
        before = state.read_bytes()

        result = runner.invoke(
            app,
            ["repair", "platform-key", "--state-file", str(state), "--apply"],
            input="n\n",
        )

        assert result.exit_code == 0, result.output
        assert state.read_bytes() == before

    def test_apply_without_a_tty_declines_rather_than_proceeds(
        self, tmp_path: Path
    ) -> None:
        """``CliRunner`` has no TTY, which is also what an AI agent's shell
        looks like. The safe default for a destructive step is to stop."""
        state = tmp_path / "STATE.json"
        _reported_state(state)
        before = state.read_bytes()

        result = _run("--state-file", str(state), "--apply")

        assert result.exit_code == 0, result.output
        assert state.read_bytes() == before
        assert "Nothing was changed" in result.output


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_a_duplicate_of_two_real_keys_is_reported_not_repaired(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "google_ads": {"account_id": "1234567890"},
                    "logly_ads_context": {"account_id": "1234567890"},
                },
            },
        )
        before = state.read_bytes()

        result = _run("--state-file", str(state), "--apply", "--yes")

        assert result.exit_code == 0, result.output
        assert state.read_bytes() == before
        assert "google_ads" in result.output
        assert "logly_ads_context" in result.output
        # It says why mureo will not choose, rather than going silent.
        assert "mureo does not choose" in result.output

    def test_naming_a_resolvable_key_is_refused(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)

        result = _run("--state-file", str(state), "--key", "logly_ads_context")

        assert result.exit_code == 1
        assert "logly_ads_context" in result.output
        assert state.read_bytes()  # untouched

    def test_naming_an_absent_key_is_refused(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)

        result = _run("--state-file", str(state), "--key", "nope")

        assert result.exit_code == 1
        assert "nope" in result.output

    def test_naming_the_bad_key_repairs_only_it(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {"account_id": "1"},
                    "logly_adz": {"account_id": "2"},
                },
            },
        )

        result = _run("--state-file", str(state), "--key", "logly_ads", "--apply", "-y")

        assert result.exit_code == 0, result.output
        payload = json.loads(state.read_text(encoding="utf-8"))
        assert set(payload["platforms"]) == {"logly_adz"}


# ---------------------------------------------------------------------------
# The preview has to be TRUE (#616 / #617 / #618)
# ---------------------------------------------------------------------------


class TestThePreviewIsTrue:
    """Every sentence printed before the confirmation has to hold afterwards.

    The person reading it cannot open STATE.json to check, so a reassurance
    that is false for the run they are about to approve is worse than no
    reassurance at all.
    """

    def test_a_solitary_entry_with_figures_is_reported_not_offered(
        self, tmp_path: Path
    ) -> None:
        """#616. ``logly_ads_v2`` is not registered by the one pinned plugin,
        but nothing in the document says it is wrong — so it is handed back."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_v2": {
                        "account_id": "1234567890",
                        "totals": {
                            "spend": 128000.0,
                            "fetched_at": "2026-08-13T23:10:00Z",
                        },
                        "metrics_period": "LAST_30_DAYS",
                    }
                },
            },
        )
        before = state.read_bytes()

        result = _run("--state-file", str(state), "--apply", "--yes")

        assert result.exit_code == 0, result.output
        assert state.read_bytes() == before
        assert "will NOT remove" in result.output
        assert "not be installed" in result.output

    def test_a_conversion_override_is_named_and_the_entry_is_kept(
        self, tmp_path: Path
    ) -> None:
        """#617. The allow-list is operator-declared and no sync restores it,
        so it is named in the preview AND the entry is refused, not offered
        behind a confirmation the ``--yes`` flag would walk straight through."""
        state = tmp_path / "STATE.json"
        _write(
            state,
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
        before = state.read_bytes()

        result = _run("--state-file", str(state), "--apply", "--yes")

        assert result.exit_code == 0, result.output
        out = result.output
        assert "conversion_action_types" in out
        assert "offsite_conversion.custom.90210" in out
        assert "no sync restores this" in out
        assert "will NOT remove" in out
        # And nothing was removed.
        assert state.read_bytes() == before

    def test_a_collection_failure_note_is_stated(self, tmp_path: Path) -> None:
        """#643. A platform that failed on its FIRST collection holds nothing
        but the note, and the note is the one thing in the entry no sync
        brings back. The dry run is where the operator reads what an entry
        holds, so it has to say the note is there — and the entry is kept."""
        state = tmp_path / "STATE.json"
        _write(
            state,
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
        before = state.read_bytes()

        result = _run("--state-file", str(state), "--apply", "--yes")

        assert result.exit_code == 0, result.output
        out = result.output
        assert "the access token expired" in out
        assert "2026-08-13T04:00:00+00:00" in out
        assert "will NOT remove" in out
        assert state.read_bytes() == before

    def test_a_kept_note_only_entry_is_not_said_to_hold_figures(
        self, tmp_path: Path
    ) -> None:
        """#643's own doing. Before the note counted towards ``is_empty_stub``
        a note-only entry was dropped as an empty stub, so it never reached
        this refusal and "the only record of the figures below" was true of
        everything that did. Keeping it routes exactly the entry with no
        figures here, and the sentence has to name what is really there."""
        state = tmp_path / "STATE.json"
        _write(
            state,
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

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "only record of the\n    figures below" not in out
        assert "not figures but the note" in out
        # …and the step it hands back does not send them to figures either.
        assert "check the figures" not in out

    def test_a_kept_entry_with_figures_keeps_the_original_sentence(
        self, tmp_path: Path
    ) -> None:
        """The #616 case is untouched: an entry that does carry figures is
        still described as the only record of them."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_v2": {
                        "account_id": "1234567890",
                        "totals": {
                            "spend": 128000.0,
                            "fetched_at": "2026-08-13T23:10:00Z",
                        },
                        "metrics_period": "LAST_30_DAYS",
                    }
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "only record of the\n    figures below, and mureo will" in out
        assert "not figures but the note" not in out

    def test_a_kept_entry_holding_both_names_both_losses(self, tmp_path: Path) -> None:
        """Figures AND a note: neither half may be left out of the sentence
        that argues for keeping the entry."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_v2": {
                        "account_id": "1234567890",
                        "totals": {
                            "spend": 128000.0,
                            "fetched_at": "2026-08-13T23:10:00Z",
                        },
                        "not_collected": {
                            "attempted_at": "2026-08-15T04:00:00+00:00",
                            "reason": "the access token expired",
                        },
                    }
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "figures below AND of why they stopped moving" in out

    def test_a_note_on_an_entry_being_dropped_is_stated_first(
        self, tmp_path: Path
    ) -> None:
        """#643. A duplicate of a resolvable key is still removed — the note
        does not change what a duplicate is — but removing it loses the note,
        so the operator reads it before the confirmation."""
        state = tmp_path / "STATE.json"
        _write(
            state,
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
                        "totals": {
                            "spend": 4500.0,
                            "fetched_at": "2026-08-12T03:00:00+00:00",
                        },
                    },
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "Found 1 platform entry" in out
        assert "the access token expired" in out

    def test_a_dropped_notes_loss_is_not_denied_two_lines_above_it(
        self, tmp_path: Path
    ) -> None:
        """#643 meets #618. "Holds nothing a sync cannot refill" is the whole
        licence to drop a duplicate, and it stops being true of an entry
        carrying a note the same block prints as unrecoverable. One block, one
        answer."""
        state = tmp_path / "STATE.json"
        _write(
            state,
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
                        "totals": {
                            "spend": 4500.0,
                            "fetched_at": "2026-08-12T03:00:00+00:00",
                        },
                    },
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "holds nothing a sync cannot refill" not in out
        assert "no sync brings that back" in out

    def test_an_entry_with_no_note_keeps_the_plain_licence(
        self, tmp_path: Path
    ) -> None:
        """And the caveat is not printed over every duplicate: an entry with
        no note holds nothing a sync cannot refill, which is the ordinary
        case and the ordinary sentence."""
        state = tmp_path / "STATE.json"
        _reported_state(state)

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        assert "holds nothing a sync cannot refill" in result.output

    def test_two_entries_in_one_plan_never_claim_the_others_are_untouched(
        self, tmp_path: Path
    ) -> None:
        """#618, first half. ``every other platform entry is left exactly as
        it is`` printed once per block contradicts itself the moment a plan
        holds two entries."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {"account_id": "1111111111"},
                    "logly_adz": {"account_id": "2222222222"},
                    "logly_ads_context": {"account_id": "3333333333"},
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "Found 2 platform entries" in out
        assert "other platform entry is left exactly as it is" not in out
        assert "other than the 2 this run removes" in out
        assert "This run removes: logly_ads, logly_adz." in out

    def test_one_entry_in_a_plan_keeps_the_plain_reassurance(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        assert "other platform entry is left exactly as it is" in result.output

    def test_two_dropped_entries_sharing_an_account_say_it_is_left_empty(
        self, tmp_path: Path
    ) -> None:
        """#618, second half. Neither block used to mention the other, so the
        operator was never told the ad account would have no entry left."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads": {"account_id": "1234567890"},
                    "logly_adz": {"account_id": "1234567890"},
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        # Both blocks say it, not just the first.
        assert out.count("NO record of that account") == 2
        assert out.count("this run removes this entry too") == 2

    def test_the_reason_the_entry_can_go_is_stated(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _reported_state(state)

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        assert "Why it can go:" in result.output
        assert "duplicates" in result.output


# ---------------------------------------------------------------------------
# Recording the operator's own decision (#636)
# ---------------------------------------------------------------------------


def _both_keys_resolve_state(path: Path) -> None:
    """One ad account under two keys mureo can resolve — the #636 deadlock.

    The bridge's provider name and the legacy ``plugin:<distribution>``
    spelling of the same platform. The dashboard withholds this client's
    totals until one of them goes, and nothing in the #616 plan reaches
    either.
    """
    _write(
        path,
        {
            "version": "2",
            "platforms": {
                "plugin:mureo-logly-bridge": {
                    "account_id": "1234567890",
                    "totals": {
                        "spend": 9000.0,
                        "fetched_at": "2026-08-01T03:00:00+00:00",
                    },
                },
                "logly_ads_context": {
                    "account_id": "1234567890",
                    "totals": {
                        "spend": 4500.0,
                        "fetched_at": "2026-08-12T03:00:00+00:00",
                    },
                },
            },
        },
    )


class TestChoosingWhichDuplicateToDrop:
    """``--drop-duplicate`` is how an operator records a decision (#636).

    mureo will not say which of two resolvable entries holds the true
    figures. Before this flag it also had nowhere to be told, so the
    dashboard's "resolve this" instruction had no runnable next step and the
    client's totals stayed hidden for good.
    """

    def test_the_flag_is_needed_before_a_resolvable_key_is_touched(
        self, tmp_path: Path
    ) -> None:
        """Naming a key must never be enough on its own — and the refusal has
        to name the flag that IS enough, or this is the same dead end."""
        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)
        before = state.read_bytes()

        result = _run(
            "--state-file",
            str(state),
            "--key",
            "plugin:mureo-logly-bridge",
            "--apply",
            "-y",
        )

        assert result.exit_code == 1
        assert state.read_bytes() == before
        assert "--drop-duplicate" in result.output

    def test_the_dry_run_is_still_the_default(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)
        before = state.read_bytes()
        mtime = state.stat().st_mtime_ns

        result = _run(
            "--state-file",
            str(state),
            "--key",
            "plugin:mureo-logly-bridge",
            "--drop-duplicate",
        )

        assert result.exit_code == 0, result.output
        assert state.read_bytes() == before
        assert state.stat().st_mtime_ns == mtime
        assert list(tmp_path.glob("STATE.json.bak*")) == []
        assert "this was a dry run" in result.output
        # It shows the evidence in the document, not just the key.
        assert "logly_ads_context" in result.output
        assert "1234567890" in result.output
        # "Run the same command with --apply" has to name the SAME command:
        # the bare one would repair the whole document instead, and one
        # missing --drop-duplicate would do nothing at all.
        assert (
            f'mureo repair platform-key --state-file "{state}" '
            f"--key plugin:mureo-logly-bridge --drop-duplicate --apply"
        ) in result.output

    def test_apply_removes_the_named_entry_and_backs_up_first(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)

        result = _run(
            "--state-file",
            str(state),
            "--key",
            "plugin:mureo-logly-bridge",
            "--drop-duplicate",
            "--apply",
            "-y",
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(state.read_text(encoding="utf-8"))
        assert set(payload["platforms"]) == {"logly_ads_context"}
        backups = list(tmp_path.glob("STATE.json.bak.*"))
        assert len(backups) == 1
        restored = json.loads(backups[0].read_text(encoding="utf-8"))
        assert set(restored["platforms"]) == {
            "plugin:mureo-logly-bridge",
            "logly_ads_context",
        }

    def test_apply_without_a_tty_still_declines(self, tmp_path: Path) -> None:
        """The confirmation is not skipped for an explicit choice."""
        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)
        before = state.read_bytes()

        result = _run(
            "--state-file",
            str(state),
            "--key",
            "plugin:mureo-logly-bridge",
            "--drop-duplicate",
            "--apply",
        )

        assert result.exit_code == 0, result.output
        assert state.read_bytes() == before
        assert "Nothing was changed" in result.output

    def test_the_flag_needs_a_key_to_name(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)
        before = state.read_bytes()

        result = _run("--state-file", str(state), "--drop-duplicate", "--apply", "-y")

        assert result.exit_code == 1
        assert state.read_bytes() == before
        assert "--key" in result.output

    def test_it_cannot_be_swept_across_every_client(self) -> None:
        """A decision about which of two sets of figures is true is made by
        looking at ONE document. ``--all`` would apply it to documents the
        operator has not seen."""
        result = _run("--all", "--key", "logly_ads_context", "--drop-duplicate")

        assert result.exit_code == 1
        assert "--all" in result.output

    def test_an_entry_that_duplicates_nothing_is_refused(self, tmp_path: Path) -> None:
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_context": {
                        "account_id": "1234567890",
                        "totals": {"spend": 10.0},
                    },
                    "google_ads": {"account_id": "999"},
                },
            },
        )
        before = state.read_bytes()

        result = _run(
            "--state-file",
            str(state),
            "--key",
            "logly_ads_context",
            "--drop-duplicate",
            "--apply",
            "-y",
        )

        assert result.exit_code == 1
        assert state.read_bytes() == before
        assert "duplicate" in result.output

    def test_a_conversion_override_is_refused_even_when_named(
        self, tmp_path: Path
    ) -> None:
        """#617 is not overridable: no sync restores that allow-list, so the
        entry is reported with the step that WOULD free it."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "plugin:mureo-logly-bridge": {
                        "account_id": "1234567890",
                        "conversion_action_types": ["offsite_conversion.custom.90210"],
                    },
                    "logly_ads_context": {"account_id": "1234567890"},
                },
            },
        )
        before = state.read_bytes()

        result = _run(
            "--state-file",
            str(state),
            "--key",
            "plugin:mureo-logly-bridge",
            "--drop-duplicate",
            "--apply",
            "-y",
        )

        assert result.exit_code == 1
        assert state.read_bytes() == before
        assert "conversion_action_types" in result.output
        assert "offsite_conversion.custom.90210" in result.output

    def test_the_undecidable_block_names_the_command_that_resolves_it(
        self, tmp_path: Path
    ) -> None:
        """The dead end #636 reports: told to fix something, given no command.
        The block that reports the duplicate now prints the one that ends it."""
        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        assert "mureo repair platform-key" in result.output
        assert "--drop-duplicate" in result.output
        # …and it does not first tell the operator there is nothing to repair.
        assert "Nothing to repair" not in result.output


# ---------------------------------------------------------------------------
# The decision and its evidence on one screen (#645)
# ---------------------------------------------------------------------------


def _entry_lines(output: str, key: str) -> list[str]:
    """The lines indented under ``key``'s own line in a printed block.

    The keys also appear inside the sentence naming the group, so the section
    is located by a line that is nothing BUT the key.
    """
    lines = output.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == key]
    assert starts, f"{key} is never printed as a section of its own:\n{output}"
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        if len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line.strip())
    return body


class TestTheUndecidableBlockShowsTheEvidence:
    """ "Decide which entry holds the right figures" needs the figures on screen.

    The block that hands the decision back named the account and the two keys
    and stopped, so the operator was asked to weigh two entries whose contents
    were nowhere on the page. The comparison exists — naming either key
    without ``--apply`` prints it — but nothing in the block that asks for the
    decision says so, and a decision and its evidence held in two separate
    command outputs is a decision made from memory.
    """

    def test_every_key_named_in_the_group_has_its_facts_printed(
        self, tmp_path: Path
    ) -> None:
        """Pinned over the group the module itself reports, not over two
        hard-coded key names: whatever ``undecidable_groups`` names, the block
        has to describe."""
        from mureo.cli._repair_preview import undecidable_groups
        from mureo.context.state import read_state_file

        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)
        (group,) = undecidable_groups(read_state_file(state))

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        for key in group.platform_keys:
            body = _entry_lines(result.output, key)
            assert [line.split(":")[0] for line in body[:3]] == [
                "campaigns",
                "totals",
                "periods",
            ], body
        # Both fetch times — the thing the operator is actually comparing.
        assert "2026-08-01T03:00:00+00:00" in result.output
        assert "2026-08-12T03:00:00+00:00" in result.output

    def test_an_entry_holding_nothing_says_so_rather_than_going_blank(
        self, tmp_path: Path
    ) -> None:
        """An empty section under a key would read as "mureo did not look"."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_context": {"account_id": "1234567890"},
                    "google_ads": {
                        "account_id": "1234567890",
                        "totals": {
                            "spend": 4500.0,
                            "fetched_at": "2026-08-12T03:00:00+00:00",
                        },
                    },
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        body = _entry_lines(result.output, "logly_ads_context")
        assert body[0].startswith("campaigns:")
        assert body[0].endswith("0")
        assert body[1] == "totals:      none stored"
        assert body[2] == "periods:     none stored"

    def test_the_facts_are_worded_by_the_same_helpers_as_the_repair_preview(
        self, tmp_path: Path
    ) -> None:
        """One wording of one fact. A second rendering of "what this entry
        holds" is free to drift from the first, and the operator comparing a
        repair block with this one would be comparing two vocabularies."""
        from mureo.cli._repair_preview import _periods_line, _totals_line
        from mureo.context.platform_repair import describe_platform_entry
        from mureo.context.state import read_state_file

        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)
        doc = read_state_file(state)

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        for key, entry in doc.platforms.items():
            facts = describe_platform_entry(key, entry)
            body = _entry_lines(result.output, key)
            assert f"totals:      {_totals_line(facts)}" in body
            assert f"periods:     {_periods_line(facts)}" in body

    def test_a_collection_failure_note_is_part_of_the_evidence(
        self, tmp_path: Path
    ) -> None:
        """#643 meets #645: the note explains why one side of the duplicate
        has no figures, which is exactly what the decision turns on."""
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_context": {
                        "account_id": "1234567890",
                        "not_collected": {
                            "attempted_at": "2026-08-13T04:00:00+00:00",
                            "reason": "the access token expired",
                        },
                    },
                    "google_ads": {
                        "account_id": "1234567890",
                        "totals": {
                            "spend": 4500.0,
                            "fetched_at": "2026-08-12T03:00:00+00:00",
                        },
                    },
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        body = _entry_lines(result.output, "logly_ads_context")
        assert any("the access token expired" in line for line in body), body

    def test_the_command_that_records_the_decision_still_follows(
        self, tmp_path: Path
    ) -> None:
        """The evidence is added to the block #636 built, not put in place of
        it: the runnable next step is still the last thing on screen."""
        state = tmp_path / "STATE.json"
        _both_keys_resolve_state(state)

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        out = result.output
        assert "--drop-duplicate" in out
        assert out.index("What each entry holds:") < out.index("--drop-duplicate")


# ---------------------------------------------------------------------------
# STATE.json is agent-writable, so its strings are attacker-influenceable
# ---------------------------------------------------------------------------


class TestUntrustedText:
    def test_control_characters_from_state_json_never_reach_the_terminal(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "STATE.json"
        _write(
            state,
            {
                "version": "2",
                "platforms": {
                    "logly\x1b[2Jads": {
                        "account_id": "1\x07",
                        "totals": {"fetched_at": "2026\rlater"},
                    }
                },
            },
        )

        result = _run("--state-file", str(state))

        assert result.exit_code == 0, result.output
        assert "\x1b" not in result.output
        assert "\x07" not in result.output
