"""#201 — configure-handler endpoints for the generic plugin OAuth flow.

Covers ``POST /api/credentials/plugins/<p>/oauth/start`` and
``GET  …/oauth/status`` plus the ``oauth`` descriptor block surfaced by
``GET /api/credentials/plugins``. The OAuth bridge is patched so no real
wizard binds; these tests pin the handler's policy: a provider must be
registered and declare ``account_oauth``, the saved client id/secret are
loaded before the flow starts (else ``400 client_credentials_missing``),
and the descriptor exposes only field *keys*, never secret values.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mureo.core.providers import AccountCredentialField, AccountOAuthConfig
from mureo.core.providers.registry import ProviderEntry, default_registry
from mureo.web.oauth_bridge import OAuthHandoffResult
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path

_OAUTH = AccountOAuthConfig(
    authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
    token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
    client_id_field="client_id",
    client_secret_field="client_secret",
    target_field="refresh_token",
    scopes=("scopeA",),
)
_FIELDS = (
    AccountCredentialField(key="client_id", display_name="Client ID"),
    AccountCredentialField(key="client_secret", display_name="Secret", secret=True),
    AccountCredentialField(key="refresh_token", display_name="Refresh", secret=True),
)


def _oauth_class() -> type:
    class _Yahoo:
        name = "yahoo_ads"
        display_name = "Yahoo! JAPAN Ads"
        capabilities = frozenset()
        account_credential_fields = _FIELDS
        account_oauth = _OAUTH

    return _Yahoo


def _plain_class() -> type:
    class _Demo:
        name = "demo_ads"
        display_name = "Demo Ads"
        capabilities = frozenset()
        account_credential_fields = (
            AccountCredentialField(key="api_key", display_name="API Key", secret=True),
        )

    return _Demo


def _entry(cls: type) -> ProviderEntry:
    return ProviderEntry(
        name=cls.name,  # type: ignore[attr-defined]
        display_name=cls.display_name,  # type: ignore[attr-defined]
        capabilities=frozenset(),
        provider_class=cls,
        source_distribution=None,
    )


@pytest.fixture
def wizard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ConfigureWizard]:
    home = tmp_path / "home"
    for sub in ("", ".claude", ".claude/commands", ".mureo"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {"yahoo_ads": _entry(_oauth_class()), "demo_ads": _entry(_plain_class())},
    )
    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _url(wiz: ConfigureWizard, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


def _get(wiz: ConfigureWizard, path: str) -> HTTPResponse:
    return urllib.request.urlopen(_url(wiz, path), timeout=2.0)


def _post(wiz: ConfigureWizard, path: str) -> HTTPResponse:
    req = urllib.request.Request(_url(wiz, path), data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    return urllib.request.urlopen(req, timeout=2.0)


def _seed_client_creds(wiz: ConfigureWizard) -> None:
    path = wiz.host_paths.credentials_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"yahoo_ads": {"client_id": "CID", "client_secret": "SECRET"}})
    )


# ---------------------------------------------------------------------------
# GET /api/credentials/plugins — oauth descriptor block (#201 / Batch 6)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_plugin_list_exposes_oauth_block(wizard: ConfigureWizard) -> None:
    body = json.loads(_get(wizard, "/api/credentials/plugins").read())
    by_name = {p["provider_name"]: p for p in body["plugins"]}
    assert by_name["yahoo_ads"]["oauth"] == {
        "target_field": "refresh_token",
        "client_id_field": "client_id",
        "client_secret_field": "client_secret",
    }
    # A manual-entry provider declares no oauth → null (no Authenticate button).
    assert by_name["demo_ads"]["oauth"] is None
    # The descriptor leaks no endpoints/secrets.
    assert "authorize_url" not in json.dumps(by_name["yahoo_ads"]["oauth"])


# ---------------------------------------------------------------------------
# POST …/oauth/start
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_start_400_when_client_credentials_missing(wizard: ConfigureWizard) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(wizard, "/api/credentials/plugins/yahoo_ads/oauth/start")
    assert exc.value.code == 400
    assert json.loads(exc.value.read())["error"] == "client_credentials_missing"


@pytest.mark.unit
def test_start_success_returns_consent_url(wizard: ConfigureWizard) -> None:
    _seed_client_creds(wizard)
    fake = OAuthHandoffResult(
        url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize?x=1",
        state="pending",
        provider="yahoo_ads",
    )
    with patch.object(
        wizard.oauth_bridge, "start_plugin_oauth", return_value=fake
    ) as mock_start:
        resp = _post(wizard, "/api/credentials/plugins/yahoo_ads/oauth/start")
        body = json.loads(resp.read())
    assert body["url"].startswith("https://biz-oauth.yahoo.co.jp/oauth/v1/authorize")
    kwargs = mock_start.call_args.kwargs
    assert kwargs["provider"] == "yahoo_ads"
    assert kwargs["client_id"] == "CID"
    assert kwargs["client_secret"] == "SECRET"
    assert kwargs["oauth_config"].target_field == "refresh_token"


@pytest.mark.unit
def test_start_404_for_unknown_provider(wizard: ConfigureWizard) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(wizard, "/api/credentials/plugins/nope_ads/oauth/start")
    assert exc.value.code == 404


@pytest.mark.unit
def test_start_404_when_provider_has_no_oauth(wizard: ConfigureWizard) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(wizard, "/api/credentials/plugins/demo_ads/oauth/start")
    assert exc.value.code == 404
    assert json.loads(exc.value.read())["error"] == "oauth_not_supported"


# ---------------------------------------------------------------------------
# GET …/oauth/status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_status_idle_before_start(wizard: ConfigureWizard) -> None:
    resp = _get(wizard, "/api/credentials/plugins/yahoo_ads/oauth/status")
    assert json.loads(resp.read()) == {
        "pending": False,
        "success": False,
        "error": None,
    }


@pytest.mark.unit
def test_status_404_for_unknown_provider(wizard: ConfigureWizard) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard, "/api/credentials/plugins/nope_ads/oauth/status")
    assert exc.value.code == 404
