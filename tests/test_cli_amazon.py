"""`mureo amazon refresh-manifest` CLI (TDD, #113 Phase 1).

The generator itself is unit-tested in test_amazon_manifest.py; here we
only assert the CLI orchestration: creds gate, success echo, clean
failure exit.
"""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from mureo.amazon_ads.lwa import AmazonAuthError, LwaTokens
from mureo.auth import AmazonAdsCredentials
from mureo.cli.main import app

runner = CliRunner()


def _creds(**kw: Any) -> AmazonAdsCredentials:
    base: dict[str, Any] = {"client_id": "cid", "access_token": "tok"}
    base.update(kw)
    return AmazonAdsCredentials(**base)


@pytest.fixture(autouse=True)
def _no_real_manifest(monkeypatch: Any, tmp_path: Any) -> None:
    """Keep the age banner off the operator's real ~/.mureo manifest."""
    monkeypatch.setattr(
        "mureo.cli.amazon_cmd.manifest_path", lambda: tmp_path / "amazon_tools.json"
    )


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


@pytest.mark.unit
class TestManifestAgeBanner:
    """Audit #47 — the command reports the current manifest's age first.

    Refreshing a two-day-old manifest and refreshing a year-old one are very
    different operations; the operator should be told which one this is.
    """

    def _run(self, monkeypatch: Any, tmp_path: Any, generated_at: str | None) -> Any:
        import json

        path = tmp_path / "amazon_tools.json"
        if generated_at is not None:
            path.write_text(
                json.dumps({"generated_at": generated_at, "tools": []}),
                encoding="utf-8",
            )
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.load_amazon_ads_credentials", lambda *a, **k: _creds()
        )
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.generate_manifest_sync", lambda creds: path
        )
        return runner.invoke(app, ["amazon", "refresh-manifest"])

    def _iso(self, days_ago: float) -> str:
        from datetime import datetime, timedelta, timezone

        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(
            timespec="seconds"
        )

    def test_absent_manifest_says_so(self, monkeypatch: Any, tmp_path: Any) -> None:
        r = self._run(monkeypatch, tmp_path, None)
        assert r.exit_code == 0
        assert "No existing Amazon tool manifest" in r.output

    def test_fresh_manifest_reports_its_age(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        r = self._run(monkeypatch, tmp_path, self._iso(3))
        assert r.exit_code == 0
        assert "3.0 days old" in r.output
        assert "stale" not in r.output.lower()

    def test_stale_manifest_is_called_out(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        r = self._run(monkeypatch, tmp_path, self._iso(90))
        assert r.exit_code == 0
        assert "90.0 days old" in r.output
        assert "stale" in r.output.lower()

    def test_unreadable_timestamp_does_not_break_the_command(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        r = self._run(monkeypatch, tmp_path, "not-a-date")
        assert r.exit_code == 0
        assert "age is unknown" in r.output


@pytest.mark.unit
class TestMintBeforeRefresh:
    """Audit #49 — the recommended refresh-token-only setup used to 401.

    ``request_headers`` was handed an empty ``access_token``, so the very
    command an operator runs first failed against a perfectly valid setup.
    Minting happens here now, exactly as the dispatch path does it.
    """

    def _wire(
        self,
        monkeypatch: Any,
        tmp_path: Any,
        creds: AmazonAdsCredentials,
        refresher: Any,
        saver: Any = None,
    ) -> list[AmazonAdsCredentials]:
        seen: list[AmazonAdsCredentials] = []

        def _generate(c: AmazonAdsCredentials):
            seen.append(c)
            return tmp_path / "amazon_tools.json"

        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.load_amazon_ads_credentials", lambda *a, **k: creds
        )
        monkeypatch.setattr("mureo.cli.amazon_cmd.generate_manifest_sync", _generate)
        monkeypatch.setattr("mureo.cli.amazon_cmd.refresh_access_token", refresher)
        monkeypatch.setattr(
            "mureo.cli.amazon_cmd.save_amazon_access_token",
            saver or (lambda *a, **k: None),
        )
        return seen

    def test_empty_access_token_is_minted_and_persisted(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        saved: list[tuple] = []
        creds = _creds(access_token="", refresh_token="Atzr|R", client_secret="s")
        seen = self._wire(
            monkeypatch,
            tmp_path,
            creds,
            lambda c: LwaTokens(
                access_token="Atza|MINTED", refresh_token="Atzr|R2", expires_in=3600
            ),
            saver=lambda *a: saved.append(a),
        )
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 0
        assert saved == [("Atza|MINTED", "Atzr|R2")]
        # The generator receives the MINTED token, not the empty one.
        assert seen[0].access_token == "Atza|MINTED"
        assert seen[0].refresh_token == "Atzr|R2"
        assert "MINTED" not in r.output

    def test_a_stored_access_token_is_used_as_is(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        def _never(c):
            raise AssertionError("must not mint when a token is already stored")

        seen = self._wire(monkeypatch, tmp_path, _creds(), _never)
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 0
        assert seen[0].access_token == "tok"

    def test_without_refresh_material_nothing_is_minted(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        def _never(c):
            raise AssertionError("must not mint without refresh_token+client_secret")

        creds = _creds(access_token="", refresh_token="Atzr|R")  # no client_secret
        self._wire(monkeypatch, tmp_path, creds, _never)
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 1
        assert "no amazon_ads access_token" in r.output

    def test_a_failed_mint_exits_1_without_leaking(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        def _boom(c):
            raise AmazonAuthError("invalid_grant for Atzr|LEAKED-token-123")

        creds = _creds(access_token="", refresh_token="Atzr|R", client_secret="s")
        self._wire(monkeypatch, tmp_path, creds, _boom)
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 1
        assert "could not be obtained" in r.output
        assert "LEAKED" not in r.output

    def test_a_failed_save_exits_1(self, monkeypatch: Any, tmp_path: Any) -> None:
        from mureo.providers.config_writer import ConfigWriteError

        def _bad_save(*a: Any) -> None:
            raise ConfigWriteError("credentials.json is malformed")

        creds = _creds(access_token="", refresh_token="Atzr|R", client_secret="s")
        self._wire(
            monkeypatch,
            tmp_path,
            creds,
            lambda c: LwaTokens(
                access_token="Atza|M", refresh_token="Atzr|R", expires_in=3600
            ),
            saver=_bad_save,
        )
        r = runner.invoke(app, ["amazon", "refresh-manifest"])
        assert r.exit_code == 1
        assert "could not be saved" in r.output
