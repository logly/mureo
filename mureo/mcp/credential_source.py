"""Per-call credential source for the built-in MCP handlers.

A plugin that re-exposes the built-in tool handlers under its own namespace
can supply the credentials for one call instead of letting the handler read
``~/.mureo/credentials.json`` (or the environment). The source is held in a
``contextvars.ContextVar`` so it is scoped to the current task; nothing
changes for callers that never set it. The context is copied into
``asyncio.to_thread`` calls and into tasks created inside the block, but NOT
into a plain ``threading.Thread`` or a ``loop.run_in_executor`` call: work
started that way does not see the source.

Usage::

    with use_credential_source(CredentialSource(google=my_google_source)):
        result = await tools_google_ads.handle_tool(name, arguments)

Semantics:

- **No credentials.** ``load_credentials()`` returning ``None`` means "no
  credentials": the handler returns its usual credentials-not-found result.
  It never falls back to the credentials file in that case.
- **Google OAuth.** ``oauth_credentials(creds)`` returns the ``google.auth``
  credentials object the client should use (any
  ``google.auth.credentials.Credentials``; the token URI, refresh behaviour
  and scopes are the source's business). The handler still resolves
  ``customer_id`` / ``login_customer_id`` and the workspace allow-list from
  ``creds`` and the tool arguments exactly as it does without a source.
- **Placeholders.** :class:`~mureo.auth.GoogleAdsCredentials` requires
  ``client_id``, ``client_secret`` and ``refresh_token``. A source that does
  not hold them may fill placeholders: while a source is active the handlers
  only read ``customer_id``, ``login_customer_id`` and ``developer_token``
  from it.
- **Precedence.** An active source wins over BYOD mode (an explicit per-call
  choice beats the ambient manifest) and over the credentials file. A source
  that leaves a platform at ``None`` leaves that platform's handlers exactly
  as they are without a source. ``google`` serves both Google Ads and Search
  Console, which share one OAuth identity.
- **Meta token lifecycle.** While ``meta_ads`` is set the handler does not
  call ``refresh_meta_token_if_needed``: the source owns the token lifecycle.
- **Threading.** ``load_credentials()`` and ``oauth_credentials()`` may be
  called on the event-loop thread or on a worker thread
  (``asyncio.to_thread``), depending on the path. Implementations must be
  thread-safe, must not depend on a running event loop, and should return
  quickly (cache what they resolve). ``oauth_credentials()`` may block, for
  example to refresh a token; the handlers that run on the loop call it off
  the loop.

This module is the supported surface. The ``mureo.mcp._handlers_*`` modules
remain private.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator

    import google.auth.credentials

    from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials


class GoogleCredentialSource(Protocol):
    """Supplies the Google credentials (Google Ads and Search Console)."""

    def load_credentials(self) -> GoogleAdsCredentials | None:
        """Return the credentials for this call, or ``None`` for none.

        May run on the event-loop thread or a worker thread: must be
        thread-safe, must not need a running loop, and should return quickly.
        """
        ...

    def oauth_credentials(
        self, credentials: GoogleAdsCredentials
    ) -> google.auth.credentials.Credentials:
        """Return the ``google.auth`` credentials the client should use.

        Must be thread-safe and must not need a running loop. May block (for
        example to refresh a token): the handlers that run on the event loop
        call it off the loop.
        """
        ...


class MetaCredentialSource(Protocol):
    """Supplies the Meta Ads credentials."""

    def load_credentials(self) -> MetaAdsCredentials | None:
        """Return the credentials for this call, or ``None`` for none.

        May run on the event-loop thread or a worker thread: must be
        thread-safe, must not need a running loop, and should return quickly.
        """
        ...


@dataclass(frozen=True)
class CredentialSource:
    """The per-platform sources in effect for the enclosed calls.

    ``google`` serves Google Ads and Search Console, which share one OAuth
    identity. A platform left at ``None`` keeps its usual resolution.
    """

    google: GoogleCredentialSource | None = None
    meta_ads: MetaCredentialSource | None = None


_CURRENT_SOURCE: ContextVar[CredentialSource | None] = ContextVar(
    "mureo_credential_source", default=None
)


def current_credential_source() -> CredentialSource | None:
    """Return the source in effect for this context, or ``None``."""
    return _CURRENT_SOURCE.get()


def current_google_source() -> GoogleCredentialSource | None:
    """Return the active source's ``google`` entry, or ``None``."""
    source = _CURRENT_SOURCE.get()
    return source.google if source is not None else None


def current_meta_source() -> MetaCredentialSource | None:
    """Return the active source's ``meta_ads`` entry, or ``None``."""
    source = _CURRENT_SOURCE.get()
    return source.meta_ads if source is not None else None


def _require_methods(entry: object, field: str, methods: tuple[str, ...]) -> None:
    """Raise ``TypeError`` unless ``entry`` has every method in ``methods``.

    A class passed where an instance belongs is refused too: its methods
    would be unbound and fail on the first call, far from the mistake.
    """
    if isinstance(entry, type):
        raise TypeError(
            f"CredentialSource.{field} must be an instance, "
            f"got the class {entry.__name__}"
        )
    missing = [name for name in methods if not callable(getattr(entry, name, None))]
    if missing:
        raise TypeError(
            f"CredentialSource.{field} must have callable "
            f"{', '.join(missing)}; got {type(entry).__name__}"
        )


def _validate(source: CredentialSource) -> None:
    """Check the source's shape before it can reach a handler."""
    if source.google is not None:
        _require_methods(
            source.google, "google", ("load_credentials", "oauth_credentials")
        )
    if source.meta_ads is not None:
        _require_methods(source.meta_ads, "meta_ads", ("load_credentials",))


@contextmanager
def use_credential_source(source: CredentialSource) -> Iterator[None]:
    """Make ``source`` the credential source for the enclosed calls.

    Always resets on the way out, even on error. Raises ``TypeError`` before
    anything is set when ``source`` is not a :class:`CredentialSource`, or
    when an entry is a class or lacks a method its Protocol requires.
    """
    if not isinstance(source, CredentialSource):
        raise TypeError(
            "use_credential_source expects a CredentialSource, "
            f"got {type(source).__name__}"
        )
    _validate(source)
    token = _CURRENT_SOURCE.set(source)
    try:
        yield
    finally:
        _CURRENT_SOURCE.reset(token)


__all__ = [
    "CredentialSource",
    "GoogleCredentialSource",
    "MetaCredentialSource",
    "current_credential_source",
    "current_google_source",
    "current_meta_source",
    "use_credential_source",
]
