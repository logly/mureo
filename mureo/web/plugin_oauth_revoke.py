"""Best-effort OAuth token revocation for plugin providers (#970).

A plugin provider whose :class:`~mureo.core.providers.AccountOAuthConfig`
declares ``revoke_url`` gets its stored token revoked at that RFC 7009
endpoint in two places: the configure wizard's authorization-code callback
(:func:`mureo.web.plugin_oauth_spec.persist_plugin_token`), once
re-authentication has saved the token that replaces it, and
:func:`disconnect_plugin_provider`, the dashboard's Disconnect action, before
the provider's credential section is removed.

Revocation is best effort in both. The new token is already saved, or the
operator has asked for the credentials to go, so a provider that is down or
answers unexpectedly must not block the save or the removal: a failure is one
WARNING naming the provider and nothing more. The token, the client secret,
the request headers and the response body are never logged.

Removing a section rewrites ``credentials.json`` through
:class:`~mureo.core.secret_store.FilesystemSecretStore` (an atomic write) after
copying the file to ``credentials.json.bak`` with
:func:`mureo.fsutil.backup_file`, as ``remove_credential_section`` does for
the built-in platforms.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mureo.core.providers import default_registry, get_account_oauth_config
from mureo.core.secret_store import FilesystemSecretStore
from mureo.fsutil import backup_file
from mureo.oauth_authcode import revoke_token
from mureo.web.plugin_credentials import UnknownProviderError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

logger = logging.getLogger(__name__)


def revoke_plugin_token(
    provider: str,
    *,
    revoke_url: str,
    token: str,
    client_id: str,
    client_secret: str,
    client_auth: str = "basic",
    headers: Mapping[str, str] | None = None,
) -> bool:
    """Revoke ``token`` for ``provider``; ``True`` when the endpoint confirmed.

    Never raises: a refused revocation or any exception (transport, a bad
    declaration) is one WARNING naming the provider, with the exception class
    name when there was one.
    """
    try:
        done = revoke_token(
            revoke_url=revoke_url,
            token=token,
            client_id=client_id,
            client_secret=client_secret,
            client_auth=client_auth,
            headers=headers,
        )
    except Exception as exc:  # noqa: BLE001 — revocation is best effort; never blocks
        logger.warning(
            "Token revocation failed for provider %s: %s",
            provider,
            type(exc).__name__,
        )
        return False
    if not done:
        logger.warning("Token revocation failed for provider %s", provider)
    return done


def disconnect_plugin_provider(
    provider_name: str, *, credentials_path: Path | None
) -> bool:
    """Remove a plugin provider's credential section; ``False`` if none is stored.

    When the provider declares ``revoke_url`` the stored token is revoked first,
    unless the client id or secret it needs is missing (logged, not revoked).

    Raises:
        UnknownProviderError: ``provider_name`` is not registered.
        TypeError, ValueError: a malformed ``account_oauth`` declaration
            (from :func:`get_account_oauth_config`); nothing is removed.
    """
    if provider_name not in default_registry:
        raise UnknownProviderError(f"unknown provider to disconnect: {provider_name!r}")
    entry = default_registry.get(provider_name)
    config = get_account_oauth_config(entry.provider_class)
    store = FilesystemSecretStore(path=credentials_path)
    section = store.load(provider_name)
    if not section:
        return False
    if config is not None and config.revoke_url:
        # A hand-edited value that is not a string counts as missing.
        token, client_id, client_secret = (
            value if isinstance(value, str) else ""
            for value in (
                section.get(config.target_field),
                section.get(config.client_id_field),
                section.get(config.client_secret_field),
            )
        )
        if token and client_id and client_secret:
            revoke_plugin_token(
                provider_name,
                revoke_url=config.revoke_url,
                token=token,
                client_id=client_id,
                client_secret=client_secret,
                client_auth=config.token_auth_style,
                headers=dict(config.token_headers) or None,
            )
        elif token:
            logger.warning(
                "Token revocation skipped for provider %s: client credentials missing",
                provider_name,
            )
    backup_file(store.path)  # keep the prior good file before the overwrite
    store.delete(provider_name)
    logger.info("Removed plugin credential section %s", provider_name)
    return True


__all__ = ["disconnect_plugin_provider", "revoke_plugin_token"]
