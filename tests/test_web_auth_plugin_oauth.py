"""#201 — the wizard's generic plugin authorization-code callback.

A ``WebAuthWizard`` constructed with a ``PluginOAuthSpec`` serves the
provider-neutral ``GET /oauth/callback``: it validates ``state``,
exchanges the code via the library-agnostic
``exchange_authorization_code``, and merge-saves the obtained
``refresh_token`` into the provider's own ``credentials.json`` section
(preserving the client id/secret already stored there). These tests pin
that success path, the constant-time ``state`` rejection, and the
exchange-failure path — without making any real network call.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from mureo.cli.web_auth import PluginOAuthSpec, WebAuthWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 30x as an HTTPError so the test can read the Location."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _url(wiz: Any, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


@pytest.fixture
def plugin_wizard(tmp_path: Path) -> Iterator[Any]:
    creds_path = tmp_path / ".mureo" / "credentials.json"
    creds_path.parent.mkdir(parents=True)
    # Pre-seed the client credentials the operator saved before clicking
    # Authenticate — the callback must preserve them.
    creds_path.write_text(
        json.dumps({"yahoo_ads": {"client_id": "CID", "client_secret": "SECRET"}})
    )
    spec = PluginOAuthSpec(
        provider="yahoo_ads",
        target_field="refresh_token",
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:0/oauth/callback",
        state="state-xyz",
    )
    wiz = WebAuthWizard(credentials_path=creds_path, plugin_oauth=spec)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=2.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


@pytest.mark.unit
def test_default_wizard_has_no_plugin_oauth() -> None:
    assert WebAuthWizard().plugin_oauth is None


@pytest.mark.unit
def test_plugin_callback_saves_refresh_token(plugin_wizard: Any) -> None:
    from mureo.oauth_authcode import AuthCodeResult

    with patch(
        "mureo.cli.web_auth.exchange_authorization_code",
        return_value=AuthCodeResult(refresh_token="RT-new", access_token="AT"),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(plugin_wizard, "/oauth/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 302
        assert exc.value.headers.get("Location", "") == "/done"

    saved = json.loads(plugin_wizard.credentials_path.read_text())
    assert saved["yahoo_ads"]["refresh_token"] == "RT-new"
    # Client credentials saved earlier survive the merge.
    assert saved["yahoo_ads"]["client_id"] == "CID"
    assert saved["yahoo_ads"]["client_secret"] == "SECRET"


@pytest.mark.unit
def test_plugin_callback_rejects_state_mismatch(plugin_wizard: Any) -> None:
    def _must_not_exchange(**_kwargs: Any) -> Any:
        raise AssertionError("token exchange must not run on a state mismatch")

    with patch(
        "mureo.cli.web_auth.exchange_authorization_code", side_effect=_must_not_exchange
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(plugin_wizard, "/oauth/callback?code=AC&state=WRONG"),
                timeout=2.0,
            )
        assert exc.value.code == 403

    saved = json.loads(plugin_wizard.credentials_path.read_text())
    assert "refresh_token" not in saved["yahoo_ads"]


@pytest.mark.unit
def test_plugin_callback_exchange_failure_renders_error(plugin_wizard: Any) -> None:
    from mureo.oauth_authcode import OAuthExchangeError

    with patch(
        "mureo.cli.web_auth.exchange_authorization_code",
        side_effect=OAuthExchangeError("nope"),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(plugin_wizard, "/oauth/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 400

    saved = json.loads(plugin_wizard.credentials_path.read_text())
    assert "refresh_token" not in saved["yahoo_ads"]
