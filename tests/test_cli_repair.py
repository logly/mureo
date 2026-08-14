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
