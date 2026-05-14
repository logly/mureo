"""RED-phase tests for ``mureo.adapters.google_ads.mappers``.

The mapper module is a pile of pure functions that turn the legacy
``dict`` / ``list[dict]`` output of the existing
``mureo.google_ads.mappers`` into the frozen-dataclass entities defined
in ``mureo.core.providers.models``.

Marks: every test is ``@pytest.mark.unit``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module ``mureo.adapters.google_ads.mappers`` does not exist yet.
from mureo.adapters.google_ads.mappers import (
    to_ad,
    to_campaign,
    to_campaigns,
    to_daily_report_row,
    to_extension,
    to_keyword,
    to_search_term,
)
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Campaign,
    CampaignStatus,
    DailyReportRow,
    Extension,
    ExtensionKind,
    ExtensionStatus,
    Keyword,
    KeywordMatchType,
    KeywordStatus,
    SearchTerm,
)

_ACCOUNT_ID = "1234567890"


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_campaign_maps_required_fields() -> None:
    raw: dict[str, Any] = {
        "id": "111",
        "name": "Search — JP",
        "status": "ENABLED",
        "budget_amount_micros": 5_000_000,
    }
    out = to_campaign(raw, account_id=_ACCOUNT_ID)
    assert isinstance(out, Campaign)
    assert out.id == "111"
    assert out.account_id == _ACCOUNT_ID
    assert out.name == "Search — JP"
    assert out.status == CampaignStatus.ENABLED
    assert out.daily_budget_micros == 5_000_000


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("ENABLED", CampaignStatus.ENABLED),
        ("PAUSED", CampaignStatus.PAUSED),
        ("REMOVED", CampaignStatus.REMOVED),
    ],
)
def test_to_campaign_status_strings_are_mapped(
    raw_status: str, expected: CampaignStatus
) -> None:
    raw = {
        "id": "1",
        "name": "x",
        "status": raw_status,
        "budget_amount_micros": 1,
    }
    out = to_campaign(raw, account_id=_ACCOUNT_ID)
    assert out.status == expected


@pytest.mark.unit
def test_to_campaign_unknown_status_raises_value_error() -> None:
    """Unknown status string raises ``ValueError`` — no silent fallback
    to a default enum value (the planner's explicit rule)."""
    raw = {
        "id": "1",
        "name": "x",
        "status": "TOTALLY_NOT_A_STATUS",
        "budget_amount_micros": 0,
    }
    with pytest.raises(ValueError):
        to_campaign(raw, account_id=_ACCOUNT_ID)


@pytest.mark.unit
def test_to_campaigns_returns_tuple() -> None:
    rows = [
        {"id": "1", "name": "a", "status": "ENABLED", "budget_amount_micros": 1},
        {"id": "2", "name": "b", "status": "PAUSED", "budget_amount_micros": 2},
    ]
    out = to_campaigns(rows, account_id=_ACCOUNT_ID)
    assert isinstance(out, tuple)
    assert len(out) == 2
    assert all(isinstance(c, Campaign) for c in out)


@pytest.mark.unit
def test_to_campaigns_accepts_iterable_not_just_list() -> None:
    """``to_campaigns`` accepts any ``Iterable`` — generators included."""

    def _gen() -> Any:
        yield {"id": "1", "name": "a", "status": "ENABLED", "budget_amount_micros": 1}

    out = to_campaigns(_gen(), account_id=_ACCOUNT_ID)
    assert isinstance(out, tuple)
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Ad
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_ad_maps_required_fields() -> None:
    raw: dict[str, Any] = {
        "id": "9",
        "status": "ENABLED",
        "headlines": ["H1", "H2"],
        "descriptions": ["D1"],
        "final_urls": ["https://example.com", "https://example.com/x"],
    }
    out = to_ad(raw, account_id=_ACCOUNT_ID, campaign_id="111")
    assert isinstance(out, Ad)
    assert out.id == "9"
    assert out.account_id == _ACCOUNT_ID
    assert out.campaign_id == "111"
    assert out.status == AdStatus.ENABLED
    # Tuples, not lists — immutability rule.
    assert isinstance(out.headlines, tuple)
    assert isinstance(out.descriptions, tuple)
    assert out.headlines == ("H1", "H2")
    assert out.descriptions == ("D1",)
    # final_url is the first final URL.
    assert out.final_url == "https://example.com"


@pytest.mark.unit
def test_to_ad_with_no_final_urls_uses_empty_string() -> None:
    raw: dict[str, Any] = {
        "id": "9",
        "status": "PAUSED",
        "headlines": [],
        "descriptions": [],
        "final_urls": [],
    }
    out = to_ad(raw, account_id=_ACCOUNT_ID, campaign_id="111")
    assert out.final_url == ""


@pytest.mark.unit
def test_to_ad_unknown_status_raises_value_error() -> None:
    raw = {
        "id": "9",
        "status": "NOT_REAL",
        "headlines": [],
        "descriptions": [],
        "final_urls": [],
    }
    with pytest.raises(ValueError):
        to_ad(raw, account_id=_ACCOUNT_ID, campaign_id="111")


# ---------------------------------------------------------------------------
# Keyword
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_keyword_maps_required_fields() -> None:
    raw: dict[str, Any] = {
        "id": "k1",
        "text": "buy widgets",
        "match_type": "EXACT",
        "status": "ENABLED",
    }
    out = to_keyword(raw, account_id=_ACCOUNT_ID, campaign_id="111")
    assert isinstance(out, Keyword)
    assert out.id == "k1"
    assert out.account_id == _ACCOUNT_ID
    assert out.campaign_id == "111"
    assert out.text == "buy widgets"
    assert out.match_type == KeywordMatchType.EXACT
    assert out.status == KeywordStatus.ENABLED


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("EXACT", KeywordMatchType.EXACT),
        ("PHRASE", KeywordMatchType.PHRASE),
        ("BROAD", KeywordMatchType.BROAD),
    ],
)
def test_to_keyword_match_type_strings_are_mapped(
    raw: str, expected: KeywordMatchType
) -> None:
    row = {
        "id": "k1",
        "text": "t",
        "match_type": raw,
        "status": "ENABLED",
    }
    out = to_keyword(row, account_id=_ACCOUNT_ID, campaign_id="111")
    assert out.match_type == expected


@pytest.mark.unit
def test_to_keyword_unknown_match_type_raises() -> None:
    row = {
        "id": "k1",
        "text": "t",
        "match_type": "FUZZY",
        "status": "ENABLED",
    }
    with pytest.raises(ValueError):
        to_keyword(row, account_id=_ACCOUNT_ID, campaign_id="111")


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "kind",
    [ExtensionKind.SITELINK, ExtensionKind.CALLOUT, ExtensionKind.CONVERSION],
)
def test_to_extension_maps_with_explicit_kind(kind: ExtensionKind) -> None:
    raw: dict[str, Any] = {
        "id": "e1",
        "text": "label",
        "status": "ENABLED",
    }
    out = to_extension(raw, account_id=_ACCOUNT_ID, kind=kind)
    assert isinstance(out, Extension)
    assert out.id == "e1"
    assert out.account_id == _ACCOUNT_ID
    assert out.kind == kind
    assert out.status == ExtensionStatus.ENABLED
    assert out.text == "label"


@pytest.mark.unit
def test_to_extension_unknown_status_raises() -> None:
    raw = {"id": "e1", "text": "x", "status": "WHO_KNOWS"}
    with pytest.raises(ValueError):
        to_extension(raw, account_id=_ACCOUNT_ID, kind=ExtensionKind.SITELINK)


@pytest.mark.unit
def test_to_extension_conversion_uses_name_as_text_when_present() -> None:
    """Conversion actions are named ``name`` in the legacy mapper
    output; the adapter should map this onto the ``text`` field of
    ``Extension`` when ``text`` is absent."""
    raw: dict[str, Any] = {
        "id": "cv1",
        "name": "Purchase",
        "status": "ENABLED",
    }
    out = to_extension(raw, account_id=_ACCOUNT_ID, kind=ExtensionKind.CONVERSION)
    assert out.text == "Purchase"


# ---------------------------------------------------------------------------
# DailyReportRow
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_daily_report_row_returns_date_type() -> None:
    raw: dict[str, Any] = {
        "date": "2024-01-15",
        "impressions": 100,
        "clicks": 10,
        "cost_micros": 5_000_000,
        "conversions": 1.5,
    }
    out = to_daily_report_row(raw)
    assert isinstance(out, DailyReportRow)
    assert isinstance(out.date, date)
    assert out.date == date(2024, 1, 15)
    assert out.impressions == 100
    assert out.clicks == 10
    assert out.cost_micros == 5_000_000
    assert out.conversions == 1.5


@pytest.mark.unit
def test_to_daily_report_row_cost_micros_is_int() -> None:
    raw: dict[str, Any] = {
        "date": "2024-01-15",
        "impressions": 0,
        "clicks": 0,
        "cost_micros": 999_999_999,
        "conversions": 0.0,
    }
    out = to_daily_report_row(raw)
    assert isinstance(out.cost_micros, int)
    assert out.cost_micros == 999_999_999


@pytest.mark.unit
def test_to_daily_report_row_bad_date_raises() -> None:
    raw: dict[str, Any] = {
        "date": "not-a-date",
        "impressions": 0,
        "clicks": 0,
        "cost_micros": 0,
        "conversions": 0.0,
    }
    with pytest.raises(ValueError):
        to_daily_report_row(raw)


# ---------------------------------------------------------------------------
# SearchTerm
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_search_term_maps_required_fields() -> None:
    raw: dict[str, Any] = {
        "search_term": "buy widgets cheap",
        "impressions": 50,
        "clicks": 5,
        "cost_micros": 1_000_000,
        "conversions": 0.5,
        "ctr": 0.1,
    }
    out = to_search_term(raw, campaign_id="111")
    assert isinstance(out, SearchTerm)
    assert out.text == "buy widgets cheap"
    assert out.campaign_id == "111"
    assert out.impressions == 50
    assert out.clicks == 5
