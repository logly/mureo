"""Spawn ``WebAuthWizard`` instances on behalf of the configure UI."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mureo.web._helpers import read_json_safe

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.cli.web_auth import WebAuthWizard

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
    """JSON-friendly payload returned by ``OAuthBridge.start``."""

    url: str | None
    state: str = "pending"
    provider: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "redirect_url": self.url,
            "state": self.state,
            "provider": self.provider,
        }


@dataclass
class _ActiveHandoff:
    """Per-provider bookkeeping for one in-flight WebAuthWizard."""

    wizard: WebAuthWizard
    thread: threading.Thread
    watcher: threading.Thread
    started_at: float = field(default_factory=time.monotonic)


def _credentials_present_for(
    provider: str, credentials_path: Path | None
) -> bool:
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
    ) -> OAuthHandoffResult:
        """Spawn a wizard for ``provider`` and return the consent URL."""
        if provider not in _PROVIDER_TO_PATH:
            raise ValueError(f"unknown provider: {provider!r}")

        self.cancel(provider)

        from mureo.cli.web_auth import WebAuthWizard

        wizard = WebAuthWizard(credentials_path=credentials_path)
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
        consent_url = wizard.home_url() + path

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
        return OAuthHandoffResult(
            url=consent_url, state="pending", provider=provider
        )

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
    ) -> None:
        """Poll wizard.completed and surface the result to the configure UI."""
        deadline = time.monotonic() + _HANDOFF_DEADLINE_SECONDS
        success: bool = False
        error: str | None = None
        try:
            while time.monotonic() < deadline:
                if wizard.completed:
                    success = _credentials_present_for(provider, credentials_path)
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
