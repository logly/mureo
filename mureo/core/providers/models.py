"""Shared frozen dataclasses and enums for the domain Protocols.

This module is the shared entity vocabulary consumed by the four Phase 1
domain Protocols (``CampaignProvider``, ``KeywordProvider``,
``AudienceProvider``, ``ExtensionProvider``) and by adapters / third-party
plugins implementing them. Every model is ``@dataclass(frozen=True)`` and
every enum is a ``StrEnum`` (or the 3.10 shim from
:mod:`mureo.core.providers.capabilities`) — collection-typed fields use
``tuple[T, ...]``, never ``list[T]``.

Foundation rule
---------------
The only allowed internal import is
:mod:`mureo.core.providers.capabilities` (re-using its ``StrEnum`` shim).
Everything else is stdlib.

Currency convention (Phase 1)
-----------------------------
Monetary amounts use ``int`` micros (1/1,000,000 of the account currency),
matching the existing Google Ads convention in ``mureo/AGENTS.md``. The
Meta adapter is responsible for converting to/from the currency's minor
units at its boundary — see :data:`ZERO_DECIMAL_CURRENCIES` /
:func:`minor_units_per_unit` (Meta's per-currency offset: 100 for e.g.
USD, 1 for JPY and the other zero-decimal currencies).
A future ``Money(amount_minor: int, currency: str)`` abstraction may
replace these raw ``_micros: int`` fields in Phase 2.

Date / datetime convention
--------------------------
Day-grain reporting fields use ``datetime.date``. No ``int`` epoch
seconds at the Protocol boundary.

Capability ↔ Protocol mapping (informational)
---------------------------------------------
Implementing a Protocol does NOT grant the corresponding capabilities;
the provider's ``capabilities`` frozenset must explicitly include them.
See the per-Protocol docstrings in ``campaign.py``, ``keyword.py``,
``audience.py``, ``extension.py`` for the canonical table.
"""

# ruff: noqa: TC003
# ``date`` must stay at module top-level (NOT under ``TYPE_CHECKING``) so
# ``typing.get_type_hints()`` can resolve the field annotations at test /
# registry introspection time on Python 3.10.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mureo.core.providers.capabilities import StrEnum

# Meta Marketing API per-currency offsets. Offset-1 currencies express
# budgets/bids as whole currency units; offset-100 as hundredths
# ("cents"). Both sets transcribed from the official table:
# https://developers.facebook.com/docs/marketing-api/currencies
ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "CLP",
        "COP",
        "CRC",
        "HUF",
        "IDR",
        "ISK",
        "JPY",
        "KRW",
        "PYG",
        "TWD",
        "VND",
    }
)

# Offset-100 currencies Meta supports (includes legacy codes Meta still
# lists, e.g. LVL/LTL/SKK/VEF, and Meta's own FBZ).
META_OFFSET_100_CURRENCIES: frozenset[str] = frozenset(
    {
        "AED",
        "ARS",
        "AUD",
        "BDT",
        "BGN",
        "BHD",
        "BOB",
        "BRL",
        "CAD",
        "CHF",
        "CNY",
        "CZK",
        "DKK",
        "DZD",
        "EGP",
        "EUR",
        "FBZ",
        "GBP",
        "GTQ",
        "HKD",
        "HNL",
        "HRK",
        "ILS",
        "INR",
        "JOD",
        "KES",
        "LTL",
        "LVL",
        "MOP",
        "MXN",
        "MYR",
        "NGN",
        "NIO",
        "NOK",
        "NZD",
        "PEN",
        "PHP",
        "PKR",
        "PLN",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "SAR",
        "SEK",
        "SGD",
        "SKK",
        "THB",
        "TRY",
        "UAH",
        "USD",
        "UYU",
        "VEF",
        "VES",
        "ZAR",
    }
)


def minor_units_per_unit(currency: str) -> int:
    """Minor units per one currency unit under Meta's offset rules.

    Returns 1 for zero-decimal currencies (a Meta budget of ``"5000"``
    in JPY means exactly ¥5,000) and 100 for offset-100 currencies
    (``"1500"`` in USD means 15.00 USD). A blanket divide-by-100
    silently shrinks JPY budgets 100x, so every Meta money conversion
    must go through here.

    Unrecognized codes raise ``ValueError`` instead of guessing: on the
    write path a wrong guess (e.g. the typo ``"JPN"`` falling back to
    offset 100) would send a 100x-too-large budget to the live API, and
    an unknown-but-real code likely means Meta extended its currency
    table — fail loudly so the whitelist gets updated.
    """
    code = currency.strip().upper()
    if code in ZERO_DECIMAL_CURRENCIES:
        return 1
    if code in META_OFFSET_100_CURRENCIES:
        return 100
    raise ValueError(
        f"Unknown Meta currency code: {currency!r}. Expected an ISO 4217 "
        "code from Meta's supported-currency table "
        "(https://developers.facebook.com/docs/marketing-api/currencies)."
    )


# ---------------------------------------------------------------------------
# Enums (StrEnum — values are snake_case strings forming the public ABI)
# ---------------------------------------------------------------------------


class AdStatus(StrEnum):
    """Stable status values for ads and (re-used) campaigns.

    The ``REMOVED`` member is the canonical delete signal: per the
    Capability enum convention, deletion is folded into status updates.
    """

    ENABLED = "enabled"
    PAUSED = "paused"
    REMOVED = "removed"


class CampaignStatus(StrEnum):
    """Stable status values for campaigns."""

    ENABLED = "enabled"
    PAUSED = "paused"
    REMOVED = "removed"


class KeywordStatus(StrEnum):
    """Stable status values for keywords."""

    ENABLED = "enabled"
    PAUSED = "paused"
    REMOVED = "removed"


class AudienceStatus(StrEnum):
    """Stable status values for audiences.

    ``REMOVED`` is the canonical delete signal — adapters translate this
    to a platform-native delete call.
    """

    ENABLED = "enabled"
    REMOVED = "removed"


class ExtensionStatus(StrEnum):
    """Stable status values for ad extensions."""

    ENABLED = "enabled"
    PAUSED = "paused"
    REMOVED = "removed"


class ExtensionKind(StrEnum):
    """Stable identifiers for ad extension categories.

    Matches the existing MCP extension categories in
    ``mureo/AGENTS.md``: sitelinks, callouts, and conversion extensions.
    """

    SITELINK = "sitelink"
    CALLOUT = "callout"
    CONVERSION = "conversion"


class KeywordMatchType(StrEnum):
    """Stable identifiers for keyword match types (search platforms)."""

    EXACT = "exact"
    PHRASE = "phrase"
    BROAD = "broad"


class BidStrategy(StrEnum):
    """Stable identifiers for campaign bidding strategies."""

    MANUAL_CPC = "manual_cpc"
    TARGET_CPA = "target_cpa"
    MAXIMIZE_CONVERSIONS = "maximize_conversions"


# ---------------------------------------------------------------------------
# Entity dataclasses (read-side surface — what providers return)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Campaign:
    """A single campaign as returned by a provider.

    ``account_id`` scopes the campaign to a single ad account; the
    provider instance is assumed to be scoped to one account already, so
    Protocol method signatures do not take ``account_id`` separately.
    """

    id: str
    account_id: str
    name: str
    status: CampaignStatus
    daily_budget_micros: int


@dataclass(frozen=True)
class Ad:
    """A single ad as returned by a provider.

    ``headlines`` and ``descriptions`` are immutable tuples (never
    ``list``) per the Protocol-boundary immutability rule.
    """

    id: str
    account_id: str
    campaign_id: str
    status: AdStatus
    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    final_url: str


@dataclass(frozen=True)
class Keyword:
    """A single keyword as returned by a provider."""

    id: str
    account_id: str
    campaign_id: str
    text: str
    match_type: KeywordMatchType
    status: KeywordStatus


@dataclass(frozen=True)
class KeywordSpec:
    """Creation DTO for a new keyword.

    The ``text`` field must be non-empty; the Protocol layer is purely
    structural (no ``__post_init__`` validation in Phase 1), but adapter
    implementations are responsible for enforcing the non-empty
    invariant at their boundary.
    """

    # Future: enforce via __post_init__ when adapter validation lands (P2-tracked)
    text: str
    match_type: KeywordMatchType
    cpc_bid_micros: int | None = None


@dataclass(frozen=True)
class SearchTerm:
    """A single search-term row (actual user query) for reporting."""

    text: str
    campaign_id: str
    impressions: int
    clicks: int


@dataclass(frozen=True)
class Audience:
    """A single audience as returned by a provider."""

    id: str
    account_id: str
    name: str
    status: AudienceStatus
    size_estimate: int | None = None


@dataclass(frozen=True)
class Extension:
    """A single ad extension as returned by a provider."""

    id: str
    account_id: str
    kind: ExtensionKind
    status: ExtensionStatus
    text: str


@dataclass(frozen=True)
class DailyReportRow:
    """One day's reporting row.

    ``date`` is ``datetime.date`` (day-grain in the account's timezone) —
    never an ``int`` epoch.
    """

    date: date
    impressions: int
    clicks: int
    cost_micros: int
    conversions: float


# ---------------------------------------------------------------------------
# Request / Filter DTOs (write-side surface — what providers accept)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CampaignFilters:
    """All-optional filter DTO for narrowing ``list_campaigns`` results."""

    status: CampaignStatus | None = None
    name_contains: str | None = None


@dataclass(frozen=True)
class CreateCampaignRequest:
    """Required fields for creating a campaign.

    ``daily_budget_micros`` follows the micros convention (see module
    docstring). A future ``Money`` abstraction may replace it in Phase 2.
    """

    name: str
    daily_budget_micros: int
    start_date: date | None = None
    end_date: date | None = None
    bidding_strategy: BidStrategy | None = None


@dataclass(frozen=True)
class UpdateCampaignRequest:
    """Partial-update DTO for campaign mutation — all fields optional.

    Adapters interpret ``None`` as "do not touch this field".
    """

    name: str | None = None
    daily_budget_micros: int | None = None
    status: CampaignStatus | None = None
    bidding_strategy: BidStrategy | None = None


@dataclass(frozen=True)
class CreateAdRequest:
    """Required fields for creating an ad.

    ``headlines`` and ``descriptions`` are immutable tuples — adapters
    that internally hold lists must ``tuple(...)``-convert before
    constructing this DTO.
    """

    ad_group_id: str
    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    final_urls: tuple[str, ...] | None = None
    path1: str | None = None
    path2: str | None = None


@dataclass(frozen=True)
class UpdateAdRequest:
    """Partial-update DTO for ad mutation — all fields optional."""

    headlines: tuple[str, ...] | None = None
    descriptions: tuple[str, ...] | None = None
    final_urls: tuple[str, ...] | None = None
    path1: str | None = None
    path2: str | None = None


@dataclass(frozen=True)
class CreateAudienceRequest:
    """Required fields for creating an audience."""

    name: str
    description: str | None = None
    seed_audience_id: str | None = None


@dataclass(frozen=True)
class ExtensionRequest:
    """Required fields for creating / updating an ad extension."""

    kind: ExtensionKind
    text: str
    url: str | None = None
    description1: str | None = None
    description2: str | None = None


__all__ = [
    "META_OFFSET_100_CURRENCIES",
    "ZERO_DECIMAL_CURRENCIES",
    "minor_units_per_unit",
    "Ad",
    "AdStatus",
    "Audience",
    "AudienceStatus",
    "BidStrategy",
    "Campaign",
    "CampaignFilters",
    "CampaignStatus",
    "CreateAdRequest",
    "CreateAudienceRequest",
    "CreateCampaignRequest",
    "DailyReportRow",
    "Extension",
    "ExtensionKind",
    "ExtensionRequest",
    "ExtensionStatus",
    "Keyword",
    "KeywordMatchType",
    "KeywordSpec",
    "KeywordStatus",
    "SearchTerm",
    "UpdateAdRequest",
    "UpdateCampaignRequest",
]
