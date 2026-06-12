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


# ---------------------------------------------------------------------------
# #216 — operator-supplied loopback callback URL: bind_port / bind_error
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Probe a currently-free loopback port, then release it."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


@pytest.mark.unit
def test_default_wizard_bind_error_is_none() -> None:
    assert WebAuthWizard().bind_error is None


@pytest.mark.unit
def test_wizard_binds_requested_port() -> None:
    """``bind_port`` makes the wizard listen on that exact port so the
    operator-registered loopback redirect_uri (#216) — which encodes a
    fixed port — resolves on every run instead of a fresh ephemeral one."""
    port = _free_port()
    wiz = WebAuthWizard(bind_port=port)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    try:
        wiz.wait_until_ready(timeout=2.0)
        assert wiz.bind_error is None
        assert wiz.port == port
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


@pytest.mark.unit
def test_wizard_bind_error_when_port_in_use() -> None:
    """A port already held by an active listener surfaces as
    ``bind_error`` (and ``wait_until_ready`` returns promptly rather than
    timing out) so the bridge reports a clean 'port unavailable' (#216)."""
    import socket

    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = int(held.getsockname()[1])
    try:
        wiz = WebAuthWizard(bind_port=port)
        thread = threading.Thread(target=wiz.serve, daemon=True)
        thread.start()
        wiz.wait_until_ready(timeout=2.0)  # prompt return, not a timeout
        assert isinstance(wiz.bind_error, OSError)
        thread.join(timeout=2.0)
    finally:
        held.close()


# ---------------------------------------------------------------------------
# #217 — Authenticate IS save: persist_values + token in one atomic write,
# served at the operator-chosen callback_path (#216).
# ---------------------------------------------------------------------------


@pytest.fixture
def authsave_wizard(tmp_path: Path) -> Iterator[Any]:
    """A plugin wizard whose spec carries #217 ``persist_values`` and a
    non-default #216 ``callback_path`` — nothing is on disk beforehand."""
    creds_path = tmp_path / ".mureo" / "credentials.json"
    creds_path.parent.mkdir(parents=True)
    # No pre-seed: Authenticate-is-save means the operator's form values
    # arrive together with the token in a single write (#217).
    spec = PluginOAuthSpec(
        provider="yahoo_ads",
        target_field="refresh_token",
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:8765/cb",
        state="state-xyz",
        callback_path="/cb",
        persist_values={
            "client_id": "CID",
            "client_secret": "SECRET",
            "base_account_id": "ACC-1",
        },
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
def test_authsave_persists_values_and_token_atomically(authsave_wizard: Any) -> None:
    """A successful callback at the operator's ``callback_path`` writes the
    submitted form values AND the obtained token into one section, with no
    prior save on disk (#216 path + #217 atomic persist)."""
    from mureo.oauth_authcode import AuthCodeResult

    with patch(
        "mureo.cli.web_auth.exchange_authorization_code",
        return_value=AuthCodeResult(refresh_token="RT-new", access_token="AT"),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(authsave_wizard, "/cb?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 302
        assert exc.value.headers.get("Location", "") == "/done"

    saved = json.loads(authsave_wizard.credentials_path.read_text())["yahoo_ads"]
    assert saved["refresh_token"] == "RT-new"
    assert saved["client_id"] == "CID"
    assert saved["client_secret"] == "SECRET"
    assert saved["base_account_id"] == "ACC-1"


@pytest.mark.unit
def test_authsave_failure_persists_nothing(authsave_wizard: Any) -> None:
    """On exchange failure neither the form values nor a token are written
    — abandoning consent leaves disk untouched (#217)."""
    from mureo.oauth_authcode import OAuthExchangeError

    with patch(
        "mureo.cli.web_auth.exchange_authorization_code",
        side_effect=OAuthExchangeError("nope"),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(authsave_wizard, "/cb?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 400

    path = authsave_wizard.credentials_path
    assert not path.exists() or "yahoo_ads" not in json.loads(path.read_text())


# ---------------------------------------------------------------------------
# token_auth_style — the callback exchange honours the provider's declared
# token-endpoint client-auth style (Yahoo! JAPAN biz-oauth needs "body").
# ---------------------------------------------------------------------------


@pytest.fixture
def body_auth_wizard(tmp_path: Path) -> Iterator[Any]:
    creds_path = tmp_path / ".mureo" / "credentials.json"
    creds_path.parent.mkdir(parents=True)
    spec = PluginOAuthSpec(
        provider="yahoo_ads",
        target_field="refresh_token",
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:8765/oauth/callback",
        state="state-xyz",
        token_auth_style="body",
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
def test_plugin_callback_passes_declared_token_auth_style(
    body_auth_wizard: Any,
) -> None:
    """The exchange is called with ``client_auth`` taken from the spec's
    ``token_auth_style`` so a body-style provider authenticates correctly."""
    from mureo.oauth_authcode import AuthCodeResult

    with patch(
        "mureo.cli.web_auth.exchange_authorization_code",
        return_value=AuthCodeResult(refresh_token="RT", access_token="AT"),
    ) as mock_exchange:
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(body_auth_wizard, "/oauth/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 302
    assert mock_exchange.call_args.kwargs["client_auth"] == "body"


@pytest.mark.unit
def test_default_spec_token_auth_style_is_basic() -> None:
    """A spec built without the field defaults to Basic (regression)."""
    spec = PluginOAuthSpec(
        provider="p",
        target_field="refresh_token",
        token_url="https://a.test/token",
        client_id="c",
        client_secret="s",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        state="x",
    )
    assert spec.token_auth_style == "basic"
