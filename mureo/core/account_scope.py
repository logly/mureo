"""Workspace account scoping (#411): bind the effective account id to the
active client's allow-list.

A tenant-scoped run refuses an account outside its configured set
(fail-closed); a run that is not tenant-scoped passes the id through. Every
platform client opener — the MCP handlers, analytics and change import —
calls these before building a client.
"""

from __future__ import annotations

from mureo.core.runtime_context import (
    runtime_google_ads_customer_ids,
    runtime_meta_account_ids,
)


def normalize_customer_id(value: str) -> str:
    """Strip hyphens so membership checks are format-insensitive."""
    return value.replace("-", "")


def resolve_customer_id(requested: str | None, default: str | None) -> str:
    """Resolve and workspace-enforce the Google Ads ``customer_id`` (#411).

    Every Google Ads tool funnels through ``_get_client``, which takes
    ``customer_id`` as a free caller argument while the (possibly shared)
    OAuth client (plus the optional legacy developer token) can reach
    every managed account. This binds the EFFECTIVE id — explicit
    argument or credentials default alike — to the active client's
    allow-list, mirroring Search Console's ``site_url`` enforcement
    (#375):

    - **Not tenant-scoped** (:func:`runtime_google_ads_customer_ids` →
      ``None``): unchanged — argument wins, credentials default
      (``customer_id`` then ``login_customer_id``) second, missing both is
      an error.
    - **Tenant-scoped**: an out-of-set value is refused (fail-closed,
      hyphen-insensitive). No usable value — including a credentials
      default that is not in the set, the common case when only the
      operator's MCC ``login_customer_id`` is present — resolves to the
      single configured account, or is refused when several are configured
      (ambiguous) or none are (fail-fast).
    """
    allowed = runtime_google_ads_customer_ids()
    if allowed is None:
        customer_id = requested or default
        if not customer_id:
            raise ValueError(
                "customer_id is required. Provide it as a parameter or "
                "configure it in ~/.mureo/credentials.json via mureo auth "
                "setup."
            )
        return str(customer_id)
    if not allowed:
        raise ValueError(
            "Google Ads is not configured for this client. Configure the "
            "client's account before querying it."
        )
    normalized_allowed = {normalize_customer_id(entry) for entry in allowed}
    if requested:
        if normalize_customer_id(str(requested)) not in normalized_allowed:
            raise ValueError(
                f"customer_id {requested!r} is not one of this client's "
                "configured accounts and was refused."
            )
        return str(requested)
    if default and normalize_customer_id(str(default)) in normalized_allowed:
        return str(default)
    if len(allowed) == 1:
        return next(iter(allowed))
    raise ValueError(
        "customer_id is required: this client has multiple configured "
        "accounts — pass one of them explicitly."
    )


def normalize_meta_account_id(value: str) -> str:
    """Strip the ``act_`` prefix so membership checks are prefix-insensitive."""
    return value[4:] if value.startswith("act_") else value


def canonical_meta_account_id(value: str) -> str:
    """Ensure the ``act_`` prefix the Meta client factory requires."""
    return value if value.startswith("act_") else f"act_{value}"


def resolve_account_id(requested: str | None, default: str | None) -> str:
    """Resolve and workspace-enforce the Meta ``account_id`` (#411).

    Every Meta tool funnels through ``_get_client``, which takes
    ``account_id`` as a free caller argument while the (possibly shared)
    credentials can reach every managed ad account. This binds the
    EFFECTIVE id — explicit argument or credentials default alike — to the
    active client's allow-list, mirroring Search Console's ``site_url``
    enforcement (#375):

    - **Not tenant-scoped** (:func:`runtime_meta_account_ids` → ``None``):
      unchanged — argument wins, credentials default second, missing both
      is an error.
    - **Tenant-scoped**: an out-of-set value is refused (fail-closed,
      prefix-insensitive); no usable value resolves to the single
      configured account, or is refused when several are configured
      (ambiguous) or none are (fail-fast).
    """
    allowed = runtime_meta_account_ids()
    if allowed is None:
        account_id = requested or default
        if not account_id:
            raise ValueError(
                "account_id is required. Provide it as a parameter or "
                "configure it in ~/.mureo/credentials.json via mureo auth "
                "setup."
            )
        return str(account_id)
    if not allowed:
        raise ValueError(
            "Meta Ads is not configured for this client. Configure the "
            "client's ad account before querying it."
        )
    normalized_allowed = {normalize_meta_account_id(entry) for entry in allowed}
    if requested:
        if normalize_meta_account_id(str(requested)) not in normalized_allowed:
            raise ValueError(
                f"account_id {requested!r} is not one of this client's "
                "configured ad accounts and was refused."
            )
        return canonical_meta_account_id(str(requested))
    if default and normalize_meta_account_id(str(default)) in normalized_allowed:
        return canonical_meta_account_id(str(default))
    if len(allowed) == 1:
        return canonical_meta_account_id(next(iter(allowed)))
    raise ValueError(
        "account_id is required: this client has multiple configured ad "
        "accounts — pass one of them explicitly."
    )


__all__ = [
    "canonical_meta_account_id",
    "normalize_customer_id",
    "normalize_meta_account_id",
    "resolve_account_id",
    "resolve_customer_id",
]
