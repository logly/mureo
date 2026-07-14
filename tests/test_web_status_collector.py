"""Unit tests for ``mureo.web.status_collector``.

Locks in the public snapshot shape — specifically the env-var masking
contract and the ``credentials_oauth`` flags surfaced for the Search
Console re-auth UX. Tests construct a synthetic ``HostPaths`` rooted
in ``tmp_path`` so they never touch the operator's real home.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

import pytest

from mureo.web.host_paths import HostPaths
from mureo.web.status_collector import (
    MUREO_NATIVE_ID,
    StatusSnapshot,
    _mask_value,
    _shipped_skill_names,
    collect_status,
)

if TYPE_CHECKING:
    from pathlib import Path

    pass


def _paths(tmp_path: Path) -> HostPaths:
    """Synthetic HostPaths bundle rooted in ``tmp_path``."""
    return HostPaths(
        host="claude-code",
        settings_path=tmp_path / "settings.json",
        skills_dir=tmp_path / "skills",
        commands_dir=tmp_path / "commands",
        credentials_path=tmp_path / "credentials.json",
        mcp_registry_path=tmp_path / ".claude.json",
    )


def _build_home(tmp_path: Path) -> Path:
    """Return a clean fake home dir, so nothing leaks in from the real one."""
    home = tmp_path / "home"
    (home / ".mureo").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    return home


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.unit
class TestMaskValue:
    def test_secret_name_masks_to_last_four(self) -> None:
        assert _mask_value("GOOGLE_ADS_DEVELOPER_TOKEN", "abcdefghij12") == "••••ij12"

    def test_secret_short_value_fully_masked(self) -> None:
        # Below the 8-char threshold the entire secret is hidden.
        result = _mask_value("GOOGLE_ADS_REFRESH_TOKEN", "abc")
        assert "abc" not in result
        assert result == "•" * 8

    def test_non_secret_returns_full_value(self) -> None:
        path_value = "/home/operator/sa.json"
        assert _mask_value("GOOGLE_APPLICATION_CREDENTIALS", path_value) == path_value

    def test_account_id_returns_full_value(self) -> None:
        assert _mask_value("META_ADS_ACCOUNT_ID", "act_1234567890") == "act_1234567890"

    def test_empty_value_returns_empty(self) -> None:
        assert _mask_value("GOOGLE_ADS_DEVELOPER_TOKEN", "") == ""


@pytest.mark.unit
class TestEnvVarsCollection:
    """Credentials panel reads from ``credentials.json``, not ``os.environ``.

    The wizard and the dashboard "Set environment variable" form both
    persist into ``credentials.json``; if the panel were reading from
    ``os.environ`` instead, wizard-saved values would never surface.
    """

    def test_unset_env_vars_report_set_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Even if the OS env var is set, an empty credentials.json must
        # report `set: False` — the data source is the file, not the env.
        monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "should-be-ignored")
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=_paths(tmp_path)
        )
        entry = snapshot.env_vars["GOOGLE_ADS_DEVELOPER_TOKEN"]
        assert entry["set"] is False
        assert entry["value_preview"] is None

    def test_set_secret_env_var_is_masked(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {"google_ads": {"developer_token": "abcdefghij12"}},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        entry = snapshot.env_vars["GOOGLE_ADS_DEVELOPER_TOKEN"]
        assert entry["set"] is True
        assert entry["value_preview"] == "••••ij12"
        # Defense in depth: the raw value never appears in the snapshot.
        raw_snapshot = json.dumps(snapshot.as_dict(), ensure_ascii=False)
        assert "abcdefghij12" not in raw_snapshot

    def test_set_non_secret_env_var_surfaces_full_value(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {"ga4": {"service_account_path": "/srv/sa-key.json"}},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        entry = snapshot.env_vars["GOOGLE_APPLICATION_CREDENTIALS"]
        assert entry["set"] is True
        assert entry["value_preview"] == "/srv/sa-key.json"

    def test_wizard_saved_value_appears_in_panel(self, tmp_path: Path) -> None:
        # Regression: bug where the panel read os.environ but the wizard
        # writes credentials.json. The two stores were disjoint, so
        # wizard-saved values never appeared in the dashboard panel.
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {
                "google_ads": {
                    "developer_token": "tokenfromwizard",
                    "client_id": "1234567890.apps.googleusercontent.com",
                },
                "ga4": {"project_id": "my-gcp-project"},
            },
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        # TOKEN matches the secret regex → masked to last 4.
        token_entry = snapshot.env_vars["GOOGLE_ADS_DEVELOPER_TOKEN"]
        assert token_entry["set"] is True
        assert token_entry["value_preview"] == "••••zard"
        # CLIENT_ID does NOT match TOKEN|SECRET|KEY|PASSWORD → full value.
        client_id_entry = snapshot.env_vars["GOOGLE_ADS_CLIENT_ID"]
        assert client_id_entry["set"] is True
        assert (
            client_id_entry["value_preview"] == "1234567890.apps.googleusercontent.com"
        )
        # Non-secret project id surfaces full.
        project_entry = snapshot.env_vars["GOOGLE_PROJECT_ID"]
        assert project_entry["set"] is True
        assert project_entry["value_preview"] == "my-gcp-project"
        # Untouched fields stay unset.
        assert snapshot.env_vars["META_ADS_ACCESS_TOKEN"]["set"] is False

    def test_empty_string_in_credentials_reports_unset(self, tmp_path: Path) -> None:
        # An accidentally-blank value should look like "unset" in the UI,
        # not like a real masked secret.
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {"google_ads": {"developer_token": ""}},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        entry = snapshot.env_vars["GOOGLE_ADS_DEVELOPER_TOKEN"]
        assert entry["set"] is False
        assert entry["value_preview"] is None

    def test_non_string_in_credentials_reports_unset(self, tmp_path: Path) -> None:
        # Defensive: corrupted credentials.json with a non-string value
        # must not crash the panel.
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {"google_ads": {"developer_token": 12345}},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        entry = snapshot.env_vars["GOOGLE_ADS_DEVELOPER_TOKEN"]
        assert entry["set"] is False
        assert entry["value_preview"] is None


@pytest.mark.unit
class TestCredentialsOauth:
    def test_missing_credentials_file_reports_no_oauth(self, tmp_path: Path) -> None:
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=_paths(tmp_path)
        )
        assert snapshot.credentials_oauth == {"google": False, "meta": False}

    def test_refresh_token_present_reports_google_has_oauth(
        self, tmp_path: Path
    ) -> None:
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {"google_ads": {"refresh_token": "REDACTED-REFRESH"}},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        assert snapshot.credentials_oauth["google"] is True
        assert snapshot.credentials_oauth["meta"] is False
        # Refresh token never appears in the serialized snapshot.
        raw_snapshot = json.dumps(snapshot.as_dict(), ensure_ascii=False)
        assert "REDACTED-REFRESH" not in raw_snapshot

    def test_meta_access_token_present_reports_meta_has_oauth(
        self, tmp_path: Path
    ) -> None:
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {"meta_ads": {"access_token": "REDACTED-ACCESS"}},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        assert snapshot.credentials_oauth["meta"] is True


@pytest.mark.unit
class TestStatusSnapshotShape:
    def test_snapshot_is_frozen_dataclass(self, tmp_path: Path) -> None:
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=_paths(tmp_path)
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            snapshot.host = "claude-desktop"  # type: ignore[misc]

    def test_as_dict_contains_expected_top_level_keys(self, tmp_path: Path) -> None:
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=_paths(tmp_path)
        )
        payload = snapshot.as_dict()
        for key in (
            "host",
            "setup_parts",
            "providers_installed",
            "credentials_present",
            "credentials_oauth",
            "env_vars",
            "legacy_commands_present",
        ):
            assert key in payload

    def test_returned_type_is_status_snapshot(self, tmp_path: Path) -> None:
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=_paths(tmp_path)
        )
        assert isinstance(snapshot, StatusSnapshot)


@pytest.mark.unit
class TestMureoDisableState:
    """`mureo_disable` reports the per-platform MUREO_DISABLE_<P> state
    read from mcpServers.mureo.env in the host's MCP registry."""

    def test_absent_means_all_false(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        (tmp_path / ".claude.json").write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "python"}}}),
            encoding="utf-8",
        )
        snap = collect_status("claude-code", home=_build_home(tmp_path), paths=paths)
        assert snap.mureo_disable == {
            "google_ads": False,
            "meta_ads": False,
            "ga4": False,
        }
        assert "mureo_disable" in snap.as_dict()

    def test_reflects_set_flag(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        (tmp_path / ".claude.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "mureo": {
                            "command": "python",
                            "env": {"MUREO_DISABLE_GOOGLE_ADS": "1"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        snap = collect_status("claude-code", home=_build_home(tmp_path), paths=paths)
        assert snap.mureo_disable["google_ads"] is True
        assert snap.mureo_disable["meta_ads"] is False

    def test_missing_registry_is_all_false(self, tmp_path: Path) -> None:
        snap = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=_paths(tmp_path)
        )
        assert snap.mureo_disable == {
            "google_ads": False,
            "meta_ads": False,
            "ga4": False,
        }


@pytest.mark.unit
class TestMultiAccountAuthFlag:
    """#222 — the snapshot carries a ``multi_account_auth`` flag so the UI
    can suppress the bare-``mureo`` MCP registration. The handler computes
    it behind the ``home is None`` gate; ``collect_status`` just relays it.
    """

    def test_default_is_false(self, tmp_path: Path) -> None:
        snap = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=_paths(tmp_path)
        )
        assert snap.multi_account_auth is False
        assert snap.as_dict()["multi_account_auth"] is False

    def test_flag_propagates_to_snapshot(self, tmp_path: Path) -> None:
        snap = collect_status(
            "claude-code",
            home=_build_home(tmp_path),
            paths=_paths(tmp_path),
            multi_account_auth=True,
        )
        assert snap.multi_account_auth is True
        assert snap.as_dict()["multi_account_auth"] is True


def _install_all_skills(skills_dir: Path) -> None:
    """Put every skill mureo ships into ``skills_dir``, as an install would."""
    skills_dir.mkdir(parents=True, exist_ok=True)
    for name in _shipped_skill_names():
        (skills_dir / name).mkdir(parents=True, exist_ok=True)
        (skills_dir / name / "SKILL.md").write_text(
            "---\nname: x\n---\n", encoding="utf-8"
        )


def _state_file(home: Path) -> Path:
    """The legacy flag file. Written by these tests only to prove it is now
    IGNORED — the status comes from disk (#423)."""
    return home / ".mureo" / "setup_state.json"


@pytest.mark.unit
class TestSetupPartsComeFromDisk:
    """The three basic-setup rows must be DETECTED, not recalled (#423).

    Every other row on the snapshot is read off the filesystem; these three
    came from a flag file only the configure UI's own actions ever wrote. So
    skills installed by ``mureo setup`` (or by hand) read ✗ while present, and
    skills deleted after a UI install read ✓ while absent. The second is the
    dangerous direction: the UI asserts a guardrail-bearing component is there
    when it is not, and nothing prompts the operator to look.
    """

    def test_skills_on_disk_read_installed_even_with_no_flag(
        self, tmp_path: Path
    ) -> None:
        paths = _paths(tmp_path)
        home = _build_home(tmp_path)  # no flag file written at all
        _install_all_skills(paths.skills_dir)

        snap = collect_status("claude-code", home=home, paths=paths)

        assert snap.setup_parts.skills is True

    def test_skills_absent_read_not_installed_despite_the_flag(
        self, tmp_path: Path
    ) -> None:
        """The false-POSITIVE direction: the flag says yes, the disk says no."""
        paths = _paths(tmp_path)
        home = _build_home(tmp_path)
        _write_json(
            _state_file(home),
            {"mureo_mcp": True, "auth_hook": True, "skills": True},
        )

        snap = collect_status("claude-code", home=home, paths=paths)

        assert snap.setup_parts.skills is False

    def test_a_partial_install_reads_not_installed(self, tmp_path: Path) -> None:
        """One skill missing means the install is incomplete — say so, so the
        operator re-runs it, rather than reporting a half-installed set as ✓."""
        import shutil

        paths = _paths(tmp_path)
        home = _build_home(tmp_path)
        _install_all_skills(paths.skills_dir)
        victim = sorted(p.name for p in paths.skills_dir.iterdir())[0]
        shutil.rmtree(paths.skills_dir / victim)

        snap = collect_status("claude-code", home=home, paths=paths)

        assert snap.setup_parts.skills is False

    def test_mureo_mcp_cannot_contradict_the_provider_detection(
        self, tmp_path: Path
    ) -> None:
        """One snapshot could say ``setup_parts.mureo_mcp = True`` while
        ``providers_installed["mureo"] = False`` — two sources of truth for one
        fact, read in the same call."""
        paths = _paths(tmp_path)
        home = _build_home(tmp_path)
        _write_json(_state_file(home), {"mureo_mcp": True})
        _write_json(paths.mcp_registry_path, {"mcpServers": {}})  # mureo absent

        snap = collect_status("claude-code", home=home, paths=paths)

        assert snap.providers_installed[MUREO_NATIVE_ID] is False
        assert snap.setup_parts.mureo_mcp is False

    def test_auth_hook_is_read_from_the_settings_file(self, tmp_path: Path) -> None:
        from mureo.credential_guard import GUARD_TAG

        paths = _paths(tmp_path)
        home = _build_home(tmp_path)
        _write_json(
            paths.settings_path,
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'python3 -c "..." # {GUARD_TAG}',
                                }
                            ]
                        }
                    ]
                }
            },
        )

        snap = collect_status("claude-code", home=home, paths=paths)

        assert snap.setup_parts.auth_hook is True

    def test_auth_hook_absent_reads_not_installed_despite_the_flag(
        self, tmp_path: Path
    ) -> None:
        paths = _paths(tmp_path)
        home = _build_home(tmp_path)
        _write_json(_state_file(home), {"auth_hook": True})
        _write_json(paths.settings_path, {"hooks": {}})  # guard not installed

        snap = collect_status("claude-code", home=home, paths=paths)

        assert snap.setup_parts.auth_hook is False

    def test_a_users_own_hook_is_not_claimed_as_ours(self, tmp_path: Path) -> None:
        """Detection is scoped to the entry's own ``command``, via the same
        ``is_guard_entry`` the installer and remover use — so an unrelated hook
        never reads as mureo's guard."""
        paths = _paths(tmp_path)
        home = _build_home(tmp_path)
        _write_json(
            paths.settings_path,
            {
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"type": "command", "command": "echo hi"}]}
                    ]
                }
            },
        )

        snap = collect_status("claude-code", home=home, paths=paths)

        assert snap.setup_parts.auth_hook is False


@pytest.mark.unit
class TestDetectorsAgreeWithTheRealInstallers:
    """Round-trip the real installers through the detectors (#423).

    The detectors read a shape somebody else writes. Hand-written fixtures pin
    the reader against a shape that was true when the test was authored — they
    would keep passing if the *writer* moved. These call the actual installers,
    so the two cannot drift apart in silence.
    """

    def test_credential_guard_install_then_remove_round_trips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.auth_setup import install_credential_guard
        from mureo.cli.settings_remove import remove_credential_guard

        home = _build_home(tmp_path)
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        paths = dataclasses.replace(
            _paths(tmp_path), settings_path=home / ".claude" / "settings.json"
        )

        install_credential_guard()
        assert (
            collect_status("claude-code", home=home, paths=paths).setup_parts.auth_hook
            is True
        )

        remove_credential_guard(settings_path=paths.settings_path)
        assert (
            collect_status("claude-code", home=home, paths=paths).setup_parts.auth_hook
            is False
        )

    def test_codex_guard_is_found_beside_the_codex_config(self, tmp_path: Path) -> None:
        """Codex keeps hooks in ``hooks.json`` next to ``config.toml``. The
        detector derives that from the resolved HostPaths, so it reads the same
        tree as the rest of the snapshot — never the operator's real ~/.codex.
        """
        from mureo.cli.setup_codex import install_codex_credential_guard
        from mureo.web.host_paths import get_host_paths

        home = _build_home(tmp_path)
        paths = get_host_paths("codex", home)

        assert collect_status(
            "codex", home=home, paths=paths
        ).setup_parts.auth_hook is (False)

        install_codex_credential_guard(paths.settings_path.parent / "hooks.json")

        assert (
            collect_status("codex", home=home, paths=paths).setup_parts.auth_hook
            is True
        )

    def test_skills_install_then_remove_round_trips(self, tmp_path: Path) -> None:
        from mureo.cli.setup_cmd import install_skills, remove_skills

        home = _build_home(tmp_path)
        paths = _paths(tmp_path)

        assert (
            collect_status("claude-code", home=home, paths=paths).setup_parts.skills
            is False
        )

        install_skills(target_dir=paths.skills_dir)
        assert (
            collect_status("claude-code", home=home, paths=paths).setup_parts.skills
            is True
        )

        remove_skills(target_dir=paths.skills_dir)
        assert (
            collect_status("claude-code", home=home, paths=paths).setup_parts.skills
            is False
        )
