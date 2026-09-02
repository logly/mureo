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
    SKILLS_CURRENT,
    SKILLS_MISSING,
    SKILLS_STALE,
    SkillsStatus,
    StatusSnapshot,
    _detect_workflow_skills,
    _mask_value,
    _read_skill_version,
    _shipped_skill_names,
    _shipped_skill_versions,
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
class TestAmazonCredentialsPresence:
    """#121 — the Amazon bridge gets a ``credentials_present`` row.

    Unlike the other sections (present ⇔ non-empty), Amazon needs a
    ``client_id`` PLUS token material to be usable, so presence mirrors
    ``mureo.auth.load_amazon_ads_credentials``.
    """

    def _present(self, tmp_path: Path, section: dict[str, object] | None) -> bool:
        paths = _paths(tmp_path)
        if section is not None:
            _write_json(paths.credentials_path, {"amazon_ads": section})
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        return snapshot.credentials_present["amazon_ads"]

    def test_missing_file_reports_absent(self, tmp_path: Path) -> None:
        assert self._present(tmp_path, None) is False

    def test_access_token_material_reports_present(self, tmp_path: Path) -> None:
        assert (
            self._present(tmp_path, {"client_id": "cid", "access_token": "Atza|T"})
            is True
        )

    def test_refresh_trio_reports_present(self, tmp_path: Path) -> None:
        assert (
            self._present(
                tmp_path,
                {"client_id": "cid", "refresh_token": "Atzr|R", "client_secret": "s"},
            )
            is True
        )

    def test_client_id_without_token_material_reports_absent(
        self, tmp_path: Path
    ) -> None:
        assert self._present(tmp_path, {"client_id": "cid", "region": "eu"}) is False

    def test_token_without_client_id_reports_absent(self, tmp_path: Path) -> None:
        assert self._present(tmp_path, {"access_token": "Atza|T"}) is False

    def test_no_secret_value_reaches_the_serialized_snapshot(
        self, tmp_path: Path
    ) -> None:
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path,
            {"amazon_ads": {"client_id": "cid", "access_token": "REDACTED-AMZ"}},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        assert "REDACTED-AMZ" not in json.dumps(snapshot.as_dict(), ensure_ascii=False)


@pytest.mark.unit
class TestAmazonManifestRow:
    """Audit #47 — the tool manifest's age is surfaced, not just written.

    The manifest is a snapshot of Amazon's tool surface; a months-old one
    silently exposes a stale tool list. The row reports present/absent, the
    age in days, and whether that age is past the threshold.
    """

    def _row(self, tmp_path: Path, generated_at: object | None) -> dict:
        paths = _paths(tmp_path)
        if generated_at is not None:
            _write_json(
                paths.credentials_path.parent / "amazon_tools.json",
                {"generated_at": generated_at, "tools": []},
            )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        return snapshot.amazon_manifest

    def _iso(self, days_ago: float) -> str:
        from datetime import datetime, timedelta, timezone

        moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return moment.isoformat(timespec="seconds")

    def test_absent_manifest(self, tmp_path: Path) -> None:
        row = self._row(tmp_path, None)
        assert row == {"present": False, "stale": False, "age_days": None}

    def test_fresh_manifest(self, tmp_path: Path) -> None:
        row = self._row(tmp_path, self._iso(2))
        assert row["present"] is True
        assert row["stale"] is False
        assert 1.9 < row["age_days"] < 2.1

    def test_stale_manifest(self, tmp_path: Path) -> None:
        row = self._row(tmp_path, self._iso(60))
        assert row["present"] is True
        assert row["stale"] is True

    def test_unreadable_timestamp_is_present_with_unknown_age(
        self, tmp_path: Path
    ) -> None:
        row = self._row(tmp_path, "not-a-date")
        assert row == {"present": True, "stale": False, "age_days": None}

    def test_the_row_survives_serialization(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        _write_json(
            paths.credentials_path.parent / "amazon_tools.json",
            {"generated_at": self._iso(1), "tools": []},
        )
        snapshot = collect_status(
            "claude-code", home=_build_home(tmp_path), paths=paths
        )
        assert snapshot.as_dict()["amazon_manifest"] == snapshot.amazon_manifest


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


def _skill_md(version: str | None) -> str:
    """A minimal SKILL.md, shaped like the ones mureo ships (#728).

    ``version=None`` writes the pre-#728 shape — frontmatter with no
    ``metadata.version`` — which is what an ancient deployed copy looks like.
    """
    if version is None:
        return "---\nname: x\n---\n"
    return f"---\nname: x\nmetadata:\n  version: {version}\n---\n"


def _install_all_skills(skills_dir: Path, version: str | None = None) -> None:
    """Put every skill mureo ships into ``skills_dir``, as an install would.

    Each copy records the version its shipped counterpart records, so the
    result reads as a CURRENT install. Pass ``version`` to simulate the copies
    a different mureo left behind (#728).
    """
    skills_dir.mkdir(parents=True, exist_ok=True)
    for name, shipped_version in _shipped_skill_versions().items():
        (skills_dir / name).mkdir(parents=True, exist_ok=True)
        (skills_dir / name / "SKILL.md").write_text(
            _skill_md(version if version is not None else shipped_version),
            encoding="utf-8",
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


@pytest.mark.unit
class TestReadSkillVersion:
    """The version a deployed SKILL.md records about itself (#728)."""

    def test_reads_the_metadata_version(self, tmp_path: Path) -> None:
        path = tmp_path / "SKILL.md"
        path.write_text(_skill_md("0.10.39"), encoding="utf-8")
        assert _read_skill_version(path) == "0.10.39"

    def test_quoted_version_is_unquoted(self, tmp_path: Path) -> None:
        path = tmp_path / "SKILL.md"
        path.write_text(
            '---\nname: x\nmetadata:\n  version: "0.10.39"\n---\n', encoding="utf-8"
        )
        assert _read_skill_version(path) == "0.10.39"

    def test_missing_file_is_unknown(self, tmp_path: Path) -> None:
        assert _read_skill_version(tmp_path / "nope" / "SKILL.md") is None

    def test_frontmatter_without_a_version_is_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "SKILL.md"
        path.write_text(_skill_md(None), encoding="utf-8")
        assert _read_skill_version(path) is None

    def test_body_text_is_not_frontmatter(self, tmp_path: Path) -> None:
        """A ``version:`` line AFTER the closing delimiter is prose, not
        metadata — reading it would let any skill's body claim a version."""
        path = tmp_path / "SKILL.md"
        path.write_text(
            "---\nname: x\n---\n\n# Body\n\n  version: 9.9.9\n", encoding="utf-8"
        )
        assert _read_skill_version(path) is None

    def test_no_leading_delimiter_is_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "SKILL.md"
        path.write_text("# Not a skill\n\nversion: 9.9.9\n", encoding="utf-8")
        assert _read_skill_version(path) is None

    def test_every_shipped_skill_records_a_version(self) -> None:
        """The whole check rests on this: CI pins ``metadata.version`` in all
        57 shipped SKILL.md files, so an unset one would make the comparison
        vacuous rather than loud."""
        shipped = _shipped_skill_versions()
        assert shipped
        assert all(v is not None for v in shipped.values())


@pytest.mark.unit
class TestWorkflowSkillFreshness:
    """Presence alone said ✓ for months-old copies (#728).

    Every shipped SKILL.md pins ``metadata.version`` to the mureo that shipped
    it, but ``pip install -U mureo`` never rewrites the deployed copies under
    ``~/.claude/skills``. So the row read ✓ on an install whose daily-check
    skill was five minor versions behind the tools it calls.
    """

    def test_matching_versions_read_current(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _install_all_skills(skills_dir)

        status = _detect_workflow_skills(skills_dir)

        assert isinstance(status, SkillsStatus)
        assert status.state == SKILLS_CURRENT
        assert status.installed_version == status.expected_version

    def test_older_versions_read_stale(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _install_all_skills(skills_dir, version="0.10.39")

        status = _detect_workflow_skills(skills_dir)

        assert status.state == SKILLS_STALE
        assert status.installed_version == "0.10.39"
        assert status.expected_version != "0.10.39"

    def test_one_stale_skill_is_enough(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _install_all_skills(skills_dir)
        victim = sorted(_shipped_skill_versions())[0]
        (skills_dir / victim / "SKILL.md").write_text(
            _skill_md("0.10.39"), encoding="utf-8"
        )

        status = _detect_workflow_skills(skills_dir)

        assert status.state == SKILLS_STALE
        assert status.installed_versions[victim] == "0.10.39"

    def test_unparseable_version_reads_stale(self, tmp_path: Path) -> None:
        """A copy that cannot say where it came from predates the pin — which
        makes it older than every version that can, not "probably fine"."""
        skills_dir = tmp_path / "skills"
        _install_all_skills(skills_dir)
        victim = sorted(_shipped_skill_versions())[0]
        (skills_dir / victim / "SKILL.md").write_text(_skill_md(None), encoding="utf-8")

        status = _detect_workflow_skills(skills_dir)

        assert status.state == SKILLS_STALE
        assert status.installed_versions[victim] is None

    def test_absent_skill_reads_missing_not_stale(self, tmp_path: Path) -> None:
        """Missing beats stale: the remedy is the same re-install either way,
        and "half of them are also gone" is the more urgent half of the fact."""
        import shutil

        skills_dir = tmp_path / "skills"
        _install_all_skills(skills_dir, version="0.10.39")
        victim = sorted(_shipped_skill_versions())[0]
        shutil.rmtree(skills_dir / victim)

        assert _detect_workflow_skills(skills_dir).state == SKILLS_MISSING

    def test_empty_dir_reads_missing(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        assert _detect_workflow_skills(skills_dir).state == SKILLS_MISSING

    def test_unreadable_package_data_never_claims_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing shipped means nothing can be verified — say missing rather
        than ✓ off an empty comparison."""
        monkeypatch.setattr(
            "mureo.web.status_collector._shipped_skill_versions", lambda: {}
        )
        skills_dir = tmp_path / "skills"
        _install_all_skills(skills_dir)

        assert _detect_workflow_skills(skills_dir).state == SKILLS_MISSING

    def test_installed_version_reports_the_common_one(self, tmp_path: Path) -> None:
        """One odd copy does not rename the whole set: the line names the
        version most of the deployed skills came from."""
        skills_dir = tmp_path / "skills"
        _install_all_skills(skills_dir, version="0.10.39")
        victim = sorted(_shipped_skill_versions())[0]
        (skills_dir / victim / "SKILL.md").write_text(
            _skill_md("0.9.0"), encoding="utf-8"
        )

        assert _detect_workflow_skills(skills_dir).installed_version == "0.10.39"


@pytest.mark.unit
class TestStaleSkillsOnTheSnapshot:
    """The three-state result reaches the browser (#728)."""

    def test_current_install_is_ok_and_says_so(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        _install_all_skills(paths.skills_dir)

        snap = collect_status("claude-code", home=_build_home(tmp_path), paths=paths)
        parts = snap.as_dict()["setup_parts"]

        assert snap.setup_parts.skills is True
        assert parts["skills"] is True
        assert parts["skills_state"] == SKILLS_CURRENT
        assert parts["skills_installed_version"] == parts["skills_expected_version"]

    def test_stale_install_is_not_ok_and_names_both_versions(
        self, tmp_path: Path
    ) -> None:
        """``skills`` stays the boolean the dashboard, the wizard and the
        landing page already read — a stale set is NOT a working set."""
        paths = _paths(tmp_path)
        _install_all_skills(paths.skills_dir, version="0.10.39")

        snap = collect_status("claude-code", home=_build_home(tmp_path), paths=paths)
        parts = snap.as_dict()["setup_parts"]

        assert snap.setup_parts.skills is False
        assert parts["skills_state"] == SKILLS_STALE
        assert parts["skills_installed_version"] == "0.10.39"
        assert parts["skills_expected_version"] != "0.10.39"

    def test_absent_install_reports_missing(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)

        snap = collect_status("claude-code", home=_build_home(tmp_path), paths=paths)
        parts = snap.as_dict()["setup_parts"]

        assert parts["skills"] is False
        assert parts["skills_state"] == SKILLS_MISSING
        assert parts["skills_installed_version"] is None

    def test_shipped_skill_names_still_answers_the_names(self) -> None:
        assert _shipped_skill_names() == frozenset(_shipped_skill_versions())
