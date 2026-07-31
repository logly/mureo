"""``/api/amazon/oauth/*`` — the paste-code authorization wizard (#121).

Amazon's Login-with-Amazon consent is a browser redirect to a URL the
advertiser's own security profile allows; there is no loopback callback
mureo can listen on. The wizard therefore builds the consent URL, the
operator completes consent and pastes the redirected address back, and
the server exchanges the ``code`` for tokens.

Contract pinned here:

- ``authorize-url`` needs only the stored ``client_id`` (the card is
  saved before any token exists, so the credentials LOADER — which
  demands token material — must not be the gate);
- ``exchange`` accepts either the bare code or the whole pasted URL;
- a rejected code is a 400 that says codes expire in 5 minutes, any
  other upstream failure is a 502, both with SCRUBBED, length-capped
  detail;
- success persists access + refresh token AND the re-authorization
  clock, answers with no token material at all, and refreshes the tool
  manifest best-effort — a manifest failure is reported alongside
  ``status: ok`` rather than failing the authorization the operator just
  completed.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from mureo.amazon_ads.lwa import AmazonAuthCodeError, AmazonAuthError, LwaTokens
from mureo.mcp.plugin_audit import _MAX_STR
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path

_AUTHORIZE_URL = "/api/amazon/oauth/authorize-url"
_EXCHANGE_URL = "/api/amazon/oauth/exchange"


@pytest.fixture
def wizard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ConfigureWizard]:
    home = tmp_path / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".mureo").mkdir(parents=True)
    # No AMAZON_ADS_* env fallback may leak into these assertions.
    for name in (
        "AMAZON_ADS_CLIENT_ID",
        "AMAZON_ADS_CLIENT_SECRET",
        "AMAZON_ADS_ACCESS_TOKEN",
        "AMAZON_ADS_REFRESH_TOKEN",
        "AMAZON_ADS_REGION",
    ):
        monkeypatch.delenv(name, raising=False)

    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _post(
    wiz: ConfigureWizard, path: str, payload: dict[str, Any] | None = None
) -> HTTPResponse:
    req = urllib.request.Request(
        f"http://127.0.0.1:{wiz.port}{path}",
        data=json.dumps(payload or {}).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    return urllib.request.urlopen(req, timeout=5.0)


def _post_json(
    wiz: ConfigureWizard, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return json.loads(_post(wiz, path, payload).read().decode())


def _post_error(
    wiz: ConfigureWizard, path: str, payload: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    try:
        resp = _post(wiz, path, payload)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())
    raise AssertionError(f"expected an HTTP error, got {resp.status}")


def _post_raw(
    wiz: ConfigureWizard,
    path: str,
    *,
    csrf: bool = True,
    host: str | None = None,
) -> urllib.error.HTTPError:
    """POST with the hardening headers under test deliberately wrong."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{wiz.port}{path}", data=b"{}", method="POST"
    )
    req.add_header("Content-Type", "application/json")
    if csrf:
        req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    if host is not None:
        req.add_header("Host", host)
    try:
        urllib.request.urlopen(req, timeout=5.0)
    except urllib.error.HTTPError as exc:
        return exc
    raise AssertionError("expected an HTTP error")


def _write_credentials(wiz: ConfigureWizard, section: dict[str, Any]) -> None:
    path = wiz.host_paths.credentials_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"amazon_ads": section}), encoding="utf-8")


def _read_section(wiz: ConfigureWizard) -> dict[str, Any]:
    doc = json.loads(wiz.host_paths.credentials_path.read_text(encoding="utf-8"))
    return doc["amazon_ads"]


def _query(url: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(url)
    return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}


def _stub_manifest(monkeypatch: pytest.MonkeyPatch, tools: int = 2) -> None:
    async def _fake_generate(_creds: Any, *, out_path: Any = None, **_: Any) -> Any:
        out_path.write_text(
            json.dumps({"tools": [{"name": f"t{i}"} for i in range(tools)]}),
            encoding="utf-8",
        )
        return out_path

    monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _fake_generate)


def _stub_exchange(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    def _fake_exchange(**kwargs: Any) -> LwaTokens:
        captured.update(kwargs)
        return LwaTokens(
            access_token="Atza|MINTED", refresh_token="Atzr|MINTED", expires_in=3600
        )

    monkeypatch.setattr(
        "mureo.amazon_ads.lwa.exchange_authorization_code", _fake_exchange
    )


@pytest.mark.unit
class TestAuthorizeUrlRoute:
    def test_missing_client_id_is_a_clean_400(self, wizard: ConfigureWizard) -> None:
        code, body = _post_error(wizard, _AUTHORIZE_URL)
        assert code == 400
        assert body["error"] == "amazon_client_id_missing"

    def test_half_saved_card_still_gets_an_authorize_url(
        self, wizard: ConfigureWizard
    ) -> None:
        """No token exists yet at authorize time — the credentials loader
        would answer ``None`` here, so the route must read the section."""
        _write_credentials(wizard, {"client_id": "amzn1.app.CID"})
        body = _post_json(wizard, _AUTHORIZE_URL)
        assert body["region"] == "na"
        assert body["authorize_url"].startswith("https://www.amazon.com/ap/oa?")

    def test_url_carries_the_documented_query(self, wizard: ConfigureWizard) -> None:
        _write_credentials(wizard, {"client_id": "amzn1.app.CID", "region": "fe"})
        body = _post_json(wizard, _AUTHORIZE_URL)
        assert body["region"] == "fe"
        assert body["authorize_url"].startswith(
            "https://apac.account.amazon.com/ap/oa?"
        )
        assert _query(body["authorize_url"]) == {
            "client_id": "amzn1.app.CID",
            "scope": "advertising::campaign_management",
            "response_type": "code",
            "redirect_uri": "https://amazon.com",
        }

    def test_custom_redirect_uri_is_honoured(self, wizard: ConfigureWizard) -> None:
        _write_credentials(wizard, {"client_id": "cid"})
        body = _post_json(
            wizard, _AUTHORIZE_URL, {"redirect_uri": "https://example.com/cb"}
        )
        assert _query(body["authorize_url"])["redirect_uri"] == "https://example.com/cb"

    def test_non_http_redirect_uri_is_refused(self, wizard: ConfigureWizard) -> None:
        """The URL is handed straight to ``window.open`` — a ``javascript:``
        redirect target has no business round-tripping through the server."""
        _write_credentials(wizard, {"client_id": "cid"})
        code, body = _post_error(
            wizard, _AUTHORIZE_URL, {"redirect_uri": "javascript:alert(1)"}
        )
        assert code == 400
        assert body["error"] == "invalid_redirect_uri"

    def test_unknown_region_degrades_to_na(self, wizard: ConfigureWizard) -> None:
        _write_credentials(wizard, {"client_id": "cid", "region": "ZZ"})
        assert _post_json(wizard, _AUTHORIZE_URL)["region"] == "na"

    def test_response_never_echoes_secrets(self, wizard: ConfigureWizard) -> None:
        _write_credentials(
            wizard,
            {
                "client_id": "cid",
                "client_secret": "SECRETSHH",
                "refresh_token": "Atzr|SECRETREFRESH",
                "access_token": "Atza|SECRETTOKEN",
            },
        )
        raw = _post(wizard, _AUTHORIZE_URL).read().decode()
        for secret in ("SECRETSHH", "SECRETREFRESH", "SECRETTOKEN"):
            assert secret not in raw

    def test_csrf_token_is_required(self, wizard: ConfigureWizard) -> None:
        exc = _post_raw(wizard, _AUTHORIZE_URL, csrf=False)
        assert exc.code == 403
        assert json.loads(exc.read().decode())["error"] == "csrf_invalid"

    def test_spoofed_host_rejected(self, wizard: ConfigureWizard) -> None:
        """The route is Host-gated like every sibling POST route (DNS
        rebinding: a page on attacker.example.com resolving to 127.0.0.1
        must not be able to drive the configure server)."""
        exc = _post_raw(wizard, _AUTHORIZE_URL, host="attacker.example.com")
        assert exc.code == 403
        assert json.loads(exc.read().decode())["error"] == "host_not_allowed"


@pytest.mark.unit
class TestExchangeRouteValidation:
    def test_missing_credentials_is_a_clean_400(self, wizard: ConfigureWizard) -> None:
        code, body = _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})
        assert code == 400
        assert body["error"] == "amazon_client_credentials_missing"

    def test_client_secret_alone_missing_is_the_same_400(
        self, wizard: ConfigureWizard
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid"})
        code, body = _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})
        assert code == 400
        assert body["error"] == "amazon_client_credentials_missing"

    def test_blank_input_is_a_clean_400(self, wizard: ConfigureWizard) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        code, body = _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "   "})
        assert code == 400
        assert body["error"] == "authorization_code_required"

    def test_url_without_a_code_param_is_a_clean_400(
        self, wizard: ConfigureWizard
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        code, body = _post_error(
            wizard,
            _EXCHANGE_URL,
            {"code_or_url": "https://amazon.com/?error=access_denied"},
        )
        assert code == 400
        assert body["error"] == "authorization_code_required"

    def test_non_http_redirect_uri_is_refused(self, wizard: ConfigureWizard) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        code, body = _post_error(
            wizard,
            _EXCHANGE_URL,
            {"code_or_url": "ANcode", "redirect_uri": "javascript:alert(1)"},
        )
        assert code == 400
        assert body["error"] == "invalid_redirect_uri"


@pytest.mark.unit
class TestExchangeRouteCodeParsing:
    def test_bare_code_is_passed_through(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)
        _stub_manifest(monkeypatch)

        body = _post_json(wizard, _EXCHANGE_URL, {"code_or_url": "  ANbareCode  "})

        assert body["status"] == "ok"
        assert captured["code"] == "ANbareCode"
        assert captured["redirect_uri"] == "https://amazon.com"
        assert captured["client_id"] == "cid"
        assert captured["client_secret"] == "s"
        assert captured["region"] == "na"

    def test_pasted_redirect_url_is_parsed(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)
        _stub_manifest(monkeypatch)

        _post_json(
            wizard,
            _EXCHANGE_URL,
            {
                "code_or_url": (
                    " https://amazon.com/?code=ANfromUrl&scope=advertising"
                    "%3A%3Acampaign_management "
                )
            },
        )
        assert captured["code"] == "ANfromUrl"

    def test_pasted_url_with_a_fragment_is_parsed(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)
        _stub_manifest(monkeypatch)

        _post_json(
            wizard, _EXCHANGE_URL, {"code_or_url": "amazon.com/?code=ANfrag#done"}
        )
        assert captured["code"] == "ANfrag"

    def test_bare_query_string_is_parsed(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Copying only the tail of the address bar yields a query string
        with no ``?`` — sending that to Amazon verbatim would turn a clear
        message into an opaque upstream rejection."""
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)
        _stub_manifest(monkeypatch)

        _post_json(
            wizard,
            _EXCHANGE_URL,
            {
                "code_or_url": (
                    "code=ANfromBareQuery&scope=advertising%3A%3Acampaign_management"
                )
            },
        )
        assert captured["code"] == "ANfromBareQuery"

    def test_leading_question_mark_query_is_parsed(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)
        _stub_manifest(monkeypatch)

        _post_json(wizard, _EXCHANGE_URL, {"code_or_url": "?code=ANfromLeadingQ"})
        assert captured["code"] == "ANfromLeadingQ"

    def test_genuinely_bare_code_is_not_treated_as_a_query(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare code that merely contains ``=`` (base64 padding) must
        still be sent as a code — only an actual ``code=`` segment makes
        the text a query string."""
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)
        _stub_manifest(monkeypatch)

        _post_json(wizard, _EXCHANGE_URL, {"code_or_url": "ANpaddedCode=="})
        assert captured["code"] == "ANpaddedCode=="

    def test_code_hidden_behind_a_fragment_is_a_clean_400(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail safe: a fragment-routed URL (``#/callback?code=…``) never
        reaches the server in Amazon's flow, so treating its text as a
        code would guarantee an opaque upstream rejection. Say "no code"
        instead — and never call Amazon at all."""
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)

        code, body = _post_error(
            wizard,
            _EXCHANGE_URL,
            {"code_or_url": "https://amazon.com/#/callback?code=ANhidden"},
        )
        assert code == 400
        assert body["error"] == "authorization_code_required"
        assert captured == {}

    def test_region_and_redirect_uri_reach_the_exchange(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(
            wizard, {"client_id": "cid", "client_secret": "s", "region": "eu"}
        )
        captured: dict[str, Any] = {}
        _stub_exchange(monkeypatch, captured)
        _stub_manifest(monkeypatch)

        body = _post_json(
            wizard,
            _EXCHANGE_URL,
            {"code_or_url": "ANcode", "redirect_uri": "https://example.com/cb"},
        )
        assert body["region"] == "eu"
        assert captured["region"] == "eu"
        assert captured["redirect_uri"] == "https://example.com/cb"


@pytest.mark.unit
class TestExchangeRouteSuccess:
    def test_tokens_and_the_reauth_clock_are_persisted(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(
            wizard, {"client_id": "cid", "client_secret": "s", "region": "eu"}
        )
        _stub_exchange(monkeypatch, {})
        _stub_manifest(monkeypatch, tools=3)

        body = _post_json(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})
        section = _read_section(wizard)

        assert body["status"] == "ok"
        assert section["access_token"] == "Atza|MINTED"
        assert section["refresh_token"] == "Atzr|MINTED"
        assert section["refresh_token_obtained_at"]
        # Untouched fields survive the write.
        assert section["client_id"] == "cid"
        assert section["region"] == "eu"

    def test_obtained_at_is_iso_utc_from_the_server_clock(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import datetime, timedelta, timezone

        from mureo.core import clock

        frozen = datetime(2026, 7, 31, 4, 5, 6, tzinfo=timezone(timedelta(hours=9)))
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        _stub_exchange(monkeypatch, {})
        _stub_manifest(monkeypatch)

        _post_json(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})
        assert (
            _read_section(wizard)["refresh_token_obtained_at"]
            == "2026-07-30T19:05:06+00:00"
        )

    def test_response_carries_no_token_material(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(
            wizard, {"client_id": "amzn1.app.SECRETCID", "client_secret": "SECRETSHH"}
        )
        _stub_exchange(monkeypatch, {})
        _stub_manifest(monkeypatch)

        raw = _post(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"}).read().decode()
        for secret in ("Atza|", "Atzr|", "MINTED", "SECRETSHH", "SECRETCID", "ANcode"):
            assert secret not in raw

    def test_manifest_is_refreshed_and_reported(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        _stub_exchange(monkeypatch, {})
        _stub_manifest(monkeypatch, tools=4)

        body = _post_json(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})
        assert body["manifest"] == "ok"
        assert body["tool_count"] == 4
        written = wizard.host_paths.credentials_path.parent / "amazon_tools.json"
        assert written.exists()

    def test_manifest_failure_does_not_fail_the_exchange(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The authorization succeeded and is already persisted; failing the
        response would tell the operator to redo a consent that worked."""
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})
        _stub_exchange(monkeypatch, {})

        async def _boom(_creds: Any, **_kw: Any) -> Any:
            raise RuntimeError("401 with Authorization: Bearer Atza|LEAKED-123")

        monkeypatch.setattr("mureo.amazon_ads.manifest.generate_manifest", _boom)

        body = _post_json(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})
        assert body["status"] == "ok"
        assert body["manifest"] == "failed"
        assert "LEAKED" not in json.dumps(body)
        assert "***" in body["manifest_detail"]
        # ...and the tokens are still on disk.
        assert _read_section(wizard)["refresh_token"] == "Atzr|MINTED"


@pytest.mark.unit
class TestExchangeRouteFailures:
    def test_expired_code_is_a_400_with_the_five_minute_hint(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})

        def _reject(**_kw: Any) -> LwaTokens:
            raise AmazonAuthCodeError(
                "Amazon rejected the authorization code (error='invalid_grant'). "
                "Codes are single-use and expire 5 minutes after consent"
            )

        monkeypatch.setattr("mureo.amazon_ads.lwa.exchange_authorization_code", _reject)
        code, body = _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "ANstale"})

        assert code == 400
        assert body["error"] == "authorization_code_invalid"
        assert "5 minutes" in body["detail"]

    def test_other_failure_is_502_with_scrubbed_detail(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})

        def _boom(**_kw: Any) -> LwaTokens:
            raise AmazonAuthError("HTTP 500 while holding Bearer Atza|LEAKED-123")

        monkeypatch.setattr("mureo.amazon_ads.lwa.exchange_authorization_code", _boom)
        code, body = _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})

        assert code == 502
        assert body["error"] == "amazon_authorization_failed"
        assert "LEAKED" not in json.dumps(body)
        assert "***" in body["detail"]

    def test_failure_detail_is_length_capped(
        self, wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})

        def _boom(**_kw: Any) -> LwaTokens:
            raise AmazonAuthError("x" * 5000)

        monkeypatch.setattr("mureo.amazon_ads.lwa.exchange_authorization_code", _boom)
        _code, body = _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})
        assert len(body["detail"]) == _MAX_STR

    def test_no_secret_reaches_the_response_or_the_log(
        self,
        wizard: ConfigureWizard,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Two decoy shapes, because they leak through different paths: a
        prefixed token (``Atza|…``) and a bare ``client_secret=…`` pair,
        which has no distinguishing prefix at all. Both must be gone from
        the response AND the log."""
        _write_credentials(
            wizard, {"client_id": "cid", "client_secret": "SECRET-CLIENT-SECRET"}
        )

        def _boom(**_kw: Any) -> LwaTokens:
            raise AmazonAuthError(
                "rejected for client_secret=SECRET-CLIENT-SECRET with "
                "Bearer Atza|LEAKED-TOKEN-VALUE"
            )

        monkeypatch.setattr("mureo.amazon_ads.lwa.exchange_authorization_code", _boom)
        with caplog.at_level(logging.DEBUG):
            _code, body = _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "ANcode"})

        for sink in (body["detail"], caplog.text):
            assert "Atza|" not in sink
            assert "LEAKED-TOKEN-VALUE" not in sink
            assert "SECRET-CLIENT-SECRET" not in sink
        # The key survives so the message still says what was rejected.
        assert "client_secret=***" in body["detail"]
        # The failure is recorded — scrubbing must not mean silence.
        assert "Amazon authorization" in caplog.text

    def test_pasted_code_never_reaches_the_log(
        self,
        wizard: ConfigureWizard,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An authorization code is single-use credential material for its
        5-minute life — it must not be persisted into a log file."""
        _write_credentials(wizard, {"client_id": "cid", "client_secret": "s"})

        def _boom(**_kw: Any) -> LwaTokens:
            raise AmazonAuthError("upstream said no")

        monkeypatch.setattr("mureo.amazon_ads.lwa.exchange_authorization_code", _boom)
        with caplog.at_level(logging.DEBUG):
            _post_error(wizard, _EXCHANGE_URL, {"code_or_url": "ANsecretCode123"})
        assert "ANsecretCode123" not in caplog.text

    def test_csrf_token_is_required(self, wizard: ConfigureWizard) -> None:
        exc = _post_raw(wizard, _EXCHANGE_URL, csrf=False)
        assert exc.code == 403
        assert json.loads(exc.read().decode())["error"] == "csrf_invalid"

    def test_spoofed_host_rejected(self, wizard: ConfigureWizard) -> None:
        """Host-gated like every sibling POST route — this one writes
        credentials, so the rebinding guard matters most here."""
        exc = _post_raw(wizard, _EXCHANGE_URL, host="attacker.example.com")
        assert exc.code == 403
        assert json.loads(exc.read().decode())["error"] == "host_not_allowed"
