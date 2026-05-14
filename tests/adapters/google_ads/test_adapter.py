"""RED-phase tests for ``mureo.adapters.google_ads.GoogleAdsAdapter``.

Pins the Protocol-conformant wrapping behaviour of the Google Ads
adapter (Issue #89, P1-09). Every external Google Ads API call is
mocked via ``Mock(spec=GoogleAdsApiClient)`` + ``AsyncMock`` — no live
API call is made; no real ``google.ads.googleads.client.GoogleAdsClient``
is instantiated.

CTO decisions (planner Open Questions → answers) encoded in these tests:
1. Audience is deferred — ``AudienceProvider`` is NOT implemented and
   not advertised via capabilities.
2. ``UnsupportedOperation`` exception is raised for the documented
   "impossible" transitions (e.g., ``set_keyword_status(ENABLED)``).
3. Day-grain ``daily_report`` is delegated to a new public
   ``GoogleAdsApiClient.search_gaql(query)`` method (added by the
   implementer in a tiny ``client.py`` edit).
4. ``RuntimeError`` raised by the underlying client passes through
   unchanged; only adapter-originated errors are wrapped in
   ``GoogleAdsAdapterError``.
5. ``client._customer_id`` is accessed once with ``# noqa: SLF001``
   to populate ``account_id`` on every dataclass.

Marks: every test is ``@pytest.mark.unit``.
"""

from __future__ import annotations

import asyncio
import inspect
import warnings
from datetime import date
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module ``mureo.adapters.google_ads`` does not exist yet. That is
# correct. The implementer (GREEN phase) will create it.
from mureo.adapters.google_ads import GoogleAdsAdapter
from mureo.adapters.google_ads.errors import (
    GoogleAdsAdapterError,
    UnsupportedOperation,
)
from mureo.core.providers.audience import AudienceProvider
from mureo.core.providers.base import BaseProvider, validate_provider
from mureo.core.providers.campaign import CampaignProvider
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.extension import ExtensionProvider
from mureo.core.providers.keyword import KeywordProvider
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    BidStrategy,
    Campaign,
    CampaignFilters,
    CampaignStatus,
    CreateAdRequest,
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
    clear_registry,
    get_provider,
    list_providers_by_capability,
    register_provider_class,
)
from mureo.google_ads.client import GoogleAdsApiClient

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FAKE_CUSTOMER_ID = "1234567890"


def _make_mock_client() -> Mock:
    """Return a ``Mock(spec=GoogleAdsApiClient)`` with stub async methods.

    Every public async method that the adapter is expected to call is
    pre-attached as an ``AsyncMock`` so attribute typos in the adapter
    surface immediately as ``AttributeError`` (rather than silent
    auto-attribute creation).
    """
    client = Mock(spec=GoogleAdsApiClient)
    # Customer id — adapter reads this private attribute (CTO decision).
    client._customer_id = _FAKE_CUSTOMER_ID
    # Pre-bind the async methods we expect the adapter to hit.
    for name in (
        "list_campaigns",
        "get_campaign",
        "create_campaign",
        "update_campaign",
        "update_campaign_status",
        "create_budget",
        "list_ads",
        "create_ad",
        "update_ad",
        "update_ad_status",
        "list_keywords",
        "add_keywords",
        "remove_keyword",
        "pause_keyword",
        "get_search_terms_report",
        "get_performance_report",
        "search_gaql",
        "list_sitelinks",
        "list_callouts",
        "list_conversion_actions",
        "create_sitelink",
        "create_callout",
        "create_conversion_action",
        "remove_sitelink",
        "remove_callout",
        "remove_conversion_action",
    ):
        setattr(client, name, AsyncMock())
    return client


@pytest.fixture
def mock_client() -> Mock:
    return _make_mock_client()


@pytest.fixture
def adapter(mock_client: Mock) -> GoogleAdsAdapter:
    return GoogleAdsAdapter(client=mock_client)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Reset the module-level registry around each test to prevent
    cross-test contamination of the ``google_ads`` slot."""
    clear_registry()
    yield
    clear_registry()


# ---------------------------------------------------------------------------
# Case 1 — Protocol conformance + class attribute identity
# ---------------------------------------------------------------------------


_EXPECTED_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.READ_CAMPAIGNS,
        Capability.READ_PERFORMANCE,
        Capability.READ_KEYWORDS,
        Capability.READ_SEARCH_TERMS,
        Capability.READ_EXTENSIONS,
        Capability.WRITE_BUDGET,
        Capability.WRITE_CREATIVE,
        Capability.WRITE_KEYWORDS,
        Capability.WRITE_EXTENSIONS,
        Capability.WRITE_CAMPAIGN_STATUS,
    }
)

# Capabilities explicitly NOT declared (Phase 1 deferred):
_FORBIDDEN_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.READ_AUDIENCES,
        Capability.WRITE_AUDIENCES,
        Capability.WRITE_BID,
    }
)


@pytest.mark.unit
def test_class_attributes_match_baseprovider_contract() -> None:
    """``GoogleAdsAdapter`` exposes ``name`` / ``display_name`` /
    ``capabilities`` as class attributes (introspectable without
    instantiating)."""
    assert GoogleAdsAdapter.name == "google_ads"
    assert GoogleAdsAdapter.display_name == "Google Ads"
    assert isinstance(GoogleAdsAdapter.capabilities, frozenset)


@pytest.mark.unit
def test_capabilities_match_exact_expected_set() -> None:
    """The declared ``capabilities`` frozenset matches the CTO-approved
    set EXACTLY — no extras, no missing."""
    assert GoogleAdsAdapter.capabilities == _EXPECTED_CAPABILITIES


@pytest.mark.unit
@pytest.mark.parametrize("forbidden", sorted(_FORBIDDEN_CAPABILITIES, key=str))
def test_forbidden_capabilities_not_declared(forbidden: Capability) -> None:
    """Audience and bid capabilities are explicitly NOT declared in
    Phase 1 (CTO decision: ``mureo/google_ads/`` has no audience
    mixin)."""
    assert forbidden not in GoogleAdsAdapter.capabilities


@pytest.mark.unit
def test_validate_provider_on_class_succeeds() -> None:
    """``validate_provider(GoogleAdsAdapter)`` succeeds — the class
    itself satisfies the BaseProvider contract (BaseProvider attributes
    are class attributes, so ``getattr`` on the class works)."""
    validate_provider(GoogleAdsAdapter)


@pytest.mark.unit
def test_adapter_instance_is_base_provider(adapter: GoogleAdsAdapter) -> None:
    assert isinstance(adapter, BaseProvider)


@pytest.mark.unit
def test_adapter_instance_is_campaign_provider(adapter: GoogleAdsAdapter) -> None:
    assert isinstance(adapter, CampaignProvider)


@pytest.mark.unit
def test_adapter_instance_is_keyword_provider(adapter: GoogleAdsAdapter) -> None:
    assert isinstance(adapter, KeywordProvider)


@pytest.mark.unit
def test_adapter_instance_is_extension_provider(adapter: GoogleAdsAdapter) -> None:
    assert isinstance(adapter, ExtensionProvider)


@pytest.mark.unit
def test_adapter_instance_is_not_audience_provider(adapter: GoogleAdsAdapter) -> None:
    """``AudienceProvider`` is structurally NOT satisfied — no audience
    methods are defined on the adapter (Phase 1 deferral). The
    runtime_checkable check is structural; missing methods make
    isinstance False."""
    assert not isinstance(adapter, AudienceProvider)


# ---------------------------------------------------------------------------
# Case 2 — Constructor validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_init_rejects_non_client() -> None:
    """``__init__`` rejects a non-``GoogleAdsApiClient`` value with
    ``TypeError``."""
    with pytest.raises(TypeError):
        GoogleAdsAdapter(client="not a client")  # type: ignore[arg-type]


@pytest.mark.unit
def test_init_does_no_io(mock_client: Mock) -> None:
    """``__init__`` is pure — no async call is invoked on the client."""
    GoogleAdsAdapter(client=mock_client)
    # Every AsyncMock should have been left untouched.
    for attr_name in (
        "list_campaigns",
        "get_campaign",
        "list_ads",
        "list_keywords",
        "list_sitelinks",
    ):
        method = getattr(mock_client, attr_name)
        assert method.await_count == 0
        assert method.call_count == 0


@pytest.mark.unit
def test_init_stores_client_privately(mock_client: Mock) -> None:
    """The adapter stores the injected client on a private attribute
    (``self._client``)."""
    a = GoogleAdsAdapter(client=mock_client)
    # Accessing _client is fine in a test (we're testing the
    # encapsulated state itself). The contract is "store privately,
    # don't expose publicly".
    assert getattr(a, "_client") is mock_client  # noqa: B009
    assert not hasattr(a, "client")  # no public attribute


# ---------------------------------------------------------------------------
# Case 3 — Registry round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_registry_round_trip_via_register_provider_class() -> None:
    """``register_provider_class(GoogleAdsAdapter)`` round-trips through
    ``get_provider("google_ads")`` and
    ``list_providers_by_capability(READ_CAMPAIGNS)``."""
    entry = register_provider_class(GoogleAdsAdapter)
    assert entry.name == "google_ads"
    assert entry.display_name == "Google Ads"
    assert entry.provider_class is GoogleAdsAdapter
    assert entry.capabilities == _EXPECTED_CAPABILITIES

    got = get_provider("google_ads")
    assert got is entry

    matches = list_providers_by_capability(Capability.READ_CAMPAIGNS)
    assert any(e.name == "google_ads" for e in matches)


# ---------------------------------------------------------------------------
# Case 4 — CampaignProvider methods
# ---------------------------------------------------------------------------


def _campaign_row(
    *,
    cid: str = "111",
    name: str = "Search — JP",
    status: str = "ENABLED",
    budget_micros: int = 5_000_000,
) -> dict[str, Any]:
    """Return a dict matching the real ``map_campaign`` output that the
    adapter consumes."""
    return {
        "id": cid,
        "name": name,
        "status": status,
        "budget_amount_micros": budget_micros,
        "daily_budget": budget_micros / 1_000_000,
        "bidding_strategy_type": "MANUAL_CPC",
    }


@pytest.mark.unit
def test_list_campaigns_maps_to_frozen_dataclasses(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``list_campaigns`` returns a ``tuple[Campaign, ...]`` populated
    from the underlying client's dict output."""
    mock_client.list_campaigns.return_value = [
        _campaign_row(cid="111", name="A", status="ENABLED"),
        _campaign_row(cid="222", name="B", status="PAUSED"),
    ]

    result = adapter.list_campaigns()

    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(c, Campaign) for c in result)
    assert result[0].id == "111"
    assert result[0].account_id == _FAKE_CUSTOMER_ID
    assert result[0].name == "A"
    assert result[0].status == CampaignStatus.ENABLED
    assert result[1].status == CampaignStatus.PAUSED


@pytest.mark.unit
def test_list_campaigns_passes_status_filter(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``CampaignFilters.status=PAUSED`` is forwarded to the client as
    the uppercase enum string."""
    mock_client.list_campaigns.return_value = []
    adapter.list_campaigns(CampaignFilters(status=CampaignStatus.PAUSED))
    # status_filter kwarg is the documented client signature.
    call = mock_client.list_campaigns.await_args
    assert call is not None
    kwargs = call.kwargs
    # Accept either positional or kwarg passing, but value must be PAUSED.
    if "status_filter" in kwargs:
        assert kwargs["status_filter"] == "PAUSED"
    else:
        assert call.args and call.args[0] == "PAUSED"


@pytest.mark.unit
def test_list_campaigns_applies_name_contains_clientside(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``CampaignFilters.name_contains`` is honored client-side after
    fetch (Phase 1 — push-down to GAQL is a future refactor)."""
    mock_client.list_campaigns.return_value = [
        _campaign_row(cid="111", name="Brand Search"),
        _campaign_row(cid="222", name="Generic Search"),
        _campaign_row(cid="333", name="Brand Display"),
    ]
    result = adapter.list_campaigns(CampaignFilters(name_contains="Search"))
    names = {c.name for c in result}
    assert names == {"Brand Search", "Generic Search"}


@pytest.mark.unit
def test_get_campaign_maps_to_dataclass(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.get_campaign.return_value = _campaign_row(cid="111", name="X")
    result = adapter.get_campaign("111")
    assert isinstance(result, Campaign)
    assert result.id == "111"
    mock_client.get_campaign.assert_awaited_once_with("111")


@pytest.mark.unit
def test_get_campaign_missing_raises_key_error(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """Adapter raises ``KeyError(campaign_id)`` when the client returns
    ``None``."""
    mock_client.get_campaign.return_value = None
    with pytest.raises(KeyError) as excinfo:
        adapter.get_campaign("missing-id")
    # The campaign_id should appear in the KeyError message.
    assert "missing-id" in str(excinfo.value)


@pytest.mark.unit
def test_create_campaign_invokes_create_then_refresh(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``create_campaign`` builds a budget (if budget_micros set),
    creates the campaign, and refreshes via ``get_campaign``."""
    mock_client.create_budget.return_value = {"budget_id": "999"}
    mock_client.create_campaign.return_value = {
        "resource_name": f"customers/{_FAKE_CUSTOMER_ID}/campaigns/777",
        "campaign_id": "777",
    }
    mock_client.get_campaign.return_value = _campaign_row(
        cid="777", name="New Search", budget_micros=10_000_000
    )

    out = adapter.create_campaign(
        CreateCampaignRequest(
            name="New Search",
            daily_budget_micros=10_000_000,
            bidding_strategy=BidStrategy.MANUAL_CPC,
        )
    )

    assert isinstance(out, Campaign)
    assert out.id == "777"
    assert mock_client.create_budget.await_count == 1
    assert mock_client.create_campaign.await_count == 1
    # Refresh: get_campaign must be invoked at least once after create.
    assert mock_client.get_campaign.await_count >= 1


@pytest.mark.unit
def test_update_campaign_with_status_triggers_two_client_calls(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``UpdateCampaignRequest(status=PAUSED)`` triggers both
    ``update_campaign`` (other fields) and ``update_campaign_status``."""
    mock_client.update_campaign.return_value = {"resource_name": "x"}
    mock_client.update_campaign_status.return_value = {"resource_name": "x"}
    mock_client.get_campaign.return_value = _campaign_row(cid="111", status="PAUSED")

    out = adapter.update_campaign(
        "111",
        UpdateCampaignRequest(name="renamed", status=CampaignStatus.PAUSED),
    )

    assert isinstance(out, Campaign)
    assert mock_client.update_campaign.await_count == 1
    mock_client.update_campaign_status.assert_awaited_once()
    args, kwargs = mock_client.update_campaign_status.await_args
    # Expect (campaign_id, "PAUSED") in some shape.
    flat = list(args) + list(kwargs.values())
    assert "111" in flat
    assert "PAUSED" in flat


@pytest.mark.unit
def test_update_campaign_without_status_does_not_call_status(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.update_campaign.return_value = {"resource_name": "x"}
    mock_client.get_campaign.return_value = _campaign_row(cid="111")
    adapter.update_campaign("111", UpdateCampaignRequest(name="renamed"))
    assert mock_client.update_campaign_status.await_count == 0


def _ad_row(*, ad_id: str = "9", campaign_id: str = "111") -> dict[str, Any]:
    return {
        "id": ad_id,
        "ad_group_id": "55",
        "ad_group_name": "AG",
        "campaign_id": campaign_id,
        "campaign_name": "C",
        "campaign_status": "ENABLED",
        "status": "ENABLED",
        "type": "RESPONSIVE_SEARCH_AD",
        "ad_strength": "GOOD",
        "final_urls": ["https://example.com"],
        "review_status": "REVIEWED",
        "approval_status": "APPROVED",
        "headlines": ["H1", "H2"],
        "descriptions": ["D1"],
    }


@pytest.mark.unit
def test_list_ads_maps_to_dataclasses(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_ads.return_value = [_ad_row(ad_id="9"), _ad_row(ad_id="10")]
    result = adapter.list_ads("111")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(a, Ad) for a in result)
    assert {a.id for a in result} == {"9", "10"}
    for a in result:
        assert a.account_id == _FAKE_CUSTOMER_ID
        assert a.campaign_id == "111"
        assert isinstance(a.headlines, tuple)
        assert isinstance(a.descriptions, tuple)


@pytest.mark.unit
def test_get_ad_filters_list_and_returns_match(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_ads.return_value = [_ad_row(ad_id="9"), _ad_row(ad_id="10")]
    out = adapter.get_ad("111", "10")
    assert isinstance(out, Ad)
    assert out.id == "10"


@pytest.mark.unit
def test_get_ad_missing_raises_key_error(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_ads.return_value = [_ad_row(ad_id="9")]
    with pytest.raises(KeyError):
        adapter.get_ad("111", "missing")


@pytest.mark.unit
def test_create_ad_calls_client_create_ad_and_refresh(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.create_ad.return_value = {
        "resource_name": "x",
        "ad_id": "9",
    }
    mock_client.list_ads.return_value = [_ad_row(ad_id="9")]
    out = adapter.create_ad(
        "111",
        CreateAdRequest(
            ad_group_id="55",
            headlines=("H1", "H2", "H3"),
            descriptions=("D1", "D2"),
            final_urls=("https://example.com",),
        ),
    )
    assert isinstance(out, Ad)
    assert mock_client.create_ad.await_count == 1


@pytest.mark.unit
def test_update_ad_calls_client_update_ad_and_refresh(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.update_ad.return_value = {"resource_name": "x"}
    mock_client.list_ads.return_value = [_ad_row(ad_id="9")]
    out = adapter.update_ad(
        "111",
        "9",
        UpdateAdRequest(headlines=("New H1",)),
    )
    assert isinstance(out, Ad)
    assert mock_client.update_ad.await_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "expected_str"),
    [
        (AdStatus.ENABLED, "ENABLED"),
        (AdStatus.PAUSED, "PAUSED"),
        (AdStatus.REMOVED, "REMOVED"),
    ],
)
def test_set_ad_status_maps_status_to_upper(
    adapter: GoogleAdsAdapter,
    mock_client: Mock,
    status: AdStatus,
    expected_str: str,
) -> None:
    """``set_ad_status`` calls ``client.update_ad_status`` with the
    upper-case string of the enum value (REMOVED also uses the same
    method per CTO Open Question #2: the existing client already routes
    REMOVED to a remove op internally)."""
    mock_client.update_ad_status.return_value = {"resource_name": "x"}
    mock_client.list_ads.return_value = [_ad_row(ad_id="9")]

    out = adapter.set_ad_status("111", "9", status)
    assert isinstance(out, Ad)

    mock_client.update_ad_status.assert_awaited_once()
    args, kwargs = mock_client.update_ad_status.await_args
    flat = list(args) + list(kwargs.values())
    assert "9" in flat
    assert expected_str in flat


@pytest.mark.unit
def test_daily_report_uses_search_gaql(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``daily_report`` delegates to ``client.search_gaql`` (CTO
    decision: a tiny new public method on ``GoogleAdsApiClient`` —
    implementer adds it). Returns a tuple of ``DailyReportRow``."""
    mock_client.search_gaql.return_value = [
        {
            "date": "2024-01-01",
            "impressions": 100,
            "clicks": 10,
            "cost_micros": 5_000_000,
            "conversions": 1.0,
        },
        {
            "date": "2024-01-02",
            "impressions": 150,
            "clicks": 12,
            "cost_micros": 6_000_000,
            "conversions": 2.5,
        },
    ]
    out = adapter.daily_report("111", date(2024, 1, 1), date(2024, 1, 2))
    assert isinstance(out, tuple)
    assert all(isinstance(r, DailyReportRow) for r in out)
    assert out[0].date == date(2024, 1, 1)
    assert out[0].cost_micros == 5_000_000
    mock_client.search_gaql.assert_awaited_once()


@pytest.mark.unit
def test_daily_report_iso8601_dates_in_query(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """The GAQL passed to ``search_gaql`` contains the ISO-8601
    ``BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`` clause — no string
    interpolation of unvalidated input. ``datetime.date.isoformat()``
    output is locked by Python."""
    mock_client.search_gaql.return_value = []
    adapter.daily_report("111", date(2024, 1, 1), date(2024, 1, 31))
    args, kwargs = mock_client.search_gaql.await_args
    query = (args[0] if args else kwargs.get("query")) or ""
    assert isinstance(query, str)
    assert "2024-01-01" in query
    assert "2024-01-31" in query
    # The campaign_id must also appear (as a digit-only literal —
    # _validate_id contract upstream).
    assert "111" in query


@pytest.mark.unit
def test_daily_report_rejects_non_digit_campaign_id(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """GAQL injection guard: ``campaign_id`` must be digits-only. An
    attacker-controlled value like ``"' OR 1=1 --"`` MUST be rejected
    before the query is built (either via ``ValueError`` from the GAQL
    validator pipeline or via ``GoogleAdsAdapterError``).
    """
    mock_client.search_gaql.return_value = []
    with pytest.raises((ValueError, GoogleAdsAdapterError)):
        adapter.daily_report("' OR 1=1 --", date(2024, 1, 1), date(2024, 1, 2))
    # No call must reach the client.
    assert mock_client.search_gaql.await_count == 0


# ---------------------------------------------------------------------------
# Case 5 — KeywordProvider methods
# ---------------------------------------------------------------------------


def _keyword_row(*, kid: str = "k1", campaign_id: str = "111") -> dict[str, Any]:
    return {
        "id": kid,
        "campaign_id": campaign_id,
        "campaign_name": "C",
        "ad_group_id": "55",
        "ad_group_name": "AG",
        "text": "buy widgets",
        "match_type": "EXACT",
        "status": "ENABLED",
        "approval_status": "APPROVED",
    }


@pytest.mark.unit
def test_list_keywords_maps_to_dataclasses(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_keywords.return_value = [
        _keyword_row(kid="k1"),
        _keyword_row(kid="k2"),
    ]
    result = adapter.list_keywords("111")
    assert isinstance(result, tuple)
    assert all(isinstance(k, Keyword) for k in result)
    assert {k.id for k in result} == {"k1", "k2"}
    for k in result:
        assert k.account_id == _FAKE_CUSTOMER_ID
        assert k.campaign_id == "111"
        assert k.match_type == KeywordMatchType.EXACT


@pytest.mark.unit
def test_add_keywords_accepts_sequence_types(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``keywords`` is typed ``Sequence[KeywordSpec]`` — list, tuple,
    and any other Sequence must all be accepted (covariance, read-only
    iteration only)."""
    mock_client.add_keywords.return_value = [{"resource_name": "x"}]
    mock_client.list_keywords.return_value = [_keyword_row(kid="k1")]
    spec = KeywordSpec(text="t", match_type=KeywordMatchType.EXACT)

    out_list = adapter.add_keywords("111", [spec])
    out_tuple = adapter.add_keywords("111", (spec,))

    assert isinstance(out_list, tuple)
    assert all(isinstance(k, Keyword) for k in out_list)
    assert isinstance(out_tuple, tuple)
    assert all(isinstance(k, Keyword) for k in out_tuple)


@pytest.mark.unit
def test_set_keyword_status_removed_calls_remove_keyword(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.remove_keyword.return_value = {"resource_name": "x"}
    mock_client.list_keywords.return_value = [_keyword_row(kid="k1")]
    out = adapter.set_keyword_status("111", "k1", KeywordStatus.REMOVED)
    # Result type contract — when adapter returns the post-mutation
    # read, it must be a ``Keyword`` instance.
    assert isinstance(out, Keyword)
    assert mock_client.remove_keyword.await_count == 1


@pytest.mark.unit
def test_set_keyword_status_paused_calls_pause_keyword(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.pause_keyword.return_value = {"resource_name": "x"}
    mock_client.list_keywords.return_value = [
        _keyword_row(kid="k1"),
    ]
    adapter.set_keyword_status("111", "k1", KeywordStatus.PAUSED)
    assert mock_client.pause_keyword.await_count == 1


@pytest.mark.unit
def test_set_keyword_status_enabled_raises_unsupported(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """CTO Open Question #2 decision: ``ENABLED`` for keywords is not
    supported by the existing client — raise ``UnsupportedOperation``."""
    with pytest.raises(UnsupportedOperation):
        adapter.set_keyword_status("111", "k1", KeywordStatus.ENABLED)
    # No client mutation may be issued.
    assert mock_client.pause_keyword.await_count == 0
    assert mock_client.remove_keyword.await_count == 0


@pytest.mark.unit
def test_unsupported_operation_subclasses_adapter_error() -> None:
    """``UnsupportedOperation`` is a subclass of ``GoogleAdsAdapterError``
    so callers can ``except GoogleAdsAdapterError`` broadly."""
    assert issubclass(UnsupportedOperation, GoogleAdsAdapterError)
    assert issubclass(GoogleAdsAdapterError, RuntimeError)


@pytest.mark.unit
def test_search_terms_maps_to_dataclasses(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.get_search_terms_report.return_value = [
        {
            "search_term": "buy widgets cheap",
            "impressions": 50,
            "clicks": 5,
            "cost_micros": 1_000_000,
            "conversions": 0.5,
            "ctr": 0.1,
        }
    ]
    result = adapter.search_terms("111", date(2024, 1, 1), date(2024, 1, 31))
    assert isinstance(result, tuple)
    assert len(result) == 1
    assert isinstance(result[0], SearchTerm)
    assert result[0].text == "buy widgets cheap"
    assert result[0].campaign_id == "111"


# ---------------------------------------------------------------------------
# Case 6 — ExtensionProvider methods (3 kinds × 3 ops)
# ---------------------------------------------------------------------------


def _sitelink_row(*, eid: str = "s1") -> dict[str, Any]:
    return {
        "id": eid,
        "text": "More",
        "status": "ENABLED",
    }


def _callout_row(*, eid: str = "c1") -> dict[str, Any]:
    return {
        "id": eid,
        "text": "Free shipping",
        "status": "ENABLED",
    }


def _conversion_row(*, eid: str = "cv1") -> dict[str, Any]:
    return {
        "id": eid,
        "name": "Purchase",
        "status": "ENABLED",
    }


@pytest.mark.unit
def test_list_extensions_sitelink_dispatches_to_list_sitelinks(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_sitelinks.return_value = [_sitelink_row(eid="s1")]
    result = adapter.list_extensions("111", ExtensionKind.SITELINK)
    assert isinstance(result, tuple)
    assert all(isinstance(e, Extension) for e in result)
    assert result[0].kind == ExtensionKind.SITELINK
    assert mock_client.list_sitelinks.await_count == 1
    assert mock_client.list_callouts.await_count == 0
    assert mock_client.list_conversion_actions.await_count == 0


@pytest.mark.unit
def test_list_extensions_callout_dispatches_to_list_callouts(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_callouts.return_value = [_callout_row(eid="c1")]
    result = adapter.list_extensions("111", ExtensionKind.CALLOUT)
    assert all(e.kind == ExtensionKind.CALLOUT for e in result)
    assert mock_client.list_callouts.await_count == 1


@pytest.mark.unit
def test_list_extensions_conversion_dispatches_to_list_conversion_actions(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_conversion_actions.return_value = [_conversion_row(eid="cv1")]
    result = adapter.list_extensions("111", ExtensionKind.CONVERSION)
    assert all(e.kind == ExtensionKind.CONVERSION for e in result)
    assert mock_client.list_conversion_actions.await_count == 1


@pytest.mark.unit
def test_add_extension_sitelink_calls_create_sitelink(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.create_sitelink.return_value = {"resource_name": "x", "id": "s9"}
    mock_client.list_sitelinks.return_value = [_sitelink_row(eid="s9")]
    out = adapter.add_extension(
        "111",
        ExtensionKind.SITELINK,
        ExtensionRequest(kind=ExtensionKind.SITELINK, text="More", url="https://x"),
    )
    assert isinstance(out, Extension)
    assert mock_client.create_sitelink.await_count == 1


@pytest.mark.unit
def test_add_extension_callout_calls_create_callout(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.create_callout.return_value = {"resource_name": "x", "id": "c9"}
    mock_client.list_callouts.return_value = [_callout_row(eid="c9")]
    adapter.add_extension(
        "111",
        ExtensionKind.CALLOUT,
        ExtensionRequest(kind=ExtensionKind.CALLOUT, text="Fast"),
    )
    assert mock_client.create_callout.await_count == 1


@pytest.mark.unit
def test_add_extension_conversion_calls_create_conversion_action(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.create_conversion_action.return_value = {
        "resource_name": "x",
        "id": "cv9",
    }
    mock_client.list_conversion_actions.return_value = [_conversion_row(eid="cv9")]
    adapter.add_extension(
        "111",
        ExtensionKind.CONVERSION,
        ExtensionRequest(kind=ExtensionKind.CONVERSION, text="Purchase"),
    )
    assert mock_client.create_conversion_action.await_count == 1


@pytest.mark.unit
def test_set_extension_status_removed_sitelink_calls_remove_sitelink(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_sitelinks.return_value = [_sitelink_row(eid="s1")]
    mock_client.remove_sitelink.return_value = {"resource_name": "x"}
    out = adapter.set_extension_status("111", "s1", ExtensionStatus.REMOVED)
    assert isinstance(out, Extension)
    assert mock_client.remove_sitelink.await_count == 1


@pytest.mark.unit
def test_set_extension_status_removed_callout_calls_remove_callout(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``set_extension_status`` resolves the kind by inspecting the
    available lists (Phase 1 — caller does not pass kind; adapter must
    look up). Set up so the id is found only under callouts."""
    mock_client.list_sitelinks.return_value = []
    mock_client.list_callouts.return_value = [_callout_row(eid="c1")]
    mock_client.list_conversion_actions.return_value = []
    mock_client.remove_callout.return_value = {"resource_name": "x"}
    adapter.set_extension_status("111", "c1", ExtensionStatus.REMOVED)
    assert mock_client.remove_callout.await_count == 1
    assert mock_client.remove_sitelink.await_count == 0


@pytest.mark.unit
def test_set_extension_status_removed_conversion_calls_remove_conversion(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_sitelinks.return_value = []
    mock_client.list_callouts.return_value = []
    mock_client.list_conversion_actions.return_value = [_conversion_row(eid="cv1")]
    mock_client.remove_conversion_action.return_value = {"resource_name": "x"}
    adapter.set_extension_status("111", "cv1", ExtensionStatus.REMOVED)
    assert mock_client.remove_conversion_action.await_count == 1


@pytest.mark.unit
@pytest.mark.parametrize("status", [ExtensionStatus.ENABLED, ExtensionStatus.PAUSED])
def test_set_extension_status_enabled_or_paused_raises_unsupported(
    adapter: GoogleAdsAdapter,
    mock_client: Mock,
    status: ExtensionStatus,
) -> None:
    """CTO Open Question #2: ``ENABLED`` / ``PAUSED`` for extensions
    are not supported by existing client mixins → raise
    ``UnsupportedOperation``."""
    # Make sure the id is locatable so we can hit the dispatch branch
    # instead of a "not found" path.
    mock_client.list_sitelinks.return_value = [_sitelink_row(eid="s1")]
    mock_client.list_callouts.return_value = []
    mock_client.list_conversion_actions.return_value = []
    with pytest.raises(UnsupportedOperation):
        adapter.set_extension_status("111", "s1", status)
    assert mock_client.remove_sitelink.await_count == 0
    assert mock_client.remove_callout.await_count == 0
    assert mock_client.remove_conversion_action.await_count == 0


# ---------------------------------------------------------------------------
# Case 7 — Sync/async bridge
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_methods_callable_from_outside_loop(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """Sync Protocol methods are callable from a thread with no
    running loop (the default for pytest sync tests)."""
    mock_client.list_campaigns.return_value = [_campaign_row()]
    result = adapter.list_campaigns()
    assert isinstance(result, tuple)


@pytest.mark.unit
def test_calling_from_running_loop_raises_runtime_error(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """Calling any adapter method from inside an active event loop
    raises ``RuntimeError`` with a clear message — Phase 1 sync
    Protocol cannot reentrantly call ``asyncio.run``."""
    mock_client.list_campaigns.return_value = []

    async def _inner() -> None:
        # This must raise — adapter detects the running loop.
        adapter.list_campaigns()

    with pytest.raises(RuntimeError):
        asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Case 8 — Error pass-through (CTO decision: pass-through, not wrap)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_client_runtime_error_passes_through_unwrapped(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``RuntimeError`` raised by ``GoogleAdsApiClient._wrap_mutate_error``
    propagates unchanged (CTO Open Question #4 decision)."""
    mock_client.update_campaign.side_effect = RuntimeError(
        "An error occurred while processing campaign update"
    )
    with pytest.raises(RuntimeError) as excinfo:
        adapter.update_campaign("111", UpdateCampaignRequest(name="renamed"))
    # Must NOT be wrapped in GoogleAdsAdapterError.
    assert not isinstance(excinfo.value, GoogleAdsAdapterError)
    assert "campaign update" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Case 9 — Public surface hygiene (no unintended async leaks)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_protocol_methods_are_sync(adapter: GoogleAdsAdapter) -> None:
    """Every Protocol method on the adapter is synchronous — the
    sync/async bridge is the adapter's responsibility, not the
    caller's."""
    for method_name in (
        "list_campaigns",
        "get_campaign",
        "create_campaign",
        "update_campaign",
        "list_ads",
        "get_ad",
        "create_ad",
        "update_ad",
        "set_ad_status",
        "daily_report",
        "list_keywords",
        "add_keywords",
        "set_keyword_status",
        "search_terms",
        "list_extensions",
        "add_extension",
        "set_extension_status",
    ):
        method = getattr(adapter, method_name)
        assert not inspect.iscoroutinefunction(
            method
        ), f"{method_name} must be a sync method on the Phase 1 adapter"


@pytest.mark.unit
def test_adapter_does_not_advertise_audience_methods(
    adapter: GoogleAdsAdapter,
) -> None:
    """Phase 1 deferral: the audience Protocol's methods are
    intentionally absent from the adapter (NOT stubs that raise)."""
    for method_name in (
        "list_audiences",
        "get_audience",
        "create_audience",
        "set_audience_status",
    ):
        assert not hasattr(
            adapter, method_name
        ), f"{method_name} must NOT be defined in Phase 1 (audience deferred)"


@pytest.mark.unit
def test_no_runtime_warnings_on_construction(mock_client: Mock) -> None:
    """Constructing the adapter does not emit a ``DeprecationWarning``
    / ``RuntimeWarning`` / ``ResourceWarning``."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        GoogleAdsAdapter(client=mock_client)


# ---------------------------------------------------------------------------
# Case 10 — Phase 1 silent-drop guards (reviewer follow-up)
#
# The reviewer flagged that the original implementation silently dropped
# request fields the underlying client did not yet support (budget on
# update, schedule on create). Phase 1 contract: raise
# ``UnsupportedOperation`` so callers see the gap instead of a silent
# no-op. The third test pins the budget-micros precision fix
# (``amount_micros`` int passes through unscaled — no float round-trip).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_campaign_with_budget_raises_unsupported(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``UpdateCampaignRequest.daily_budget_micros`` is not yet wired in
    Phase 1; supplying it must raise ``UnsupportedOperation`` rather
    than being silently dropped by the adapter."""
    request = UpdateCampaignRequest(daily_budget_micros=5_000_000)
    with pytest.raises(UnsupportedOperation, match="daily_budget_micros"):
        adapter.update_campaign("111", request)
    # No client mutation may be issued.
    assert mock_client.update_campaign.await_count == 0
    assert mock_client.update_campaign_status.await_count == 0


@pytest.mark.unit
def test_create_campaign_with_start_date_raises_unsupported(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``CreateCampaignRequest.start_date`` is not yet wired in Phase 1;
    supplying it must raise ``UnsupportedOperation``."""
    request = CreateCampaignRequest(
        name="Test",
        daily_budget_micros=1_000_000,
        start_date=date(2026, 1, 1),
    )
    with pytest.raises(UnsupportedOperation, match="start_date"):
        adapter.create_campaign(request)
    assert mock_client.create_campaign.await_count == 0
    assert mock_client.create_budget.await_count == 0


@pytest.mark.unit
def test_create_campaign_with_end_date_raises_unsupported(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """``CreateCampaignRequest.end_date`` follows the same Phase 1
    contract as ``start_date`` — silent drop is unacceptable."""
    request = CreateCampaignRequest(
        name="Test",
        daily_budget_micros=1_000_000,
        end_date=date(2026, 12, 31),
    )
    with pytest.raises(UnsupportedOperation, match="end_date"):
        adapter.create_campaign(request)
    assert mock_client.create_campaign.await_count == 0
    assert mock_client.create_budget.await_count == 0


@pytest.mark.unit
def test_create_campaign_passes_amount_micros_directly(
    adapter: GoogleAdsAdapter, mock_client: Mock
) -> None:
    """The adapter forwards ``daily_budget_micros`` to
    ``client.create_budget`` via the integer ``amount_micros`` key —
    not via the float ``amount`` key — so non-multiple-of-1_000_000
    micros (e.g. an odd-cent value) are not truncated by the
    ``int(amount * 1_000_000)`` round-trip inside the client."""
    mock_client.create_budget.return_value = {"budget_id": "999"}
    mock_client.create_campaign.return_value = {
        "resource_name": f"customers/{_FAKE_CUSTOMER_ID}/campaigns/777",
        "campaign_id": "777",
    }
    mock_client.get_campaign.return_value = _campaign_row(
        cid="777", name="Precision", budget_micros=1_000_001
    )

    odd_micros = 1_000_001
    adapter.create_campaign(
        CreateCampaignRequest(
            name="Precision",
            daily_budget_micros=odd_micros,
        )
    )

    mock_client.create_budget.assert_awaited_once()
    call_args = mock_client.create_budget.await_args
    # The client's create_budget accepts a single ``params: dict`` —
    # extract whichever way it was called.
    sent_params = (
        call_args.args[0] if call_args.args else call_args.kwargs.get("params")
    )
    assert isinstance(sent_params, dict)
    assert sent_params.get("amount_micros") == odd_micros
    # No float ``amount`` fallback when micros are available — the two
    # keys are mutually exclusive per client contract.
    assert "amount" not in sent_params
