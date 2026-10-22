"""``POST /api/amazon/refresh-manifest`` — the configure-UI refresh button.

The Amazon bridge exposes Amazon's tools from a locally generated
manifest (``~/.mureo/amazon_tools.json``). Until now the only way to
(re)generate it was the ``mureo amazon refresh-manifest`` CLI, so an
operator who set Amazon up entirely from the configure UI ended with a
credentialed-but-toolless bridge. This route runs the same generator
from the dashboard's Amazon card.

Contract pinned here: absent credentials → 400 with a machine code, a
generator failure → 502 with a SCRUBBED, length-capped detail (never the
token — in the log line either), and success → the written manifest path
plus the tool count. No response ever echoes credential material.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from mureo.auth import AmazonAdsCredentials
from mureo.core import scrub
from mureo.core.scrub import STRADDLE_MARGIN
from mureo.mcp.plugin_audit import _MAX_STR
from mureo.web.server import ConfigureWizard
from tests.web_support import post, post_refused

_ROUTE = "/api/amazon/refresh-manifest"


def _write_credentials(wiz: ConfigureWizard, section: dict[str, Any]) -> None:
    path = wiz.host_paths.credentials_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"amazon_ads": section}), encoding="utf-8")


@pytest.mark.unit
class TestAmazonRefreshManifestRoute:
    def test_missing_credentials_is_a_clean_400(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No file, and no AMAZON_ADS_* env fallback either.
        for name in ("AMAZON_ADS_CLIENT_ID", "AMAZON_ADS_ACCESS_TOKEN"):
            monkeypatch.delenv(name, raising=False)
        code, body = post_refused(wizard, _ROUTE)
        assert code == 400
        assert body["error"] == "amazon_credentials_missing"

    def test_success_reports_path_and_tool_count(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(
            wizard, {"client_id": "cid", "access_token": "Atza|tok", "region": "eu"}
        )
        out = wizard.host_paths.credentials_path.parent / "amazon_tools.json"
        seen: dict[str, Any] = {}

        async def _fake_generate(
            creds: AmazonAdsCredentials, *, out_path: Any = None, **_: Any
        ) -> Any:
            seen["region"] = creds.region
            seen["out_path"] = out_path
            out_path.write_text(
                json.dumps({"tools": [{"name": "a"}, {"name": "b"}]}), encoding="utf-8"
            )
            return out_path

        monkeypatch.setattr(
            "mureo.amazon_ads.manifest.generate_manifest", _fake_generate
        )
        status, body = post(wizard, _ROUTE)

        assert status == 200
        assert body["status"] == "ok"
        assert body["region"] == "eu"
        assert body["tool_count"] == 2
        assert body["path"] == str(out)
        # The generator is pointed at the wizard's own home, not the caller's.
        assert seen["out_path"] == out
        assert seen["region"] == "eu"

    def test_generator_failure_is_502_with_the_class_name(
        self,
        wizard: ConfigureWizard,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """#864: ``detail`` is the exception class name; the scrubbed
        upstream text goes to the server log only."""
        _write_credentials(wizard, {"client_id": "cid", "access_token": "Atza|tok"})

        async def _boom(_creds: AmazonAdsCredentials, **_kw: Any) -> Any:
            raise RuntimeError("401 sending Authorization: Bearer Atza|LEAKED-123")

        monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _boom)
        with caplog.at_level(logging.WARNING, logger="mureo.web.handlers"):
            code, body = post_refused(wizard, _ROUTE)

        assert (code, body) == (
            502,
            {
                "error": "manifest_refresh_failed",
                "detail": "RuntimeError",
                "region": "na",
            },
        )
        assert "LEAKED" not in caplog.text
        assert "RuntimeError: 401 sending Authorization: ***" in caplog.text

    def test_token_never_reaches_the_response_or_the_log(
        self,
        wizard: ConfigureWizard,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An HTTP client's error text can quote the bearer token, so the
        SAME scrubbed string must be the only thing that reaches either
        sink — a traceback log would persist the credential to disk."""
        _write_credentials(wizard, {"client_id": "cid", "access_token": "Atza|tok"})

        async def _boom(_creds: AmazonAdsCredentials, **_kw: Any) -> Any:
            raise RuntimeError(
                "HTTP 401 for headers {'Authorization': 'Bearer "
                "Atza|LEAKED-TOKEN-VALUE'}"
            )

        monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _boom)
        with caplog.at_level(logging.WARNING, logger="mureo.web.handlers"):
            code, body = post_refused(wizard, _ROUTE)

        assert code == 502
        assert body["detail"] == "RuntimeError"
        # The disk-bound log line, traceback included, is scrubbed.
        assert "LEAKED-TOKEN-VALUE" not in caplog.text
        assert "Atza|" not in caplog.text
        # The failure is still recorded — scrubbing must not mean silence.
        assert "Amazon manifest refresh failed" in caplog.text

    def test_logged_failure_is_length_capped(
        self,
        wizard: ConfigureWizard,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A pathological upstream error must not turn the log line into a
        payload dump (plugin_audit's 512-char convention)."""
        _write_credentials(wizard, {"client_id": "cid", "access_token": "Atza|tok"})

        async def _boom(_creds: AmazonAdsCredentials, **_kw: Any) -> Any:
            raise RuntimeError("x" * 5000)

        monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _boom)
        with caplog.at_level(logging.WARNING, logger="mureo.web.handlers"):
            _code, body = post_refused(wizard, _ROUTE)
        assert body["detail"] == "RuntimeError"
        logged = [r.args[0] for r in caplog.records if "manifest" in r.msg]
        assert [len(text) for text in logged] == [_MAX_STR]

    def test_the_scrubber_does_not_read_the_whole_failure(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#779 review — capping the OUTPUT still read the whole INPUT.

        This runs on the wizard's request thread, on text an upstream
        service controls, for a field bounded at 512 characters either
        way.
        """
        _write_credentials(wizard, {"client_id": "cid", "access_token": "Atza|tok"})
        seen: list[int] = []
        real = scrub.scrub_text

        def _spy(text: str, **kwargs: object) -> str:
            seen.append(len(text))
            return real(text, **kwargs)  # type: ignore[arg-type]

        async def _boom(_creds: AmazonAdsCredentials, **_kw: Any) -> Any:
            raise RuntimeError("x" * 2_000_000)

        monkeypatch.setattr(scrub, "scrub_text", _spy)
        monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _boom)
        _code, body = post_refused(wizard, _ROUTE)

        assert max(seen) == _MAX_STR + STRADDLE_MARGIN
        assert body["detail"] == "RuntimeError"

    def test_response_never_echoes_credential_material(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(
            wizard,
            {
                "client_id": "amzn1.app.SECRETCID",
                "access_token": "Atza|SECRETTOKEN",
                "refresh_token": "Atzr|SECRETREFRESH",
                "client_secret": "SECRETSHH",
            },
        )

        async def _fake_generate(
            _creds: AmazonAdsCredentials, *, out_path: Any = None, **_: Any
        ) -> Any:
            out_path.write_text(json.dumps({"tools": []}), encoding="utf-8")
            return out_path

        monkeypatch.setattr(
            "mureo.amazon_ads.manifest.generate_manifest", _fake_generate
        )
        status, body = post(wizard, _ROUTE)
        assert status == 200, body
        raw = json.dumps(body, ensure_ascii=False)
        for secret in ("SECRETCID", "SECRETTOKEN", "SECRETREFRESH", "SECRETSHH"):
            assert secret not in raw

    def test_csrf_token_is_required(self, wizard: ConfigureWizard) -> None:
        status, _ = post(wizard, _ROUTE, csrf=None)
        assert status == 403
