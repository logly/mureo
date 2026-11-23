"""Optional OAuth hooks a plugin provider may expose as callable attributes.

The configure layer drives a provider's OAuth lifecycle (consent, token
storage, Disconnect) from the declarative :class:`AccountOAuthConfig`. Where
a provider needs behaviour of its own at one of those points, it exposes an
optional callable attribute and the configure layer looks it up through the
getters here ("OSS = mechanism, plugin = values"):

- :func:`get_oauth_account_lister` — ``list_oauth_accounts`` (#336)
- :func:`get_oauth_persist_hook` — ``on_oauth_persisted`` (#939)
- :func:`get_oauth_disconnect_hook` — ``on_oauth_disconnected`` (#985)

Every getter reads the attribute with :func:`getattr` only (never
instantiates anything) and returns ``None`` when it is absent or not
callable, so a provider that omits a hook keeps the default behaviour. The
module imports nothing from :mod:`mureo.core.providers`, so any module there
can import it without creating a cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def _callable_attribute(provider: object, name: str) -> Callable[..., object] | None:
    """Return ``provider.<name>`` when it is callable, else ``None``."""
    hook = getattr(provider, name, None)
    return hook if callable(hook) else None


def get_oauth_account_lister(provider: object) -> Callable[..., object] | None:
    """Return a provider's ``list_oauth_accounts`` hook, or ``None`` (#336).

    A provider whose :class:`AccountOAuthConfig` declares an
    ``accounts_field`` lists the accounts its obtained OAuth token can
    reach so the configure UI can render a picker for that field instead
    of a free-text input. The behaviour lives in the plugin (the OSS layer
    must stay free of provider-specific Graph/REST calls — "OSS =
    mechanism, plugin = values"), surfaced as a callable attribute:

        list_oauth_accounts(credentials: Mapping[str, str])
            -> Sequence[Mapping[str, str]]   # [{"id": ..., "name": ...}, ...]

    The hook receives the provider's **stored credentials section** (so it
    can read the obtained token under ``target_field``) and returns one
    mapping per reachable account. It may be a plain function,
    ``staticmethod``, or ``classmethod``, and may be ``async`` — the
    configure layer (:func:`mureo.web.plugin_credentials.list_oauth_accounts`)
    awaits a coroutine result on its own loop. Read defensively via
    ``getattr`` so a provider that omits it yields ``None`` and the UI
    keeps the plain input (same convention as ``account_credential_fields``).

    Args:
        provider: The provider class/instance to introspect. Uses
            :func:`getattr` only; never instantiates anything.

    Returns:
        The callable hook, or ``None`` when the attribute is absent or not
        callable.
    """
    return _callable_attribute(provider, "list_oauth_accounts")


def get_oauth_persist_hook(provider: object) -> Callable[..., object] | None:
    """Return a provider's ``on_oauth_persisted`` hook, or ``None`` (#939).

    A provider whose :class:`AccountOAuthConfig` drives the configure
    wizard's authorization-code flow may need to derive secondary
    credential material from the token it just obtained (a file another
    tool reads, a sibling provider's section) at the moment the token
    lands. The behaviour lives in the plugin ("OSS = mechanism, plugin =
    values"), surfaced as a callable attribute:

        on_oauth_persisted(credentials: Mapping[str, str], *,
                           credentials_path: Path) -> None

    The configure wizard calls it once, right after the authorization-code
    callback has written the obtained token into the provider's section.
    ``credentials`` is the merged section just written (it includes
    ``target_field``); ``credentials_path`` is the ``credentials.json``
    written to, so a plugin that derives a sibling section uses
    ``FilesystemSecretStore(path=credentials_path)`` and lands in the same
    store as the token. It may be a plain function, ``staticmethod``, or
    ``classmethod``, and may be ``async`` — the configure layer
    (:func:`mureo.web.plugin_credentials.notify_oauth_persisted`) awaits a
    coroutine result on its own loop. A hook that raises does not undo the
    save: the wizard logs a warning naming the provider only. Read
    defensively via ``getattr`` so a provider that omits it yields
    ``None`` (same convention as :func:`get_oauth_account_lister`).

    Args:
        provider: The provider class/instance to introspect. Uses
            :func:`getattr` only; never instantiates anything.

    Returns:
        The callable hook, or ``None`` when the attribute is absent or not
        callable.
    """
    return _callable_attribute(provider, "on_oauth_persisted")


def get_oauth_disconnect_hook(provider: object) -> Callable[..., object] | None:
    """Return a provider's ``on_oauth_disconnected`` hook, or ``None`` (#985).

    The counterpart of :func:`get_oauth_persist_hook`: a provider that
    derived other local files or a sibling section from its stored token
    can remove them again when the operator disconnects it. Surfaced as a
    callable attribute:

        on_oauth_disconnected(*, credentials_path: Path) -> None

    The dashboard's Disconnect action
    (:func:`mureo.web.plugin_oauth_revoke.disconnect_plugin_provider`) calls
    it once, after the revocation attempt and after the provider's
    credential section has been removed. ``credentials_path`` is the
    ``credentials.json`` the section was removed from. The section is
    already gone, so the hook receives no credentials. It may be a plain
    function, ``staticmethod``, or ``classmethod``, and may be ``async`` —
    the Disconnect action awaits a coroutine result on its own loop. A hook
    that raises neither undoes nor fails the Disconnect: a warning naming
    the provider is logged. Read defensively via ``getattr`` so a provider
    that omits it yields ``None`` (same convention as
    :func:`get_oauth_persist_hook`).

    Args:
        provider: The provider class/instance to introspect. Uses
            :func:`getattr` only; never instantiates anything.

    Returns:
        The callable hook, or ``None`` when the attribute is absent or not
        callable.
    """
    return _callable_attribute(provider, "on_oauth_disconnected")


__all__ = [
    "get_oauth_account_lister",
    "get_oauth_disconnect_hook",
    "get_oauth_persist_hook",
]
