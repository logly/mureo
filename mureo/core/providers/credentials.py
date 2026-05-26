"""Declarative metadata for a provider's per-account credential fields.

A provider (built-in or third-party) often needs identifiers that
vary per platform account — Google Ads ``customer_id``, Meta Ads
``ad_account_id``, an analytics product's ``advertiser_id``. These
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

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountCredentialField:
    """One per-account credential field declared by a provider.

    Attributes:
        key: Stable snake_case identifier used in credential storage
            and config (e.g., ``"customer_id"``). Treat as part of
            the provider's public ABI — renaming the key after
            release breaks any operator config that referenced it.
        display_name: Human-readable label for CLI prompts and
            wizard forms (e.g., ``"Customer ID"``).
        placeholder: Example value shown as a form-input placeholder
            (e.g., ``"123-456-7890"``). Never used as a default —
            tooling that auto-applies the placeholder would surprise
            operators. Default: ``""``.
        required: ``True`` when the provider cannot function without
            the field populated; tooling may then warn or block on a
            missing value. Default: ``False``.
        description: One-line operator-facing hint pointing at where
            the value comes from (e.g., ``"From Google Ads UI >
            Settings > Account details > Customer ID"``).
            Default: ``""``.
        secret: ``True`` when the field carries a secret value (API
            key, per-account OAuth token, etc.) rather than a public
            identifier (``customer_id``, ``ad_account_id``, …). Like
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

    The dataclass is JSON-friendly: ``dataclasses.asdict(field)``
    returns a plain ``dict`` of primitive ``str`` / ``bool`` values
    suitable for serialising over HTTP / writing to a config file.
    """

    key: str
    display_name: str
    placeholder: str = ""
    required: bool = False
    description: str = ""
    secret: bool = False


__all__ = ["AccountCredentialField"]
