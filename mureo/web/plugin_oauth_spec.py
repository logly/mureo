"""The plugin authorization-code hand-off and its persist step (#201, #970).

:class:`PluginOAuthSpec` is the frozen hand-off from
:class:`mureo.web.oauth_bridge.OAuthBridge` to the
:class:`mureo.web.auth_wizard.WebAuthWizard` it spawns: everything the
wizard's callback needs to exchange the code and save the token, pinned
before the operator is sent to the consent page. :func:`persist_plugin_token`,
the callback's final step (merge-save the new token, revoke the one it
replaced, call the provider's post-persist hook), lives beside it so the
wizard module stays a request handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mureo.core.secret_store import FilesystemSecretStore
from mureo.web.plugin_credentials import notify_oauth_persisted
from mureo.web.plugin_oauth_revoke import revoke_plugin_token

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from mureo.oauth_authcode import AuthCodeResult


@dataclass(frozen=True)
class PluginOAuthSpec:
    """Parameters for one generic plugin authorization-code flow (#201).

    Constructed by :meth:`mureo.web.oauth_bridge.OAuthBridge.start_plugin_oauth`
    from the provider's :class:`~mureo.core.providers.AccountOAuthConfig`
    plus the client id/secret the operator already saved, and handed to the
    spawned :class:`WebAuthWizard`. ``provider`` is the registry name, which
    is also the ``credentials.json`` section key the obtained token is
    merge-saved under; ``state`` is the CSRF nonce echoed back on the
    provider's redirect.

    ``callback_path`` is the path component of the operator-supplied
    loopback callback URL (#216); the wizard serves *this* route instead of
    the built-in ``/oauth/callback`` so the redirect_uri matches the one
    pre-registered in the provider's console exactly. ``persist_values``
    holds the operator's submitted form values (client id/secret, callback
    URL, any non-OAuth field) that are written **atomically with** the
    obtained token in a single section, so first-time setup needs no prior
    Save (#217). Both default to the #201 behaviour (the standard callback
    path; persist only the token), keeping standalone construction valid.
    """

    provider: str
    target_field: str
    token_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    state: str
    callback_path: str = "/oauth/callback"
    persist_values: dict[str, str] = field(default_factory=dict)
    # Token-endpoint client-auth style passed to ``exchange_authorization_code``
    # (#201 follow-up): ``"basic"`` (default) or ``"body"`` for providers that
    # reject HTTP Basic, e.g. Yahoo! JAPAN biz-oauth.
    token_auth_style: str = "basic"
    # Extra ``(name, value)`` headers for the token request, copied from
    # ``AccountOAuthConfig.token_headers``; empty sends none.
    token_headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    # RFC 7009 endpoint copied from ``AccountOAuthConfig.revoke_url`` (#970);
    # ``None`` leaves a replaced token unrevoked.
    revoke_url: str | None = None
    # The stored section's keys for the client id/secret, copied from
    # ``AccountOAuthConfig``: a replaced token is revoked with the pair it was
    # issued to. ``None`` falls back to the spec's own ``client_id`` /
    # ``client_secret``.
    client_id_field: str | None = None
    client_secret_field: str | None = None


def persist_plugin_token(
    spec: PluginOAuthSpec, result: AuthCodeResult, credentials_path: Path | None
) -> None:
    """Write the obtained token into the provider's section, then notify.

    When the provider declares ``revoke_url`` and the section held a different
    token, that token is revoked after the new token is on disk (#970):
    re-authentication replaces it, so leaving it live would leave a second
    working credential behind, while revoking it before the save would leave
    no working token if the save failed. Revocation is best effort and never
    fails the callback.
    """
    store = FilesystemSecretStore(path=credentials_path)
    stored = store.load(spec.provider)
    previous = stored.get(spec.target_field)
    # Persist atomically in one write (#217): start from what is on disk, layer the
    # operator's submitted form values (client id/secret, callback URL, non-OAuth
    # fields), then the obtained token last so it can never be clobbered. With
    # Authenticate-is-save there may be *nothing* on disk yet — the form values and
    # token land together, so first-time setup needs no prior Save. The #201 path
    # has empty ``persist_values``, so its merge-only behaviour is unchanged.
    merged = dict(stored)
    merged.update(spec.persist_values)
    merged[spec.target_field] = result.refresh_token
    store.save(spec.provider, merged)
    if (
        spec.revoke_url
        and isinstance(previous, str)
        and previous
        and previous != result.refresh_token
    ):
        client_id, client_secret = _issued_client_pair(spec, stored)
        revoke_plugin_token(
            spec.provider,
            revoke_url=spec.revoke_url,
            token=previous,
            client_id=client_id,
            client_secret=client_secret,
            client_auth=spec.token_auth_style,
            headers=dict(spec.token_headers) or None,
        )
    notify_oauth_persisted(spec.provider, merged, store.path)


def _issued_client_pair(
    spec: PluginOAuthSpec, stored: Mapping[str, Any]
) -> tuple[str, str]:
    """The client id/secret a stored token was issued to.

    The pre-merge section's values under the spec's field keys when both are
    non-empty strings (the operator may have submitted a different client
    with this re-authentication); otherwise the spec's own pair.
    """
    client_id, client_secret = (
        stored.get(key) if key else None
        for key in (spec.client_id_field, spec.client_secret_field)
    )
    if (
        isinstance(client_id, str)
        and client_id
        and isinstance(client_secret, str)
        and client_secret
    ):
        return client_id, client_secret
    return spec.client_id, spec.client_secret


__all__ = ["PluginOAuthSpec", "persist_plugin_token"]
