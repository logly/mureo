"""MCP tool tests for ``analysis_tracking_consistency_check`` (#550).

The tool is deliberately platform-neutral: it takes ad records the
caller assembled from whatever read surface the platform offers (native
tools, a plugin's own tools, a bridged MCP), so a platform mureo cannot
fetch ads for is still auditable when the agent can list them.
"""

from __future__ import annotations

import json

import pytest

from mureo.mcp.server import handle_list_tools
from mureo.mcp.tools_analysis import TOOLS, handle_tool

_TOOL = "analysis_tracking_consistency_check"


def _url(article: int, campaign_value: str) -> str:
    return (
        f"https://example.com/article/{article}/"
        f"?utm_source=google&utm_medium=cpc&utm_campaign={campaign_value}"
    )


def _ads(
    prefix: str, campaign_id: str, value_prefix: str, articles: range
) -> list[dict]:
    return [
        {
            "ad_id": f"{prefix}{n}",
            "campaign_id": campaign_id,
            "final_urls": [_url(n, f"{value_prefix}0{n}")],
            "platform": "google_ads",
        }
        for n in articles
    ]


async def _call(arguments: dict) -> dict:
    result = await handle_tool(_TOOL, arguments)
    return json.loads(result[0].text)


@pytest.mark.unit
class TestToolRegistration:
    @pytest.mark.asyncio
    async def test_registered_in_server(self) -> None:
        names = {t.name for t in await handle_list_tools()}
        assert _TOOL in names

    def test_schema_is_strict(self) -> None:
        (tool,) = [t for t in TOOLS if t.name == _TOOL]
        assert tool.inputSchema["additionalProperties"] is False
        assert tool.inputSchema["required"] == ["ads"]


@pytest.mark.unit
class TestAudit:
    @pytest.mark.asyncio
    async def test_reports_the_incident(self) -> None:
        ads = [
            *_ads("a", "campaign-a", "sega", range(1, 9)),
            *_ads("b", "campaign-b", "segb", range(1, 9)),
            *[
                {
                    "ad_id": f"x{n}",
                    "campaign_id": "campaign-b",
                    "final_urls": [_url(n, f"sega0{n}")],
                    "platform": "google_ads",
                    "impressions": 0,
                }
                for n in range(1, 9)
            ],
        ]
        payload = await _call({"ads": ads})

        foreign = [
            f for f in payload["findings"] if f["code"] == "foreign_campaign_scheme"
        ]
        assert foreign
        assert {a for f in foreign for a in f["ad_ids"]} == {
            f"x{n}" for n in range(1, 9)
        }
        # The mis-tagged ads carry impressions=0, so the finding grades them
        # as a cheap fix rather than a data-integrity incident.
        assert all(f["delivery_state"] == "not_served" for f in foreign)
        assert all(f["severity"] == "high" for f in foreign)
        assert foreign[0]["evidence"]["owning_campaign_id"] == "campaign-a"
        assert payload["ads_examined"] == 24
        assert payload["mode"] == "audit"

    @pytest.mark.asyncio
    async def test_clean_account_returns_no_findings(self) -> None:
        payload = await _call({"ads": _ads("b", "campaign-b", "segb", range(1, 9))})
        assert payload["findings"] == []

    @pytest.mark.asyncio
    async def test_convention_markdown_is_parsed_by_mureo(self) -> None:
        ads = [
            *_ads("b", "campaign-b", "segb", range(1, 9)),
            {
                "ad_id": "b9",
                "campaign_id": "campaign-b",
                "final_urls": [_url(9, "spring_sale")],
                "platform": "google_ads",
            },
        ]
        payload = await _call(
            {
                "ads": ads,
                "convention_markdown": (
                    "## Tracking Convention\n\n- pattern utm_campaign: seg[ab]??\n"
                ),
            }
        )
        codes = {f["code"] for f in payload["findings"]}
        assert "convention_violation" in codes

    @pytest.mark.asyncio
    async def test_ads_without_a_readable_url_are_named(self) -> None:
        payload = await _call(
            {
                "ads": [
                    *_ads("b", "campaign-b", "segb", range(1, 9)),
                    {
                        "ad_id": "bridged-1",
                        "campaign_id": "campaign-b",
                        "final_urls": [],
                        "platform": "plugin:mureo-amazon-ads-bridge:amazon_ads",
                    },
                ]
            }
        )
        assert payload["ads_without_readable_url"] == ["bridged-1"]


@pytest.mark.unit
class TestPreflight:
    @pytest.mark.asyncio
    async def test_planned_ads_are_checked_against_the_campaign(self) -> None:
        payload = await _call(
            {
                "ads": [
                    *_ads("a", "campaign-a", "sega", range(1, 9)),
                    *_ads("b", "campaign-b", "segb", range(1, 9)),
                ],
                "planned_ads": [
                    {
                        "ad_id": "planned-1",
                        "campaign_id": "campaign-b",
                        "final_urls": [_url(3, "sega03")],
                        "platform": "google_ads",
                    }
                ],
            }
        )
        assert payload["mode"] == "preflight"
        assert {a for f in payload["findings"] for a in f["ad_ids"]} == {"planned-1"}

    @pytest.mark.asyncio
    async def test_correctly_tagged_planned_ad_passes(self) -> None:
        payload = await _call(
            {
                "ads": _ads("b", "campaign-b", "segb", range(1, 9)),
                "planned_ads": [
                    {
                        "ad_id": "planned-1",
                        "campaign_id": "campaign-b",
                        "final_urls": [_url(9, "segb09")],
                        "platform": "google_ads",
                    }
                ],
            }
        )
        assert payload["findings"] == []


@pytest.mark.unit
class TestInputValidation:
    @pytest.mark.asyncio
    async def test_missing_ads_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ads"):
            await handle_tool(_TOOL, {})

    @pytest.mark.asyncio
    async def test_ad_without_an_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ad_id"):
            await handle_tool(_TOOL, {"ads": [{"campaign_id": "c1", "final_urls": []}]})

    @pytest.mark.asyncio
    async def test_ads_must_be_a_list(self) -> None:
        with pytest.raises(ValueError, match="ads"):
            await handle_tool(_TOOL, {"ads": {"ad_id": "1"}})
