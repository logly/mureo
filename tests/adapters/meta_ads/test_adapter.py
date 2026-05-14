"""RED-phase tests for ``mureo.adapters.meta_ads.MetaAdsAdapter``.

Pins the Protocol-conformant wrapping behaviour of the Meta Ads adapter
(Issue #89, P1-10). Every external Meta Marketing API call is mocked via
``Mock(spec=MetaAdsApiClient)`` + ``AsyncMock`` — no live httpx request
is issued; no real Meta Graph API call is made.

CTO decisions encoded in these tests
------------------------------------
1. ``MetaAdsApiClient.insights_time_range`` is a new public method on
   the existing client (implementer adds it during GREEN). Tests
   pre-attach an ``AsyncMock`` for that name on the spec'd Mock so the
   adapter can call it without raising ``AttributeError``.
2. ``objective`` for ``create_campaign`` is hard-coded to
   ``"OUTCOME_TRAFFIC"`` in Phase 1.
3. ``CreateAdRequest.headlines[0]`` is interpreted as the ``creative_id``
   in Phase 1 (documented hack). Any other tuple length raises
   ``UnsupportedOperation``.
4. Lookalike audiences default to ``country="JP"`` and ``ratio=0.01``
   when ``CreateAudienceRequest.seed_audience_id`` is set.
5. ``AdSet`` hierarchy is hidden behind the adapter — ``list_ads``
   flattens AdSet→Ad with N+1 client calls in Phase 1.

Marks: every test is ``@pytest.mark.unit``.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import date
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module ``mureo.adapters.meta_ads`` does not exist yet. That is correct.
# The implementer (GREEN phase) will create it.
from mureo.adapters.meta_ads import MetaAdsAdapter
from mureo.adapters.meta_ads.errors import (
    MetaAdsAdapterError,
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
    UpdateAdRequest,
    UpdateCampaignRequest,
)
from mureo.core.providers.registry import (
    clear_registry,
    get_provider,
    list_providers_by_capability,
    register_provider_class,
)
from mureo.meta_ads.client import MetaAdsApiClient

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FAKE_AD_ACCOUNT_ID = "act_1234567890"


def _make_mock_client() -> Mock:
    """Return a ``Mock(spec=MetaAdsApiClient)`` with stub async methods.

    Every public async method that the adapter is expected to call is
    pre-attached as an ``AsyncMock`` so attribute typos in the adapter
    surface immediately as ``AttributeError`` (rather than silent
    auto-attribute creation).
    """
    client = Mock(spec=MetaAdsApiClient)
    client._ad_account_id = _FAKE_AD_ACCOUNT_ID
    for name in (
        "list_campaigns",
        "get_campaign",
        "create_campaign",
        "update_campaign",
        "pause_campaign",
        "enable_campaign",
        "list_ad_sets",
        "get_ad_set",
        "list_ads",
        "get_ad",
        "create_ad",
        "update_ad",
        "pause_ad",
        "enable_ad",
        "list_custom_audiences",
        "get_custom_audience",
        "create_custom_audience",
        "delete_custom_audience",
        "create_lookalike_audience",
        # NEW public method added in P1-10 GREEN (CTO decision #1).
        "insights_time_range",
    ):
        setattr(client, name, AsyncMock())
    return client


@pytest.fixture
def mock_client() -> Mock:
    return _make_mock_client()


@pytest.fixture
def adapter(mock_client: Mock) -> MetaAdsAdapter:
    return MetaAdsAdapter(client=mock_client)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Reset the module-level registry around each test to prevent
    cross-test contamination of the ``meta_ads`` slot."""
    clear_registry()
    yield
    clear_registry()


# ---------------------------------------------------------------------------
# Row factories (dicts that mirror the real Meta API shape)
# ---------------------------------------------------------------------------


def _campaign_row(
    *,
    cid: str = "c111",
    name: str = "Brand Awareness — JP",
    status: str = "ACTIVE",
    daily_budget_cents: str = "1500",  # Meta returns budget as cents-string
) -> dict[str, Any]:
    return {
        "id": cid,
        "name": name,
        "status": status,
        "daily_budget": daily_budget_cents,
        "objective": "OUTCOME_TRAFFIC",
    }


def _ad_set_row(*, ad_set_id: str = "as1", campaign_id: str = "c111") -> dict[str, Any]:
    return {
        "id": ad_set_id,
        "campaign_id": campaign_id,
        "name": f"AdSet {ad_set_id}",
        "status": "ACTIVE",
    }


def _ad_row(
    *,
    ad_id: str = "ad1",
    ad_set_id: str = "as1",
    campaign_id: str = "c111",
    status: str = "ACTIVE",
) -> dict[str, Any]:
    return {
        "id": ad_id,
        "adset_id": ad_set_id,
        "campaign_id": campaign_id,
        "status": status,
        "name": f"Ad {ad_id}",
        "creative": {
            "object_story_spec": {
                "link_data": {"link": "https://example.com"},
            }
        },
    }


def _audience_row(
    *,
    aud_id: str = "aud_1",
    name: str = "Site visitors 30d",
    subtype: str = "CUSTOM",
    size: int | None = 12_345,
) -> dict[str, Any]:
    return {
        "id": aud_id,
        "name": name,
        "subtype": subtype,
        "approximate_count_lower_bound": size,
        "approximate_count_upper_bound": size,
        "delivery_status": {"code": 200, "description": "Ready"},
        "description": "test",
    }


# ---------------------------------------------------------------------------
# Case 1 — Class attributes + Protocol conformance
# ---------------------------------------------------------------------------


_EXPECTED_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.READ_CAMPAIGNS,
        Capability.READ_PERFORMANCE,
        Capability.READ_AUDIENCES,
        Capability.WRITE_BUDGET,
        Capability.WRITE_CREATIVE,
        Capability.WRITE_CAMPAIGN_STATUS,
        Capability.WRITE_AUDIENCES,
    }
)

# Capabilities explicitly NOT declared (Meta has no counterpart):
_FORBIDDEN_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.READ_KEYWORDS,
        Capability.READ_SEARCH_TERMS,
        Capability.READ_EXTENSIONS,
        Capability.WRITE_KEYWORDS,
        Capability.WRITE_EXTENSIONS,
        Capability.WRITE_BID,
    }
)


@pytest.mark.unit
def test_class_attributes_match_baseprovider_contract() -> None:
    assert MetaAdsAdapter.name == "meta_ads"
    assert MetaAdsAdapter.display_name == "Meta Ads"
    assert isinstance(MetaAdsAdapter.capabilities, frozenset)


@pytest.mark.unit
def test_capabilities_match_exact_expected_set() -> None:
    """Capabilities are EXACTLY the 7 CTO-approved members — no extras,
    no missing."""
    assert MetaAdsAdapter.capabilities == _EXPECTED_CAPABILITIES


@pytest.mark.unit
@pytest.mark.parametrize("forbidden", sorted(_FORBIDDEN_CAPABILITIES, key=str))
def test_forbidden_capabilities_not_declared(forbidden: Capability) -> None:
    """Keyword / extension / bid capabilities are explicitly NOT declared
    (Meta has no counterpart)."""
    assert forbidden not in MetaAdsAdapter.capabilities


@pytest.mark.unit
def test_validate_provider_on_class_succeeds() -> None:
    validate_provider(MetaAdsAdapter)


@pytest.mark.unit
def test_adapter_instance_is_base_provider(adapter: MetaAdsAdapter) -> None:
    assert isinstance(adapter, BaseProvider)


@pytest.mark.unit
def test_adapter_instance_is_campaign_provider(adapter: MetaAdsAdapter) -> None:
    assert isinstance(adapter, CampaignProvider)


@pytest.mark.unit
def test_adapter_instance_is_audience_provider(adapter: MetaAdsAdapter) -> None:
    """``AudienceProvider`` IS implemented (Meta has Custom + Lookalike
    audiences). This is the headline difference vs. P1-09."""
    assert isinstance(adapter, AudienceProvider)


@pytest.mark.unit
def test_adapter_instance_is_not_keyword_provider(adapter: MetaAdsAdapter) -> None:
    """Meta has no keyword surface — structural check naturally fails
    because ``list_keywords`` / ``add_keywords`` / ``set_keyword_status``
    are not defined on the adapter."""
    assert not isinstance(adapter, KeywordProvider)


@pytest.mark.unit
def test_adapter_instance_is_not_extension_provider(adapter: MetaAdsAdapter) -> None:
    """Meta has no sitelink/callout/conversion-extension surface."""
    assert not isinstance(adapter, ExtensionProvider)


# ---------------------------------------------------------------------------
# Case 2 — Constructor validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_init_rejects_non_client() -> None:
    """``__init__`` rejects a non-``MetaAdsApiClient`` value with
    ``TypeError``."""
    with pytest.raises(TypeError):
        MetaAdsAdapter(client="not a client")  # type: ignore[arg-type]


@pytest.mark.unit
def test_init_does_no_io(mock_client: Mock) -> None:
    """``__init__`` is pure — no async call is invoked on the client."""
    MetaAdsAdapter(client=mock_client)
    for attr_name in (
        "list_campaigns",
        "list_ad_sets",
        "list_ads",
        "list_custom_audiences",
        "insights_time_range",
    ):
        method = getattr(mock_client, attr_name)
        assert method.await_count == 0
        assert method.call_count == 0


@pytest.mark.unit
def test_init_stores_client_privately(mock_client: Mock) -> None:
    """Adapter stores the injected client on a private attribute."""
    a = MetaAdsAdapter(client=mock_client)
    assert getattr(a, "_client") is mock_client  # noqa: B009
    assert not hasattr(a, "client")  # no public attribute


# ---------------------------------------------------------------------------
# Case 3 — Registry round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_registry_round_trip_includes_meta_ads() -> None:
    """``register_provider_class(MetaAdsAdapter)`` round-trips through
    ``get_provider("meta_ads")`` and is listed under READ_AUDIENCES."""
    entry = register_provider_class(MetaAdsAdapter)
    assert entry.name == "meta_ads"
    assert entry.display_name == "Meta Ads"
    assert entry.provider_class is MetaAdsAdapter
    assert entry.capabilities == _EXPECTED_CAPABILITIES

    got = get_provider("meta_ads")
    assert got is entry

    # The big differentiator from P1-09: ``READ_AUDIENCES`` is declared.
    matches = list_providers_by_capability(Capability.READ_AUDIENCES)
    assert any(e.name == "meta_ads" for e in matches)


# ---------------------------------------------------------------------------
# Case 4 — CampaignProvider — campaigns
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_campaigns_maps_to_frozen_dataclasses(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_campaigns.return_value = [
        _campaign_row(cid="c1", name="A", status="ACTIVE", daily_budget_cents="500"),
        _campaign_row(cid="c2", name="B", status="PAUSED", daily_budget_cents="1000"),
    ]
    result = adapter.list_campaigns()
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(c, Campaign) for c in result)
    assert result[0].id == "c1"
    assert result[0].account_id == _FAKE_AD_ACCOUNT_ID
    assert result[0].name == "A"
    assert result[0].status == CampaignStatus.ENABLED
    # cents → micros conversion (Phase 1 boundary): 500 cents = 5_000_000 micros.
    assert result[0].daily_budget_micros == 5_000_000
    assert result[1].status == CampaignStatus.PAUSED
    assert result[1].daily_budget_micros == 10_000_000


@pytest.mark.unit
def test_list_campaigns_status_filter_upper_wire(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """``CampaignFilters.status=PAUSED`` is forwarded to the client as
    the uppercase Meta wire-string ``"PAUSED"``."""
    mock_client.list_campaigns.return_value = []
    adapter.list_campaigns(CampaignFilters(status=CampaignStatus.PAUSED))
    call = mock_client.list_campaigns.await_args
    assert call is not None
    flat = list(call.args) + list(call.kwargs.values())
    assert "PAUSED" in flat


@pytest.mark.unit
def test_list_campaigns_status_enabled_maps_to_active_wire(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """``CampaignStatus.ENABLED`` is converted to Meta's ``"ACTIVE"`` on
    the way OUT (write-side mapping is the inverse of the read mapping)."""
    mock_client.list_campaigns.return_value = []
    adapter.list_campaigns(CampaignFilters(status=CampaignStatus.ENABLED))
    call = mock_client.list_campaigns.await_args
    assert call is not None
    flat = list(call.args) + list(call.kwargs.values())
    assert "ACTIVE" in flat


@pytest.mark.unit
def test_list_campaigns_applies_name_contains_clientside(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_campaigns.return_value = [
        _campaign_row(cid="1", name="Brand Awareness"),
        _campaign_row(cid="2", name="Brand Conversion"),
        _campaign_row(cid="3", name="Retargeting Display"),
    ]
    result = adapter.list_campaigns(CampaignFilters(name_contains="Brand"))
    names = {c.name for c in result}
    assert names == {"Brand Awareness", "Brand Conversion"}


@pytest.mark.unit
def test_get_campaign_maps_to_dataclass(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    mock_client.get_campaign.return_value = _campaign_row(cid="c111", name="X")
    result = adapter.get_campaign("c111")
    assert isinstance(result, Campaign)
    assert result.id == "c111"
    mock_client.get_campaign.assert_awaited_once_with("c111")


@pytest.mark.unit
def test_get_campaign_unknown_status_raises_value_error(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Meta returns ``PENDING_REVIEW`` for in-review campaigns; Phase 1
    raises ``ValueError`` (no silent fallback)."""
    mock_client.get_campaign.return_value = _campaign_row(
        cid="c1", status="PENDING_REVIEW"
    )
    with pytest.raises(ValueError):
        adapter.get_campaign("c1")


@pytest.mark.unit
def test_create_campaign_basic_hardcodes_objective(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """CTO decision #2: ``objective`` is hardcoded to ``"OUTCOME_TRAFFIC"``;
    initial status is ``"PAUSED"``; the budget micros → cents conversion
    happens at the boundary (``daily_budget = micros // 10_000``)."""
    mock_client.create_campaign.return_value = {"id": "c777"}
    mock_client.get_campaign.return_value = _campaign_row(
        cid="c777", name="New", daily_budget_cents="1500"
    )
    out = adapter.create_campaign(
        CreateCampaignRequest(
            name="New",
            daily_budget_micros=15_000_000,  # 15.0 USD → 1500 cents
        )
    )
    assert isinstance(out, Campaign)
    assert out.id == "c777"
    mock_client.create_campaign.assert_awaited_once()
    call_kwargs = mock_client.create_campaign.await_args.kwargs
    call_args = mock_client.create_campaign.await_args.args
    flat_values = list(call_args) + list(call_kwargs.values())
    # Objective is hardcoded.
    assert "OUTCOME_TRAFFIC" in flat_values
    # Initial status defaults to PAUSED so users do not accidentally
    # spend on PAUSED-by-default.
    assert "PAUSED" in flat_values
    # Budget: 15_000_000 micros = 1500 cents.
    if "daily_budget" in call_kwargs:
        assert call_kwargs["daily_budget"] == 1500
    else:
        assert 1500 in flat_values
    # Refresh.
    assert mock_client.get_campaign.await_count >= 1


@pytest.mark.unit
def test_create_campaign_with_start_date_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Phase 1: ``start_date`` is not yet wired into Meta's
    ``start_time``/``stop_time`` — supplying it must raise
    ``UnsupportedOperation`` rather than be silently dropped."""
    with pytest.raises(UnsupportedOperation, match="start_date"):
        adapter.create_campaign(
            CreateCampaignRequest(
                name="X",
                daily_budget_micros=1_000_000,
                start_date=date(2026, 6, 1),
            )
        )
    assert mock_client.create_campaign.await_count == 0


@pytest.mark.unit
def test_create_campaign_with_end_date_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    with pytest.raises(UnsupportedOperation, match="end_date"):
        adapter.create_campaign(
            CreateCampaignRequest(
                name="X",
                daily_budget_micros=1_000_000,
                end_date=date(2026, 12, 31),
            )
        )
    assert mock_client.create_campaign.await_count == 0


@pytest.mark.unit
def test_create_campaign_with_bidding_strategy_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Phase 1: ``bidding_strategy`` would require AdSet ``bid_strategy``
    mapping — out of scope. Even MANUAL_CPC is rejected."""
    with pytest.raises(UnsupportedOperation, match="bidding_strategy"):
        adapter.create_campaign(
            CreateCampaignRequest(
                name="X",
                daily_budget_micros=1_000_000,
                bidding_strategy=BidStrategy.MANUAL_CPC,
            )
        )
    assert mock_client.create_campaign.await_count == 0


@pytest.mark.unit
def test_update_campaign_name_only(adapter: MetaAdsAdapter, mock_client: Mock) -> None:
    """A name-only partial update routes to ``client.update_campaign(c, name=...)``."""
    mock_client.update_campaign.return_value = {"success": True}
    mock_client.get_campaign.return_value = _campaign_row(cid="c111", name="Renamed")
    out = adapter.update_campaign("c111", UpdateCampaignRequest(name="Renamed"))
    assert isinstance(out, Campaign)
    mock_client.update_campaign.assert_awaited_once()
    call = mock_client.update_campaign.await_args
    assert "c111" in call.args or "c111" in call.kwargs.values()
    flat = list(call.args) + list(call.kwargs.values())
    assert "Renamed" in flat


@pytest.mark.unit
def test_update_campaign_status_paused(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """``UpdateCampaignRequest(status=PAUSED)`` routes through a single
    ``client.update_campaign`` call with the wire-string ``"PAUSED"`` —
    not via a separate ``pause_campaign`` (which is sugar over
    ``update_campaign``)."""
    mock_client.update_campaign.return_value = {"success": True}
    mock_client.get_campaign.return_value = _campaign_row(cid="c111", status="PAUSED")
    out = adapter.update_campaign(
        "c111",
        UpdateCampaignRequest(status=CampaignStatus.PAUSED),
    )
    assert isinstance(out, Campaign)
    mock_client.update_campaign.assert_awaited_once()
    flat = list(mock_client.update_campaign.await_args.args) + list(
        mock_client.update_campaign.await_args.kwargs.values()
    )
    assert "PAUSED" in flat


@pytest.mark.unit
def test_update_campaign_daily_budget_micros_wired_to_cents(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Unlike Google Ads, Meta supports daily_budget on the campaign
    resource directly. The adapter converts micros → cents
    (``micros // 10_000``) at the boundary."""
    mock_client.update_campaign.return_value = {"success": True}
    mock_client.get_campaign.return_value = _campaign_row(
        cid="c111", daily_budget_cents="2000"
    )
    adapter.update_campaign(
        "c111", UpdateCampaignRequest(daily_budget_micros=20_000_000)
    )
    call_kwargs = mock_client.update_campaign.await_args.kwargs
    # The adapter should forward as ``daily_budget=2000`` (cents int).
    if "daily_budget" in call_kwargs:
        assert call_kwargs["daily_budget"] == 2000
    else:
        flat = list(mock_client.update_campaign.await_args.args) + list(
            call_kwargs.values()
        )
        assert 2000 in flat


# ---------------------------------------------------------------------------
# Case 5 — CampaignProvider — ads (AdSet hierarchy flattening)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_ads_flattens_ad_sets(adapter: MetaAdsAdapter, mock_client: Mock) -> None:
    """``list_ads(campaign_id)`` calls ``list_ad_sets(campaign_id)``,
    then ``list_ads(ad_set_id)`` per ad set, and flattens the result.

    Phase 1 accepts the N+1 cost; the design decision is to hide AdSet
    rather than expand the Protocol.
    """
    mock_client.list_ad_sets.return_value = [
        _ad_set_row(ad_set_id="as1"),
        _ad_set_row(ad_set_id="as2"),
    ]
    mock_client.list_ads.side_effect = [
        [_ad_row(ad_id="ad1", ad_set_id="as1")],
        [
            _ad_row(ad_id="ad2", ad_set_id="as2"),
            _ad_row(ad_id="ad3", ad_set_id="as2"),
        ],
    ]
    result = adapter.list_ads("c111")
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert all(isinstance(a, Ad) for a in result)
    assert {a.id for a in result} == {"ad1", "ad2", "ad3"}
    # AdSet listing happened exactly once.
    assert mock_client.list_ad_sets.await_count == 1
    # And per-ad-set ad listing happened twice (N+1 pattern, Phase 1).
    assert mock_client.list_ads.await_count == 2
    for a in result:
        assert a.account_id == _FAKE_AD_ACCOUNT_ID
        assert a.campaign_id == "c111"


@pytest.mark.unit
def test_get_ad_campaign_mismatch_raises_key_error(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """``get_ad(campaign_id, ad_id)`` verifies the returned ad's
    ``campaign_id`` matches the requested one; mismatch is treated as
    a "not found in this campaign" error → ``KeyError``."""
    mock_client.get_ad.return_value = _ad_row(
        ad_id="ad9", ad_set_id="as7", campaign_id="OTHER_CAMPAIGN"
    )
    with pytest.raises(KeyError):
        adapter.get_ad("c111", "ad9")


@pytest.mark.unit
def test_get_ad_returns_match(adapter: MetaAdsAdapter, mock_client: Mock) -> None:
    mock_client.get_ad.return_value = _ad_row(
        ad_id="ad9", ad_set_id="as1", campaign_id="c111"
    )
    out = adapter.get_ad("c111", "ad9")
    assert isinstance(out, Ad)
    assert out.id == "ad9"
    assert out.campaign_id == "c111"


@pytest.mark.unit
def test_create_ad_uses_first_headline_as_creative_id(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """CTO decision #3: Phase 1 interprets ``request.headlines[0]`` as
    the ``creative_id`` and ``request.ad_group_id`` as the ``ad_set_id``.
    """
    mock_client.create_ad.return_value = {"id": "ad9"}
    mock_client.get_ad.return_value = _ad_row(
        ad_id="ad9", ad_set_id="as1", campaign_id="c111"
    )
    out = adapter.create_ad(
        "c111",
        CreateAdRequest(
            ad_group_id="as1",
            headlines=("creative_xyz",),
            descriptions=(),
        ),
    )
    assert isinstance(out, Ad)
    mock_client.create_ad.assert_awaited_once()
    call = mock_client.create_ad.await_args
    flat = list(call.args) + list(call.kwargs.values())
    assert "as1" in flat
    assert "creative_xyz" in flat


@pytest.mark.unit
def test_create_ad_empty_headlines_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """An empty ``headlines`` tuple cannot supply a creative_id; raise
    ``UnsupportedOperation`` instead of silently dropping the create."""
    with pytest.raises(UnsupportedOperation):
        adapter.create_ad(
            "c111",
            CreateAdRequest(
                ad_group_id="as1",
                headlines=(),
                descriptions=(),
            ),
        )
    assert mock_client.create_ad.await_count == 0


@pytest.mark.unit
def test_create_ad_multiple_headlines_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Phase 1: only ``len(headlines) == 1`` is supported (the overload
    holds the creative_id)."""
    with pytest.raises(UnsupportedOperation):
        adapter.create_ad(
            "c111",
            CreateAdRequest(
                ad_group_id="as1",
                headlines=("h1", "h2"),
                descriptions=(),
            ),
        )
    assert mock_client.create_ad.await_count == 0


@pytest.mark.unit
def test_update_ad_with_headlines_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Phase 1: Meta cannot mutate an existing ad's creative fields
    without recreating the ad. Supplying any creative field raises
    ``UnsupportedOperation``."""
    with pytest.raises(UnsupportedOperation):
        adapter.update_ad("c111", "ad9", UpdateAdRequest(headlines=("new",)))
    assert mock_client.update_ad.await_count == 0


@pytest.mark.unit
def test_update_ad_with_descriptions_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    with pytest.raises(UnsupportedOperation):
        adapter.update_ad("c111", "ad9", UpdateAdRequest(descriptions=("d1",)))
    assert mock_client.update_ad.await_count == 0


@pytest.mark.unit
def test_update_ad_with_final_urls_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    with pytest.raises(UnsupportedOperation):
        adapter.update_ad(
            "c111", "ad9", UpdateAdRequest(final_urls=("https://example.com",))
        )
    assert mock_client.update_ad.await_count == 0


@pytest.mark.unit
def test_set_ad_status_paused_calls_pause_ad(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    mock_client.pause_ad.return_value = {"success": True}
    mock_client.get_ad.return_value = _ad_row(
        ad_id="ad1", ad_set_id="as1", campaign_id="c111", status="PAUSED"
    )
    out = adapter.set_ad_status("c111", "ad1", AdStatus.PAUSED)
    assert isinstance(out, Ad)
    mock_client.pause_ad.assert_awaited_once()
    assert mock_client.enable_ad.await_count == 0
    assert mock_client.update_ad.await_count == 0


@pytest.mark.unit
def test_set_ad_status_enabled_calls_enable_ad(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    mock_client.enable_ad.return_value = {"success": True}
    mock_client.get_ad.return_value = _ad_row(
        ad_id="ad1", ad_set_id="as1", campaign_id="c111", status="ACTIVE"
    )
    adapter.set_ad_status("c111", "ad1", AdStatus.ENABLED)
    mock_client.enable_ad.assert_awaited_once()
    assert mock_client.pause_ad.await_count == 0


@pytest.mark.unit
def test_set_ad_status_removed_routes_to_update_ad_deleted(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """REMOVED → ``client.update_ad(ad_id, status="DELETED")`` — Meta's
    canonical soft-delete (archive is not used in Phase 1)."""
    mock_client.update_ad.return_value = {"success": True}
    mock_client.get_ad.return_value = _ad_row(
        ad_id="ad1", ad_set_id="as1", campaign_id="c111", status="DELETED"
    )
    adapter.set_ad_status("c111", "ad1", AdStatus.REMOVED)
    mock_client.update_ad.assert_awaited_once()
    flat = list(mock_client.update_ad.await_args.args) + list(
        mock_client.update_ad.await_args.kwargs.values()
    )
    assert "DELETED" in flat


# ---------------------------------------------------------------------------
# Case 6 — Daily report (via insights_time_range)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_daily_report_calls_insights_time_range(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """``daily_report`` delegates to the new
    ``client.insights_time_range`` method with ISO dates and returns a
    tuple of ``DailyReportRow``."""
    mock_client.insights_time_range.return_value = [
        {
            "date_start": "2026-04-01",
            "date_stop": "2026-04-01",
            "impressions": "100",
            "clicks": "10",
            "spend": "5.00",
            "actions": [],
        },
        {
            "date_start": "2026-04-02",
            "date_stop": "2026-04-02",
            "impressions": "150",
            "clicks": "12",
            "spend": "6.00",
            "actions": [],
        },
    ]
    out = adapter.daily_report("111222", date(2026, 4, 1), date(2026, 4, 2))
    assert isinstance(out, tuple)
    assert all(isinstance(r, DailyReportRow) for r in out)
    assert out[0].date == date(2026, 4, 1)
    # spend dollars → micros: 5.00 USD = 5_000_000 micros.
    assert out[0].cost_micros == 5_000_000

    mock_client.insights_time_range.assert_awaited_once()
    call_kwargs = mock_client.insights_time_range.await_args.kwargs
    call_args = mock_client.insights_time_range.await_args.args
    # campaign_id is the positional (or keyword) ``node_id``.
    flat = list(call_args) + list(call_kwargs.values())
    assert "111222" in flat
    # ISO since/until appear (accept either kwarg name forms).
    assert "2026-04-01" in flat
    assert "2026-04-02" in flat


@pytest.mark.unit
def test_daily_report_passes_iso_kwargs(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """The ``since`` and ``until`` arguments are ISO-formatted dates."""
    mock_client.insights_time_range.return_value = []
    adapter.daily_report("111222", date(2026, 4, 1), date(2026, 4, 7))
    kwargs = mock_client.insights_time_range.await_args.kwargs
    # The canonical kwargs are documented as ``since`` and ``until``.
    if "since" in kwargs:
        assert kwargs["since"] == "2026-04-01"
        assert kwargs["until"] == "2026-04-07"
    else:
        # Fall back: ISO strings appear positionally.
        flat = list(mock_client.insights_time_range.await_args.args) + list(
            kwargs.values()
        )
        assert "2026-04-01" in flat
        assert "2026-04-07" in flat


@pytest.mark.unit
def test_daily_report_rejects_non_digit_campaign_id(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Phase 1 safety: ``campaign_id`` must be digits-only — an
    attacker-controlled value MUST be rejected before the request is
    issued. Mirror of P1-09's GAQL injection guard."""
    with pytest.raises((ValueError, MetaAdsAdapterError)):
        adapter.daily_report("' OR 1=1 --", date(2026, 4, 1), date(2026, 4, 2))
    assert mock_client.insights_time_range.await_count == 0


@pytest.mark.unit
def test_daily_report_extracts_conversions_from_actions(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Meta's `actions` list — when an action of type ``purchase`` (or
    other Phase 1 conversion-like action_type) is present — populates
    ``DailyReportRow.conversions``."""
    mock_client.insights_time_range.return_value = [
        {
            "date_start": "2026-04-01",
            "date_stop": "2026-04-01",
            "impressions": "100",
            "clicks": "10",
            "spend": "5.00",
            "actions": [
                {"action_type": "purchase", "value": "3"},
                {"action_type": "link_click", "value": "10"},
            ],
        }
    ]
    out = adapter.daily_report("111222", date(2026, 4, 1), date(2026, 4, 1))
    assert len(out) == 1
    # Conversions reflect the ``purchase`` action's value.
    assert out[0].conversions == 3.0


# ---------------------------------------------------------------------------
# Case 7 — AudienceProvider
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_audiences_returns_tuple_of_dataclasses(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    mock_client.list_custom_audiences.return_value = [
        _audience_row(aud_id="aud_1", name="A"),
        _audience_row(aud_id="aud_2", name="B"),
    ]
    out = adapter.list_audiences()
    assert isinstance(out, tuple)
    assert len(out) == 2
    assert all(isinstance(a, Audience) for a in out)
    for a in out:
        assert a.account_id == _FAKE_AD_ACCOUNT_ID
        # Phase 1: only ENABLED is mapped from a healthy delivery_status.
        assert a.status == AudienceStatus.ENABLED


@pytest.mark.unit
def test_get_audience_returns_dataclass(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    mock_client.get_custom_audience.return_value = _audience_row(aud_id="aud_42")
    out = adapter.get_audience("aud_42")
    assert isinstance(out, Audience)
    assert out.id == "aud_42"
    mock_client.get_custom_audience.assert_awaited_once_with("aud_42")


@pytest.mark.unit
def test_create_audience_custom_when_no_seed(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """``CreateAudienceRequest`` without ``seed_audience_id`` →
    ``client.create_custom_audience`` is invoked (NOT lookalike)."""
    mock_client.create_custom_audience.return_value = {"id": "aud_new"}
    mock_client.get_custom_audience.return_value = _audience_row(
        aud_id="aud_new", name="Visitors"
    )
    out = adapter.create_audience(
        CreateAudienceRequest(name="Visitors", description="Site visitors 30d")
    )
    assert isinstance(out, Audience)
    mock_client.create_custom_audience.assert_awaited_once()
    assert mock_client.create_lookalike_audience.await_count == 0
    # ``subtype="CUSTOM"`` is enforced.
    kwargs = mock_client.create_custom_audience.await_args.kwargs
    args = mock_client.create_custom_audience.await_args.args
    flat = list(args) + list(kwargs.values())
    assert "CUSTOM" in flat
    assert "Visitors" in flat


@pytest.mark.unit
def test_create_audience_lookalike_when_seed_set(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """CTO decision #4: ``seed_audience_id`` present → lookalike branch
    with hardcoded defaults ``country="JP"`` and ``ratio=0.01``."""
    mock_client.create_lookalike_audience.return_value = {"id": "aud_la"}
    mock_client.get_custom_audience.return_value = _audience_row(
        aud_id="aud_la", subtype="LOOKALIKE"
    )
    adapter.create_audience(
        CreateAudienceRequest(name="LA-JP", seed_audience_id="aud_seed")
    )
    mock_client.create_lookalike_audience.assert_awaited_once()
    assert mock_client.create_custom_audience.await_count == 0
    call = mock_client.create_lookalike_audience.await_args
    flat = list(call.args) + list(call.kwargs.values())
    # All four key Phase-1 args must appear.
    assert "aud_seed" in flat
    assert "JP" in flat
    assert 0.01 in flat
    assert "LA-JP" in flat


@pytest.mark.unit
def test_set_audience_status_removed_calls_delete(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """``REMOVED`` is the canonical delete signal → routes to
    ``client.delete_custom_audience``."""
    mock_client.delete_custom_audience.return_value = {"success": True}
    mock_client.get_custom_audience.return_value = _audience_row(aud_id="aud_x")
    # Phase 1 contract: returning an ``Audience`` after delete is
    # acceptable (some adapters refresh, some return the pre-delete
    # snapshot). The test only pins that the delete call happened.
    adapter.set_audience_status("aud_x", AudienceStatus.REMOVED)
    mock_client.delete_custom_audience.assert_awaited_once_with("aud_x")


@pytest.mark.unit
def test_set_audience_status_enabled_unsupported(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Meta has no re-enable for deleted audiences; status is derived
    from delivery_status. Phase 1 raises ``UnsupportedOperation``."""
    with pytest.raises(UnsupportedOperation):
        adapter.set_audience_status("aud_x", AudienceStatus.ENABLED)
    assert mock_client.delete_custom_audience.await_count == 0


# ---------------------------------------------------------------------------
# Case 8 — Sync/async bridge
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_methods_callable_from_outside_loop(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Sync Protocol methods are callable from a thread with no running
    loop (the default for pytest sync tests)."""
    mock_client.list_campaigns.return_value = [_campaign_row()]
    result = adapter.list_campaigns()
    assert isinstance(result, tuple)


@pytest.mark.unit
def test_calling_from_running_loop_raises_runtime_error(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """Calling an adapter method from inside an active event loop must
    raise ``RuntimeError`` — Phase 1 sync Protocol cannot reentrantly
    call ``asyncio.run``."""
    mock_client.list_campaigns.return_value = []

    async def _inner() -> None:
        adapter.list_campaigns()

    with pytest.raises(RuntimeError):
        asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Case 9 — Error pass-through
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_client_runtime_error_passes_through_unwrapped(
    adapter: MetaAdsAdapter, mock_client: Mock
) -> None:
    """A ``RuntimeError`` raised by the underlying client passes through
    unchanged — it must NOT be wrapped in ``MetaAdsAdapterError``."""
    mock_client.update_campaign.side_effect = RuntimeError(
        "Meta API request failed (status=400, path=/c111): boom"
    )
    with pytest.raises(RuntimeError) as excinfo:
        adapter.update_campaign("c111", UpdateCampaignRequest(name="X"))
    assert not isinstance(excinfo.value, MetaAdsAdapterError)
    assert "boom" in str(excinfo.value)


@pytest.mark.unit
def test_unsupported_operation_subclasses_adapter_error() -> None:
    """``UnsupportedOperation`` subclasses ``MetaAdsAdapterError``;
    ``MetaAdsAdapterError`` subclasses ``RuntimeError``."""
    assert issubclass(UnsupportedOperation, MetaAdsAdapterError)
    assert issubclass(MetaAdsAdapterError, RuntimeError)


# ---------------------------------------------------------------------------
# Case 10 — Public surface hygiene
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_protocol_methods_are_sync(adapter: MetaAdsAdapter) -> None:
    """Every Protocol method on the adapter is synchronous — the
    sync/async bridge is the adapter's responsibility."""
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
        "list_audiences",
        "get_audience",
        "create_audience",
        "set_audience_status",
    ):
        method = getattr(adapter, method_name)
        assert not inspect.iscoroutinefunction(
            method
        ), f"{method_name} must be a sync method on the Phase 1 adapter"


@pytest.mark.unit
def test_adapter_does_not_advertise_keyword_or_extension_methods(
    adapter: MetaAdsAdapter,
) -> None:
    """Phase 1 deferral / non-applicable: keyword / extension Protocol
    methods are intentionally absent from the adapter (NOT stubs that
    raise)."""
    for method_name in (
        "list_keywords",
        "add_keywords",
        "set_keyword_status",
        "list_extensions",
        "add_extension",
        "set_extension_status",
        "search_terms",
    ):
        assert not hasattr(
            adapter, method_name
        ), f"{method_name} must NOT be defined (Meta has no counterpart)"
