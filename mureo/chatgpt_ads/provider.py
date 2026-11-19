"""The ChatGPT Ads provider and its registry registration (#993).

:class:`ChatGPTAdsProvider` ships inside mureo rather than as a
``mureo.providers`` entry point, so :meth:`Registry.discover` never sees it.
:mod:`mureo.bundled_providers` registers it — before entry-point discovery,
first-wins and silent on repeat, the same contract as
:mod:`mureo.amazon_ads.provider` — so the MCP server serves its tools through
the plugin collect/dispatch path (audit, throttle) and the ``mureo configure``
UI renders its credential card.

Importing this module also registers the platform delivery model
(:data:`CHATGPT_ADS_PLATFORM_MODEL`): providers register their model at module
import time, so it is in place before the server builds its instructions, and
:func:`mureo.policy.platform_model.models_in_scope` renders it only while
this provider actually owns the ``chatgpt_ads_`` tools.

It also opts into before-state capture
(:class:`mureo.mcp.tool_provider.MCPReversibleToolProvider`):
:meth:`ChatGPTAdsProvider.capture_reversal` hands each mutation to
:mod:`mureo.chatgpt_ads.reversal`, so a change made through mureo lands in
``action_log`` with a reversal ``rollback_apply`` can execute. Registering
the provider also registers its change feed
(:mod:`mureo.chatgpt_ads.change_feed`), so ``mureo_external_changes_import``
records changes made on the account outside mureo.

``handle_mcp_tool`` is the single place a client exception becomes a result:
a missing key and a rejected key are the auth-failure envelope, a feature not
enabled for the account is the ``feature_not_enabled`` failure envelope, and
every other platform error is the ``API error:`` text. A refusal a handler
decides on itself (several daily spend limits) is returned as the handler's
own ``refused`` failure envelope. A malformed argument raises ``ValueError``,
which the server records and re-raises.
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.types import TextContent, Tool

from mureo.change_import.registry import register_change_feed
from mureo.chatgpt_ads._api import CHATGPT_ADS_PROVIDER_NAME
from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError
from mureo.chatgpt_ads.change_feed import ChatGPTAdsChangeFeed
from mureo.chatgpt_ads.credentials import (
    NO_CREDENTIALS_DETAIL,
    load_chatgpt_ads_credentials,
)
from mureo.chatgpt_ads.handlers import ALL_TOOLS, HANDLERS, run_tool
from mureo.chatgpt_ads.reversal import capture_reversal
from mureo.core.auth_failure import (
    AUTH_CAUSE_NO_CREDENTIALS,
    PlatformAuthError,
    auth_failure_payload,
)
from mureo.core.providers.credentials import AccountCredentialField
from mureo.core.providers.registry import ProviderEntry, default_registry
from mureo.core.tool_failure import API_ERROR_PREFIX, exception_text, failure_payload
from mureo.policy.learning_rules import Evidence
from mureo.policy.platform_model import PlatformModel, register_platform_model

#: Pip-distribution label recorded on the entry. It names the provider in the
#: audit trail (``source``) and, with :data:`CHATGPT_ADS_PROVIDER_NAME`, in
#: ``STATE.json`` ``action_log`` entries
#: (``platform=plugin:mureo-chatgpt-ads:chatgpt_ads``), so renaming it would
#: orphan existing history.
CHATGPT_ADS_SOURCE_DISTRIBUTION = "mureo-chatgpt-ads"

#: Coexistence control, matching ``MUREO_DISABLE_AMAZON_ADS`` and friends.
#: Set to the exact string ``"1"`` to keep mureo from registering the
#: provider at all.
CHATGPT_ADS_DISABLE_ENV_VAR = "MUREO_DISABLE_CHATGPT_ADS"

_API_KEY_DESCRIPTION = (
    "Advertiser API key for your own ad account. Create it on the Settings "
    "page in Ads Manager. One key reads exactly one ad account."
)

_ACCOUNT_CREDENTIAL_FIELDS: tuple[AccountCredentialField, ...] = (
    AccountCredentialField(
        key="api_key",
        display_name="Ads API key",
        required=True,
        secret=True,
        description=_API_KEY_DESCRIPTION,
        display_name_i18n={"en": "Ads API key", "ja": "Ads API キー"},
        description_i18n={
            "en": _API_KEY_DESCRIPTION,
            "ja": (
                "ご自身の広告アカウントの Advertiser API キー。Ads Manager の"
                "設定ページで作成します。1 つのキーで読み取れる広告アカウントは"
                " 1 つです。"
            ),
        },
    ),
)

#: How ChatGPT Ads selects and prices delivery, from OpenAI's developer
#: documentation. Which ChatGPT plans see ads is left out: the developer
#: documentation does not state it.
CHATGPT_ADS_PLATFORM_MODEL = PlatformModel(
    platform=CHATGPT_ADS_PROVIDER_NAME,
    tool_prefix="chatgpt_ads_",
    statement=(
        "ChatGPT Ads delivery is decided by an auction, and the auction sets "
        "the actual CPC. Each ad group's billing event decides whether you pay "
        "for impressions or clicks; conversion-optimized bidding still bills "
        "per valid click, never per conversion. Budgets and bids are set in "
        "micros (1,000,000 = one unit). Conversions arrive at least one day "
        "late, so same-day figures are provisional."
    ),
    evidence=Evidence(
        source="https://developers.openai.com/ads/conversion-optimized-campaigns",
        retrieved="2026-11-19",
        quote=(
            "OpenAI charges you only when a valid click occurs, and the "
            "auction determines the actual CPC."
        ),
    ),
)
register_platform_model(CHATGPT_ADS_PLATFORM_MODEL)


def _text_result(payload: Any) -> list[TextContent]:
    """``payload`` as the one JSON text item every tool result carries.

    The serialization of :mod:`mureo.mcp._helpers`, repeated because this
    package may not import :mod:`mureo.mcp`.
    """
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


class ChatGPTAdsProvider:
    """Tools over OpenAI's Advertiser API: nine reads, the spend-limit read,
    eleven changes that are recorded with a reversal, create and archive for
    campaigns, ad groups and ads (no reversal), an image upload, an ad
    preview, a location search, custom audiences filled from a local
    identifier file, and conversion measurement (pixels, event settings and
    the conversion report)."""

    name = CHATGPT_ADS_PROVIDER_NAME
    display_name = "ChatGPT Ads"
    #: Read by ``mureo.core.providers.get_account_credential_fields`` to
    #: render the configure card and to save into the ``chatgpt_ads`` section.
    account_credential_fields: tuple[AccountCredentialField, ...] = (
        _ACCOUNT_CREDENTIAL_FIELDS
    )

    def mcp_tools(self) -> tuple[Tool, ...]:
        """The tool definitions. Pure: no credentials, no network."""
        return ALL_TOOLS

    async def capture_reversal(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """The reversal of mutation ``name``, read before it runs; best effort.

        See :mod:`mureo.chatgpt_ads.reversal`.
        """
        return await capture_reversal(name, arguments)

    async def handle_mcp_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[TextContent]:
        # A name this provider never listed is a caller bug, not a missing
        # key: refuse it before the credential store is read.
        if name not in HANDLERS:
            raise ValueError(f"Unknown ChatGPT Ads tool: {name}")
        credentials = load_chatgpt_ads_credentials()
        if credentials is None:
            return _text_result(
                auth_failure_payload(AUTH_CAUSE_NO_CREDENTIALS, NO_CREDENTIALS_DETAIL)
            )
        try:
            payload = await run_tool(name, arguments, credentials.api_key)
        except PlatformAuthError as exc:
            detail = f"ChatGPT Ads rejected the API key: {exception_text(exc)}"
            return _text_result(auth_failure_payload(exc.cause, detail))
        except ChatGPTAdsAPIError as exc:
            if exc.is_feature_gate:
                return _text_result(
                    failure_payload("feature_not_enabled", exception_text(exc))
                )
            return [
                TextContent(
                    type="text", text=f"{API_ERROR_PREFIX} {exception_text(exc)}"
                )
            ]
        return _text_result(payload)


def chatgpt_ads_disabled() -> bool:
    """Is the provider switched off via :data:`CHATGPT_ADS_DISABLE_ENV_VAR`?

    Exact-string ``== "1"``, the contract every ``MUREO_DISABLE_*`` gate
    holds. Read at call time so the MCP server and the configure UI observe
    the same environment.
    """
    return os.environ.get(CHATGPT_ADS_DISABLE_ENV_VAR) == "1"


def provider_entry() -> ProviderEntry:
    """The synthetic :class:`ProviderEntry` for the provider.

    ``capabilities`` is empty: the provider serves its own MCP tools and
    implements none of mureo's domain Protocols.
    """
    return ProviderEntry(
        name=CHATGPT_ADS_PROVIDER_NAME,
        display_name=ChatGPTAdsProvider.display_name,
        capabilities=frozenset(),
        provider_class=ChatGPTAdsProvider,
        source_distribution=CHATGPT_ADS_SOURCE_DISTRIBUTION,
    )


def register_chatgpt_ads_provider() -> ProviderEntry:
    """Register the provider in ``default_registry``; return the live entry.

    Call before entry-point discovery. The membership check keeps a repeat
    call silent (``Registry.register`` would warn on a duplicate name), and a
    ``chatgpt_ads`` entry registered earlier is left in place (first-wins).

    The change feed (:class:`ChatGPTAdsChangeFeed`) is registered with this
    provider's own entry only, under :data:`CHATGPT_ADS_SOURCE_DISTRIBUTION`,
    so it answers for ``plugin:mureo-chatgpt-ads:chatgpt_ads``. A
    ``chatgpt_ads`` entry registered by something else keeps its own feed,
    or none.
    """
    if CHATGPT_ADS_PROVIDER_NAME in default_registry:
        return default_registry.get(CHATGPT_ADS_PROVIDER_NAME)
    entry = provider_entry()
    default_registry.register(entry)
    register_change_feed(
        ChatGPTAdsChangeFeed(), source_distribution=CHATGPT_ADS_SOURCE_DISTRIBUTION
    )
    return entry


__all__ = [
    "CHATGPT_ADS_DISABLE_ENV_VAR",
    "CHATGPT_ADS_PLATFORM_MODEL",
    "CHATGPT_ADS_PROVIDER_NAME",
    "CHATGPT_ADS_SOURCE_DISTRIBUTION",
    "ChatGPTAdsProvider",
    "chatgpt_ads_disabled",
    "provider_entry",
    "register_chatgpt_ads_provider",
]
