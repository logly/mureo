"""CLI (Typer) tests — auth and setup commands."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture()
def _no_creds():
    """Simulate no credentials configured."""
    with (
        patch("mureo.cli.auth_cmd.load_google_ads_credentials", return_value=None),
        patch("mureo.cli.auth_cmd.load_meta_ads_credentials", return_value=None),
    ):
        yield


# ---------------------------------------------------------------------------
# 1. App instance tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAppExists:
    def test_app_exists(self):
        from mureo.cli.main import app

        assert app is not None

    def test_auth_subcommand_registered(self):
        from mureo.cli.main import app

        group_names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "auth" in group_names

    def test_setup_subcommand_registered(self):
        from mureo.cli.main import app

        group_names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "setup" in group_names

    def test_no_google_ads_subcommand(self):
        """Ad operation CLIs have been removed."""
        from mureo.cli.main import app

        group_names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "google-ads" not in group_names
        assert "meta-ads" not in group_names


# ---------------------------------------------------------------------------
# 2. --help tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHelpOutput:
    def test_main_help(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "auth" in result.output
        assert "setup" in result.output

    def test_auth_help(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["auth", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output

    def test_setup_help(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["setup", "--help"])
        assert result.exit_code == 0
        assert "claude-code" in result.output
        assert "cursor" in result.output


# ---------------------------------------------------------------------------
# 3. auth command tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuthCommands:
    def test_auth_status_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Google Ads" in result.output
        assert "Meta Ads" in result.output

    def test_auth_status_with_google_creds(self):
        from mureo.auth import GoogleAdsCredentials
        from mureo.cli.main import app

        creds = GoogleAdsCredentials(
            developer_token="dev-token",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )
        with (
            patch(
                "mureo.cli.auth_cmd.load_google_ads_credentials",
                return_value=creds,
            ),
            patch(
                "mureo.cli.auth_cmd.load_meta_ads_credentials",
                return_value=None,
            ),
        ):
            result = runner.invoke(app, ["auth", "status"])
            assert result.exit_code == 0

    def test_auth_check_google_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(app, ["auth", "check-google"])
        assert result.exit_code == 1

    def test_auth_check_google_with_creds(self):
        from mureo.auth import GoogleAdsCredentials
        from mureo.cli.main import app

        creds = GoogleAdsCredentials(
            developer_token="dev-token",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )
        with patch(
            "mureo.cli.auth_cmd.load_google_ads_credentials",
            return_value=creds,
        ):
            result = runner.invoke(app, ["auth", "check-google"])
            assert result.exit_code == 0
            assert "developer_token" in result.output

    def test_auth_check_meta_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(app, ["auth", "check-meta"])
        assert result.exit_code == 1

    def test_auth_check_meta_with_creds(self):
        from mureo.auth import MetaAdsCredentials
        from mureo.cli.main import app

        creds = MetaAdsCredentials(
            access_token="test-access-token",
            app_id="app-id",
            app_secret="app-secret",
        )
        with patch(
            "mureo.cli.auth_cmd.load_meta_ads_credentials",
            return_value=creds,
        ):
            result = runner.invoke(app, ["auth", "check-meta"])
            assert result.exit_code == 0
            assert "access_token" in result.output


# ---------------------------------------------------------------------------
# 4. auth setup command tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuthSetupCommand:
    def test_auth_setup_google_only(self):
        from mureo.cli.main import app

        mock_setup_google = AsyncMock()
        mock_setup_mcp = MagicMock()

        with (
            patch("mureo.auth_setup.setup_google_ads", mock_setup_google),
            patch("mureo.auth_setup.setup_mcp_config", mock_setup_mcp),
        ):
            result = runner.invoke(app, ["auth", "setup"], input="y\nn\n")

        assert result.exit_code == 0
        mock_setup_google.assert_called_once()
        mock_setup_mcp.assert_called_once()

    def test_auth_setup_skip(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["auth", "setup"], input="n\nn\n")

        assert result.exit_code == 0
        assert "Setup skipped." in result.output
