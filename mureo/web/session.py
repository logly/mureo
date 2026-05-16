"""In-memory session state for the configure UI.

The configure UI is single-user — only one browser tab drives it at a
time. The session holds the per-run CSRF token, the operator's locale,
the current OAuth-bridge progress flags, and the chosen Claude
application host. Nothing is persisted to disk by the session itself.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from mureo.web._helpers import fresh_csrf_token

# Allow-list of provider slugs the OAuth bridge can drive.
OAUTH_PROVIDERS: tuple[str, ...] = ("google", "meta")

# Allow-list of supported host slugs.
SUPPORTED_HOSTS: tuple[str, ...] = ("claude-code", "claude-desktop")


@dataclass
class OAuthState:
    """Per-provider OAuth completion flags."""

    pending: bool = False
    success: bool = False
    error: str | None = None


@dataclass
class ConfigureSession:
    """Mutable per-run state for the configure UI."""

    csrf_token: str = field(default_factory=fresh_csrf_token)
    locale: str = "en"
    host: str = "claude-code"
    oauth_status: dict[str, OAuthState] = field(
        default_factory=lambda: {p: OAuthState() for p in OAUTH_PROVIDERS}
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_locale(self, locale: str) -> None:
        """Accept ``en`` or ``ja``; ignore other values."""
        if locale in {"en", "ja"}:
            self.locale = locale

    def set_host(self, host: str) -> None:
        """Set the Claude application host. Allow-list only."""
        if host in SUPPORTED_HOSTS:
            self.host = host

    def mark_oauth_pending(self, provider: str) -> None:
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        with self._lock:
            self.oauth_status[provider] = OAuthState(
                pending=True, success=False, error=None
            )

    def mark_oauth_complete(
        self, provider: str, *, success: bool, error: str | None = None
    ) -> None:
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        with self._lock:
            self.oauth_status[provider] = OAuthState(
                pending=False, success=success, error=error
            )

    def get_oauth_status(self, provider: str) -> dict[str, Any]:
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        with self._lock:
            state = self.oauth_status[provider]
            return {
                "pending": state.pending,
                "success": state.success,
                "error": state.error,
            }

    def get_oauth_status_all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                provider: {
                    "pending": state.pending,
                    "success": state.success,
                    "error": state.error,
                }
                for provider, state in self.oauth_status.items()
            }
