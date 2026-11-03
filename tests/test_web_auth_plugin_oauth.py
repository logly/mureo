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

import contextlib
import json
import threading
import urllib.error
import urllib.request
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mureo.web.auth_wizard import PluginOAuthSpec, WebAuthWizard

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
        "mureo.web.auth_wizard.exchange_authorization_code",
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
        "mureo.web.auth_wizard.exchange_authorization_code",
        side_effect=_must_not_exchange,
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
        "mureo.web.auth_wizard.exchange_authorization_code",
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
        "mureo.web.auth_wizard.exchange_authorization_code",
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
        "mureo.web.auth_wizard.exchange_authorization_code",
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
        "mureo.web.auth_wizard.exchange_authorization_code",
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


# ---------------------------------------------------------------------------
# token_headers — the callback exchange sends the provider's declared extra
# token-request headers, and none when the provider declares none.
# ---------------------------------------------------------------------------


@pytest.fixture
def headers_wizard(tmp_path: Path) -> Iterator[Any]:
    creds_path = tmp_path / ".mureo" / "credentials.json"
    creds_path.parent.mkdir(parents=True)
    spec = PluginOAuthSpec(
        provider="broker_ads",
        target_field="refresh_token",
        token_url="https://broker.example.com/oauth/token",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:8765/oauth/callback",
        state="state-xyz",
        token_headers=(("X-Example", "abc"),),
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


def _complete_callback(wiz: Any) -> Any:
    from mureo.oauth_authcode import AuthCodeResult

    with patch(
        "mureo.web.auth_wizard.exchange_authorization_code",
        return_value=AuthCodeResult(refresh_token="RT", access_token="AT"),
    ) as mock_exchange:
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(wiz, "/oauth/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 302
    return mock_exchange


@pytest.mark.unit
def test_plugin_callback_passes_declared_token_headers(headers_wizard: Any) -> None:
    mock_exchange = _complete_callback(headers_wizard)
    assert mock_exchange.call_args.kwargs["headers"] == {"X-Example": "abc"}


@pytest.mark.unit
def test_plugin_callback_passes_no_headers_by_default(plugin_wizard: Any) -> None:
    mock_exchange = _complete_callback(plugin_wizard)
    assert mock_exchange.call_args.kwargs["headers"] is None


@pytest.mark.unit
def test_default_spec_token_headers_is_empty() -> None:
    spec = PluginOAuthSpec(
        provider="p",
        target_field="refresh_token",
        token_url="https://a.test/token",
        client_id="c",
        client_secret="s",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        state="x",
    )
    assert spec.token_headers == ()


# ---------------------------------------------------------------------------
# #939 — the callback calls the provider's on_oauth_persisted hook once,
# after the merged section is on disk; a failing hook keeps the token.
# ---------------------------------------------------------------------------

_HOOK_PROVIDER = "broker_ads"
_HOOK_TOKEN = "RT-hook-939-secret"


def _hook_entry(hook: Any | None, *, as_classmethod: bool = False) -> Any:
    from mureo.core.providers.registry import ProviderEntry

    class _Broker:
        name = _HOOK_PROVIDER
        display_name = "Broker Ads"
        capabilities = frozenset()

    if hook is not None:
        wrapped = classmethod(hook) if as_classmethod else staticmethod(hook)
        _Broker.on_oauth_persisted = wrapped  # type: ignore[attr-defined]
    return ProviderEntry(
        name=_HOOK_PROVIDER,
        display_name="Broker Ads",
        capabilities=frozenset(),
        provider_class=_Broker,
        source_distribution=None,
    )


def _register_hook(
    monkeypatch: pytest.MonkeyPatch, hook: Any | None, *, as_classmethod: bool = False
) -> None:
    from mureo.core.providers import default_registry

    entry = _hook_entry(hook, as_classmethod=as_classmethod)
    monkeypatch.setattr(default_registry, "_entries", {_HOOK_PROVIDER: entry})


@pytest.fixture
def hook_wizard(tmp_path: Path) -> Iterator[Any]:
    creds_path = tmp_path / ".mureo" / "credentials.json"
    creds_path.parent.mkdir(parents=True)
    spec = PluginOAuthSpec(
        provider=_HOOK_PROVIDER,
        target_field="refresh_token",
        token_url="https://broker.example.com/oauth/token",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:8765/oauth/callback",
        state="state-xyz",
        persist_values={"client_id": "CID", "account_id": "acct-1"},
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


def _callback_redirect(wiz: Any) -> tuple[int, str]:
    """Run the callback with a stubbed exchange; return (status, Location)."""
    from mureo.oauth_authcode import AuthCodeResult

    with patch(
        "mureo.web.auth_wizard.exchange_authorization_code",
        return_value=AuthCodeResult(refresh_token=_HOOK_TOKEN, access_token="AT"),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(wiz, "/oauth/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
    return exc.value.code, exc.value.headers.get("Location", "")


def _saved_section(wiz: Any) -> dict[str, str]:
    return dict(json.loads(wiz.credentials_path.read_text())[_HOOK_PROVIDER])


@pytest.mark.unit
def test_persist_hook_called_once_after_section_is_on_disk(
    hook_wizard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mureo.core.secret_store import FilesystemSecretStore

    calls: list[dict[str, Any]] = []

    def _hook(credentials: Any, *, credentials_path: Path) -> None:
        on_disk = FilesystemSecretStore(path=credentials_path).load(_HOOK_PROVIDER)
        calls.append(
            {
                "credentials": dict(credentials),
                "credentials_path": credentials_path,
                "on_disk": on_disk,
                "read_only": isinstance(credentials, MappingProxyType),
            }
        )

    _register_hook(monkeypatch, _hook)
    assert _callback_redirect(hook_wizard) == (302, "/done")

    expected = {
        "client_id": "CID",
        "account_id": "acct-1",
        "refresh_token": _HOOK_TOKEN,
    }
    assert len(calls) == 1
    assert calls[0]["credentials"] == expected
    assert calls[0]["credentials_path"] == hook_wizard.credentials_path
    assert calls[0]["on_disk"] == expected
    assert calls[0]["read_only"] is True


@pytest.mark.unit
def test_persist_hook_failure_keeps_token_and_redirects(
    hook_wizard: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(credentials: Any, *, credentials_path: Path) -> None:
        raise RuntimeError(f"derive failed for {credentials['refresh_token']}")

    _register_hook(monkeypatch, _boom)
    with caplog.at_level("WARNING"):
        assert _callback_redirect(hook_wizard) == (302, "/done")

    assert _saved_section(hook_wizard)["refresh_token"] == _HOOK_TOKEN
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert _HOOK_PROVIDER in message
    assert _HOOK_TOKEN not in message
    assert _HOOK_TOKEN not in caplog.text


@pytest.mark.unit
def test_persist_hook_async_is_awaited(
    hook_wizard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []

    async def _hook(credentials: Any, *, credentials_path: Path) -> None:
        ran.append(credentials["refresh_token"])

    _register_hook(monkeypatch, _hook)
    assert _callback_redirect(hook_wizard) == (302, "/done")
    assert ran == [_HOOK_TOKEN]


@pytest.mark.unit
def test_persist_hook_absent_still_redirects(
    hook_wizard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register_hook(monkeypatch, None)
    assert _callback_redirect(hook_wizard) == (302, "/done")
    assert _saved_section(hook_wizard)["refresh_token"] == _HOOK_TOKEN


@pytest.mark.unit
def test_persist_hook_async_failure_keeps_token_and_redirects(
    hook_wizard: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The await path sits inside the same guard as the call."""

    async def _boom(credentials: Any, *, credentials_path: Path) -> None:
        raise RuntimeError(f"derive failed for {credentials['refresh_token']}")

    _register_hook(monkeypatch, _boom)
    with caplog.at_level("WARNING"):
        assert _callback_redirect(hook_wizard) == (302, "/done")

    assert _saved_section(hook_wizard)["refresh_token"] == _HOOK_TOKEN
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert _HOOK_PROVIDER in warnings[0].getMessage()
    assert "RuntimeError" in warnings[0].getMessage()
    assert _HOOK_TOKEN not in caplog.text


@pytest.mark.unit
def test_persist_hook_classmethod_called_through_wizard(
    hook_wizard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []

    def _hook(cls: Any, credentials: Any, *, credentials_path: Path) -> None:
        seen.append((cls.name, credentials["refresh_token"]))

    _register_hook(monkeypatch, _hook, as_classmethod=True)
    assert _callback_redirect(hook_wizard) == (302, "/done")
    assert seen == [(_HOOK_PROVIDER, _HOOK_TOKEN)]


@pytest.mark.unit
def test_persist_hook_view_rejects_mutation(
    hook_wizard: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[type[BaseException]] = []

    def _hook(credentials: Any, *, credentials_path: Path) -> None:
        try:
            credentials["refresh_token"] = "overwritten"
        except TypeError as exc:
            errors.append(type(exc))

    _register_hook(monkeypatch, _hook)
    assert _callback_redirect(hook_wizard) == (302, "/done")
    assert errors == [TypeError]
    assert _saved_section(hook_wizard)["refresh_token"] == _HOOK_TOKEN


@pytest.mark.unit
def test_notify_oauth_persisted_unregistered_provider_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mureo.core.providers import default_registry
    from mureo.web.plugin_credentials import notify_oauth_persisted

    monkeypatch.setattr(default_registry, "_entries", {})
    notify_oauth_persisted(
        "nobody", {"refresh_token": _HOOK_TOKEN}, tmp_path / "credentials.json"
    )


# ---------------------------------------------------------------------------
# revoke_url (#970) — re-authentication revokes the token it replaces, best
# effort: a failed revocation never blocks saving the new token.
# ---------------------------------------------------------------------------

_REVOKE_URL = "https://biz-oauth.yahoo.co.jp/oauth/v1/revoke"


@contextlib.contextmanager
def _serving_wizard(
    tmp_path: Path, section: dict[str, str], *, revoke_url: str | None
) -> Iterator[Any]:
    creds_path = tmp_path / ".mureo" / "credentials.json"
    creds_path.parent.mkdir(parents=True)
    creds_path.write_text(json.dumps({"yahoo_ads": section}))
    spec = PluginOAuthSpec(
        provider="yahoo_ads",
        target_field="refresh_token",
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:0/oauth/callback",
        state="state-xyz",
        token_auth_style="body",
        token_headers=(("X-Example", "abc"),),
        revoke_url=revoke_url,
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


_STORED = {"client_id": "CID", "client_secret": "SECRET", "refresh_token": "RT-old"}


@pytest.fixture
def revoke_wizard(tmp_path: Path) -> Iterator[Any]:
    with _serving_wizard(tmp_path, dict(_STORED), revoke_url=_REVOKE_URL) as wiz:
        yield wiz


def _reauth(wiz: Any, revoke: Any, new_token: str = "RT-new") -> tuple[int, str]:
    """Run the callback with a stubbed exchange and ``revoke`` standing in
    for ``revoke_token``; return (status, Location)."""
    from mureo.oauth_authcode import AuthCodeResult

    with (
        patch(
            "mureo.web.auth_wizard.exchange_authorization_code",
            return_value=AuthCodeResult(refresh_token=new_token, access_token="AT"),
        ),
        patch("mureo.web.plugin_oauth_revoke.revoke_token", revoke),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(wiz, "/oauth/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
    return exc.value.code, exc.value.headers.get("Location", "")


def _stored_token(wiz: Any) -> str:
    return str(
        json.loads(wiz.credentials_path.read_text())["yahoo_ads"]["refresh_token"]
    )


@pytest.mark.unit
def test_reauth_revokes_the_replaced_token(revoke_wizard: Any) -> None:
    revoke = MagicMock(return_value=True)
    assert _reauth(revoke_wizard, revoke) == (302, "/done")
    revoke.assert_called_once_with(
        revoke_url=_REVOKE_URL,
        token="RT-old",
        client_id="CID",
        client_secret="SECRET",
        client_auth="body",
        headers={"X-Example": "abc"},
    )
    assert _stored_token(revoke_wizard) == "RT-new"


@pytest.mark.unit
@pytest.mark.parametrize(
    "revoke",
    [
        MagicMock(return_value=False),
        MagicMock(side_effect=RuntimeError("revocation exploded RT-old")),
    ],
    ids=["refused", "raised"],
)
def test_reauth_failed_revocation_still_saves_new_token(
    revoke_wizard: Any, revoke: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="mureo.web.plugin_oauth_revoke"):
        assert _reauth(revoke_wizard, revoke) == (302, "/done")
    assert _stored_token(revoke_wizard) == "RT-new"
    warnings = [r for r in caplog.records if r.name == "mureo.web.plugin_oauth_revoke"]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"
    assert "yahoo_ads" in warnings[0].getMessage()
    assert "RT-old" not in caplog.text
    assert "SECRET" not in caplog.text


@pytest.mark.unit
def test_reauth_unreachable_revoke_endpoint_is_one_warning(
    revoke_wizard: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Through the real ``revoke_token``: an endpoint that cannot be reached
    is a single WARNING for the whole callback, and the new token is kept."""
    from mureo.oauth_authcode import revoke_token

    with (
        caplog.at_level("WARNING"),
        patch(
            "mureo.oauth_authcode._post_form",
            side_effect=httpx.ConnectError("down RT-old SECRET"),
        ),
    ):
        assert _reauth(revoke_wizard, revoke_token) == (302, "/done")
    assert _stored_token(revoke_wizard) == "RT-new"
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert warnings[0].name == "mureo.web.plugin_oauth_revoke"
    assert "yahoo_ads" in warnings[0].getMessage()
    assert "ConnectError" in warnings[0].getMessage()
    assert "RT-old" not in caplog.text
    assert "SECRET" not in caplog.text


@pytest.mark.unit
def test_reauth_without_previous_token_does_not_revoke(tmp_path: Path) -> None:
    section = {"client_id": "CID", "client_secret": "SECRET"}
    revoke = MagicMock(return_value=True)
    with _serving_wizard(tmp_path, section, revoke_url=_REVOKE_URL) as wiz:
        assert _reauth(wiz, revoke) == (302, "/done")
        assert _stored_token(wiz) == "RT-new"
    revoke.assert_not_called()


@pytest.mark.unit
def test_reauth_returning_the_same_token_does_not_revoke(
    revoke_wizard: Any,
) -> None:
    revoke = MagicMock(return_value=True)
    assert _reauth(revoke_wizard, revoke, new_token="RT-old") == (302, "/done")
    revoke.assert_not_called()


@pytest.mark.unit
def test_reauth_without_revoke_url_does_not_revoke(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    revoke = MagicMock(return_value=True)
    with (
        caplog.at_level("DEBUG", logger="mureo.web.plugin_oauth_revoke"),
        _serving_wizard(tmp_path, dict(_STORED), revoke_url=None) as wiz,
    ):
        assert _reauth(wiz, revoke) == (302, "/done")
        assert _stored_token(wiz) == "RT-new"
    revoke.assert_not_called()
    assert not [r for r in caplog.records if r.name == "mureo.web.plugin_oauth_revoke"]


@pytest.mark.unit
def test_default_spec_revoke_url_is_none() -> None:
    spec = PluginOAuthSpec(
        provider="p",
        target_field="refresh_token",
        token_url="https://a.test/token",
        client_id="c",
        client_secret="s",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        state="x",
    )
    assert spec.revoke_url is None
