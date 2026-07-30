"""`mureo amazon refresh-manifest` CLI (TDD, #113 Phase 1).

The generator itself is unit-tested in test_amazon_manifest.py; here we
only assert the CLI orchestration: creds gate, success echo, clean
failure exit.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mureo.auth import AmazonAdsCredentials
from mureo.cli.main import app

runner = CliRunner()


@pytest.mark.unit
class TestAmazonRefreshManifest:
    def test_no_credentials_exits_1_with_guidance(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.load_amazon_ads_credentials",
            lambda *a, **k: None,
        )
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 1
        assert "amazon_ads credentials not found" in r.output

    def test_success_writes_and_echoes_path(self, monkeypatch, tmp_path) -> None:
        out = tmp_path / "amazon_tools.json"
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.load_amazon_ads_credentials",
            lambda *a, **k: AmazonAdsCredentials(client_id="cid", access_token="tok"),
        )
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.generate_manifest_sync",
            lambda creds: out,
        )
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 0
        assert str(out) in r.output

    def test_generator_failure_exits_1_clean(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.load_amazon_ads_credentials",
            lambda *a, **k: AmazonAdsCredentials(
                client_id="cid", access_token="tok", region="eu"
            ),
        )

        def _boom(creds):
            raise RuntimeError("401 sending Authorization: Bearer Atza|LEAKED.tok-123")

        monkeypatch.setattr("mureo.cli.amazon_cmd.generate_manifest_sync", _boom)
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 1
        assert "Failed to refresh" in r.output
        assert "region=eu" in r.output
        # M2: token shape scrubbed from the terminal error
        assert "LEAKED" not in r.output
        assert "***" in r.output
