"""Central factory for ad-platform clients used by every live-client opener.

The MCP handlers, the analytics adapters and change import open their
clients here (#863: it sits below ``mureo.mcp``, so none of them loads the
MCP server to reach it). Google Ads has one opener for all three,
:func:`open_google_ads_client` (#875).

Per-platform auto-detection: if BYOD data is registered for a platform
(``~/.mureo/byod/manifest.json`` lists it), this factory returns a
CSV-backed ``mureo.byod.clients`` instance. Otherwise it delegates to
``mureo.auth.create_*_client`` for live API access.

Openers MUST go through this factory to pick up BYOD mode automatically.
There is no global ``--byod`` flag; the manifest's existence is the switch.
"""

from __future__ import annotations

from typing import Any

from mureo.byod.clients import ByodGoogleAdsClient, ByodMetaAdsClient

# Bound at import: patch ``mureo.client_factory.byod_has``, not
# ``mureo.byod.runtime.byod_has`` (which only callers' own checks read through).
from mureo.byod.runtime import byod_data_dir, byod_has
from mureo.core import credential_source
from mureo.core.account_scope import resolve_customer_id
from mureo.throttle import GOOGLE_ADS_THROTTLE, Throttler

#: One per process: every live Google Ads client — MCP tools, analytics and
#: change import alike — shares this rate limiter (#875). ``Throttler`` holds
#: an ``asyncio.Lock``, so the shared instance is for coroutines on one event
#: loop; :func:`open_google_ads_client` itself never awaits it, so calling the
#: opener from a worker thread is fine.
GOOGLE_ADS_THROTTLER = Throttler(GOOGLE_ADS_THROTTLE)

#: The ``customer_id`` a BYOD client is opened with when none is given.
_BYOD_CUSTOMER_ID = "byod"

_GOOGLE_ADS_NO_CREDENTIALS = "google_ads credentials are not configured"


class NoCredentialsError(RuntimeError):
    """Raised when the platform's credentials are missing.

    Distinct subclass so a caller can catch this case and map it to its own
    result (the MCP tools' no-credentials result, the analytics adapters'
    honest empty result, change import's ``ERROR`` outcome) rather than
    surfacing a noisy error. Subclasses signal other "cannot fetch this
    account, degrade gracefully" conditions (see
    :class:`mureo.analytics.builtin._live_clients.AccountNotAvailableError`)
    and are caught by the same ``except NoCredentialsError``.
    """


class AccountIdRefused(ValueError):  # noqa: N818
    """Raised by the opener when the id is outside the workspace scope or is
    not numeric.

    Distinct from faults in credential loading or client construction, which
    propagate as whatever they raise (a plain ``ValueError`` included).

    The name says the condition, a refusal, not a failure. ``N818`` is
    suppressed locally, the same way
    ``mureo.meta_ads.accounts.MetaTokenInspectUnavailable`` does it.
    """


def get_google_ads_client(
    creds: Any, customer_id: str, throttler: Any | None = None
) -> Any:
    """Return a Google Ads client (real or BYOD)."""
    if byod_has("google_ads"):
        return ByodGoogleAdsClient(
            data_dir=byod_data_dir() / "google_ads", customer_id=customer_id
        )

    # Startup cost (~0.5 s CPU): mureo.auth is deferred to first client build (#809).
    from mureo.auth import (  # noqa: PLC0415 — startup cost (#809)
        create_google_ads_client as _real,
    )

    return _real(creds, customer_id, throttler=throttler)


def open_google_ads_client(customer_id: str | None = None) -> tuple[Any, str]:
    """Return ``(client, resolved_customer_id)`` for the active configuration.

    Precedence: an active credential source → BYOD → the credentials file.
    Raises :class:`NoCredentialsError` when no credentials are configured and
    :class:`AccountIdRefused` when the workspace scope refuses the id or the
    id is not numeric.

    The id is bound to the workspace allow-list (#411/#413) on every path.
    The one exception is BYOD mode with no ``customer_id`` or with
    ``"byod"`` itself (the id the BYOD client's ``list_accounts`` returns):
    there are no credentials to default from, so the BYOD client is opened as
    ``"byod"`` without the scope and numeric checks. Any other id in BYOD
    mode is scoped and checked like a live one. Every live client gets
    :data:`GOOGLE_ADS_THROTTLER`. Synchronous: async callers run it with
    ``asyncio.to_thread`` (SDK import and token refresh, #809/#821).

    Test patch sites: ``mureo.auth.load_google_ads_credentials`` and
    ``mureo.auth.create_google_ads_client`` (looked up at call time),
    ``mureo.client_factory.byod_has`` and
    ``mureo.core.credential_source.current_google_source``.
    """
    google = credential_source.current_google_source()
    if google is None and byod_has("google_ads"):
        resolved = (
            _resolve_google_customer_id(customer_id, None)
            if customer_id and customer_id != _BYOD_CUSTOMER_ID
            else _BYOD_CUSTOMER_ID
        )
        client = get_google_ads_client(
            creds=None, customer_id=resolved, throttler=GOOGLE_ADS_THROTTLER
        )
        return client, resolved
    return _open_live_google_ads_client(google, customer_id)


def _open_live_google_ads_client(
    google: credential_source.GoogleCredentialSource | None,
    customer_id: str | None,
) -> tuple[Any, str]:
    """Load credentials (source or file), scope the id and build a live client.

    ``oauth_credentials`` is passed only when a source supplies one, so the
    no-source call keeps the factory's original (narrower) signature.
    """
    # Startup cost (~0.5 s CPU): mureo.auth is deferred to first client build (#809).
    from mureo.auth import (  # noqa: PLC0415 — startup cost (#809)
        create_google_ads_client,
        load_google_ads_credentials,
    )

    creds = (
        load_google_ads_credentials()
        if google is None
        else credential_source.call_source("google", google.load_credentials)
    )
    if creds is None:
        raise NoCredentialsError(_GOOGLE_ADS_NO_CREDENTIALS)

    # getattr, not attribute access: the default must not be evaluated
    # eagerly against credential objects that lack the field (the old
    # ``or``-chain short-circuited when an explicit id was passed).
    resolved = _resolve_google_customer_id(
        customer_id,
        getattr(creds, "customer_id", None)
        or getattr(creds, "login_customer_id", None),
    )
    kwargs: dict[str, Any] = {"throttler": GOOGLE_ADS_THROTTLER}
    if google is not None:
        oauth = credential_source.call_source("google", google.oauth_credentials, creds)
        if oauth is not None:
            kwargs["oauth_credentials"] = oauth
    return create_google_ads_client(creds, resolved, **kwargs), resolved


def _resolve_google_customer_id(requested: str | None, default: str | None) -> str:
    """Bind the id to the workspace allow-list, then require a numeric id.

    Both refusals raise :class:`AccountIdRefused`.
    """
    try:
        customer_id = resolve_customer_id(requested, default)
    except ValueError as exc:
        raise AccountIdRefused(str(exc)) from exc
    if not str(customer_id).replace("-", "").isdigit():
        raise AccountIdRefused(
            f"Invalid customer_id format: {customer_id} (must be numeric, hyphens allowed)"
        )
    return customer_id


def get_meta_ads_client(
    creds: Any, account_id: str, throttler: Any | None = None
) -> Any:
    """Return a Meta Ads client (real or BYOD)."""
    if byod_has("meta_ads"):
        return ByodMetaAdsClient(
            data_dir=byod_data_dir() / "meta_ads", account_id=account_id
        )

    # Startup cost (~0.5 s CPU): mureo.auth is deferred to first client build (#809).
    from mureo.auth import (  # noqa: PLC0415 — startup cost (#809)
        create_meta_ads_client as _real,
    )

    return _real(creds, account_id, throttler=throttler)
