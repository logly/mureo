"""The tracking pre-flight that runs whether the agent asks for it or not.

`analysis_tracking_consistency_check` is opt-in — the agent has to choose
to call it. These tests cover the enforced path: the native Google Ads
ad-create handlers run the check before the mutation and refuse the
create when the planned ad carries another campaign's tracking identity.

The failure policy is pinned here too: a pre-flight that cannot read the
account must never block an operator from shipping an ad.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.mcp._tracking_preflight import (
    DISABLE_ENV,
    google_ads_create_preflight,
)


def _url(article: int, campaign_value: str) -> str:
    return (
        f"https://example.com/article/{article}/"
        f"?utm_source=google&utm_medium=cpc&utm_campaign={campaign_value}"
    )


def _row(ad_id: str, campaign_id: str, ad_group_id: str, value: str, n: int) -> dict:
    return {
        "id": ad_id,
        "campaign_id": campaign_id,
        "campaign_name": f"Display / {campaign_id}",
        "ad_group_id": ad_group_id,
        "status": "ENABLED",
        "final_urls": [_url(n, value)],
    }


def _account_rows() -> list[dict]:
    """Segment A and segment B campaigns, each correctly tagged."""
    return [
        *[_row(f"a{n}", "campaign-a", "ag-a", f"sega0{n}", n) for n in (1, 2, 3)],
        *[_row(f"b{n}", "campaign-b", "ag-b", f"segb0{n}", n) for n in (4, 5, 6)],
    ]


def _client(rows: list[dict] | None = None, **overrides: Any) -> Any:
    client = AsyncMock()
    client.list_ads = AsyncMock(
        return_value=rows if rows is not None else _account_rows()
    )
    client.list_ad_groups = AsyncMock(
        return_value=[
            {"id": "ag-a", "campaign_id": "campaign-a"},
            {"id": "ag-b", "campaign_id": "campaign-b"},
            {"id": "ag-new", "campaign_id": "campaign-b"},
        ]
    )
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


def _payload(result: list) -> dict:
    return json.loads(result[0].text)


@pytest.mark.unit
class TestRefusal:
    async def test_refuses_an_ad_carrying_another_campaigns_scheme(self) -> None:
        refusal = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-b",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert refusal is not None
        payload = _payload(refusal)
        assert payload["error"] == "tracking_preflight_failed"
        assert payload["findings"]
        assert payload["findings"][0]["code"] == "foreign_campaign_scheme"
        assert payload["findings"][0]["evidence"]["owning_campaign_id"] == "campaign-a"

    async def test_allows_a_correctly_tagged_ad(self) -> None:
        assert (
            await google_ads_create_preflight(
                _client(),
                ad_group_id="ag-b",
                final_url=_url(7, "segb07"),
                acknowledged=False,
            )
            is None
        )

    async def test_resolves_the_campaign_for_a_brand_new_ad_group(self) -> None:
        """An ad group with no ads yet joins through list_ad_groups."""
        refusal = await google_ads_create_preflight(
            _client(),
            ad_group_id="ag-new",
            final_url=_url(1, "sega01"),
            acknowledged=False,
        )
        assert refusal is not None


@pytest.mark.unit
class TestOverrides:
    async def test_acknowledged_call_proceeds(self) -> None:
        assert (
            await google_ads_create_preflight(
                _client(),
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=True,
            )
            is None
        )

    async def test_env_kill_switch_disables_the_preflight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DISABLE_ENV, "1")
        assert (
            await google_ads_create_preflight(
                _client(),
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )
            is None
        )

    async def test_an_ad_without_a_final_url_is_not_blocked(self) -> None:
        assert (
            await google_ads_create_preflight(
                _client(), ad_group_id="ag-b", final_url=None, acknowledged=False
            )
            is None
        )


@pytest.mark.unit
class TestFailsOpen:
    """A check that cannot read the account must not block a create."""

    async def test_a_read_failure_lets_the_create_proceed(self) -> None:
        client = _client()
        client.list_ads = AsyncMock(side_effect=RuntimeError("API unavailable"))
        assert (
            await google_ads_create_preflight(
                client,
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )
            is None
        )

    async def test_an_unresolvable_campaign_lets_the_create_proceed(self) -> None:
        client = _client()
        client.list_ad_groups = AsyncMock(return_value=[])
        assert (
            await google_ads_create_preflight(
                client,
                ad_group_id="ag-unknown",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )
            is None
        )

    async def test_an_empty_account_lets_the_create_proceed(self) -> None:
        client = _client(rows=[])
        client.list_ad_groups = AsyncMock(
            return_value=[{"id": "ag-b", "campaign_id": "campaign-b"}]
        )
        assert (
            await google_ads_create_preflight(
                client,
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )
            is None
        )


@pytest.mark.unit
class TestHandlerWiring:
    """The refusal actually stops the platform mutation."""

    async def _handler_client(
        self, monkeypatch: pytest.MonkeyPatch, client: Any
    ) -> Any:
        from mureo.mcp import _handlers_google_ads as handlers

        monkeypatch.setattr(handlers, "_get_client", lambda args: client)
        return handlers

    async def test_ads_create_refuses_and_does_not_mutate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_ad = AsyncMock(
            return_value={"resource_name": "should-not-happen"}
        )
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "descriptions": ["d1"],
                "final_url": _url(1, "sega01"),
            }
        )

        assert _payload(result)["error"] == "tracking_preflight_failed"
        client.create_ad.assert_not_awaited()

    async def test_ads_create_proceeds_when_acknowledged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_ad = AsyncMock(return_value={"resource_name": "created"})
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "descriptions": ["d1"],
                "final_url": _url(1, "sega01"),
                "acknowledge_tracking_findings": True,
            }
        )

        assert _payload(result)["resource_name"] == "created"
        client.create_ad.assert_awaited_once()

    async def test_ads_create_display_refuses_and_does_not_mutate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_display_ad = AsyncMock(return_value={"resource_name": "nope"})
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create_display(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "long_headline": "long",
                "descriptions": ["d1"],
                "business_name": "Acme",
                "marketing_image_paths": ["/tmp/a.png"],
                "square_marketing_image_paths": ["/tmp/b.png"],
                "final_url": _url(1, "sega01"),
            }
        )

        assert _payload(result)["error"] == "tracking_preflight_failed"
        client.create_display_ad.assert_not_awaited()

    async def test_a_correctly_tagged_create_still_reaches_the_platform(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        client.create_ad = AsyncMock(return_value={"resource_name": "created"})
        handlers = await self._handler_client(monkeypatch, client)

        result = await handlers.handle_ads_create(
            {
                "ad_group_id": "ag-b",
                "headlines": ["h1"],
                "descriptions": ["d1"],
                "final_url": _url(7, "segb07"),
            }
        )

        assert _payload(result)["resource_name"] == "created"
        client.create_ad.assert_awaited_once()


@pytest.mark.unit
class TestToolSchema:
    def test_both_create_tools_expose_the_acknowledgement(self) -> None:
        from mureo.mcp.tools_google_ads import TOOLS

        for name in ("google_ads_ads_create", "google_ads_ads_create_display"):
            (tool,) = [t for t in TOOLS if t.name == name]
            assert "acknowledge_tracking_findings" in tool.inputSchema["properties"]
