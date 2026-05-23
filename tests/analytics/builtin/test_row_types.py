"""Smoke tests for the row-shape TypedDicts.

The TypedDicts document the platform-row shapes our adapters consume.
They are part of the plugin ABI (re-exported from
:mod:`mureo.analytics`) so plugin authors can refer to them when
implementing their own analytics modules. These tests pin the field
sets so a refactor that drops or renames a field becomes an obvious
test break rather than a silent ABI shift.
"""

from __future__ import annotations

import pytest

from mureo.analytics import (
    GoogleAdRow,
    GoogleByodPerformanceRow,
    GoogleLivePerformanceRow,
    GoogleMetricsDict,
    GooglePerformanceRow,
    MetaActionEntry,
    MetaAdRow,
    MetaPerformanceRow,
)


@pytest.mark.unit
def test_typeddicts_constructible_with_partial_keys() -> None:
    """Each TypedDict is ``total=False`` so partial instances work —
    that's the reality of real API responses (mappers omit keys whose
    underlying field was None).
    """
    live: GoogleLivePerformanceRow = {
        "campaign_id": "c1",
        "metrics": GoogleMetricsDict(cost=100.0, conversions=5),
    }
    byod: GoogleByodPerformanceRow = {
        "campaign_id": "c1",
        "cost": 100.0,
        "conversions": 5.0,
    }
    assert live["campaign_id"] == byod["campaign_id"]


@pytest.mark.unit
def test_google_performance_row_union_accepts_both_shapes() -> None:
    rows: list[GooglePerformanceRow] = [
        {"campaign_id": "a", "metrics": {"cost": 1.0}},  # live shape
        {"campaign_id": "b", "cost": 2.0},  # BYOD shape
    ]
    assert len(rows) == 2


@pytest.mark.unit
def test_meta_action_entry_shape() -> None:
    action: MetaActionEntry = {
        "action_type": "offsite_conversion.fb_pixel_lead",
        "value": 3.0,
    }
    assert action["action_type"].endswith("_lead")


@pytest.mark.unit
def test_meta_performance_row_union_accepts_both_shapes() -> None:
    rows: list[MetaPerformanceRow] = [
        {
            "campaign_id": "a",
            "spend": 100.0,
            "actions": [{"action_type": "lead", "value": 3.0}],
        },
        {"campaign_id": "b", "spend": 100.0, "conversions": 5.0},
    ]
    assert len(rows) == 2


@pytest.mark.unit
def test_google_ad_row_carries_audit_relevant_fields() -> None:
    ad: GoogleAdRow = {
        "id": "ad1",
        "campaign_id": "camp_X",
        "type": "RESPONSIVE_SEARCH_AD",
        "headlines": ["h1", "h2", "h3"],
        "descriptions": ["d1", "d2"],
    }
    assert ad["type"] == "RESPONSIVE_SEARCH_AD"


@pytest.mark.unit
def test_meta_ad_row_carries_audit_relevant_fields() -> None:
    ad: MetaAdRow = {
        "id": "ad1",
        "campaign_id": "camp_X",
        "creative": {"title": "t", "body": "b"},
    }
    assert ad["campaign_id"] == "camp_X"
