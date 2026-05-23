"""Creative audit pure-function tests + adapter wiring tests."""

from __future__ import annotations

from typing import Any

import pytest

from mureo.analytics.builtin._creative_audit import (
    audit_google_ads_creatives,
    audit_meta_ads_creatives,
)
from mureo.analytics.builtin.google_ads import GoogleAdsAnalyticsModule
from mureo.analytics.builtin.meta_ads import MetaAdsAnalyticsModule
from mureo.analytics.models import AnomalySeverity
from mureo.analytics.protocol import AnalyticsCapability

# ---------------------------------------------------------------------------
# Google RSA / RDA — pure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_google_audit_flags_rsa_with_two_headlines() -> None:
    """BYOD shape (headlines as a 2-element list) trips the
    minimum-headline check naturally — that's exactly the case we want
    surfaced to the user.
    """
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "type": "RESPONSIVE_SEARCH_AD",
            "headlines": ["short headline 1", "short headline 2"],
            "descriptions": ["desc 1", "desc 2"],
        }
    ]
    findings = audit_google_ads_creatives(ads)
    assert any(
        f.asset_id == "ad1"
        and f.severity is AnomalySeverity.CRITICAL
        and "minimum is 3" in f.message
        for f in findings
    )


@pytest.mark.unit
def test_google_audit_passes_well_formed_rsa() -> None:
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "type": "RESPONSIVE_SEARCH_AD",
            "headlines": [f"headline {i}" for i in range(15)],
            "descriptions": [f"description {i}" for i in range(4)],
        }
    ]
    findings = audit_google_ads_creatives(ads)
    assert findings == []


@pytest.mark.unit
def test_google_audit_flags_rsa_below_recommended_headlines() -> None:
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "type": "RESPONSIVE_SEARCH_AD",
            "headlines": [f"h{i}" for i in range(5)],
            "descriptions": ["d1", "d2"],
        }
    ]
    findings = audit_google_ads_creatives(ads)
    assert any(
        f.severity is AnomalySeverity.HIGH and "Google recommends 15" in f.message
        for f in findings
    )


@pytest.mark.unit
def test_google_audit_flags_missing_descriptions() -> None:
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "type": "RESPONSIVE_SEARCH_AD",
            "headlines": [f"h{i}" for i in range(3)],
            "descriptions": ["only one"],
        }
    ]
    findings = audit_google_ads_creatives(ads)
    assert any("description" in f.message.lower() for f in findings)


@pytest.mark.unit
def test_google_audit_accepts_dict_headline_shape() -> None:
    """Live API may return headlines as ``[{text: "..."}]`` rather
    than plain strings; both shapes must be accepted.
    """
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "type": "RESPONSIVE_SEARCH_AD",
            "headlines": [{"text": f"h{i}"} for i in range(3)],
            "descriptions": [{"text": "d1"}, {"text": "d2"}],
        }
    ]
    findings = audit_google_ads_creatives(ads)
    # Has 3 headlines so minimum check passes; should still flag
    # below-recommended (15).
    assert any(f.severity is AnomalySeverity.HIGH for f in findings)


@pytest.mark.unit
def test_google_audit_flags_rda_missing_image() -> None:
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "type": "RESPONSIVE_DISPLAY_AD",
            "headlines": ["short"],
            "long_headline": "long",
            "descriptions": ["d1"],
            "marketing_images": [],
        }
    ]
    findings = audit_google_ads_creatives(ads)
    assert any("marketing images" in f.message for f in findings)


@pytest.mark.unit
def test_google_audit_drops_ads_without_id() -> None:
    findings = audit_google_ads_creatives(
        [
            {"type": "RESPONSIVE_SEARCH_AD", "headlines": [], "descriptions": []},
            {"id": "", "type": "RESPONSIVE_SEARCH_AD"},
        ]
    )
    assert findings == []


@pytest.mark.unit
def test_google_audit_skips_unknown_ad_types() -> None:
    findings = audit_google_ads_creatives(
        [
            {"id": "ad1", "type": "IMAGE_AD", "headlines": []},
        ]
    )
    assert findings == []


# ---------------------------------------------------------------------------
# Meta — pure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_meta_audit_flags_missing_body() -> None:
    ads: list[dict[str, Any]] = [
        {
            "id": "act_1",
            "creative": {
                "title": "hi",
                "image_url": "https://example.com/a.png",
                "object_story_spec": {
                    "link_data": {"call_to_action": {"type": "LEARN_MORE"}}
                },
            },
        }
    ]
    findings = audit_meta_ads_creatives(ads)
    assert any("primary text" in f.message for f in findings)


@pytest.mark.unit
def test_meta_audit_accepts_flat_byod_shape() -> None:
    """BYOD Meta does not nest under ``creative`` — the audit must
    fall back to top-level fields.
    """
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "title": "headline",
            "body": "primary text",
            "image_url": "url",
        }
    ]
    findings = audit_meta_ads_creatives(ads)
    # Has body / title / image, but no cta — should flag one finding.
    assert any("call_to_action" in f.message for f in findings)


@pytest.mark.unit
def test_meta_audit_passes_complete_creative() -> None:
    ads: list[dict[str, Any]] = [
        {
            "id": "ad1",
            "creative": {
                "title": "headline",
                "body": "primary text",
                "image_url": "url",
                "object_story_spec": {
                    "link_data": {"call_to_action": {"type": "LEARN_MORE"}}
                },
            },
        }
    ]
    findings = audit_meta_ads_creatives(ads)
    assert findings == []


# ---------------------------------------------------------------------------
# Adapter wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_adapter_audit_creative_via_injected_fetcher() -> None:
    async def fetcher(account_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "ad1",
                "type": "RESPONSIVE_SEARCH_AD",
                "headlines": ["h1", "h2"],
                "descriptions": ["d1", "d2"],
            }
        ]

    module = GoogleAdsAnalyticsModule(ads_list_fetcher=fetcher)
    audit = await module.audit_creative("acct-1")
    assert audit.platform == "google_ads"
    assert audit.account_id == "acct-1"
    assert any(f.asset_id == "ad1" for f in audit.findings)


@pytest.mark.asyncio
async def test_meta_adapter_audit_creative_via_injected_fetcher() -> None:
    async def fetcher(account_id: str) -> list[dict[str, Any]]:
        return [{"id": "ad1"}]  # missing everything

    module = MetaAdsAnalyticsModule(ads_list_fetcher=fetcher)
    audit = await module.audit_creative("act_1")
    assert len(audit.findings) >= 3  # title, body, image at minimum


@pytest.mark.unit
def test_capabilities_advertise_audit_creative() -> None:
    g_caps = GoogleAdsAnalyticsModule().capabilities()
    m_caps = MetaAdsAnalyticsModule().capabilities()
    assert AnalyticsCapability.AUDIT_CREATIVE in g_caps
    assert AnalyticsCapability.AUDIT_CREATIVE in m_caps
