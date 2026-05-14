"""Public provider abstraction surface.

Re-exports the stable ABI from :mod:`mureo.core.providers.capabilities`,
:mod:`mureo.core.providers.base`, the four Phase 1 domain Protocols
(:mod:`mureo.core.providers.campaign`, :mod:`~.keyword`, :mod:`~.audience`,
:mod:`~.extension`), the shared domain models / enums in
:mod:`mureo.core.providers.models`, and the entry-points-based discovery
:mod:`mureo.core.providers.registry`.
"""

from __future__ import annotations

from mureo.core.providers.audience import AudienceProvider
from mureo.core.providers.base import (
    BaseProvider,
    validate_provider,
    validate_provider_name,
)
from mureo.core.providers.campaign import CampaignProvider
from mureo.core.providers.capabilities import (
    CAPABILITY_NAMES,
    Capability,
    parse_capabilities,
    parse_capability,
)
from mureo.core.providers.extension import ExtensionProvider
from mureo.core.providers.keyword import KeywordProvider
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Audience,
    AudienceStatus,
    BidStrategy,
    Campaign,
    CampaignFilters,
    CampaignStatus,
    CreateAdRequest,
    CreateAudienceRequest,
    CreateCampaignRequest,
    DailyReportRow,
    Extension,
    ExtensionKind,
    ExtensionRequest,
    ExtensionStatus,
    Keyword,
    KeywordMatchType,
    KeywordSpec,
    KeywordStatus,
    SearchTerm,
    UpdateAdRequest,
    UpdateCampaignRequest,
)
from mureo.core.providers.registry import (
    PROVIDERS_ENTRY_POINT_GROUP,
    SKILLS_ENTRY_POINT_GROUP,
    ProviderEntry,
    Registry,
    RegistryWarning,
    clear_registry,
    default_registry,
    discover_providers,
    get_provider,
    list_providers_by_capability,
    register_provider_class,
)

__all__ = [
    "CAPABILITY_NAMES",
    "PROVIDERS_ENTRY_POINT_GROUP",
    "SKILLS_ENTRY_POINT_GROUP",
    "Ad",
    "AdStatus",
    "Audience",
    "AudienceProvider",
    "AudienceStatus",
    "BaseProvider",
    "BidStrategy",
    "Campaign",
    "CampaignFilters",
    "CampaignProvider",
    "CampaignStatus",
    "Capability",
    "CreateAdRequest",
    "CreateAudienceRequest",
    "CreateCampaignRequest",
    "DailyReportRow",
    "Extension",
    "ExtensionKind",
    "ExtensionProvider",
    "ExtensionRequest",
    "ExtensionStatus",
    "Keyword",
    "KeywordMatchType",
    "KeywordProvider",
    "KeywordSpec",
    "KeywordStatus",
    "ProviderEntry",
    "Registry",
    "RegistryWarning",
    "SearchTerm",
    "UpdateAdRequest",
    "UpdateCampaignRequest",
    "clear_registry",
    "default_registry",
    "discover_providers",
    "get_provider",
    "list_providers_by_capability",
    "parse_capabilities",
    "parse_capability",
    "register_provider_class",
    "validate_provider",
    "validate_provider_name",
]
