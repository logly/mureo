"""A path-valued credential only counts when the file is readable (#761).

``_is_credentialed`` is the #102 no-strand gate: mureo steps its native
tools aside only once the official MCP can actually authenticate. It used
to be satisfied by the mere PRESENCE of every ``required_env`` name — but
``GOOGLE_APPLICATION_CREDENTIALS`` is a path the upstream server opens at
launch, so a typo'd or deleted service-account JSON passed the gate and
mureo-native Google Ads was switched off behind a server that could not
read its credentials: zero working tools for the platform.

These tests pin the tightened gate end to end (``install_provider``
returns ``needs_credentials`` and re-enables native) and as a unit
(missing file / directory / readable file). All FS via ``tmp_path``;
``run_install`` and the config writers are mocked, so no subprocess,
no network and no real user config is touched. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mureo.providers.catalog import get_provider
from mureo.providers.installer import InstallResult
from mureo.web.setup_actions import install_provider

_GOOGLE = "google-ads-official"


@pytest.fixture(autouse=True)
def _isolate_credentials_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the ``credentials_path=None`` default off the real user file."""
    iso = tmp_path / "_iso_credentials.json"
    monkeypatch.setattr(
        "mureo.web.env_var_writer._resolve_credentials_path",
        lambda p: p if p is not None else iso,
    )


def _ok_install() -> InstallResult:
    return InstallResult(returncode=0, stdout="", stderr="", argv=[])


def _creds_with_sa_path(tmp_path: Path, sa_path: Path) -> Path:
    """Write a credentials file whose Google Ads section points at ``sa_path``."""
    creds = tmp_path / "config" / "creds.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text(
        json.dumps({"google_ads": {"service_account_path": str(sa_path)}}),
        "utf-8",
    )
    return creds


@pytest.mark.unit
class TestInstallProviderRequiresReadableCredentialFile:
    def test_missing_service_account_file_needs_credentials(
        self, tmp_path: Path
    ) -> None:
        """A stored path that points at nothing must NOT disable native.

        This is the path the wizard's retry card produces when the operator
        mistypes the service-account location: the value is saved, the name
        resolves, and before #761 the install reported ``ok`` while native
        went off behind an unauthenticatable server.
        """
        creds = _creds_with_sa_path(tmp_path, tmp_path / "absent-sa.json")

        with (
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
            patch(
                "mureo.providers.config_writer.add_provider_to_claude_settings"
            ) as mock_add,
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
            patch("mureo.providers.mureo_env.unset_mureo_disable_env") as mock_unset,
        ):
            result = install_provider(_GOOGLE, credentials_path=creds)

        assert result.status == "needs_credentials"
        assert result.detail == _GOOGLE
        mock_disable.assert_not_called()
        mock_add.assert_called_once()
        mock_unset.assert_called_once_with("google_ads")

    def test_readable_service_account_file_is_ok_and_disables_native(
        self, tmp_path: Path
    ) -> None:
        """A path that resolves to a readable file still passes the gate."""
        sa_file = tmp_path / "ads-sa.json"
        sa_file.write_text('{"type": "service_account"}', "utf-8")
        creds = _creds_with_sa_path(tmp_path, sa_file)

        with (
            patch(
                "mureo.providers.installer.run_install",
                return_value=_ok_install(),
            ),
            patch(
                "mureo.providers.mureo_env.add_provider_and_disable_in_mureo"
            ) as mock_disable,
        ):
            result = install_provider(_GOOGLE, credentials_path=creds)

        assert result.status == "ok"
        mock_disable.assert_called_once()
        _, kwargs = mock_disable.call_args
        assert kwargs["extra_env"] == {"GOOGLE_APPLICATION_CREDENTIALS": str(sa_file)}


@pytest.mark.unit
class TestIsCredentialedChecksTheFile:
    def test_readable_file_is_credentialed(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import _is_credentialed

        sa_file = tmp_path / "sa.json"
        sa_file.write_text("{}", "utf-8")
        spec = get_provider(_GOOGLE)

        assert _is_credentialed(spec, {"GOOGLE_APPLICATION_CREDENTIALS": str(sa_file)})

    def test_directory_is_not_credentialed(self, tmp_path: Path) -> None:
        """A directory is not something the upstream can open as JSON."""
        from mureo.web.setup_actions import _is_credentialed

        spec = get_provider(_GOOGLE)

        assert not _is_credentialed(
            spec, {"GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path)}
        )

    def test_missing_file_is_not_credentialed(self, tmp_path: Path) -> None:
        from mureo.web.setup_actions import _is_credentialed

        spec = get_provider(_GOOGLE)

        assert not _is_credentialed(
            spec, {"GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "gone.json")}
        )

    def test_tilde_and_relative_paths_are_not_credentialed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stored value is placed verbatim into the MCP's env, where no
        shell expands ``~`` and the cwd is not ours; a value that only
        resolves after expansion or relative to our cwd would strand."""
        from mureo.web.setup_actions import _is_credentialed

        sa_file = tmp_path / "sa.json"
        sa_file.write_text("{}", "utf-8")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        spec = get_provider(_GOOGLE)

        for value in ("~/sa.json", "sa.json", "./sa.json"):
            assert not _is_credentialed(
                spec, {"GOOGLE_APPLICATION_CREDENTIALS": value}
            ), value

    def test_non_path_required_env_is_unaffected(self, tmp_path: Path) -> None:
        """Only the declared path-valued names get the file check; every
        other required name still counts as credentialed on presence."""
        from mureo.web.setup_actions import _is_credentialed

        sa_file = tmp_path / "sa.json"
        sa_file.write_text("{}", "utf-8")
        spec = get_provider("ga4-official")  # GAC + GOOGLE_PROJECT_ID

        assert _is_credentialed(
            spec,
            {
                "GOOGLE_APPLICATION_CREDENTIALS": str(sa_file),
                "GOOGLE_PROJECT_ID": "proj-1",
            },
        )
