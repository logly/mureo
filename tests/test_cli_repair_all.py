"""``mureo repair platform-key --all`` — the whole-machine sweep (#614).

The incident the command exists for spans EVERY client directory on the
affected machine, and the operator is a non-engineer. Running the
single-workspace command once per directory gives them no way to notice the
directory they missed and no single view of how much is wrong, so ``--all``
has to:

  - survey every client the active ``StateStore`` advertises and print a
    **summary first** — how many need work out of how many exist;
  - stay a dry run by default, and confirm exactly **once** for ``--apply``
    (a per-client prompt trains people to hold down ``y``);
  - carry on when one client fails, report it, and exit non-zero;
  - degrade to the single active workspace on a store with no client seam,
    which is every OSS install.

The store capabilities are faked here on purpose. mureo-agency supplies them
in production and IS installed on the machine this was written on, so a test
that leaned on it would pass here and assert nothing in CI.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mureo.cli.main import app
from mureo.context import platform_guards
from mureo.context.state import read_state_file

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from mureo.context.models import StateDocument

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
    """One installed provider, ``logly_ads_context`` — the reported machine."""
    entries = (SimpleNamespace(name="logly_ads_context"),)
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: entries)


# ---------------------------------------------------------------------------
# Fakes for the two optional StateStore capabilities
# ---------------------------------------------------------------------------


class _ClientStore:
    """A per-client store: the one attribute the repair needs is the path."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def read_state(self) -> StateDocument:
        return read_state_file(self.state_path)


class _AgencyStore(_ClientStore):
    """A store advertising ``list_clients`` / ``state_store_for_client``."""

    def __init__(
        self,
        state_path: Path,
        rows: list[dict[str, Any]],
        stores: dict[str, Any],
    ) -> None:
        super().__init__(state_path)
        self._rows = rows
        self._stores = stores

    def list_clients(self) -> list[dict[str, Any]]:
        return self._rows

    def state_store_for_client(self, slug: str) -> Any:
        return self._stores[slug]


def _install_store(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    """Make ``store`` the active one for the Agency seam the CLI reuses."""
    from mureo.web import report_clients

    monkeypatch.setattr(
        report_clients,
        "get_runtime_context",
        lambda: SimpleNamespace(state_store=store, workspace_id="default"),
    )


# ---------------------------------------------------------------------------
# Fixtures on disk
# ---------------------------------------------------------------------------


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _bad_state(path: Path, account_id: str) -> None:
    """The reported shape: LOGLY snapshots under the invented key."""
    _write(
        path,
        {
            "version": "2",
            "platforms": {
                "logly_ads": {
                    "account_id": account_id,
                    "totals": {
                        "spend": 9000.0,
                        "fetched_at": "2026-08-01T03:00:00+00:00",
                    },
                    "metrics_period": "LAST_30_DAYS",
                },
                "logly_ads_context": {
                    "account_id": account_id,
                    "totals": {"fetched_at": "2026-08-12T03:00:00+00:00"},
                },
            },
        },
    )


def _clean_state(path: Path, account_id: str) -> None:
    _write(
        path,
        {
            "version": "2",
            "platforms": {"logly_ads_context": {"account_id": account_id}},
        },
    )


def _three_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """acme + beta hold the bad key; gamma is clean."""
    paths = {slug: tmp_path / slug / "STATE.json" for slug in ("acme", "beta", "gamma")}
    _bad_state(paths["acme"], "1111111111")
    _bad_state(paths["beta"], "2222222222")
    _clean_state(paths["gamma"], "3333333333")
    stores = {slug: _ClientStore(path) for slug, path in paths.items()}
    rows = [
        {"slug": "acme", "name": "Acme Co", "active": True},
        {"slug": "beta", "name": "Beta Ltd", "active": False},
        {"slug": "gamma", "name": "Gamma KK", "active": False},
    ]
    _install_store(monkeypatch, _AgencyStore(paths["acme"], rows, dict(stores)))
    return paths


def _run(*args: str, **kwargs: Any) -> Any:
    return runner.invoke(app, ["repair", "platform-key", *args], **kwargs)


def _platform_keys(path: Path) -> set[str]:
    return set(json.loads(path.read_text(encoding="utf-8"))["platforms"])


# ---------------------------------------------------------------------------
# The summary is the point
# ---------------------------------------------------------------------------


class TestSurvey:
    def test_the_summary_says_how_many_of_how_many_need_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _three_clients(tmp_path, monkeypatch)

        result = _run("--all")

        assert result.exit_code == 0, result.output
        out = result.output
        assert "Surveyed 3 clients." in out
        assert "Need repair (2 of 3)" in out
        assert "Clean (1 of 3)" in out
        assert "acme" in out
        assert "beta" in out
        assert "gamma" in out

    def test_an_undecidable_duplicate_is_not_counted_as_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its own group, not a note hung off "Clean".

        A client whose account sits under two keys that BOTH name real
        platforms is still double-counting; mureo just will not choose which
        entry to drop. Counting it in "Clean (N of M)" tells the operator
        this command is written for — a non-engineer sweeping every client —
        that it is fine, and the qualifier after the em dash is exactly what
        a person skimming a summary does not read.
        """
        paths = {
            slug: tmp_path / slug / "STATE.json" for slug in ("acme", "delta", "gamma")
        }
        _bad_state(paths["acme"], "1111111111")
        _write(
            paths["delta"],
            {
                "version": "2",
                "platforms": {
                    "google_ads": {"account_id": "4444444444"},
                    "logly_ads_context": {"account_id": "4444444444"},
                },
            },
        )
        _clean_state(paths["gamma"], "3333333333")
        stores = {slug: _ClientStore(path) for slug, path in paths.items()}
        rows = [
            {"slug": "acme", "name": "Acme Co", "active": True},
            {"slug": "delta", "name": "Delta Inc", "active": False},
            {"slug": "gamma", "name": "Gamma KK", "active": False},
        ]
        _install_store(monkeypatch, _AgencyStore(paths["acme"], rows, dict(stores)))

        result = _run("--all")

        assert result.exit_code == 0, result.output
        out = result.output
        assert "Need repair (1 of 3)" in out
        assert "Need your decision (1 of 3)" in out
        # The one genuinely finished client is the only one called clean.
        assert "Clean (1 of 3)" in out

    def test_an_entry_mureo_will_not_remove_is_not_counted_as_needing_repair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#616 narrowed the plan, and the summary has to follow it.

        ``theta``'s only finding is a solitary entry under a key no plugin
        installed HERE registers, holding figures and duplicating nothing.
        mureo will not remove it, so counting theta under "Need repair" would
        promise a repair the sweep never makes — and counting it under "Clean"
        would tell the operator there is nothing to look at.
        """
        paths = {
            slug: tmp_path / slug / "STATE.json" for slug in ("acme", "theta", "gamma")
        }
        _bad_state(paths["acme"], "1111111111")
        _write(
            paths["theta"],
            {
                "version": "2",
                "platforms": {
                    "logly_ads_v2": {
                        "account_id": "5555555555",
                        "totals": {
                            "spend": 128000.0,
                            "fetched_at": "2026-08-13T23:10:00+00:00",
                        },
                        "metrics_period": "LAST_30_DAYS",
                    }
                },
            },
        )
        _clean_state(paths["gamma"], "3333333333")
        stores = {slug: _ClientStore(path) for slug, path in paths.items()}
        rows = [
            {"slug": "acme", "name": "Acme Co", "active": True},
            {"slug": "theta", "name": "Theta AB", "active": False},
            {"slug": "gamma", "name": "Gamma KK", "active": False},
        ]
        _install_store(monkeypatch, _AgencyStore(paths["acme"], rows, dict(stores)))
        before = paths["theta"].read_bytes()

        result = _run("--all", "--apply", "--yes")

        assert result.exit_code == 0, result.output
        out = result.output
        assert "Need repair (1 of 3)" in out
        assert "Need your decision (1 of 3)" in out
        assert "Clean (1 of 3)" in out
        # And the sweep left it alone.
        assert paths["theta"].read_bytes() == before
        assert list(tmp_path.glob("theta/STATE.json.bak.*")) == []

    def test_a_sweep_whose_only_findings_are_undecidable_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With nothing to repair the sweep must not claim every key resolves
        — one of them plainly does not."""
        path = tmp_path / "theta" / "STATE.json"
        _write(
            path,
            {
                "version": "2",
                "platforms": {
                    "logly_ads_v2": {
                        "account_id": "5555555555",
                        "totals": {
                            "spend": 128000.0,
                            "fetched_at": "2026-08-13T23:10:00+00:00",
                        },
                    }
                },
            },
        )
        rows = [{"slug": "theta", "name": "Theta AB", "active": True}]
        _install_store(
            monkeypatch, _AgencyStore(path, rows, {"theta": _ClientStore(path)})
        )

        result = _run("--all")

        assert result.exit_code == 0, result.output
        out = result.output
        assert "Need your decision (1 of 1)" in out
        assert (
            "every client's platform entries are filed under keys mureo can" not in out
        )
        assert "Nothing to repair automatically" in out

    def test_the_summary_comes_before_the_per_client_detail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _three_clients(tmp_path, monkeypatch)

        result = _run("--all")

        out = result.output
        assert out.index("Need repair") < out.index("mureo cannot resolve this key")

    def test_a_dry_run_is_the_default_and_changes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = _three_clients(tmp_path, monkeypatch)
        before = {slug: path.read_bytes() for slug, path in paths.items()}

        result = _run("--all")

        assert result.exit_code == 0, result.output
        assert "this was a dry run" in result.output
        for slug, path in paths.items():
            assert path.read_bytes() == before[slug]
        assert list(tmp_path.glob("*/STATE.json.bak.*")) == []


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


class TestApplyAll:
    def test_apply_fixes_exactly_the_clients_that_needed_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = _three_clients(tmp_path, monkeypatch)
        gamma_before = paths["gamma"].read_bytes()

        result = _run("--all", "--apply", "--yes")

        assert result.exit_code == 0, result.output
        assert _platform_keys(paths["acme"]) == {"logly_ads_context"}
        assert _platform_keys(paths["beta"]) == {"logly_ads_context"}
        assert paths["gamma"].read_bytes() == gamma_before
        # Backed up, per repaired client, and never for the clean one.
        assert len(list(tmp_path.glob("acme/STATE.json.bak.*"))) == 1
        assert len(list(tmp_path.glob("beta/STATE.json.bak.*"))) == 1
        assert list(tmp_path.glob("gamma/STATE.json.bak.*")) == []

    def test_the_confirmation_is_asked_once_not_per_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = _three_clients(tmp_path, monkeypatch)
        asked: list[str] = []

        def _fake_confirm(prompt: str, **kwargs: Any) -> bool:
            asked.append(prompt)
            return True

        from mureo.cli import repair_cmd

        monkeypatch.setattr(repair_cmd, "confirm_or_default", _fake_confirm)

        result = _run("--all", "--apply")

        assert result.exit_code == 0, result.output
        assert len(asked) == 1, asked
        assert _platform_keys(paths["acme"]) == {"logly_ads_context"}
        assert _platform_keys(paths["beta"]) == {"logly_ads_context"}

    def test_declining_the_single_confirmation_changes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = _three_clients(tmp_path, monkeypatch)
        before = {slug: path.read_bytes() for slug, path in paths.items()}

        result = _run("--all", "--apply", input="n\n")

        assert result.exit_code == 0, result.output
        for slug, path in paths.items():
            assert path.read_bytes() == before[slug]


# ---------------------------------------------------------------------------
# Degradation — every OSS install has no client seam at all
# ---------------------------------------------------------------------------


class TestWithoutTheClientSeam:
    def test_a_store_with_no_list_clients_sweeps_the_active_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = tmp_path / "STATE.json"
        _bad_state(state, "1234567890")
        _install_store(monkeypatch, _ClientStore(state))

        result = _run("--all")

        assert result.exit_code == 0, result.output
        assert "Surveyed 1 client." in result.output
        assert "logly_ads" in result.output
        assert state.read_bytes()  # unchanged: still a dry run

    def test_a_store_with_no_list_clients_repairs_the_active_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = tmp_path / "STATE.json"
        _bad_state(state, "1234567890")
        _install_store(monkeypatch, _ClientStore(state))

        result = _run("--all", "--apply", "--yes")

        assert result.exit_code == 0, result.output
        assert _platform_keys(state) == {"logly_ads_context"}


# ---------------------------------------------------------------------------
# One client failing must not abort the sweep
# ---------------------------------------------------------------------------


class TestPartialFailure:
    def test_an_unreadable_client_is_reported_and_the_others_are_repaired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = _three_clients(tmp_path, monkeypatch)
        broken = tmp_path / "delta" / "STATE.json"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("{not json", encoding="utf-8")
        stores = {slug: _ClientStore(path) for slug, path in paths.items()}
        stores["delta"] = _ClientStore(broken)
        rows = [
            {"slug": slug, "name": slug, "active": slug == "acme"}
            for slug in ("acme", "beta", "gamma", "delta")
        ]
        _install_store(monkeypatch, _AgencyStore(paths["acme"], rows, stores))

        result = _run("--all", "--apply", "--yes")

        assert result.exit_code == 1, result.output
        assert "Could not be read (1 of 4)" in result.output
        assert "delta" in result.output
        # The sweep carried on.
        assert _platform_keys(paths["acme"]) == {"logly_ads_context"}
        assert _platform_keys(paths["beta"]) == {"logly_ads_context"}

    def test_an_unreadable_client_makes_even_a_dry_run_exit_non_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = tmp_path / "delta" / "STATE.json"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("{not json", encoding="utf-8")
        rows = [{"slug": "delta", "name": "delta", "active": True}]
        _install_store(
            monkeypatch,
            _AgencyStore(broken, rows, {"delta": _ClientStore(broken)}),
        )

        result = _run("--all")

        assert result.exit_code == 1, result.output
        assert "Could not be read" in result.output


# ---------------------------------------------------------------------------
# Contradictory flags
# ---------------------------------------------------------------------------


class TestRefusals:
    def test_all_with_state_file_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = _three_clients(tmp_path, monkeypatch)
        before = paths["acme"].read_bytes()

        result = _run("--all", "--state-file", str(paths["acme"]))

        assert result.exit_code == 1
        assert "--state-file" in result.output
        assert paths["acme"].read_bytes() == before

    def test_all_with_a_resolvable_key_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _three_clients(tmp_path, monkeypatch)

        result = _run("--all", "--key", "logly_ads_context")

        assert result.exit_code == 1
        assert "logly_ads_context" in result.output


# ---------------------------------------------------------------------------
# Archived clients are swept too — see the module docstring in repair_cmd
# ---------------------------------------------------------------------------


class TestArchivedClients:
    def test_an_archived_client_is_surveyed_and_labelled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = {slug: tmp_path / slug / "STATE.json" for slug in ("acme", "old")}
        _bad_state(paths["acme"], "1111111111")
        _bad_state(paths["old"], "9999999999")
        stores = {slug: _ClientStore(path) for slug, path in paths.items()}
        rows = [
            {"slug": "acme", "name": "Acme Co", "active": True},
            {"slug": "old", "name": "Old Co", "active": False, "archived": True},
        ]
        _install_store(monkeypatch, _AgencyStore(paths["acme"], rows, stores))

        result = _run("--all", "--apply", "--yes")

        assert result.exit_code == 0, result.output
        assert "Surveyed 2 clients." in result.output
        assert "archived" in result.output
        assert _platform_keys(paths["old"]) == {"logly_ads_context"}
