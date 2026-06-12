"""Configure-UI persistence for plugins' per-account credential fields.

A plugin provider declares its per-account credential fields via
:class:`mureo.core.providers.credentials.AccountCredentialField`. This
module is the small bridge between that declarative metadata and the
``~/.mureo/credentials.json`` storage layer
(:class:`mureo.core.secret_store.FilesystemSecretStore`):

- :func:`list_plugin_credential_fields` walks
  :data:`mureo.core.providers.default_registry` and returns a
  JSON-serialisable description of each provider that declares
  non-empty ``account_credential_fields``. The configure-UI JS
  consumes this to render the form.
- :func:`save_plugin_credentials` persists one provider's values back
  to the secret store with three pieces of policy: unknown providers
  are rejected (no path for a stale UI to inject arbitrary top-level
  keys); unknown field keys are silently dropped (the UI may legitimately
  fall behind the plugin's declared schema); a blank ``secret=True``
  value is treated as "keep the existing value" so an edit form does
  not force the operator to re-enter the API key on every save.

Secret values never appear in this module's log output — the
``secret`` flag is the provider author's contract that the value is
sensitive, and the configure-UI layer honours it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.core.providers import (
    default_registry,
    get_account_credential_fields,
    get_account_oauth_config,
)
from mureo.core.secret_store import FilesystemSecretStore, SecretStore

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from mureo.core.providers.credentials import AccountCredentialField

logger = logging.getLogger(__name__)


class PluginCredentialsError(Exception):
    """Base class for save-time failures the HTTP layer can map to 4xx."""


class UnknownProviderError(PluginCredentialsError):
    """Raised when the requested provider name is not in the registry."""


class InvalidFieldValueError(PluginCredentialsError):
    """Raised when a field value is not a plain string."""


class RequiredFieldMissingError(PluginCredentialsError):
    """Raised when a ``required=True`` field has no value to persist.

    Covers both the "operator left the input blank for a non-secret
    required field" and the "operator left a secret required field
    blank with no existing value to keep" cases. The "blank means
    keep" carve-out for ``secret=True`` only applies when an existing
    value is already stored — there is nothing to keep for a fresh
    install.
    """


def list_plugin_credential_fields(
    locale: str = "en",
    *,
    field_scope: Mapping[str, Collection[str]] | None = None,
) -> list[dict[str, Any]]:
    """Enumerate providers that declare per-account credential fields.

    Args:
        locale: BCP-47 language code used to resolve plugin-supplied
            ``display_name_i18n`` / ``description_i18n`` entries on
            each field. The fallback chain is
            ``i18n[locale] → i18n["en"] → display_name`` (and the
            equivalent for description), so a plugin may ship only
            the locales it has translated. Defaults to ``"en"`` —
            matches pre-#186 behaviour for callers that don't yet
            pass a locale.
        field_scope: Optional per-provider allow-list of field keys to
            render (#207). ``None`` (the standalone-OSS default) renders
            every declared field. When a mapping is supplied, a provider
            **present** in it shows only the listed keys (and is dropped
            entirely if none of its declared fields match); a provider
            **absent** from it keeps all its fields. Resolved by the
            handler from the active store's ``ui_plugin_credential_fields``
            capability behind a ``home is None`` gate, so a multi-account
            backend can hide per-account ids that live on its own
            per-client form.

    Returns:
        A list of provider descriptors sorted alphabetically by
        ``provider_name``. Each entry has the shape::

            {
                "provider_name": "demo_ads",
                "display_name": "Demo Ads",
                "fields": [
                    {
                        "key": "api_key",
                        "display_name": "API Key",
                        "placeholder": "...",
                        "required": True,
                        "secret": True,
                        "description": "...",
                    },
                    ...
                ],
            }

        ``display_name`` and ``description`` on each field are the
        locale-resolved strings; the ``key`` is locale-independent.
        Providers without declared fields are skipped — they have
        nothing for the operator to fill in.
    """
    result: list[dict[str, Any]] = []
    for entry in sorted(default_registry, key=lambda e: e.name):
        fields = get_account_credential_fields(entry.provider_class)
        if not fields:
            continue
        if field_scope is not None and entry.name in field_scope:
            allowed = field_scope[entry.name]
            fields = tuple(f for f in fields if f.key in allowed)
            if not fields:
                # Every declared field was scoped out — drop the card so
                # the section shows no empty provider block.
                continue
        result.append(
            {
                "provider_name": entry.name,
                "display_name": entry.display_name,
                "fields": [_field_to_dict(f, locale) for f in fields],
                # OAuth descriptor (#201) — field *keys* only, never
                # secret values; ``None`` for manual-entry providers so
                # the UI shows no Authenticate button (regression-free).
                "oauth": _oauth_to_dict(entry.provider_class),
            }
        )
    return result


def _oauth_to_dict(provider_class: type) -> dict[str, str] | None:
    """Return the provider's OAuth field-key mapping, or ``None``.

    Exposes only the three ``*_field`` key names so the configure UI can
    render an Authenticate button next to the target field and know which
    fields must be saved first. The endpoints (``authorize_url`` /
    ``token_url``) and any secret values stay server-side.

    A provider that declares a fixed ``callback_port`` (#220) additionally
    gets a ``default_callback_url`` — the canonical
    ``http://127.0.0.1:<port><path>`` the dashboard pre-fills so the
    operator registers the exact loopback redirect URI the provider's
    OAuth server requires. Omitted entirely when no port is declared (the
    #216 default), keeping the block to its original three keys.
    """
    config = get_account_oauth_config(provider_class)
    if config is None:
        return None
    block = {
        "target_field": config.target_field,
        "client_id_field": config.client_id_field,
        "client_secret_field": config.client_secret_field,
    }
    if config.callback_port is not None:
        block["default_callback_url"] = (
            f"http://127.0.0.1:{config.callback_port}{config.callback_path}"
        )
    return block


def save_plugin_credentials(
    provider_name: str,
    values: dict[str, Any],
    *,
    secret_store: SecretStore | None = None,
    field_scope: Mapping[str, Collection[str]] | None = None,
) -> dict[str, Any]:
    """Persist one provider's per-account credential values.

    Args:
        provider_name: Snake_case registry key of the provider whose
            credentials are being saved. Must already be registered.
        values: Operator-supplied values, keyed by
            :class:`AccountCredentialField.key`. Unknown keys are
            dropped silently; non-string values raise
            :class:`InvalidFieldValueError`.
        secret_store: Persistence backend. Defaults to a fresh
            :class:`FilesystemSecretStore` pointing at
            ``~/.mureo/credentials.json``.
        field_scope: Optional per-provider allow-list of field keys in
            this surface's jurisdiction — the save-side mirror of #207's
            list filtering (#211). When the provider is **present** in the
            mapping, ``required=True`` is enforced only for fields whose
            key is **listed**; a per-account required field the backend
            scoped out of the dashboard (and supplies through its own
            per-client flow) is not enforced here, so a scoped form can
            actually save. ``None`` / provider absent → every declared
            required field is enforced, exactly as before. Resolved by the
            handler from the same ``ui_plugin_credential_fields``
            capability used for listing, behind the ``home is None`` gate.

    Returns:
        A response envelope ``{"merged": <dict>, "accepted_keys":
        [...]}``. ``merged`` is the full value dict that was persisted
        (existing + newly-accepted, after dropping unknown keys);
        ``accepted_keys`` is the subset of field keys this call
        actually changed (excludes blank-secret-skipped fields). The
        HTTP layer echoes the latter back to the UI.

    Raises:
        UnknownProviderError: ``provider_name`` is not registered.
        InvalidFieldValueError: A supplied value is not a string.
        RequiredFieldMissingError: A ``required=True`` field has no
            value to persist (blank submission with no existing
            value, or absent from the payload entirely).
    """
    if provider_name not in default_registry:
        raise UnknownProviderError(
            f"unknown provider for credential save: {provider_name!r}"
        )
    entry = default_registry.get(provider_name)

    declared = get_account_credential_fields(entry.provider_class)
    declared_by_key: dict[str, AccountCredentialField] = {f.key: f for f in declared}

    # Fields in this surface's jurisdiction for required-enforcement
    # (#211). ``None`` means "no scoping" (standalone OSS, or the provider
    # is not in the mapping) → enforce every declared required field. A
    # set means enforce ``required`` only for the listed keys; the rest
    # are supplied by the backend's own per-client flow.
    scoped = field_scope.get(provider_name) if field_scope is not None else None

    # The OAuth target_field (#217) is acquired via the Authenticate flow,
    # never typed into the Save form, so it must not be required-enforced
    # here — otherwise first-time setup deadlocks (Save wants the token,
    # Authenticate wants Save). Exempt it regardless of UI (defense in
    # depth). A malformed oauth declaration is treated as "no oauth".
    try:
        oauth_config = get_account_oauth_config(entry.provider_class)
    except (TypeError, ValueError):
        oauth_config = None
    oauth_target_field = oauth_config.target_field if oauth_config is not None else None

    # Validate the value type before reading the existing store — a bad
    # payload should not even cause a read.
    for key, value in values.items():
        if key in declared_by_key and not isinstance(value, str):
            raise InvalidFieldValueError(
                f"value for {provider_name}.{key} must be a string, "
                f"got {type(value).__name__}"
            )

    store = secret_store if secret_store is not None else FilesystemSecretStore()
    existing = store.load(provider_name)

    merged: dict[str, Any] = dict(existing)
    accepted_keys: list[str] = []
    for field in declared:
        supplied = values.get(field.key)
        # Scope-aware required-ness (#211) + OAuth-target exemption (#217):
        # a field scoped OUT of this surface, or the OAuth target_field
        # (obtained via Authenticate, not Save), is not enforced here so a
        # scoped/OAuth form can still save.
        required = (
            field.required
            and field.key != oauth_target_field
            and (scoped is None or field.key in scoped)
        )
        if supplied is None:
            # Absent from payload. Required fields without an existing
            # stored value are an error; otherwise the field is left
            # untouched.
            if required and field.key not in existing:
                raise RequiredFieldMissingError(
                    f"required field missing: {provider_name}.{field.key}"
                )
            continue
        if field.secret and supplied == "":
            # Blank secret = "keep existing". Only OK when there is an
            # existing value to keep; otherwise the operator submitted
            # a fresh form with a blank required field.
            if required and field.key not in existing:
                raise RequiredFieldMissingError(
                    f"required secret field has no value to keep: "
                    f"{provider_name}.{field.key}"
                )
            continue
        if required and not field.secret and supplied == "":
            # Blank non-secret required field is taken literally as
            # "clear" — refuse so the operator does not silently land
            # in a state the plugin will reject at runtime.
            raise RequiredFieldMissingError(
                f"required field cleared: {provider_name}.{field.key}"
            )
        merged[field.key] = supplied
        accepted_keys.append(field.key)

    store.save(provider_name, merged)

    # Log the operation without ever surfacing a secret value. Listing
    # the accepted keys gives operators an audit trail; the values
    # themselves stay in the secret store.
    logger.info(
        "plugin credentials saved: provider=%s accepted_keys=%s",
        provider_name,
        sorted(accepted_keys),
    )
    return {"merged": merged, "accepted_keys": accepted_keys}


def _field_to_dict(field: AccountCredentialField, locale: str) -> dict[str, Any]:
    """Convert one ``AccountCredentialField`` to its JSON payload shape.

    Args:
        field: The plugin-declared field.
        locale: BCP-47 language code used for the ``display_name`` /
            ``description`` lookup chain. Resolution order:
            ``i18n[locale]`` → ``i18n["en"]`` → the bare
            ``field.display_name`` / ``field.description``. A plugin
            that ships only English keeps working unchanged because
            both ``*_i18n`` mappings default to ``{}`` so the chain
            collapses to the bare attribute on every locale.

    We do not use :func:`dataclasses.asdict` here so the wire-level
    shape is pinned by this module — a future ``AccountCredentialField``
    attribute gets a deliberate decision about whether the UI should
    see it.
    """
    return {
        "key": field.key,
        "display_name": _resolve_localized(
            field.display_name_i18n, field.display_name, locale
        ),
        "placeholder": field.placeholder,
        "required": field.required,
        "secret": field.secret,
        "description": _resolve_localized(
            field.description_i18n, field.description, locale
        ),
    }


def _resolve_localized(i18n: Mapping[str, str], fallback: str, locale: str) -> str:
    """Return ``i18n[locale]`` if present, else ``i18n["en"]``, else fallback.

    Empty-string entries are treated as "not declared" so a plugin
    cannot accidentally erase a label by shipping an empty JA entry —
    the chain falls through to the next layer instead. ``en`` is
    privileged as the universal fallback because the configure UI
    defaults to it and every existing in-tree provider already ships
    English copy as ``display_name`` / ``description``.
    """
    candidate = i18n.get(locale)
    if candidate:
        return candidate
    if locale != "en":
        en_candidate = i18n.get("en")
        if en_candidate:
            return en_candidate
    return fallback


__all__ = [
    "InvalidFieldValueError",
    "PluginCredentialsError",
    "RequiredFieldMissingError",
    "UnknownProviderError",
    "list_plugin_credential_fields",
    "save_plugin_credentials",
]
