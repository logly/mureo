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
    StatusSnapshot,
    _mask_value,
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
    )


def _build_home(tmp_path: Path) -> Path:
    """Return a clean fake home dir (so read_setup_state finds nothing)."""
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
