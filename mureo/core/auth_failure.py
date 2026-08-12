"""Auth failure as a first-class outcome, on every platform (#580).

A platform whose credentials are missing, or whose token has expired, used
to answer a read with an ordinary *successful* MCP result whose text
happened to be a sentence about credentials — ``"Credentials not found. Set
environment variable ..."`` or ``"API error: Meta API request failed
(status=400, ...)"``. Nothing downstream could tell that apart from any
other error, let alone from real data, so a report skill folded the prose in
next to real figures and shipped a report that looked complete. "Could not
read" and "nothing to read" must never look alike.

This module holds the one vocabulary that makes them different:

- :data:`AUTH_ERROR_STATUS` — the ``status`` value stamped on the payload.
  It reuses the ``status``-field convention the rest of mureo already uses
  for exactly this "what did I fail to see" question (``blind_spots`` /
  ``ChangeImportStatus`` in the change-import feed, ``no_credentials`` /
  ``data_unavailable`` on :class:`~mureo.analytics.models.DeliveryCollapseReport`)
  rather than inventing a second convention a skill would have to learn.
- :data:`AUTH_CAUSE_NO_CREDENTIALS` / :data:`AUTH_CAUSE_TOKEN_INVALID` — the
  two causes, because they have different recovery actions: one was never
  configured, the other was configured and rejected.

It lives in ``mureo.core`` and not next to the MCP handlers because the
platform clients raise :class:`PlatformAuthError` and the MCP layer renders
it; a client importing from ``mureo.mcp`` would invert the layering.
"""

from __future__ import annotations

from typing import Any

#: ``status`` value every auth-failure payload carries, whatever the
#: platform. This is the marker a skill keys on: one string, one meaning —
#: mureo could not read this platform at all, so it has no numbers for this
#: run and its silence is not evidence of anything.
AUTH_ERROR_STATUS = "auth_error"

#: No credential is configured for the platform at all.
AUTH_CAUSE_NO_CREDENTIALS = "no_credentials"

#: A credential exists and the platform rejected it — an expired or revoked
#: token, a withdrawn permission. Distinct from the above because the
#: recovery differs: configure vs. re-authorize.
AUTH_CAUSE_TOKEN_INVALID = "token_invalid"

#: The closed vocabulary. A cause outside it would reach a skill that has no
#: branch for it, which is the failure this module exists to end.
AUTH_CAUSES = frozenset({AUTH_CAUSE_NO_CREDENTIALS, AUTH_CAUSE_TOKEN_INVALID})

#: HTTP statuses that mean "the credential was rejected" rather than "the
#: request was wrong". Deliberately narrow: labelling a 400/429/500 as an
#: auth failure would send an operator to re-authorize a healthy account and
#: would withhold a report section for no reason.
_AUTH_HTTP_STATUSES = frozenset({401, 403})

#: The Google Ads ``error_code`` oneof names that mean the credential, not
#: the request, was refused.
_GOOGLE_ADS_AUTH_ONEOFS = frozenset({"authentication_error", "authorization_error"})

#: How far up the ``__cause__`` / ``__context__`` chain to look. Clients
#: re-raise as ``RuntimeError(...) from exc``, so the auth signal is usually
#: one or two links down; the bound stops a self-referential chain.
_MAX_CHAIN_DEPTH = 5


class PlatformAuthError(RuntimeError):
    """A platform refused mureo's credential.

    Raised at the point where a client can actually tell an auth failure
    from a bad request — which is platform-specific knowledge (Meta answers
    an expired token with HTTP 400 and an ``OAuthException`` body, not a
    401), so it belongs in the client rather than in a downstream sniffer.
    """

    def __init__(self, message: str, *, cause: str = AUTH_CAUSE_TOKEN_INVALID) -> None:
        super().__init__(message)
        self.cause = cause if cause in AUTH_CAUSES else AUTH_CAUSE_TOKEN_INVALID


def auth_failure_payload(cause: str, detail: str) -> dict[str, Any]:
    """Build the one payload shape every platform's auth failure carries.

    ``detail`` keeps the operator-facing sentence (which env var to set,
    what the platform said) so nothing readable is lost — but it is a
    *field*, never the whole answer, so no reader can mistake it for data.
    """
    if cause not in AUTH_CAUSES:
        raise ValueError(
            f"Unknown auth cause {cause!r}; expected one of {sorted(AUTH_CAUSES)}"
        )
    return {"status": AUTH_ERROR_STATUS, "auth_cause": cause, "detail": detail}


def is_auth_failure_payload(payload: object) -> bool:
    """True if ``payload`` is an auth-failure payload."""
    return isinstance(payload, dict) and payload.get("status") == AUTH_ERROR_STATUS


def _http_status(exc: BaseException) -> int | None:
    """The HTTP status an ``httpx.HTTPStatusError``-shaped exception carries.

    Duck-typed rather than imported so this module stays free of every
    client's dependency; the attribute path is the same for httpx and for
    the SDK wrappers that mimic it.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _is_google_ads_auth_failure(exc: BaseException) -> bool:
    """True for a ``GoogleAdsException`` whose failure is an auth failure.

    The ``error_code`` field is a protobuf oneof, so an unset member still
    reads back as its zero enum value — ``WhichOneof`` is the only reliable
    way to ask which error kind was actually set.
    """
    errors = getattr(getattr(exc, "failure", None), "errors", None) or ()
    for error in errors:
        which = getattr(getattr(error, "error_code", None), "WhichOneof", None)
        if which is None:
            continue
        try:
            name = which("error_code")
        except Exception:  # noqa: BLE001 - classification must never itself raise
            continue
        if name in _GOOGLE_ADS_AUTH_ONEOFS:
            return True
    return False


def classify_auth_exception(exc: BaseException | None) -> str | None:
    """Return the auth cause behind ``exc``, or ``None`` if it is not one.

    ``None`` is the safe answer: an unclassified failure stays an ordinary
    API error, which is what it was before this existed. Over-claiming is
    the expensive direction — it would withhold a report section and send
    the operator to fix credentials that are fine.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    for _ in range(_MAX_CHAIN_DEPTH):
        if current is None or id(current) in seen:
            return None
        seen.add(id(current))
        if isinstance(current, PlatformAuthError):
            return current.cause
        if _http_status(current) in _AUTH_HTTP_STATUSES:
            return AUTH_CAUSE_TOKEN_INVALID
        if _is_google_ads_auth_failure(current):
            return AUTH_CAUSE_TOKEN_INVALID
        current = current.__cause__ or current.__context__
    return None


__all__ = [
    "AUTH_CAUSES",
    "AUTH_CAUSE_NO_CREDENTIALS",
    "AUTH_CAUSE_TOKEN_INVALID",
    "AUTH_ERROR_STATUS",
    "PlatformAuthError",
    "auth_failure_payload",
    "classify_auth_exception",
    "is_auth_failure_payload",
]
