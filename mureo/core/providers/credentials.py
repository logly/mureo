"""Declarative metadata for a provider's per-account credential fields.

A provider (built-in or third-party) often needs identifiers that
vary per platform account — Google Ads ``customer_id``, Meta Ads
``account_id``, an analytics product's ``advertiser_id``. These
are distinct from operator-shared OAuth credentials (developer
tokens, refresh tokens) which typically apply to every account on
the same platform.

:class:`AccountCredentialField` lets a provider declare these
per-account fields so introspection tooling — the ``mureo
providers …`` CLI, configuration wizards, plugin authoring guides,
third-party setup UIs — can render prompts, validate config, and
document the provider's needs without hardcoding per-provider
knowledge.

The dataclass is **declarative metadata only**: it carries no
behaviour and never reads or writes a value. Storage policy
(env vars, ``~/.mureo/credentials.json``, an injected
:class:`SecretStore`, etc.) is the consumer's concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class AccountCredentialField:
    """One per-account credential field declared by a provider.

    Attributes:
        key: Stable snake_case identifier used in credential storage
            and config (e.g., ``"customer_id"``). Treat as part of
            the provider's public ABI — renaming the key after
            release breaks any operator config that referenced it.
        display_name: Human-readable label for CLI prompts and
            wizard forms (e.g., ``"Customer ID"``). Used as the
            fallback when no ``display_name_i18n`` entry resolves
            for the active locale — see the ``*_i18n`` attributes.
        placeholder: Example value shown as a form-input placeholder
            (e.g., ``"123-456-7890"``). Never used as a default —
            tooling that auto-applies the placeholder would surprise
            operators. Default: ``""``.
        required: ``True`` when the provider cannot function without
            the field populated; tooling may then warn or block on a
            missing value. Default: ``False``.
        description: One-line operator-facing hint pointing at where
            the value comes from (e.g., ``"From Google Ads UI >
            Settings > Account details > Customer ID"``). Used as
            the fallback when no ``description_i18n`` entry resolves
            for the active locale. Default: ``""``.
        secret: ``True`` when the field carries a secret value (API
            key, per-account OAuth token, etc.) rather than a public
            identifier (``customer_id``, ``account_id``, …). Like
            the other attributes this flag is declarative metadata
            only — mureo itself does not redact or remask the value.
            Consumers — configure wizards, third-party setup UIs —
            can use this flag to render a masked input, redact the
            value in logs, and choose tighter storage permissions
            (typically ``0o600``). Default: ``False`` — most
            per-account fields are non-secret identifiers, and the
            OSS-shipped ``GoogleAdsAdapter`` / ``MetaAdsAdapter``
            leave secret material (refresh tokens, system user
            tokens) in the operator-shared ``SecretStore`` layer
            rather than declaring it here.
        display_name_i18n: Optional locale → label mapping (BCP-47
            language codes; mureo's configure UI currently switches
            between ``"en"`` and ``"ja"``). The consumer resolves the
            label via ``i18n[locale] → i18n["en"] → display_name`` so
            a plugin can supply only the locales it has translated.
            Default: empty ``dict`` (pre-#186 behaviour — the bare
            ``display_name`` is used in every locale).
        description_i18n: Same shape and fallback chain as
            ``display_name_i18n``, applied to the hint text.

    The dataclass is JSON-friendly: ``dataclasses.asdict(field)``
    returns a plain ``dict`` of primitive ``str`` / ``bool`` / dict
    values suitable for serialising over HTTP / writing to a config
    file.

    The ``*_i18n`` attributes were added in #186 so plugins shipping
    to non-English audiences (Yahoo! JAPAN Ads, LINE Ads, ...) can
    keep their translation strings in their own package without
    forking mureo. The translation tables are plugin-owned by design
    — mureo itself never ships strings for plugin-declared fields.
    """

    key: str
    display_name: str
    placeholder: str = ""
    required: bool = False
    description: str = ""
    secret: bool = False
    display_name_i18n: Mapping[str, str] = field(default_factory=dict)
    description_i18n: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountOAuthConfig:
    """Declarative OAuth2 authorization-code metadata for a provider (#201).

    A provider whose per-account secret is obtained through an OAuth2
    *authorization-code* consent flow (e.g. Yahoo! JAPAN Ads, whose
    ``refresh_token`` is issued by
    ``https://biz-oauth.yahoo.co.jp/oauth/v1/...``) declares this on the
    class as ``account_oauth``. mureo's configure UI then offers an
    "Authenticate" action that runs the consent in the browser, exchanges
    the returned code at :attr:`token_url`, and stores the resulting
    ``refresh_token`` in the field named by :attr:`target_field`. The
    plugin's runtime adapter consumes that token with
    ``grant_type=refresh_token`` exactly as before.

    Like :class:`AccountCredentialField` this is **declarative metadata
    only** — it carries no behaviour and holds no secret values. The
    three ``*_field`` attributes name keys of the provider's own
    :class:`AccountCredentialField` list, keeping the OSS layer free of
    plugin-specific values ("OSS = mechanism, plugin = values", as #186).

    Attributes:
        authorize_url: The provider's OAuth2 authorization endpoint. The
            operator's browser is sent here (with ``response_type=code``,
            ``client_id``, ``redirect_uri``, ``scope`` and ``state``
            appended) to grant consent. Must be an ``https://`` URL.
        token_url: The provider's token endpoint. The configure server
            POSTs the returned authorization ``code`` here with
            ``grant_type=authorization_code`` to obtain the
            ``refresh_token``. Must be an ``https://`` URL.
        client_id_field: ``key`` of the declared
            :class:`AccountCredentialField` holding the OAuth client id.
        client_secret_field: ``key`` of the declared field holding the
            OAuth client secret (typically ``secret=True``).
        target_field: ``key`` of the declared field that receives the
            obtained ``refresh_token`` (typically ``secret=True``).
        scopes: OAuth scopes requested at the authorize step. Default:
            empty tuple (no explicit scope parameter sent).
        callback_path: Path the provider redirects back to on the local
            loopback callback server. Default ``"/oauth/callback"``; the
            ephemeral port is chosen at runtime, mirroring the loopback
            redirect flow Google's wizard already uses.
        callback_port: Fixed loopback port the provider's redirect_uri is
            registered on (#220). ``None`` (the default) keeps the
            operator-supplied / ephemeral behaviour (#216). A provider
            whose OAuth server requires the ``redirect_uri`` to match a
            **pre-registered** value exactly (Yahoo! JAPAN Ads, whose port
            cannot vary) declares the canonical port here; the configure UI
            pre-fills the callback URL as
            ``http://127.0.0.1:<callback_port><callback_path>`` so the
            operator registers — and the wizard binds — that exact URL. It
            is a *default* the operator can still override, not an
            authority: the bind + verbatim redirect_uri path (#216) is
            unchanged.
        token_auth_style: How the client id/secret are presented at the
            token endpoint. ``"basic"`` (default) sends them in the HTTP
            ``Authorization`` header (RFC 6749 §2.3.1, what Google and most
            providers expect); ``"body"`` sends them in the form body for
            providers that reject Basic — Yahoo! JAPAN biz-oauth requires
            this. Declarative only; the OSS exchange (#201) honours it.
        accounts_field: ``key`` of the declared field that names a
            *per-account selection* the operator makes **after** consent —
            e.g. a broker-managed Meta provider whose ``access_token`` is
            obtained via consent and whose ad ``account_id`` is then chosen
            from the accounts that token can reach (#336). ``None`` (the
            default) keeps the field a free-text input. When set, the
            configure UI renders that field as a post-auth picker, populated
            by the provider's ``list_oauth_accounts`` hook
            (:func:`mureo.core.providers.get_oauth_account_lister`); and a
            multi-account backend hides it entirely, since the account is
            selected per-client at runtime, not pinned once at configure
            time (#337). Declarative only — the OSS layer carries the
            mechanism; the plugin supplies the lister behaviour and values.
    """

    authorize_url: str
    token_url: str
    client_id_field: str
    client_secret_field: str
    target_field: str
    scopes: tuple[str, ...] = ()
    callback_path: str = "/oauth/callback"
    callback_port: int | None = None
    token_auth_style: str = "basic"
    accounts_field: str | None = None


__all__ = ["AccountCredentialField", "AccountOAuthConfig"]
