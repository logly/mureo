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
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from mureo.auth import AmazonAdsCredentials
from mureo.mcp.plugin_audit import _MAX_STR
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path


@pytest.fixture
def wizard(tmp_path: Path) -> Iterator[ConfigureWizard]:
    home = tmp_path / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".mureo").mkdir(parents=True)

    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _post(wiz: ConfigureWizard, payload: dict[str, Any] | None = None) -> HTTPResponse:
    req = urllib.request.Request(
        f"http://127.0.0.1:{wiz.port}/api/amazon/refresh-manifest",
        data=json.dumps(payload or {}).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    return urllib.request.urlopen(req, timeout=5.0)


def _post_error(
    wiz: ConfigureWizard, payload: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    try:
        resp = _post(wiz, payload)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())
    raise AssertionError(f"expected an HTTP error, got {resp.status}")


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
        code, body = _post_error(wizard)
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
        resp = _post(wizard)
        body = json.loads(resp.read().decode())

        assert resp.status == 200
        assert body["status"] == "ok"
        assert body["region"] == "eu"
        assert body["tool_count"] == 2
        assert body["path"] == str(out)
        # The generator is pointed at the wizard's own home, not the caller's.
        assert seen["out_path"] == out
        assert seen["region"] == "eu"

    def test_generator_failure_is_502_with_scrubbed_detail(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "access_token": "Atza|tok"})

        async def _boom(_creds: AmazonAdsCredentials, **_kw: Any) -> Any:
            raise RuntimeError("401 sending Authorization: Bearer Atza|LEAKED-123")

        monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _boom)
        code, body = _post_error(wizard)

        assert code == 502
        assert body["error"] == "manifest_refresh_failed"
        assert "LEAKED" not in json.dumps(body)
        assert "***" in body["detail"]
        assert "RuntimeError" in body["detail"]

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
            code, body = _post_error(wizard)

        assert code == 502
        assert "LEAKED-TOKEN-VALUE" not in body["detail"]
        assert "Atza|" not in body["detail"]
        # Same for the disk-bound log line, traceback included.
        assert "LEAKED-TOKEN-VALUE" not in caplog.text
        assert "Atza|" not in caplog.text
        # The failure is still recorded — scrubbing must not mean silence.
        assert "Amazon manifest refresh failed" in caplog.text

    def test_failure_detail_is_length_capped(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pathological upstream error must not turn the envelope into a
        payload dump (plugin_audit's 512-char convention)."""
        _write_credentials(wizard, {"client_id": "cid", "access_token": "Atza|tok"})

        async def _boom(_creds: AmazonAdsCredentials, **_kw: Any) -> Any:
            raise RuntimeError("x" * 5000)

        monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _boom)
        _code, body = _post_error(wizard)
        assert len(body["detail"]) == _MAX_STR

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
        raw = _post(wizard).read().decode()
        for secret in ("SECRETCID", "SECRETTOKEN", "SECRETREFRESH", "SECRETSHH"):
            assert secret not in raw

    def test_csrf_token_is_required(self, wizard: ConfigureWizard) -> None:
        req = urllib.request.Request(
            f"http://127.0.0.1:{wizard.port}/api/amazon/refresh-manifest",
            data=b"{}",
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5.0)
        assert exc.value.code == 403
