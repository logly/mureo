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
the built-in platforms. After the removal, Disconnect calls the provider's
optional ``on_oauth_disconnected`` hook (#985) so a provider can remove what it
derived from the token; a failing hook is one WARNING with the provider name
and the exception class, and the Disconnect still succeeds.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.core.providers import (
    default_registry,
    get_account_oauth_config,
    get_oauth_disconnect_hook,
)
from mureo.core.secret_store import FilesystemSecretStore
from mureo.fsutil import backup_file
from mureo.oauth_authcode import revoke_token
from mureo.web._helpers import run_best_effort_hook
from mureo.web.plugin_credentials import UnknownProviderError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from mureo.core.providers import AccountOAuthConfig

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
    Once the section is removed, the provider's optional
    ``on_oauth_disconnected`` hook runs (best effort, #985).

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
    if config is not None:
        _revoke_stored_token(provider_name, config, section)
    backup_file(store.path)  # keep the prior good file before the overwrite
    store.delete(provider_name)
    logger.info("Removed plugin credential section %s", provider_name)
    _notify_oauth_disconnected(provider_name, entry.provider_class, store.path)
    return True


def _revoke_stored_token(
    provider_name: str, config: AccountOAuthConfig, section: Mapping[str, Any]
) -> None:
    """Revoke the token stored in ``section`` at ``config.revoke_url``.

    A no-op when the provider declares no ``revoke_url`` or the section holds
    no token. Skipped (one WARNING) when a token is stored but the client id
    or secret the revocation needs is missing.
    """
    if not config.revoke_url:
        return
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


def _notify_oauth_disconnected(
    provider_name: str, provider_class: type, credentials_path: Path
) -> None:
    """Call the provider's ``on_oauth_disconnected`` hook, if any (#985).

    Runs once the section is gone, so a provider can remove what it derived
    from the token. Best effort, like the revocation: the operator asked for
    the credentials to go and they are gone, so a failing hook is logged and
    the Disconnect still succeeds.
    """
    hook = get_oauth_disconnect_hook(provider_class)
    if hook is None:
        return
    run_best_effort_hook(
        lambda: hook(credentials_path=credentials_path),
        log=logger,
        label="post-disconnect",
        provider_name=provider_name,
    )


__all__ = ["disconnect_plugin_provider", "revoke_plugin_token"]
