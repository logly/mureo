"""CLI (Typer) テスト — TDDで先行作成"""

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
    """認証情報が存在しない状態をシミュレート"""
    with (
        patch("mureo.cli.google_ads.load_google_ads_credentials", return_value=None),
        patch("mureo.cli.meta_ads.load_meta_ads_credentials", return_value=None),
        patch("mureo.cli.auth_cmd.load_google_ads_credentials", return_value=None),
        patch("mureo.cli.auth_cmd.load_meta_ads_credentials", return_value=None),
    ):
        yield


# ---------------------------------------------------------------------------
# 1. appインスタンスの存在テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAppExists:
    def test_app_exists(self):
        from mureo.cli.main import app

        assert app is not None

    def test_google_ads_subcommand_registered(self):
        from mureo.cli.main import app

        # サブコマンドグループが登録されていることを確認
        group_names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "google-ads" in group_names

    def test_meta_ads_subcommand_registered(self):
        from mureo.cli.main import app

        group_names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "meta-ads" in group_names

    def test_auth_subcommand_registered(self):
        from mureo.cli.main import app

        group_names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "auth" in group_names


# ---------------------------------------------------------------------------
# 2. --help テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHelpOutput:
    def test_main_help(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "google-ads" in result.output
        assert "meta-ads" in result.output
        assert "auth" in result.output

    def test_google_ads_help(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["google-ads", "--help"])
        assert result.exit_code == 0
        assert "campaigns-list" in result.output

    def test_meta_ads_help(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["meta-ads", "--help"])
        assert result.exit_code == 0
        assert "campaigns-list" in result.output

    def test_auth_help(self):
        from mureo.cli.main import app

        result = runner.invoke(app, ["auth", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output


# ---------------------------------------------------------------------------
# 3. auth コマンドテスト
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
        assert "見つかりません" in result.output or "Error" in result.output

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
        assert "見つかりません" in result.output or "Error" in result.output

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
# 4. Google Ads コマンドテスト — 認証なし
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsNoCredentials:
    def test_campaigns_list_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["google-ads", "campaigns-list", "--customer-id", "1234567890"],
        )
        assert result.exit_code == 1

    def test_campaigns_get_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            [
                "google-ads", "campaigns-get",
                "--customer-id", "1234567890",
                "--campaign-id", "123",
            ],
        )
        assert result.exit_code == 1

    def test_ads_list_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            [
                "google-ads", "ads-list",
                "--customer-id", "1234567890",
                "--ad-group-id", "456",
            ],
        )
        assert result.exit_code == 1

    def test_keywords_list_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            [
                "google-ads", "keywords-list",
                "--customer-id", "1234567890",
                "--ad-group-id", "456",
            ],
        )
        assert result.exit_code == 1

    def test_budget_get_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            [
                "google-ads", "budget-get",
                "--customer-id", "1234567890",
                "--campaign-id", "123",
            ],
        )
        assert result.exit_code == 1

    def test_performance_report_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            [
                "google-ads", "performance-report",
                "--customer-id", "1234567890",
            ],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 5. Google Ads コマンドテスト — モッククライアントで正常動作
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsWithMock:
    def _mock_google_creds(self):
        from mureo.auth import GoogleAdsCredentials

        return GoogleAdsCredentials(
            developer_token="dev-token",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )

    def test_campaigns_list_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.list_campaigns.return_value = [
            {"id": "123", "name": "Campaign 1", "status": "ENABLED"}
        ]

        with (
            patch(
                "mureo.cli.google_ads.load_google_ads_credentials",
                return_value=self._mock_google_creds(),
            ),
            patch(
                "mureo.cli.google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                ["google-ads", "campaigns-list", "--customer-id", "1234567890"],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1
            assert output[0]["name"] == "Campaign 1"

    def test_campaigns_get_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.get_campaign.return_value = {
            "id": "123",
            "name": "Campaign 1",
            "status": "ENABLED",
        }

        with (
            patch(
                "mureo.cli.google_ads.load_google_ads_credentials",
                return_value=self._mock_google_creds(),
            ),
            patch(
                "mureo.cli.google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "google-ads", "campaigns-get",
                    "--customer-id", "1234567890",
                    "--campaign-id", "123",
                ],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert output["id"] == "123"

    def test_ads_list_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.list_ads.return_value = [
            {"id": "789", "ad_group_id": "456", "status": "ENABLED"}
        ]

        with (
            patch(
                "mureo.cli.google_ads.load_google_ads_credentials",
                return_value=self._mock_google_creds(),
            ),
            patch(
                "mureo.cli.google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "google-ads", "ads-list",
                    "--customer-id", "1234567890",
                    "--ad-group-id", "456",
                ],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1

    def test_keywords_list_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.list_keywords.return_value = [
            {"id": "111", "text": "keyword1", "match_type": "BROAD"}
        ]

        with (
            patch(
                "mureo.cli.google_ads.load_google_ads_credentials",
                return_value=self._mock_google_creds(),
            ),
            patch(
                "mureo.cli.google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "google-ads", "keywords-list",
                    "--customer-id", "1234567890",
                    "--ad-group-id", "456",
                ],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1

    def test_budget_get_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.get_budget.return_value = {
            "campaign_id": "123",
            "amount_micros": 50000000,
        }

        with (
            patch(
                "mureo.cli.google_ads.load_google_ads_credentials",
                return_value=self._mock_google_creds(),
            ),
            patch(
                "mureo.cli.google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "google-ads", "budget-get",
                    "--customer-id", "1234567890",
                    "--campaign-id", "123",
                ],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert output["campaign_id"] == "123"

    def test_performance_report_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.get_performance_report.return_value = [
            {"campaign_id": "123", "clicks": 100, "impressions": 1000}
        ]

        with (
            patch(
                "mureo.cli.google_ads.load_google_ads_credentials",
                return_value=self._mock_google_creds(),
            ),
            patch(
                "mureo.cli.google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "google-ads", "performance-report",
                    "--customer-id", "1234567890",
                    "--days", "30",
                ],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1
            assert output[0]["clicks"] == 100

    def test_performance_report_default_days(self):
        """--days省略時はデフォルト7日"""
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.get_performance_report.return_value = []

        with (
            patch(
                "mureo.cli.google_ads.load_google_ads_credentials",
                return_value=self._mock_google_creds(),
            ),
            patch(
                "mureo.cli.google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                ["google-ads", "performance-report", "--customer-id", "123"],
            )
            assert result.exit_code == 0
            mock_client.get_performance_report.assert_called_once()
            call_kwargs = mock_client.get_performance_report.call_args[1]
            assert call_kwargs["days"] == 7


# ---------------------------------------------------------------------------
# 6. Meta Ads コマンドテスト — 認証なし
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsNoCredentials:
    def test_campaigns_list_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["meta-ads", "campaigns-list", "--account-id", "act_123"],
        )
        assert result.exit_code == 1

    def test_campaigns_get_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            [
                "meta-ads", "campaigns-get",
                "--account-id", "act_123",
                "--campaign-id", "456",
            ],
        )
        assert result.exit_code == 1

    def test_ad_sets_list_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["meta-ads", "ad-sets-list", "--account-id", "act_123"],
        )
        assert result.exit_code == 1

    def test_ads_list_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["meta-ads", "ads-list", "--account-id", "act_123"],
        )
        assert result.exit_code == 1

    def test_insights_report_no_creds(self, _no_creds):
        from mureo.cli.main import app

        result = runner.invoke(
            app,
            ["meta-ads", "insights-report", "--account-id", "act_123"],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 7. Meta Ads コマンドテスト — モッククライアントで正常動作
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsWithMock:
    def _mock_meta_creds(self):
        from mureo.auth import MetaAdsCredentials

        return MetaAdsCredentials(
            access_token="test-access-token",
            app_id="app-id",
            app_secret="app-secret",
        )

    def test_campaigns_list_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.list_campaigns.return_value = [
            {"id": "456", "name": "Meta Campaign 1", "status": "ACTIVE"}
        ]

        with (
            patch(
                "mureo.cli.meta_ads.load_meta_ads_credentials",
                return_value=self._mock_meta_creds(),
            ),
            patch(
                "mureo.cli.meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                ["meta-ads", "campaigns-list", "--account-id", "act_123"],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1
            assert output[0]["name"] == "Meta Campaign 1"

    def test_campaigns_get_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.get_campaign.return_value = {
            "id": "456",
            "name": "Meta Campaign 1",
        }

        with (
            patch(
                "mureo.cli.meta_ads.load_meta_ads_credentials",
                return_value=self._mock_meta_creds(),
            ),
            patch(
                "mureo.cli.meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "meta-ads", "campaigns-get",
                    "--account-id", "act_123",
                    "--campaign-id", "456",
                ],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert output["id"] == "456"

    def test_ad_sets_list_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.list_ad_sets.return_value = [
            {"id": "789", "name": "Ad Set 1"}
        ]

        with (
            patch(
                "mureo.cli.meta_ads.load_meta_ads_credentials",
                return_value=self._mock_meta_creds(),
            ),
            patch(
                "mureo.cli.meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                ["meta-ads", "ad-sets-list", "--account-id", "act_123"],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1

    def test_ads_list_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.list_ads.return_value = [
            {"id": "111", "name": "Ad 1"}
        ]

        with (
            patch(
                "mureo.cli.meta_ads.load_meta_ads_credentials",
                return_value=self._mock_meta_creds(),
            ),
            patch(
                "mureo.cli.meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                ["meta-ads", "ads-list", "--account-id", "act_123"],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1

    def test_insights_report_with_mock(self):
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.get_performance_report.return_value = [
            {"campaign_id": "456", "impressions": "500", "clicks": "50"}
        ]

        with (
            patch(
                "mureo.cli.meta_ads.load_meta_ads_credentials",
                return_value=self._mock_meta_creds(),
            ),
            patch(
                "mureo.cli.meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "meta-ads", "insights-report",
                    "--account-id", "act_123",
                    "--days", "30",
                ],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert len(output) == 1

    def test_insights_report_default_days(self):
        """--days省略時はデフォルト7日（last_7d）"""
        from mureo.cli.main import app

        mock_client = AsyncMock()
        mock_client.get_performance_report.return_value = []

        with (
            patch(
                "mureo.cli.meta_ads.load_meta_ads_credentials",
                return_value=self._mock_meta_creds(),
            ),
            patch(
                "mureo.cli.meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = runner.invoke(
                app,
                ["meta-ads", "insights-report", "--account-id", "act_123"],
            )
            assert result.exit_code == 0
            mock_client.get_performance_report.assert_called_once()
            call_kwargs = mock_client.get_performance_report.call_args[1]
            assert call_kwargs["period"] == "last_7d"


# ---------------------------------------------------------------------------
# 8. auth setup コマンドテスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuthSetupCommand:
    def test_auth_setup_google_only(self):
        """Google Adsのみ設定するフロー"""
        from mureo.cli.main import app

        mock_setup_google = AsyncMock()
        mock_setup_mcp = MagicMock()

        with (
            patch(
                "mureo.auth_setup.setup_google_ads",
                mock_setup_google,
            ),
            patch(
                "mureo.auth_setup.setup_mcp_config",
                mock_setup_mcp,
            ),
        ):
            # y=Google Ads Yes, n=Meta Ads No
            result = runner.invoke(app, ["auth", "setup"], input="y\nn\n")

        assert result.exit_code == 0
        mock_setup_google.assert_called_once()
        mock_setup_mcp.assert_called_once()
        assert "セットアップが完了しました" in result.output

    def test_auth_setup_meta_only(self):
        """Meta Adsのみ設定するフロー"""
        from mureo.cli.main import app

        mock_setup_meta = AsyncMock()
        mock_setup_mcp = MagicMock()

        with (
            patch(
                "mureo.auth_setup.setup_meta_ads",
                mock_setup_meta,
            ),
            patch(
                "mureo.auth_setup.setup_mcp_config",
                mock_setup_mcp,
            ),
        ):
            result = runner.invoke(app, ["auth", "setup"], input="n\ny\n")

        assert result.exit_code == 0
        mock_setup_meta.assert_called_once()
        mock_setup_mcp.assert_called_once()
        assert "セットアップが完了しました" in result.output

    def test_auth_setup_both(self):
        """両方設定するフロー"""
        from mureo.cli.main import app

        mock_setup_google = AsyncMock()
        mock_setup_meta = AsyncMock()
        mock_setup_mcp = MagicMock()

        with (
            patch(
                "mureo.auth_setup.setup_google_ads",
                mock_setup_google,
            ),
            patch(
                "mureo.auth_setup.setup_meta_ads",
                mock_setup_meta,
            ),
            patch(
                "mureo.auth_setup.setup_mcp_config",
                mock_setup_mcp,
            ),
        ):
            result = runner.invoke(app, ["auth", "setup"], input="y\ny\n")

        assert result.exit_code == 0
        mock_setup_google.assert_called_once()
        mock_setup_meta.assert_called_once()
        mock_setup_mcp.assert_called_once()
        assert "セットアップが完了しました" in result.output

    def test_auth_setup_skip(self):
        """両方スキップした場合"""
        from mureo.cli.main import app

        result = runner.invoke(app, ["auth", "setup"], input="n\nn\n")

        assert result.exit_code == 0
        assert "セットアップをスキップしました" in result.output

    def test_auth_setup_mcp_error(self):
        """MCP設定でエラーが出ても認証は成功（例外が伝播する）"""
        from mureo.cli.main import app

        mock_setup_google = AsyncMock()
        mock_setup_mcp = MagicMock(side_effect=OSError("permission denied"))

        with (
            patch(
                "mureo.auth_setup.setup_google_ads",
                mock_setup_google,
            ),
            patch(
                "mureo.auth_setup.setup_mcp_config",
                mock_setup_mcp,
            ),
        ):
            result = runner.invoke(app, ["auth", "setup"], input="y\nn\n")

        # setup_google_adsは呼ばれている
        mock_setup_google.assert_called_once()
        mock_setup_mcp.assert_called_once()
