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

A task created inside the block (``asyncio.create_task``) copies the context
when it is created, so it keeps the source after the block exits.

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
  as they are without a source: they read the host's own credentials file,
  environment or BYOD manifest. ``google`` serves both Google Ads and Search
  Console, which share one OAuth identity.
- **Strict.** ``CredentialSource(..., strict=True)`` fails closed instead:
  a handler for a platform the source leaves at ``None`` raises
  :class:`CredentialSourceError` naming the platform and never reads the
  host's credentials or BYOD data.
- **Nesting.** A nested :func:`use_credential_source` *replaces* the outer
  source for the inner block; entries are not merged. Pass
  ``outer.merged_with(inner)`` to keep the outer entries.
- **Errors.** Every call into a source goes through :func:`call_source`: an
  exception raised by ``load_credentials()`` or ``oauth_credentials()``
  reaches the MCP client only as ``CredentialSourceError("credential source
  failed for <platform> (<ExceptionClass>)")``, and only the class name is
  logged. Sources should still keep secrets out of their exception text:
  a host may log or report the exception elsewhere.
- **Meta token lifecycle.** While ``meta_ads`` is set the handler does not
  call ``refresh_meta_token_if_needed``: the source owns the token lifecycle.
- **Threading.** ``load_credentials()`` and ``oauth_credentials()`` may be
  called on the event-loop thread or on a worker thread
  (``asyncio.to_thread``), depending on the path. Implementations must be
  thread-safe, must not depend on a running event loop, and should return
  quickly (cache what they resolve). ``oauth_credentials()`` may block, for
  example to refresh a token; the handlers that run on the loop call it off
  the loop.

:class:`CredentialSource` names each platform as its own field on purpose.
It is deliberately explicit; a mapping keyed by platform id was considered and
rejected so the type checker sees each platform. Adding a platform adds a
field.

This module is the supported surface. The ``mureo.mcp._handlers_*`` modules
remain private.
"""

from __future__ import annotations

import dataclasses
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import google.auth.credentials

    from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: The ``CredentialSource`` field of each platform, in field order.
_PLATFORMS = ("google", "meta_ads")


class CredentialSourceError(RuntimeError):
    """A credential source failed, or does not cover a platform it must.

    The message names the platform and, for a failing source, the exception
    class only: it never carries the source's own exception text.
    """


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


@dataclasses.dataclass(frozen=True)
class CredentialSource:
    """The per-platform sources in effect for the enclosed calls.

    ``google`` serves Google Ads and Search Console, which share one OAuth
    identity. A platform left at ``None`` keeps its usual resolution, unless
    ``strict`` is true: then a handler for that platform raises
    :class:`CredentialSourceError` instead of reading the host's credentials.
    """

    google: GoogleCredentialSource | None = None
    meta_ads: MetaCredentialSource | None = None
    strict: bool = dataclasses.field(default=False, kw_only=True)

    def merged_with(self, other: CredentialSource) -> CredentialSource:
        """Return a source with ``other``'s entries over this one's.

        A platform ``other`` leaves at ``None`` keeps this source's entry;
        the result is strict when either side is.
        """
        if not isinstance(other, CredentialSource):
            raise TypeError(f"expected a CredentialSource, got {type(other).__name__}")
        return CredentialSource(
            google=other.google if other.google is not None else self.google,
            meta_ads=other.meta_ads if other.meta_ads is not None else self.meta_ads,
            strict=self.strict or other.strict,
        )


_CURRENT_SOURCE: ContextVar[CredentialSource | None] = ContextVar(
    "mureo_credential_source", default=None
)


def current_credential_source() -> CredentialSource | None:
    """Return the source in effect for this context, or ``None``."""
    return _CURRENT_SOURCE.get()


def _refuse_uncovered(platform: str) -> None:
    """Fail closed for a platform a strict source leaves at ``None``."""
    raise CredentialSourceError(
        f"the active credential source is strict and has no {platform} entry; "
        "refusing to fall back to the host's own credentials"
    )


def current_google_source() -> GoogleCredentialSource | None:
    """Return the active source's ``google`` entry, or ``None``.

    Raises :class:`CredentialSourceError` when the active source is strict
    and has no ``google`` entry.
    """
    source = _CURRENT_SOURCE.get()
    if source is None:
        return None
    if source.google is None and source.strict:
        _refuse_uncovered("google")
    return source.google


def current_meta_source() -> MetaCredentialSource | None:
    """Return the active source's ``meta_ads`` entry, or ``None``.

    Raises :class:`CredentialSourceError` when the active source is strict
    and has no ``meta_ads`` entry.
    """
    source = _CURRENT_SOURCE.get()
    if source is None:
        return None
    if source.meta_ads is None and source.strict:
        _refuse_uncovered("meta_ads")
    return source.meta_ads


def active_source_identity(platform: str) -> int | None:
    """Return ``id()`` of the active source's entry for ``platform``.

    ``None`` when no source is active or it leaves ``platform`` at ``None``.
    Lets a process-wide cache keep what one source resolved apart from what
    another (or the host's own credentials) resolved. Never raises for a
    strict source; raises ``ValueError`` for an unknown platform.
    """
    if platform not in _PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}; expected one of {_PLATFORMS}")
    source = _CURRENT_SOURCE.get()
    entry = getattr(source, platform) if source is not None else None
    return id(entry) if entry is not None else None


def call_source(platform: str, method: Callable[..., _T], *args: Any) -> _T:
    """Call ``method(*args)`` on a source, curating any exception it raises.

    The source's exception text may carry a token, so it is neither logged
    nor returned: only its class name is, inside a
    :class:`CredentialSourceError`. The original stays reachable as
    ``__context__`` (so an auth failure is still classified as one) but is
    suppressed from tracebacks.
    """
    try:
        return method(*args)
    except Exception as exc:  # noqa: BLE001 — any source failure is curated
        name = type(exc).__name__
        logger.warning("credential source failed for %s (%s)", platform, name)
        raise CredentialSourceError(
            f"credential source failed for {platform} ({name})"
        ) from None


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
    if not isinstance(source.strict, bool):
        raise TypeError(
            "CredentialSource.strict must be a bool, "
            f"got {type(source.strict).__name__}"
        )
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
    anything is set when ``source`` is not a :class:`CredentialSource`, when
    an entry is a class or lacks a method its Protocol requires, or when
    ``strict`` is not a bool. A nested call replaces the outer source for the
    inner block (use :meth:`CredentialSource.merged_with` to combine them).
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
    "CredentialSourceError",
    "GoogleCredentialSource",
    "MetaCredentialSource",
    "active_source_identity",
    "call_source",
    "current_credential_source",
    "current_google_source",
    "current_meta_source",
    "use_credential_source",
]
