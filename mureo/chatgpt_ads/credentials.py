"""The operator's Ads API key, from the credential store or the environment.

One key is scoped to one ad account, and ``GET /ad_account`` answers with that
account's id, so the key is the whole credential: there is no account-id
field to keep in step with it.

``OPENAI_API_KEY`` (the image-generation key Creative Studio reads) is never
consulted: it is a different key for a different API, and using it for ads by
accident would send requests on the wrong account's behalf or fail
confusingly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from mureo.chatgpt_ads._api import CHATGPT_ADS_PROVIDER_NAME
from mureo.core.runtime_context import (
    get_runtime_context,
    runtime_account_env_fallback_allowed,
)

#: Environment fallback, read when the credential store has no usable key and
#: the store is not a multi-account backend (the variable names one account).
CHATGPT_ADS_API_KEY_ENV_VAR = "CHATGPT_ADS_API_KEY"

#: What a missing key is reported as, by the tools and the change feed alike.
NO_CREDENTIALS_DETAIL = (
    "No ChatGPT Ads API key is configured. Add it with `mureo configure` (the "
    "ChatGPT Ads card, or the account's own credential form on a "
    "multi-account backend) or, on a single-account install, set "
    f"{CHATGPT_ADS_API_KEY_ENV_VAR}."
)


@dataclass(frozen=True)
class ChatGPTAdsCredentials:
    """The Ads API key. Excluded from ``repr`` so a logged object leaks nothing."""

    api_key: str = field(repr=False)


def _usable(value: object) -> str | None:
    """``value`` when it is a non-blank string; blank counts as absent."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def load_chatgpt_ads_credentials() -> ChatGPTAdsCredentials | None:
    """The key from the ``chatgpt_ads`` store section, then the environment.

    The environment is skipped when the active store is a multi-account
    backend: the variable names one ad account and that backend's accounts
    share one process environment, so an account without its own section
    must fail rather than use another account's key (#1057).

    Returns ``None`` when no allowed source supplies a non-blank key, which
    the provider reports as the ``no_credentials`` auth failure.
    """
    section = get_runtime_context().secret_store.load(CHATGPT_ADS_PROVIDER_NAME)
    key = _usable(section.get("api_key"))
    if key is None and runtime_account_env_fallback_allowed():
        key = _usable(os.environ.get(CHATGPT_ADS_API_KEY_ENV_VAR))
    return ChatGPTAdsCredentials(api_key=key) if key is not None else None


__all__ = [
    "CHATGPT_ADS_API_KEY_ENV_VAR",
    "NO_CREDENTIALS_DETAIL",
    "ChatGPTAdsCredentials",
    "load_chatgpt_ads_credentials",
]
