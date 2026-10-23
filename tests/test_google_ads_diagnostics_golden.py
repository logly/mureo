"""Golden output of ``diagnose_campaign_delivery`` (#865).

The fixtures under ``tests/fixtures/`` (the two results and their top-level
key order) and ``_EXPECTED_CALLS`` were produced by the function before it
was split into one method per section (c3075cc). The split must not change
a single key, key order, value, list order, API call (arguments included)
or log line, so the result is compared with the stored JSON as a whole.

Rows are real ``GoogleAdsRow`` messages converted to raw protobuf, the shape
``_search`` returns on a live account (``use_proto_plus=False``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from google.ads.googleads import util
from google.ads.googleads.v25.services.types.google_ads_service import GoogleAdsRow

from tests.test_google_ads_diagnostics import _MockDiagClient

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_DIAG_LOGGER = "mureo.google_ads._diagnostics"

#: GAQL ``FROM`` / select marker -> the read it stands for, most specific first.
_QUERY_KINDS: tuple[tuple[str, str], ...] = (
    ("FROM ad_group_criterion", "keywords"),
    ("FROM ad_group_ad", "ads"),
    ("FROM campaign_criterion", "locations"),
    ("FROM billing_setup", "billing"),
    ("FROM conversion_action", "conversion_actions"),
    ("segments.conversion_action_name", "conversion_action_performance"),
    ("search_impression_share", "impression_share"),
)

#: (read, positional args, keyword args) of one mocked client call.
_Call = tuple[str, tuple[Any, ...], dict[str, Any]]

#: Every call both fixtures make, in order, generated from the function
#: before the split (c3075cc). The GAQL text is compared byte for byte.
_EXPECTED_CALLS: list[_Call] = [
    ("get_campaign", ("123",), {}),
    ("ad_groups", (), {"campaign_id": "123", "status_filter": "ENABLED"}),
    (
        "keywords",
        (
            (
                "\n"
                "            SELECT\n"
                "                ad_group_criterion.keyword.text,\n"
                "                ad_group_criterion.keyword.match_type,\n"
                "                ad_group_criterion.status,\n"
                "                ad_group_criterion.approval_status,\n"
                "                ad_group_criterion.system_serving_status\n"
                "            FROM ad_group_criterion\n"
                "            WHERE ad_group_criterion.type = 'KEYWORD'\n"
                "                AND campaign.id = 123\n"
                "                AND ad_group_criterion.status = 'ENABLED'\n"
                "        "
            ),
        ),
        {},
    ),
    (
        "ads",
        (
            (
                "\n"
                "            SELECT\n"
                "                ad_group.id, ad_group.name,\n"
                "                ad_group_ad.ad.id, ad_group_ad.ad.type,\n"
                "                ad_group_ad.ad.responsive_search_ad.headlines,\n"
                "                ad_group_ad.ad.responsive_search_ad.descriptions,\n"
                "                ad_group_ad.ad.final_urls,\n"
                "                ad_group_ad.status,\n"
                "                ad_group_ad.policy_summary.approval_status,\n"
                "                ad_group_ad.policy_summary.review_status\n"
                "            FROM ad_group_ad\n"
                "            WHERE campaign.id = 123\n"
                "                AND ad_group_ad.status = 'ENABLED'\n"
                "        "
            ),
        ),
        {},
    ),
    (
        "locations",
        (
            (
                "\n"
                "            SELECT\n"
                "                campaign_criterion.location.geo_target_constant,\n"
                "                campaign_criterion.negative\n"
                "            FROM campaign_criterion\n"
                "            WHERE campaign.id = 123\n"
                "                AND campaign_criterion.type = 'LOCATION'\n"
                "        "
            ),
        ),
        {},
    ),
    ("performance", (), {"campaign_id": "123", "period": "LAST_30_DAYS"}),
    ("sitelinks", ("123",), {}),
    (
        "billing",
        (
            (
                "\n"
                "                SELECT billing_setup.id, billing_setup.status\n"
                "                FROM billing_setup\n"
                "                WHERE billing_setup.status = 'APPROVED'\n"
                "            "
            ),
        ),
        {},
    ),
    (
        "conversion_actions",
        (
            (
                "\n"
                "                    SELECT\n"
                "                        conversion_action.id,\n"
                "                        conversion_action.status\n"
                "                    FROM conversion_action\n"
                "                    WHERE conversion_action.status = 'ENABLED'\n"
                "                "
            ),
        ),
        {},
    ),
    (
        "conversion_action_performance",
        (
            (
                "\n"
                "                    SELECT\n"
                "                        segments.conversion_action_name,\n"
                "                        metrics.conversions,\n"
                "                        metrics.conversions_value\n"
                "                    FROM campaign\n"
                "                    WHERE campaign.id = 123\n"
                "                        AND segments.date DURING LAST_30_DAYS\n"
                "                        AND metrics.conversions > 0\n"
                "                "
            ),
        ),
        {},
    ),
    (
        "impression_share",
        (
            (
                "\n"
                "                SELECT\n"
                "                    metrics.search_impression_share,\n"
                "                    metrics.search_rank_lost_impression_share,\n"
                "                    metrics.search_budget_lost_impression_share\n"
                "                FROM campaign\n"
                "                WHERE campaign.id = 123\n"
                "                    AND segments.date DURING LAST_30_DAYS\n"
                "            "
            ),
        ),
        {},
    ),
]


class _ReadError(Exception):
    """A failed platform read."""


def _row(fields: dict[str, Any]) -> Any:
    return util.convert_proto_plus_to_protobuf(GoogleAdsRow(fields))


def _keyword(text: str, match_type: int, approval: int, serving: int) -> Any:
    return _row(
        {
            "ad_group_criterion": {
                "keyword": {"text": text, "match_type": match_type},
                "approval_status": approval,
                "system_serving_status": serving,
            }
        }
    )


def _ad(
    ad_id: int,
    ad_type: int,
    approval: int,
    ad_group: tuple[int, str],
    final_urls: list[str],
    headlines: list[str],
    descriptions: list[str],
) -> Any:
    return _row(
        {
            "ad_group": {"id": ad_group[0], "name": ad_group[1]},
            "ad_group_ad": {
                "ad": {
                    "id": ad_id,
                    "type_": ad_type,
                    "final_urls": final_urls,
                    "responsive_search_ad": {
                        "headlines": [{"text": t} for t in headlines],
                        "descriptions": [{"text": t} for t in descriptions],
                    },
                },
                "policy_summary": {"approval_status": approval, "review_status": 3},
            },
        }
    )


def _campaign() -> dict[str, Any]:
    return {
        "id": "123",
        "name": "Golden campaign",
        "status": "ENABLED",
        "serving_status": "SUSPENDED",
        "primary_status": "LIMITED",
        "primary_status_reasons": [
            "BUDGET_CONSTRAINED",
            "HAS_ADS_DISAPPROVED",
            "BIDDING_STRATEGY_MISCONFIGURED",
            "SEARCH_VOLUME_LIMITED",
            "UNKNOWN",
            "SOME_FUTURE_REASON",
        ],
        "bidding_strategy_system_status": "LEARNING_BUDGET_CHANGE",
        "start_date": "2099-01-01",
        "end_date": "2020-01-01",
        "budget_daily": 5000,
        "budget_status": "ENABLED",
        "bidding_details": {
            "strategy": "MAXIMIZE_CONVERSIONS",
            "optional_target_cpa": 3000.0,
        },
    }


def _full_rows() -> dict[str, list[Any]]:
    # match_type 2 EXACT / 3 PHRASE / 4 BROAD; approval 2 APPROVED /
    # 3 DISAPPROVED; serving 2 ELIGIBLE / 3 RARELY_SERVED.
    keywords = [
        _keyword("shoes", 4, 2, 2),
        _keyword("Shoes", 2, 2, 3),
        _keyword("boots", 3, 3, 2),
        _keyword("shoes", 3, 2, 3),
        _keyword("sandals", 4, 3, 3),
    ]
    # ad type 15 RESPONSIVE_SEARCH_AD / 3 EXPANDED_TEXT_AD; approval
    # 4 APPROVED / 3 APPROVED_LIMITED / 2 DISAPPROVED.
    ads = [
        _ad(
            11,
            15,
            4,
            (1, "AG1"),
            ["https://example.com/b", "https://example.com/a"],
            ["Headline A", "Headline B", "Headline C"],
            ["Description A", "Description B"],
        ),
        _ad(
            12,
            15,
            3,
            (1, "AG1"),
            ["https://example.com/a"],
            ["Headline A", "Headline D"],
            ["Description C"],
        ),
        _ad(13, 3, 2, (2, "AG2"), ["https://example.com/c"], [], []),
    ]
    locations = [
        _row(
            {
                "campaign_criterion": {
                    "location": {"geo_target_constant": "geoTargetConstants/2392"},
                    "negative": False,
                }
            }
        ),
        _row(
            {
                "campaign_criterion": {
                    "location": {"geo_target_constant": "geoTargetConstants/1023191"},
                    "negative": True,
                }
            }
        ),
    ]
    cv_by_action = [
        _row(
            {
                "segments": {"conversion_action_name": "Signup"},
                "metrics": {"conversions": 2.0, "conversions_value": 0.0},
            }
        ),
        _row(
            {
                "segments": {"conversion_action_name": "Purchase"},
                "metrics": {"conversions": 3.0, "conversions_value": 45000.0},
            }
        ),
    ]
    impression_share = [
        _row(
            {
                "metrics": {
                    "search_impression_share": 0.42,
                    "search_rank_lost_impression_share": 0.35,
                    "search_budget_lost_impression_share": 0.23,
                }
            }
        ),
        _row({"metrics": {"search_impression_share": 0.99}}),
    ]
    return {
        "keywords": keywords,
        "ads": ads,
        "locations": locations,
        "billing": [_row({"billing_setup": {"id": 1, "status": 2}})],
        "conversion_actions": [],
        "conversion_action_performance": cv_by_action,
        "impression_share": impression_share,
    }


def _install(
    client: _MockDiagClient,
    rows: dict[str, list[Any]],
    failing: frozenset[str],
    calls: list[_Call],
) -> None:
    """Wire the client so every call is recorded and the ``failing`` ones raise."""

    def _read(kind: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        calls.append((kind, args, kwargs))
        if kind in failing:
            raise _ReadError(kind)
        if kind == "get_campaign":
            return _campaign()
        return rows.get(kind, [])

    async def _search(*args: Any, **kwargs: Any) -> list[Any]:
        kind = next(k for marker, k in _QUERY_KINDS if marker in args[0])
        return list(_read(kind, args, kwargs))

    def _fake(kind: str) -> AsyncMock:
        async def _call(*args: Any, **kwargs: Any) -> Any:
            return _read(kind, args, kwargs)

        return AsyncMock(side_effect=_call)

    client._search = AsyncMock(side_effect=_search)
    client.get_campaign = _fake("get_campaign")
    client.list_ad_groups = _fake("ad_groups")
    client.get_performance_report = _fake("performance")
    client.list_sitelinks = _fake("sitelinks")


async def run_full(calls: list[_Call]) -> dict[str, Any]:
    """Every read succeeds and returns rows."""
    client = _MockDiagClient()
    rows = _full_rows()
    rows["ad_groups"] = [{"id": "1", "name": "AG1"}, {"id": "2", "name": "AG2"}]
    rows["performance"] = [
        {
            "metrics": {
                "impressions": 1000,
                "clicks": 50,
                "cost": 25000.0,
                "conversions": 5.0,
            }
        }
    ]
    rows["sitelinks"] = [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
    _install(client, rows, frozenset(), calls)
    return await client.diagnose_campaign_delivery("123")


#: Every read guarded as a partial read, except the 30-day performance it
#: needs to reach the conversion-action read; no ad groups, keywords or ads.
_PARTIAL_FAILING = frozenset(
    {
        "sitelinks",
        "billing",
        "conversion_actions",
        "conversion_action_performance",
        "impression_share",
    }
)


async def run_partial(calls: list[_Call]) -> dict[str, Any]:
    """The guarded reads fail; the rest of the result is still there."""
    client = _MockDiagClient()
    rows: dict[str, Any] = {
        "performance": [
            {"metrics": {"impressions": 10, "clicks": 1, "cost": 300.0}},
        ],
    }
    _install(client, rows, _PARTIAL_FAILING, calls)
    return await client.diagnose_campaign_delivery("123")


def _load(name: str) -> Any:
    path = _FIXTURES / f"google_ads_diagnose_delivery_{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _DIAG_LOGGER and r.levelno >= logging.WARNING
    ]


@pytest.mark.unit
class TestDiagnoseCampaignDeliveryGolden:
    @pytest.mark.asyncio
    async def test_full_matches_golden(self, caplog: pytest.LogCaptureFixture) -> None:
        calls: list[_Call] = []
        with caplog.at_level(logging.DEBUG, logger=_DIAG_LOGGER):
            result = await run_full(calls)

        assert json.loads(json.dumps(result)) == _load("full")
        assert list(result) == _load("key_order")["full"]
        assert calls == _EXPECTED_CALLS
        assert _warnings(caplog) == []

    @pytest.mark.asyncio
    async def test_partial_matches_golden(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls: list[_Call] = []
        with caplog.at_level(logging.DEBUG, logger=_DIAG_LOGGER):
            result = await run_partial(calls)

        assert json.loads(json.dumps(result)) == _load("partial")
        assert list(result) == _load("key_order")["partial"]
        assert calls == _EXPECTED_CALLS
        assert _warnings(caplog) == [
            "Failed to retrieve sitelink count (_ReadError)",
            "Failed to retrieve billing setup (_ReadError)",
            "Failed to retrieve active conversion actions (_ReadError)",
            "Failed to retrieve conversion action performance (_ReadError)",
            "Failed to retrieve impression share (_ReadError)",
        ]

    @pytest.mark.asyncio
    async def test_unparsable_end_date_is_skipped(self) -> None:
        """The one section ``except`` neither fixture reaches."""
        client = _MockDiagClient()
        campaign = dict(_campaign(), end_date="not-a-date")
        client.get_campaign = AsyncMock(return_value=campaign)

        result = await client.diagnose_campaign_delivery("123")

        assert not any("end date" in issue for issue in result["issues"])
        assert any("start date" in issue for issue in result["issues"])
