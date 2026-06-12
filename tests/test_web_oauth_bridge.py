"""Bridging logic for ``mureo.web.oauth_bridge``.

The OAuth bridge spawns a separate ``WebAuthWizard`` (in
``mureo.cli.web_auth``) per provider, returns the consent URL, and
runs a watcher thread that updates the parent configure-wizard
session on completion. Every test in here MUST mock the spawned
wizard — no real sub-server, no real socket bind, no network.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.web.oauth_bridge import (
    OAuthBridge,
    OAuthHandoffResult,
    _credentials_present_for,
    _plugin_credentials_present,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.mark.unit
class TestOAuthHandoffResult:
    def test_default_state_is_pending(self) -> None:
        result = OAuthHandoffResult(url=None)
        assert result.state == "pending"
        assert result.provider == ""

    def test_as_dict_shape(self) -> None:
        result = OAuthHandoffResult(url="https://x/oauth", provider="google")
        out = result.as_dict()
        assert out == {
            "url": "https://x/oauth",
            "redirect_url": "https://x/oauth",
            "state": "pending",
            "provider": "google",
            "error": None,
        }

    def test_as_dict_surfaces_error(self) -> None:
        """A bind/validation failure (#216) travels to the client as an
        ``error`` code so the dashboard can toast the specific reason."""
        result = OAuthHandoffResult(
            url=None, provider="yahoo_ads", error="callback_url_invalid"
        )
        out = result.as_dict()
        assert out["error"] == "callback_url_invalid"
        assert out["url"] is None

    def test_is_frozen(self) -> None:
        import dataclasses

        result = OAuthHandoffResult(url="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.url = "y"  # type: ignore[misc]

    def test_url_can_be_none(self) -> None:
        result = OAuthHandoffResult(url=None, provider="meta")
        out = result.as_dict()
        assert out["url"] is None
        assert out["redirect_url"] is None


class _FakeWizard:
    """Stand-in for ``mureo.cli.web_auth.WebAuthWizard`` — never binds."""

    def __init__(
        self,
        *,
        credentials_path: Path | None = None,
        bind_port: int = 0,
        port: int = 12345,
        completed: bool = False,
        ready_timeout: bool = False,
        bind_error: Exception | None = None,
        multi_account_auth: bool = False,
    ) -> None:
        self.credentials_path = credentials_path
        self.bind_port = bind_port
        self.port = port
        self.completed = completed
        self._ready_timeout = ready_timeout
        # Mirrors WebAuthWizard.bind_error: set by the bridge's bind path
        # (#216) when the operator-chosen port is unavailable.
        self.bind_error = bind_error
        self.multi_account_auth = multi_account_auth
        self.shutdown_called = False
        self.serve_called = False
        self.plugin_oauth: Any = None

    def serve(self) -> None:
        self.serve_called = True

    def wait_until_ready(self, timeout: float = 5.0) -> None:
        if self._ready_timeout:
            raise TimeoutError("bind timeout")

    def home_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.fixture
def patched_wizard_class() -> Iterator[Any]:
    """Patch the lazy-imported WebAuthWizard. Yields the class mock."""
    instances: list[_FakeWizard] = []

    def _factory(**kwargs: Any) -> _FakeWizard:
        w = _FakeWizard(**kwargs)
        instances.append(w)
        return w

    with patch("mureo.cli.web_auth.WebAuthWizard", side_effect=_factory) as mock_cls:
        mock_cls.instances = instances  # type: ignore[attr-defined]
        yield mock_cls


@pytest.fixture
def fake_configure_wizard() -> MagicMock:
    wiz = MagicMock()
    wiz.mark_oauth_complete = MagicMock()
    return wiz


@pytest.mark.unit
class TestOAuthBridgeStart:
    def test_unknown_provider_raises_value_error(
        self, fake_configure_wizard: MagicMock
    ) -> None:
        bridge = OAuthBridge()
        with pytest.raises(ValueError, match="unknown provider"):
            bridge.start(provider="twitter", configure_wizard=fake_configure_wizard)

    def test_google_start_returns_consent_url(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
        tmp_path: Path,
    ) -> None:
        bridge = OAuthBridge()
        creds = tmp_path / "credentials.json"
        result = bridge.start(
            provider="google",
            configure_wizard=fake_configure_wizard,
            credentials_path=creds,
        )
        assert isinstance(result, OAuthHandoffResult)
        assert result.url is not None
        # The URL now carries an explicit ?locale=en query string so the
        # legacy wizard can switch HTML to JA when the configure UI's
        # operator picked Japanese. Default locale is English.
        assert "/google-ads?locale=en" in result.url
        assert result.url.startswith("http://127.0.0.1:")
        assert result.state == "pending"
        assert result.provider == "google"
        bridge.cancel_all()

    def test_meta_start_returns_meta_path(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
    ) -> None:
        bridge = OAuthBridge()
        result = bridge.start(provider="meta", configure_wizard=fake_configure_wizard)
        assert result.url is not None
        assert "/meta-ads?locale=en" in result.url
        bridge.cancel_all()

    def test_japanese_locale_appears_in_consent_url(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
    ) -> None:
        bridge = OAuthBridge()
        result = bridge.start(
            provider="google",
            configure_wizard=fake_configure_wizard,
            locale="ja",
        )
        assert result.url is not None
        assert "?locale=ja" in result.url
        bridge.cancel_all()

    def test_unknown_locale_falls_back_to_english(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
    ) -> None:
        bridge = OAuthBridge()
        result = bridge.start(
            provider="google",
            configure_wizard=fake_configure_wizard,
            locale="fr",
        )
        assert result.url is not None
        assert "?locale=en" in result.url
        bridge.cancel_all()

    def test_start_again_cancels_prior_handoff(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
    ) -> None:
        bridge = OAuthBridge()
        bridge.start(provider="google", configure_wizard=fake_configure_wizard)
        first_wizard = patched_wizard_class.instances[0]
        bridge.start(provider="google", configure_wizard=fake_configure_wizard)
        assert first_wizard.shutdown_called is True
        bridge.cancel_all()


@pytest.mark.unit
class TestOAuthBridgeStartTimeout:
    def test_bind_timeout_returns_pending_result_without_url(
        self, fake_configure_wizard: MagicMock
    ) -> None:
        bridge = OAuthBridge()

        def _factory(**kwargs: Any) -> _FakeWizard:
            return _FakeWizard(ready_timeout=True, **kwargs)

        with patch("mureo.cli.web_auth.WebAuthWizard", side_effect=_factory):
            result = bridge.start(
                provider="google", configure_wizard=fake_configure_wizard
            )
        assert result.url is None
        assert result.state == "pending"
        assert result.provider == "google"

    def test_bind_timeout_shuts_down_wizard(
        self, fake_configure_wizard: MagicMock
    ) -> None:
        captured: list[_FakeWizard] = []

        def _factory(**kwargs: Any) -> _FakeWizard:
            w = _FakeWizard(ready_timeout=True, **kwargs)
            captured.append(w)
            return w

        bridge = OAuthBridge()
        with patch("mureo.cli.web_auth.WebAuthWizard", side_effect=_factory):
            bridge.start(provider="meta", configure_wizard=fake_configure_wizard)
        assert captured[0].shutdown_called is True


@pytest.mark.unit
class TestOAuthBridgeCancel:
    def test_cancel_unknown_provider_is_noop(self) -> None:
        bridge = OAuthBridge()
        bridge.cancel("google")  # must not raise

    def test_cancel_shuts_down_active_wizard(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
    ) -> None:
        bridge = OAuthBridge()
        bridge.start(provider="google", configure_wizard=fake_configure_wizard)
        wizard = patched_wizard_class.instances[0]
        bridge.cancel("google")
        assert wizard.shutdown_called is True

    def test_cancel_all_tears_down_every_provider(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
    ) -> None:
        bridge = OAuthBridge()
        bridge.start(provider="google", configure_wizard=fake_configure_wizard)
        bridge.start(provider="meta", configure_wizard=fake_configure_wizard)
        bridge.cancel_all()
        for wizard in patched_wizard_class.instances:
            assert wizard.shutdown_called is True


@pytest.mark.unit
class TestCredentialsPresentFor:
    def test_none_path_returns_false(self) -> None:
        assert _credentials_present_for("google", None) is False

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        absent = tmp_path / "missing.json"
        assert _credentials_present_for("google", absent) is False

    def test_google_with_refresh_token_returns_true(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"google_ads": {"refresh_token": "RT"}}),
            encoding="utf-8",
        )
        assert _credentials_present_for("google", creds) is True

    def test_google_without_refresh_token_returns_false(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"google_ads": {"developer_token": "DT"}}),
            encoding="utf-8",
        )
        assert _credentials_present_for("google", creds) is False

    def test_meta_with_access_token_returns_true(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"meta_ads": {"access_token": "AT"}}),
            encoding="utf-8",
        )
        assert _credentials_present_for("meta", creds) is True

    def test_meta_without_access_token_returns_false(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"meta_ads": {"app_id": "X"}}),
            encoding="utf-8",
        )
        assert _credentials_present_for("meta", creds) is False

    def test_section_not_a_dict_returns_false(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"google_ads": "not a dict"}),
            encoding="utf-8",
        )
        assert _credentials_present_for("google", creds) is False

    def test_unknown_provider_returns_false(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"twitter": {"access_token": "AT"}}),
            encoding="utf-8",
        )
        assert _credentials_present_for("twitter", creds) is False


@pytest.mark.unit
class TestWatcherCompletion:
    def test_completion_with_credentials_marks_success(
        self, fake_configure_wizard: MagicMock, tmp_path: Path
    ) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"google_ads": {"refresh_token": "RT"}}),
            encoding="utf-8",
        )

        def _factory(**kwargs: Any) -> _FakeWizard:
            w = _FakeWizard(**kwargs)
            w.completed = True
            return w

        bridge = OAuthBridge()
        with patch("mureo.cli.web_auth.WebAuthWizard", side_effect=_factory):
            bridge.start(
                provider="google",
                configure_wizard=fake_configure_wizard,
                credentials_path=creds,
            )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if fake_configure_wizard.mark_oauth_complete.called:
                break
            time.sleep(0.05)
        fake_configure_wizard.mark_oauth_complete.assert_called_once()
        kwargs = fake_configure_wizard.mark_oauth_complete.call_args.kwargs
        assert kwargs["success"] is True
        assert kwargs["error"] is None

    def test_completion_without_credentials_marks_failure(
        self, fake_configure_wizard: MagicMock, tmp_path: Path
    ) -> None:
        creds = tmp_path / "credentials.json"

        def _factory(**kwargs: Any) -> _FakeWizard:
            w = _FakeWizard(**kwargs)
            w.completed = True
            return w

        bridge = OAuthBridge()
        with patch("mureo.cli.web_auth.WebAuthWizard", side_effect=_factory):
            bridge.start(
                provider="meta",
                configure_wizard=fake_configure_wizard,
                credentials_path=creds,
            )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if fake_configure_wizard.mark_oauth_complete.called:
                break
            time.sleep(0.05)
        kwargs = fake_configure_wizard.mark_oauth_complete.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"] == "credentials_not_written"

    def test_watcher_swallows_mark_value_error(
        self, fake_configure_wizard: MagicMock, tmp_path: Path
    ) -> None:
        """If mark_oauth_complete raises ValueError (unknown provider),
        the watcher must not crash."""
        fake_configure_wizard.mark_oauth_complete.side_effect = ValueError("x")

        def _factory(**kwargs: Any) -> _FakeWizard:
            w = _FakeWizard(**kwargs)
            w.completed = True
            return w

        bridge = OAuthBridge()
        with patch("mureo.cli.web_auth.WebAuthWizard", side_effect=_factory):
            bridge.start(
                provider="google",
                configure_wizard=fake_configure_wizard,
                credentials_path=tmp_path / "creds.json",
            )
        time.sleep(0.5)


@pytest.mark.unit
class TestNoRealSubprocessOrSocket:
    def test_start_does_not_call_real_webauth_wizard(
        self, fake_configure_wizard: MagicMock
    ) -> None:
        bridge = OAuthBridge()
        with patch("mureo.cli.web_auth.WebAuthWizard") as mock_cls:
            fake = _FakeWizard()
            mock_cls.return_value = fake
            bridge.start(provider="google", configure_wizard=fake_configure_wizard)
            mock_cls.assert_called_once()
        bridge.cancel_all()


# ---------------------------------------------------------------------------
# #201 — generic plugin authorization-code flow
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPluginCredentialsPresent:
    def test_true_when_target_field_set(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        path.write_text(json.dumps({"yahoo_ads": {"refresh_token": "RT"}}))
        assert _plugin_credentials_present("yahoo_ads", "refresh_token", path) is True

    def test_false_when_target_field_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "creds.json"
        path.write_text(json.dumps({"yahoo_ads": {"client_id": "CID"}}))
        assert _plugin_credentials_present("yahoo_ads", "refresh_token", path) is False

    def test_false_when_file_missing(self, tmp_path: Path) -> None:
        assert (
            _plugin_credentials_present(
                "yahoo_ads", "refresh_token", tmp_path / "nope.json"
            )
            is False
        )


@pytest.mark.unit
class TestStartPluginOAuth:
    def _config(self) -> Any:
        from mureo.core.providers import AccountOAuthConfig

        return AccountOAuthConfig(
            authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
            token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="refresh_token",
            scopes=("scopeA",),
        )

    _CALLBACK_URL = "http://127.0.0.1:8765/oauth/callback"

    def test_threads_body_token_auth_style(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A provider declaring ``token_auth_style='body'`` (Yahoo! JAPAN)
        has it pinned onto the spec so the callback exchange sends the
        client creds in the form body, not an Authorization header."""
        from mureo.core.providers import AccountOAuthConfig

        config = AccountOAuthConfig(
            authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
            token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="refresh_token",
            scopes=("scopeA",),
            token_auth_style="body",
        )
        bridge = OAuthBridge()
        try:
            bridge.start_plugin_oauth(
                provider="yahoo_ads",
                configure_wizard=fake_configure_wizard,
                oauth_config=config,
                client_id="CID",
                client_secret="SECRET",
                callback_url=self._CALLBACK_URL,
                credentials_path=tmp_path / "creds.json",
            )
            spec = patched_wizard_class.instances[0].plugin_oauth
            assert spec.token_auth_style == "body"
        finally:
            bridge.cancel("yahoo_ads")

    def test_builds_external_consent_url_and_pins_spec(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
        tmp_path: Path,
    ) -> None:
        bridge = OAuthBridge()
        try:
            result = bridge.start_plugin_oauth(
                provider="yahoo_ads",
                configure_wizard=fake_configure_wizard,
                oauth_config=self._config(),
                client_id="CID",
                client_secret="SECRET",
                callback_url=self._CALLBACK_URL,
                persist_values={
                    "client_id": "CID",
                    "client_secret": "SECRET",
                    "oauth_callback_url": self._CALLBACK_URL,
                },
                credentials_path=tmp_path / "creds.json",
            )
            assert result.provider == "yahoo_ads"
            assert result.error is None
            # The handed-off URL is the EXTERNAL provider authorize URL,
            # not a mureo wizard form.
            assert result.url is not None
            assert result.url.startswith(
                "https://biz-oauth.yahoo.co.jp/oauth/v1/authorize?"
            )
            assert "client_id=CID" in result.url
            assert "response_type=code" in result.url
            assert "scope=scopeA" in result.url

            wizard = patched_wizard_class.instances[0]
            # #216: the wizard binds the operator-registered port.
            assert wizard.bind_port == 8765
            spec = wizard.plugin_oauth
            assert spec.provider == "yahoo_ads"
            assert spec.target_field == "refresh_token"
            assert spec.token_url == "https://biz-oauth.yahoo.co.jp/oauth/v1/token"
            assert spec.client_id == "CID"
            assert spec.client_secret == "SECRET"
            # #216: redirect_uri is the operator URL VERBATIM (exact match
            # with what was pre-registered), and callback_path is its path.
            assert spec.redirect_uri == self._CALLBACK_URL
            assert spec.callback_path == "/oauth/callback"
            # #217: the operator's form values ride along for atomic save.
            assert spec.persist_values["client_id"] == "CID"
            assert spec.persist_values["oauth_callback_url"] == self._CALLBACK_URL
            # Token-endpoint auth style defaults to Basic (regression).
            assert spec.token_auth_style == "basic"
            assert spec.state  # non-empty CSRF nonce
            # The same state + redirect_uri are echoed into the consent URL.
            assert f"state={spec.state}" in result.url
            assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765" in result.url
        finally:
            bridge.cancel("yahoo_ads")

    def test_invalid_callback_url_returns_error_without_spawning(
        self,
        patched_wizard_class: Any,
        fake_configure_wizard: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A non-loopback / malformed callback URL (#216) is rejected
        before any wizard is spawned — clean error, no socket churn."""
        bridge = OAuthBridge()
        result = bridge.start_plugin_oauth(
            provider="yahoo_ads",
            configure_wizard=fake_configure_wizard,
            oauth_config=self._config(),
            client_id="CID",
            client_secret="SECRET",
            callback_url="http://example.com:8765/oauth/callback",
            credentials_path=tmp_path / "creds.json",
        )
        assert result.url is None
        assert result.error == "callback_url_invalid"
        assert patched_wizard_class.instances == []

    def test_port_unavailable_returns_error(
        self,
        fake_configure_wizard: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If the operator's port is already in use, the wizard reports
        ``bind_error`` and the bridge surfaces ``callback_port_unavailable``
        rather than handing out a dead consent URL (#216)."""

        def _factory(**kwargs: Any) -> _FakeWizard:
            w = _FakeWizard(**kwargs)
            w.bind_error = OSError("address already in use")
            return w

        bridge = OAuthBridge()
        with patch("mureo.cli.web_auth.WebAuthWizard", side_effect=_factory):
            result = bridge.start_plugin_oauth(
                provider="yahoo_ads",
                configure_wizard=fake_configure_wizard,
                oauth_config=self._config(),
                client_id="CID",
                client_secret="SECRET",
                callback_url=self._CALLBACK_URL,
                credentials_path=tmp_path / "creds.json",
            )
        assert result.url is None
        assert result.error == "callback_port_unavailable"
