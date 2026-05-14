"""RED-phase tests for ``mureo.adapters.meta_ads.mappers``.

The mapper module is a pile of pure functions that turn the raw
``dict`` / ``list[dict]`` returned by ``MetaAdsApiClient`` mixins into
the frozen-dataclass entities defined in
``mureo.core.providers.models``.

Phase 1 conversions enforced here
---------------------------------
- Budget: Meta returns ``daily_budget`` as a **cents** string; mapper
  converts to **micros** (``int(cents) * 10_000``).
- Spend: Meta returns ``spend`` as a **dollars** string; mapper
  converts to **micros** (``int(round(float(s) * 1_000_000))``).
- Status: Meta wire-strings (``ACTIVE`` / ``PAUSED`` / ``DELETED`` /
  ``ARCHIVED`` / ``CAMPAIGN_PAUSED`` / ``ADSET_PAUSED``) are mapped
  to the canonical ``CampaignStatus`` / ``AdStatus`` enum members.
- Unknown / unparseable values raise ``ValueError`` — no silent
  fallback to a default.

Marks: every test is ``@pytest.mark.unit``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module ``mureo.adapters.meta_ads.mappers`` does not exist yet.
from mureo.adapters.meta_ads.mappers import (
    map_ad_status,
    map_campaign_status,
    to_ad,
    to_audience,
    to_campaign,
    to_campaigns,
    to_daily_report_row,
)
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Audience,
    AudienceStatus,
    Campaign,
    CampaignStatus,
    DailyReportRow,
)

_ACCOUNT_ID = "act_1234567890"


# ---------------------------------------------------------------------------
# Status mapping (parametrized: Meta wire-string → mureo canonical)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("meta_wire", "expected"),
    [
        ("ACTIVE", CampaignStatus.ENABLED),
        ("PAUSED", CampaignStatus.PAUSED),
        ("CAMPAIGN_PAUSED", CampaignStatus.PAUSED),
        ("ADSET_PAUSED", CampaignStatus.PAUSED),
        ("DELETED", CampaignStatus.REMOVED),
        ("ARCHIVED", CampaignStatus.REMOVED),
    ],
)
def test_map_campaign_status_known_values(
    meta_wire: str, expected: CampaignStatus
) -> None:
    assert map_campaign_status(meta_wire) == expected


@pytest.mark.unit
def test_map_campaign_status_unknown_raises_value_error() -> None:
    """No silent fallback — unknown Meta wire-strings raise
    ``ValueError`` with the offending value."""
    with pytest.raises(ValueError) as excinfo:
        map_campaign_status("PENDING_REVIEW")
    # Offending value must be in the message for debuggability.
    assert "PENDING_REVIEW" in str(excinfo.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("meta_wire", "expected"),
    [
        ("ACTIVE", AdStatus.ENABLED),
        ("PAUSED", AdStatus.PAUSED),
        ("CAMPAIGN_PAUSED", AdStatus.PAUSED),
        ("ADSET_PAUSED", AdStatus.PAUSED),
        ("DELETED", AdStatus.REMOVED),
        ("ARCHIVED", AdStatus.REMOVED),
    ],
)
def test_map_ad_status_known_values(meta_wire: str, expected: AdStatus) -> None:
    assert map_ad_status(meta_wire) == expected


@pytest.mark.unit
def test_map_ad_status_unknown_raises_value_error() -> None:
    with pytest.raises(ValueError):
        map_ad_status("WITH_ISSUES")


# ---------------------------------------------------------------------------
# Campaign mapper — cents → micros boundary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_campaign_maps_required_fields_and_cents_to_micros() -> None:
    """``daily_budget="1500"`` (cents string) → ``daily_budget_micros=15_000_000``."""
    raw: dict[str, Any] = {
        "id": "c1",
        "name": "Test",
        "status": "ACTIVE",
        "daily_budget": "1500",
    }
    out = to_campaign(raw, account_id=_ACCOUNT_ID)
    assert isinstance(out, Campaign)
    assert out.id == "c1"
    assert out.account_id == _ACCOUNT_ID
    assert out.name == "Test"
    assert out.status == CampaignStatus.ENABLED
    assert out.daily_budget_micros == 15_000_000
    # Exact integer arithmetic (no float round-trip).
    assert isinstance(out.daily_budget_micros, int)


@pytest.mark.unit
def test_to_campaign_missing_daily_budget_defaults_to_zero() -> None:
    """Phase 1: when Meta returns no ``daily_budget`` (e.g. lifetime-only
    campaigns), the mapper produces ``daily_budget_micros=0`` rather
    than raising."""
    raw: dict[str, Any] = {
        "id": "c1",
        "name": "Lifetime",
        "status": "ACTIVE",
    }
    out = to_campaign(raw, account_id=_ACCOUNT_ID)
    assert out.daily_budget_micros == 0


@pytest.mark.unit
def test_to_campaign_unknown_status_raises_value_error() -> None:
    raw: dict[str, Any] = {
        "id": "c1",
        "name": "x",
        "status": "PENDING_REVIEW",
        "daily_budget": "0",
    }
    with pytest.raises(ValueError):
        to_campaign(raw, account_id=_ACCOUNT_ID)


@pytest.mark.unit
def test_to_campaigns_returns_tuple_of_campaign() -> None:
    rows = [
        {"id": "1", "name": "a", "status": "ACTIVE", "daily_budget": "100"},
        {"id": "2", "name": "b", "status": "PAUSED", "daily_budget": "200"},
    ]
    out = to_campaigns(rows, account_id=_ACCOUNT_ID)
    assert isinstance(out, tuple)
    assert len(out) == 2
    assert all(isinstance(c, Campaign) for c in out)
    assert out[0].daily_budget_micros == 1_000_000
    assert out[1].daily_budget_micros == 2_000_000


# ---------------------------------------------------------------------------
# Ad mapper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_ad_with_creative_link_data() -> None:
    """The ``creative.object_story_spec.link_data.link`` field populates
    ``Ad.final_url`` when present."""
    raw: dict[str, Any] = {
        "id": "ad1",
        "status": "ACTIVE",
        "creative": {
            "object_story_spec": {
                "link_data": {"link": "https://example.com/landing"},
            }
        },
    }
    out = to_ad(raw, account_id=_ACCOUNT_ID, campaign_id="c1")
    assert isinstance(out, Ad)
    assert out.id == "ad1"
    assert out.account_id == _ACCOUNT_ID
    assert out.campaign_id == "c1"
    assert out.status == AdStatus.ENABLED
    assert out.final_url == "https://example.com/landing"
    # Immutability — headlines / descriptions are tuples (empty in Phase 1).
    assert isinstance(out.headlines, tuple)
    assert isinstance(out.descriptions, tuple)


@pytest.mark.unit
def test_to_ad_without_creative_uses_empty_final_url() -> None:
    raw: dict[str, Any] = {
        "id": "ad2",
        "status": "PAUSED",
    }
    out = to_ad(raw, account_id=_ACCOUNT_ID, campaign_id="c1")
    assert out.final_url == ""


@pytest.mark.unit
def test_to_ad_unknown_status_raises() -> None:
    raw: dict[str, Any] = {
        "id": "ad3",
        "status": "WITH_ISSUES",
    }
    with pytest.raises(ValueError):
        to_ad(raw, account_id=_ACCOUNT_ID, campaign_id="c1")


# ---------------------------------------------------------------------------
# Audience mapper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_audience_maps_required_fields() -> None:
    raw: dict[str, Any] = {
        "id": "aud_1",
        "name": "Site visitors",
        "approximate_count_lower_bound": 10_000,
        "approximate_count_upper_bound": 10_000,
        "delivery_status": {"code": 200, "description": "Ready"},
    }
    out = to_audience(raw, account_id=_ACCOUNT_ID)
    assert isinstance(out, Audience)
    assert out.id == "aud_1"
    assert out.account_id == _ACCOUNT_ID
    assert out.name == "Site visitors"
    assert out.status == AudienceStatus.ENABLED


@pytest.mark.unit
def test_to_audience_missing_size_estimate_is_none() -> None:
    """When Meta omits size estimate fields, ``size_estimate`` is
    ``None`` rather than 0."""
    raw: dict[str, Any] = {
        "id": "aud_2",
        "name": "Tiny audience",
        "delivery_status": {"code": 200, "description": "Ready"},
    }
    out = to_audience(raw, account_id=_ACCOUNT_ID)
    assert out.size_estimate is None


# ---------------------------------------------------------------------------
# DailyReportRow mapper — dollars → micros, date parsing, action conv.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_daily_report_row_parses_date_and_converts_dollars_to_micros() -> None:
    raw: dict[str, Any] = {
        "date_start": "2026-04-15",
        "date_stop": "2026-04-15",
        "impressions": "100",
        "clicks": "10",
        "spend": "12.34",
        "actions": [],
    }
    out = to_daily_report_row(raw)
    assert isinstance(out, DailyReportRow)
    assert isinstance(out.date, date)
    assert out.date == date(2026, 4, 15)
    assert out.impressions == 100
    assert out.clicks == 10
    # 12.34 USD → 12_340_000 micros (rounded to nearest integer).
    assert out.cost_micros == 12_340_000
    assert isinstance(out.cost_micros, int)


@pytest.mark.unit
def test_to_daily_report_row_unparseable_date_raises_value_error() -> None:
    raw: dict[str, Any] = {
        "date_start": "not-a-date",
        "impressions": "0",
        "clicks": "0",
        "spend": "0",
        "actions": [],
    }
    with pytest.raises(ValueError):
        to_daily_report_row(raw)


@pytest.mark.unit
def test_to_daily_report_row_extracts_purchase_conversions_from_actions() -> None:
    raw: dict[str, Any] = {
        "date_start": "2026-04-15",
        "impressions": "100",
        "clicks": "10",
        "spend": "0",
        "actions": [
            {"action_type": "purchase", "value": "5"},
            {"action_type": "link_click", "value": "20"},
        ],
    }
    out = to_daily_report_row(raw)
    # The mapper recognises ``purchase`` as the conversion action_type
    # (Phase 1 convention).
    assert out.conversions == 5.0
    assert isinstance(out.conversions, float)


@pytest.mark.unit
def test_to_daily_report_row_no_actions_zero_conversions() -> None:
    raw: dict[str, Any] = {
        "date_start": "2026-04-15",
        "impressions": "1",
        "clicks": "0",
        "spend": "0",
        # ``actions`` may be absent entirely on days with no events.
    }
    out = to_daily_report_row(raw)
    assert out.conversions == 0.0
