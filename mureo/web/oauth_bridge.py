"""Spawn ``WebAuthWizard`` instances on behalf of the configure UI."""

from __future__ import annotations

import contextlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mureo.oauth_authcode import (
    build_authorization_code_url,
    parse_loopback_callback_url,
)
from mureo.web._helpers import read_json_safe

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mureo.cli.web_auth import WebAuthWizard
    from mureo.core.providers import AccountOAuthConfig

logger = logging.getLogger(__name__)

# Slug → inner wizard's per-platform form path.
_PROVIDER_TO_PATH: dict[str, str] = {
    "google": "google-ads",
    "meta": "meta-ads",
}

# Hard deadline for a single OAuth handoff. Matches the CLI's 600s
# fallback in ``run_web_wizard``.
_HANDOFF_DEADLINE_SECONDS = 600.0
_POLL_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True)
class OAuthHandoffResult:
    """JSON-friendly payload returned by ``OAuthBridge.start``.

    ``error`` carries a stable machine code for a pre-consent failure
    (#216) — ``callback_url_invalid`` / ``callback_port_unavailable`` /
    ``bind_timeout`` — so the dashboard can toast the specific reason
    instead of a generic failure. ``None`` on the happy path.
    """

    url: str | None
    state: str = "pending"
    provider: str = ""
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "redirect_url": self.url,
            "state": self.state,
            "provider": self.provider,
            "error": self.error,
        }


@dataclass
class _ActiveHandoff:
    """Per-provider bookkeeping for one in-flight WebAuthWizard."""

    wizard: WebAuthWizard
    thread: threading.Thread
    watcher: threading.Thread
    started_at: float = field(default_factory=time.monotonic)


def _credentials_present_for(provider: str, credentials_path: Path | None) -> bool:
    """Inspect credentials.json for the OAuth-success marker fields."""
    if credentials_path is None or not credentials_path.exists():
        return False
    payload = read_json_safe(credentials_path)
    if provider == "google":
        section = payload.get("google_ads")
        if not isinstance(section, dict):
            return False
        return bool(section.get("refresh_token"))
    if provider == "meta":
        section = payload.get("meta_ads")
        if not isinstance(section, dict):
            return False
        return bool(section.get("access_token"))
    return False


def _plugin_credentials_present(
    provider: str, target_field: str, credentials_path: Path | None
) -> bool:
    """Success marker for a generic plugin OAuth flow (#201).

    The wizard merge-saves the obtained ``refresh_token`` under the
    provider's registry name (the ``credentials.json`` section key); the
    flow succeeded once that section carries a truthy ``target_field``.
    """
    if credentials_path is None or not credentials_path.exists():
        return False
    payload = read_json_safe(credentials_path)
    section = payload.get(provider)
    if not isinstance(section, dict):
        return False
    return bool(section.get(target_field))


class OAuthBridge:
    """Lifecycle manager for spawned ``WebAuthWizard`` instances."""

    def __init__(self) -> None:
        self._active: dict[str, _ActiveHandoff] = {}
        self._lock = threading.Lock()

    def start(
        self,
        *,
        provider: str,
        configure_wizard: Any,
        credentials_path: Path | None = None,
        locale: str = "en",
        multi_account_auth: bool = False,
    ) -> OAuthHandoffResult:
        """Spawn a wizard for ``provider`` and return the consent URL.

        ``locale`` is passed through to the spawned ``WebAuthWizard``'s
        per-platform form via a ``?locale=`` query string so the legacy
        wizard (English-only HTML) can switch its inline strings to
        Japanese when the operator picked JA in the configure UI.

        ``multi_account_auth`` is threaded through to the spawned
        ``WebAuthWizard`` so a multi-account backend persists only the
        operator-shared credentials and skips the per-account picker
        (#198). The caller (``ConfigureHandler``) resolves it from the
        active ``RuntimeContext`` behind a ``home is None`` gate, so this
        bridge stays oblivious to process globals and defaults to the
        standalone single-account behavior.
        """
        if provider not in _PROVIDER_TO_PATH:
            raise ValueError(f"unknown provider: {provider!r}")

        self.cancel(provider)

        from mureo.cli.web_auth import WebAuthWizard

        wizard = WebAuthWizard(
            credentials_path=credentials_path,
            multi_account_auth=multi_account_auth,
        )
        thread = threading.Thread(target=wizard.serve, daemon=True)
        thread.start()
        try:
            wizard.wait_until_ready(timeout=5.0)
        except TimeoutError:
            with contextlib.suppress(Exception):
                wizard.shutdown()
            logger.warning("OAuth bridge bind timed out for %s", provider)
            return OAuthHandoffResult(url=None, state="pending", provider=provider)

        path = _PROVIDER_TO_PATH[provider]
        # Allow-list locales to keep the spawned URL injection-free.
        safe_locale = locale if locale in {"en", "ja"} else "en"
        consent_url = wizard.home_url() + path + f"?locale={safe_locale}"

        watcher = threading.Thread(
            target=self._watch_handoff,
            args=(provider, wizard, configure_wizard, credentials_path),
            daemon=True,
            name=f"oauth-bridge-watch-{provider}",
        )
        with self._lock:
            self._active[provider] = _ActiveHandoff(
                wizard=wizard, thread=thread, watcher=watcher
            )
        watcher.start()
        return OAuthHandoffResult(url=consent_url, state="pending", provider=provider)

    def start_plugin_oauth(
        self,
        *,
        provider: str,
        configure_wizard: Any,
        oauth_config: AccountOAuthConfig,
        client_id: str,
        client_secret: str,
        callback_url: str,
        persist_values: dict[str, str] | None = None,
        credentials_path: Path | None = None,
    ) -> OAuthHandoffResult:
        """Run a generic plugin authorization-code flow (#201/#216/#217).

        Unlike :meth:`start` (which hands the browser a mureo wizard form
        that then redirects to Google/Meta), this builds the **external**
        provider authorize URL directly and the spawned wizard only serves
        the operator-supplied callback route.

        ``callback_url`` is the loopback URL the operator pre-registered in
        the provider's developer console (#216). Most providers require the
        ``redirect_uri`` to match a registered value **exactly**, so a
        fresh ephemeral port every run can never be registered — instead
        the wizard binds *that* URL's port and the URL is sent verbatim as
        the ``redirect_uri``. Validation is loopback-only.

        ``persist_values`` (#217) are the operator's submitted form values
        (client id/secret, callback URL, any non-OAuth field); the callback
        writes them atomically with the obtained token in one section, so
        first-time setup needs no prior Save.

        ``provider`` is the registry name, used both as the bridge's
        bookkeeping key and as the ``credentials.json`` section the
        obtained ``refresh_token`` lands in.
        """
        self.cancel(provider)

        # Validate the operator URL BEFORE spawning anything — a bad URL is
        # a clean error, not socket churn (#216).
        try:
            _host, port, callback_path = parse_loopback_callback_url(callback_url)
        except ValueError:
            logger.warning("Plugin OAuth callback URL invalid for %s", provider)
            return OAuthHandoffResult(
                url=None,
                state="pending",
                provider=provider,
                error="callback_url_invalid",
            )

        from mureo.cli.web_auth import PluginOAuthSpec, WebAuthWizard

        wizard = WebAuthWizard(credentials_path=credentials_path, bind_port=port)
        thread = threading.Thread(target=wizard.serve, daemon=True)
        thread.start()
        try:
            wizard.wait_until_ready(timeout=5.0)
        except TimeoutError:
            with contextlib.suppress(Exception):
                wizard.shutdown()
            logger.warning("Plugin OAuth bridge bind timed out for %s", provider)
            return OAuthHandoffResult(
                url=None, state="pending", provider=provider, error="bind_timeout"
            )

        if wizard.bind_error is not None:
            # The operator's registered port is already in use — surface a
            # clean code so the dashboard can tell them to free it (#216).
            with contextlib.suppress(Exception):
                wizard.shutdown()
            logger.warning(
                "Plugin OAuth callback port %s unavailable for %s", port, provider
            )
            return OAuthHandoffResult(
                url=None,
                state="pending",
                provider=provider,
                error="callback_port_unavailable",
            )

        # redirect_uri is the operator URL VERBATIM (exact match with what
        # was pre-registered); callback_path tells the wizard which route
        # to serve. The callback cannot fire until the operator visits the
        # consent URL below, so pinning the spec now is race-free.
        redirect_uri = callback_url
        state = secrets.token_urlsafe(32)
        wizard.plugin_oauth = PluginOAuthSpec(
            provider=provider,
            target_field=oauth_config.target_field,
            token_url=oauth_config.token_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            state=state,
            callback_path=callback_path,
            persist_values=dict(persist_values or {}),
            token_auth_style=oauth_config.token_auth_style,
        )
        consent_url = build_authorization_code_url(
            authorize_url=oauth_config.authorize_url,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=oauth_config.scopes,
            state=state,
        )

        target_field = oauth_config.target_field
        watcher = threading.Thread(
            target=self._watch_handoff,
            args=(provider, wizard, configure_wizard, credentials_path),
            kwargs={
                "credentials_check": lambda: _plugin_credentials_present(
                    provider, target_field, credentials_path
                )
            },
            daemon=True,
            name=f"oauth-bridge-watch-{provider}",
        )
        with self._lock:
            self._active[provider] = _ActiveHandoff(
                wizard=wizard, thread=thread, watcher=watcher
            )
        watcher.start()
        return OAuthHandoffResult(url=consent_url, state="pending", provider=provider)

    def cancel(self, provider: str) -> None:
        """Tear down any in-flight wizard for ``provider``."""
        with self._lock:
            existing = self._active.pop(provider, None)
        if existing is None:
            return
        with contextlib.suppress(Exception):
            existing.wizard.shutdown()

    def cancel_all(self) -> None:
        """Tear down every active wizard."""
        with self._lock:
            providers = list(self._active.keys())
        for provider in providers:
            self.cancel(provider)

    def _watch_handoff(
        self,
        provider: str,
        wizard: WebAuthWizard,
        configure_wizard: Any,
        credentials_path: Path | None,
        credentials_check: Callable[[], bool] | None = None,
    ) -> None:
        """Poll wizard.completed and surface the result to the configure UI.

        ``credentials_check`` overrides how success is detected once the
        wizard reports completion. The built-in Google/Meta flows leave it
        ``None`` and fall back to :func:`_credentials_present_for` (which
        knows the ``google_ads`` / ``meta_ads`` success markers); the
        generic plugin flow (#201) passes a closure that checks the
        provider's own ``target_field`` instead.
        """
        deadline = time.monotonic() + _HANDOFF_DEADLINE_SECONDS
        success: bool = False
        error: str | None = None
        try:
            while time.monotonic() < deadline:
                if wizard.completed:
                    success = (
                        credentials_check()
                        if credentials_check is not None
                        else _credentials_present_for(provider, credentials_path)
                    )
                    if not success:
                        error = "credentials_not_written"
                    break
                time.sleep(_POLL_INTERVAL_SECONDS)
            else:
                error = "deadline_exceeded"
        finally:
            with contextlib.suppress(Exception):
                wizard.shutdown()
            with self._lock:
                self._active.pop(provider, None)
            mark = getattr(configure_wizard, "mark_oauth_complete", None)
            if callable(mark):
                with contextlib.suppress(ValueError):
                    mark(provider, success=success, error=error)
