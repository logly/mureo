"""The ChatGPT Ads create tools' argument checks (#995).

Every invalid case is refused by the handler before any request, and by the
tool schema too unless ``_HANDLER_ONLY`` says why the schema cannot express
it; every valid case passes both and sends one ``POST``. The nested bounds
are pinned at their limit and one past it.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools_create import (
    MAX_CONTEXT_HINT_CHARS,
    MAX_COUNTRIES,
    MAX_LISTED_IDS,
    MAX_LOCATION_LABEL_CHARS,
)
from tests._chatgpt_ads_fakes import (
    FakeAPI,
    call_tool,
    install_fake_api,
    schema_errors,
)
from tests.test_chatgpt_ads_create import (
    _AD,
    _AD_GROUP,
    _BY_NAME,
    _CAMPAIGN,
    _CREATE_CALLS,
    _CREATIVE,
    _TARGETING,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    return install_fake_api(monkeypatch)


def _campaign_with(**changes: Any) -> dict[str, Any]:
    return {**_CAMPAIGN, **changes}


def _ad_with(**creative: Any) -> dict[str, Any]:
    return {**_AD, "creative": {**_CREATIVE, **creative}}


def _geo(**geo: Any) -> dict[str, Any]:
    return _campaign_with(targeting={"locations": geo})


def _countries(count: int) -> list[str]:
    """``count`` distinct two-letter codes of the ISO shape."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return [a + b for a in letters for b in letters][:count]


def _id_list(count: int) -> list[str]:
    return [f"id_{i}" for i in range(count)]


def _audiences(count: int) -> dict[str, Any]:
    return _campaign_with(targeting={"custom_audiences": {"ids": _id_list(count)}})


def _labelled(chars: int) -> dict[str, Any]:
    return _geo(include=[{"id": "1014044", "name": "n" * chars}])


def _hints(*hints: str) -> dict[str, Any]:
    return {**_AD_GROUP, "context_hints": list(hints)}


#: Each nested bound one past its limit; the same bound at its limit is in
#: ``_VALID``.
_OVER_BOUNDS = [
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(countries=_countries(MAX_COUNTRIES + 1)),
        id="countries-over",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _audiences(MAX_LISTED_IDS + 1),
        id="audience-ids-over",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(
            targeting={
                "excluded_custom_audiences": {"ids": _id_list(MAX_LISTED_IDS + 1)}
            }
        ),
        id="excluded-audience-ids-over",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(conversion_event_setting_ids=_id_list(MAX_LISTED_IDS + 1)),
        id="conversion-ids-over",
    ),
    *(
        pytest.param(
            "chatgpt_ads_campaigns_create",
            _geo(include=[{"id": "1", field: "x" * (MAX_LOCATION_LABEL_CHARS + 1)}]),
            id=f"location-{field}-over",
        )
        for field in ("name", "type", "country_code", "region_code")
    ),
    pytest.param(
        "chatgpt_ads_ad_groups_create",
        _hints("h" * (MAX_CONTEXT_HINT_CHARS + 1)),
        id="context-hint-over",
    ),
    pytest.param("chatgpt_ads_ad_groups_create", _hints(""), id="context-hint-empty"),
]

#: Landing pages the shape check refuses: credentials in the authority, a
#: backslash (read as a separator by some clients), no host.
_BAD_TARGET_URLS = [
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(target_url=url),
        id=f"target-url-{label}",
    )
    for label, url in (
        ("user-and-password", "https://u:p@example.com/"),
        ("user", "https://u@example.com/"),
        ("empty-host", "http://user@"),
        ("backslash", "https://example.com\\@evil.example/"),
    )
]

#: An unknown ``status`` key at each nested level of a create.
_NESTED_STATUS = [
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(status="active"),
        id="status-in-creative",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(targeting={"status": "active"}),
        id="status-in-targeting",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(countries=["US"], status="active"),
        id="status-in-locations",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(
            budget={"daily_spend_limit_micros": 50_000_000, "status": "active"}
        ),
        id="status-in-budget",
    ),
    pytest.param(
        "chatgpt_ads_ad_groups_create",
        {
            **_AD_GROUP,
            "bidding_config": {**_AD_GROUP["bidding_config"], "status": "active"},
        },
        id="status-in-bidding-config",
    ),
]


_INVALID = [
    pytest.param("chatgpt_ads_campaigns_create", {}, id="campaign-empty"),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(name="ab"),
        id="campaign-short-name",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        {k: v for k, v in _CAMPAIGN.items() if k != "bidding_type"},
        id="campaign-no-bidding-type",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(bidding_type="views"),
        id="campaign-bad-bidding-type",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(
            budget={
                "daily_spend_limit_micros": 5_000_000,
                "lifetime_spend_limit_micros": 50_000_000,
            }
        ),
        id="campaign-both-budgets",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(budget={}),
        id="campaign-no-budget-amount",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(budget={"daily_spend_limit_micros": 999_999}),
        id="campaign-budget-below-minimum",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(start_time=10),
        id="campaign-start-out-of-range",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(end_time=None),
        id="campaign-null-end",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(projected_total_daily_budget=-1),
        id="campaign-negative-total",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(conversion_event_setting_ids=["ces 1"]),
        id="campaign-bad-conversion-id",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(conversion_event_setting_ids="ces_1"),
        id="campaign-conversion-ids-not-a-list",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(targeting={"locations": {"countries": ["US"]}, "age": 1}),
        id="targeting-unknown-key",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(regions=["CA"]),
        id="targeting-geo-unknown-key",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(include=[{"id": "1", "radius": 5}]),
        id="targeting-location-unknown-key",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(include=[{"name": "California"}]),
        id="targeting-location-no-id",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(include=[{"id": str(i)} for i in range(2501)]),
        id="targeting-too-many-locations",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(countries=["USA"]),
        id="targeting-bad-country",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(targeting={"custom_audiences": {"ids": ["a/b"]}}),
        id="targeting-bad-audience-id",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(targeting={"custom_audiences": {"ids": [], "kind": "x"}}),
        id="targeting-audience-unknown-key",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(targeting={"platforms": {"included": ["tv"]}}),
        id="targeting-bad-platform",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(targeting=None),
        id="targeting-null",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(idempotency_key=""),
        id="key-empty",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(idempotency_key="has space"),
        id="key-space",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(idempotency_key="k" * 256),
        id="key-too-long",
    ),
    pytest.param(
        "chatgpt_ads_ad_groups_create",
        {k: v for k, v in _AD_GROUP.items() if k != "campaign_id"},
        id="ad-group-no-campaign",
    ),
    pytest.param(
        "chatgpt_ads_ad_groups_create",
        {**_AD_GROUP, "bidding_config": {"strategy": "fixed_bid"}},
        id="ad-group-no-billing-event",
    ),
    pytest.param(
        "chatgpt_ads_ad_groups_create",
        {**_AD_GROUP, "context_hints": ["x"] * 2001},
        id="ad-group-too-many-hints",
    ),
    pytest.param(
        "chatgpt_ads_ad_groups_create",
        {**_AD_GROUP, "context_hints": [7]},
        id="ad-group-hint-not-text",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        {k: v for k, v in _AD.items() if k != "creative"},
        id="ad-no-creative",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(type="product_ad_template"),
        id="creative-product-template",
    ),
    pytest.param("chatgpt_ads_ads_create", _ad_with(title="ab"), id="title-short"),
    pytest.param("chatgpt_ads_ads_create", _ad_with(title="t" * 51), id="title-long"),
    pytest.param(
        "chatgpt_ads_ads_create", _ad_with(title="two\nlines"), id="title-break"
    ),
    pytest.param("chatgpt_ads_ads_create", _ad_with(body="b" * 101), id="body-long"),
    pytest.param(
        "chatgpt_ads_ads_create",
        {**_AD, "creative": {k: v for k, v in _CREATIVE.items() if k != "target_url"}},
        id="creative-no-target-url",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(target_url="ftp://example.com/x"),
        id="target-url-scheme",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(target_url="https://example.com/" + "a" * 2030),
        id="target-url-long",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(file_ids=["f_1", "f_2", "f_3", "f_4"]),
        id="creative-multi-image",
    ),
    pytest.param(
        "chatgpt_ads_ads_create", _ad_with(file_id="file 1"), id="creative-bad-file-id"
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(
            file_id="file_1", image_crop={"x": 0, "y": 0, "width": 1.5, "height": 1}
        ),
        id="crop-above-one",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(file_id="file_1", image_crop={"x": 0, "y": 0, "width": 1}),
        id="crop-missing-height",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(
            file_id="file_1",
            image_crop={"x": 0, "y": 0, "width": 1, "height": 1, "angle": 0},
        ),
        id="crop-unknown-key",
    ),
    pytest.param("chatgpt_ads_campaigns_archive", {}, id="archive-no-id"),
    pytest.param("chatgpt_ads_ads_archive", {"ad_id": "a/b"}, id="archive-bad-id"),
    *_OVER_BOUNDS,
    *_BAD_TARGET_URLS,
    *_NESTED_STATUS,
]


#: Invalid cases the schema cannot express, with the reason.
_HANDLER_ONLY = {
    # "image_crop requires file_id" ties two sibling keys together; the tool
    # schemas state each key's own shape only.
    "crop-without-file",
    # An authority urlsplit cannot parse is a parse failure, not a pattern.
    "target-url-malformed",
}


_CROP_WITHOUT_FILE = pytest.param(
    "chatgpt_ads_ads_create",
    _ad_with(image_crop={"x": 0, "y": 0, "width": 1, "height": 1}),
    id="crop-without-file",
)


_MALFORMED_URL = pytest.param(
    "chatgpt_ads_ads_create",
    _ad_with(target_url="https://[::1"),
    id="target-url-malformed",
)


@pytest.mark.parametrize(
    ("name", "arguments"), [*_INVALID, _CROP_WITHOUT_FILE, _MALFORMED_URL]
)
async def test_invalid_arguments_send_nothing(
    api: FakeAPI, name: str, arguments: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
    assert api.requests == []


@pytest.mark.parametrize(("name", "arguments"), _INVALID)
def test_the_schema_refuses_what_the_handler_refuses(
    name: str, arguments: dict[str, Any]
) -> None:
    assert schema_errors(_BY_NAME[name], arguments) != []


def test_current_daily_budget_is_not_offered_on_create() -> None:
    # A create has no current budget to compare an increase against.
    name = "chatgpt_ads_campaigns_create"
    assert schema_errors(_BY_NAME[name], _campaign_with(current_daily_budget=10)) != []


def test_the_schema_cannot_parse_an_authority() -> None:
    name, arguments = _MALFORMED_URL.values
    assert _MALFORMED_URL.id in _HANDLER_ONLY
    assert schema_errors(_BY_NAME[name], arguments) == []


def test_the_schema_cannot_tie_the_crop_to_the_file() -> None:
    name, arguments = _CROP_WITHOUT_FILE.values
    assert _CROP_WITHOUT_FILE.id in _HANDLER_ONLY
    assert schema_errors(_BY_NAME[name], arguments) == []


_VALID = [
    pytest.param("chatgpt_ads_campaigns_create", _CAMPAIGN, id="campaign-minimal"),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(
            budget={"lifetime_spend_limit_micros": 1_000_000},
            bidding_type="impressions",
            targeting={"platforms": {"included": []}},
            projected_total_daily_budget=0,
        ),
        id="campaign-lifetime",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(targeting=_TARGETING, idempotency_key="A-b_9"),
        id="campaign-targeting",
    ),
    pytest.param("chatgpt_ads_ad_groups_create", _AD_GROUP, id="ad-group"),
    pytest.param("chatgpt_ads_ads_create", _AD, id="ad"),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(body="", target_url="http://example.com"),
        id="ad-empty-body-http",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(target_url="https://example.com/a?b=c#d"),
        id="ad-url-query-fragment",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(target_url="http://example.com:8080/"),
        id="ad-url-port",
    ),
    pytest.param(
        "chatgpt_ads_ads_create",
        _ad_with(target_url="https://example.com/@shop"),
        id="ad-url-at-in-path",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _geo(countries=_countries(MAX_COUNTRIES)),
        id="countries-at-bound",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _audiences(MAX_LISTED_IDS),
        id="audience-ids-at-bound",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _campaign_with(conversion_event_setting_ids=_id_list(MAX_LISTED_IDS)),
        id="conversion-ids-at-bound",
    ),
    pytest.param(
        "chatgpt_ads_campaigns_create",
        _labelled(MAX_LOCATION_LABEL_CHARS),
        id="location-label-at-bound",
    ),
    pytest.param(
        "chatgpt_ads_ad_groups_create",
        _hints("h", "h" * MAX_CONTEXT_HINT_CHARS),
        id="context-hints-at-bounds",
    ),
]


@pytest.mark.parametrize(("name", "arguments"), _VALID)
async def test_valid_arguments_pass_the_schema_and_the_handler(
    api: FakeAPI, name: str, arguments: dict[str, Any]
) -> None:
    assert schema_errors(_BY_NAME[name], arguments) == []
    path, _ = _CREATE_CALLS[name]
    api.add(path, body={"id": "x"})
    await call_tool(name, arguments)
    assert [r.method for r in api.requests] == ["POST"]
