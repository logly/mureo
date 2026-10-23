"""Library results carry ``exception_text``, never ``str(exc)`` (#865, #603).

``mureo.core.tool_failure.exception_text`` returns the curated
``failure.errors[*].message`` of an exception shaped like a platform failure
and never its ``str()``, which for ``GoogleAdsException`` carries the request
metadata. Each site below used to format the exception itself into the
result it returns.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mureo.analysis.lp_analyzer import LPAnalyzer
from mureo.google_ads._ads_display import RDAUploadError
from mureo.mcp import _handlers_google_ads
from mureo.mcp._tracking_preflight import DISABLE_ENV
from mureo.meta_ads import _creatives
from mureo.meta_ads.client import MetaAdsApiClient
from tests.test_google_ads_ads import _make_client
from tests.test_google_ads_analysis import MockAnalysisClient
from tests.test_mcp_exception_text_routing import _CURATED, _SECRET, _platform_shaped


def _assert_curated(result: Any, text: str) -> None:
    """``text`` is in the result with the curated message; no secret is."""
    assert text.endswith(_CURATED)
    assert text in str(result)
    assert _SECRET not in str(result)


def _campaign_client(exc: Exception) -> MockAnalysisClient:
    client = MockAnalysisClient()
    client.get_campaign = AsyncMock(return_value={"id": "123", "name": "C"})
    client._search = AsyncMock(side_effect=exc)
    return client


@pytest.mark.unit
async def test_device_performance_error_carries_curated_text() -> None:
    client = _campaign_client(_platform_shaped(RuntimeError))

    result = await client.analyze_device_performance("123")

    expected = f"Failed to retrieve device performance data: {_CURATED}"
    assert result == {"error": expected}
    _assert_curated(result, expected)


@pytest.mark.unit
async def test_cpc_trend_error_carries_curated_text() -> None:
    client = _campaign_client(_platform_shaped(RuntimeError))

    result = await client.detect_cpc_trend("123")

    expected = f"Failed to retrieve daily CPC data: {_CURATED}"
    assert result == {"error": expected}
    _assert_curated(result, expected)


@pytest.mark.unit
async def test_auction_insights_reason_carries_curated_text() -> None:
    client = _campaign_client(_platform_shaped(RuntimeError))

    result = await client.get_auction_insights("123")

    assert result[0]["error"] == "auction_insights_unavailable"
    assert result[0]["reason"] == _CURATED
    _assert_curated(result, _CURATED)


@pytest.mark.unit
async def test_rsa_audit_error_carries_curated_text() -> None:
    client = MockAnalysisClient()
    client.analyze_rsa_assets = AsyncMock(  # type: ignore[method-assign]
        side_effect=_platform_shaped(RuntimeError)
    )

    result = await client.audit_rsa_assets("123")

    expected = f"Failed to retrieve RSA asset data: {_CURATED}"
    assert result == {"error": expected}
    _assert_curated(result, expected)


@pytest.mark.unit
async def test_meta_image_download_error_carries_curated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://example.com/image.png"
    client = MetaAdsApiClient(access_token="t", ad_account_id="act_1")
    monkeypatch.setattr(_creatives, "validate_public_url", lambda _url: None)
    monkeypatch.setattr(
        _creatives.httpx,
        "AsyncClient",
        MagicMock(side_effect=_platform_shaped(RuntimeError)),
    )

    result = await client.upload_ad_image(url)

    expected = f"Failed to download image from {url}: {_CURATED}"
    assert result == {"error": expected}
    _assert_curated(result, expected)


@pytest.mark.unit
async def test_lp_validation_error_carries_curated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyzer = LPAnalyzer()
    monkeypatch.setattr(
        analyzer, "_fetch_html", AsyncMock(side_effect=_platform_shaped(ValueError))
    )

    result = await analyzer.analyze("https://example.com/lp")

    assert result.error == _CURATED
    _assert_curated(result, _CURATED)


# ---------------------------------------------------------------------------
# create_display_ad: raised messages and the tool result
# ---------------------------------------------------------------------------

_DISPLAY_AD: dict[str, Any] = {
    "ad_group_id": "100",
    "headlines": ["H"],
    "long_headline": "Long",
    "descriptions": ["D"],
    "business_name": "Biz",
    "marketing_image_paths": ["/tmp/m.jpg"],
    "square_marketing_image_paths": ["/tmp/s.jpg"],
    "final_url": "https://example.com",
}


def _assert_chain_cut(exc: BaseException) -> None:
    # A printed traceback would show the platform exception's repr.
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True


async def _noop_verify(_self: Any, _ad_group_id: str) -> None:
    return None


async def _uploaded(file_path: str, name: str | None = None) -> dict[str, Any]:
    return {"resource_name": f"customers/123/assets{file_path}", "id": file_path}


def _display_client(monkeypatch: pytest.MonkeyPatch, *, upload: Any = _uploaded) -> Any:
    """A real client whose image upload is ``upload`` and whose ad group is DISPLAY."""
    client = _make_client()
    client._client.get_type.side_effect = lambda *_a, **_k: MagicMock()
    monkeypatch.setattr(client, "upload_image_asset", upload)
    monkeypatch.setattr(type(client), "_verify_ad_group_is_display", _noop_verify)
    return client


@pytest.mark.unit
async def test_display_ad_group_check_error_carries_curated_text() -> None:
    client = _make_client()
    client._search = AsyncMock(side_effect=_platform_shaped(RuntimeError))

    with pytest.raises(ValueError) as info:
        await client._verify_ad_group_is_display("100")

    _assert_curated(str(info.value), f"Failed to verify ad group 100: {_CURATED}")
    _assert_chain_cut(info.value)


@pytest.mark.unit
async def test_display_ad_upload_error_carries_curated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = AsyncMock(side_effect=_platform_shaped(RuntimeError))
    client = _display_client(monkeypatch, upload=upload)

    with pytest.raises(RDAUploadError) as info:
        await client.create_display_ad(dict(_DISPLAY_AD))

    _assert_curated(str(info.value), f"RDA image upload failed: {_CURATED}")
    _assert_chain_cut(info.value)


@pytest.mark.unit
async def test_display_ad_mutate_error_carries_curated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _display_client(monkeypatch)
    service = MagicMock()
    service.mutate_ad_group_ads.side_effect = _platform_shaped(RuntimeError)
    client._client.get_service.return_value = service

    with pytest.raises(RDAUploadError) as info:
        await client.create_display_ad(dict(_DISPLAY_AD))

    message = str(info.value)
    assert message.startswith(f"RDA creation failed: {_CURATED} (orphaned")
    assert _SECRET not in message
    _assert_chain_cut(info.value)


@pytest.mark.unit
async def test_display_ad_tool_result_carries_curated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = AsyncMock(side_effect=_platform_shaped(RuntimeError))
    client = _display_client(monkeypatch, upload=upload)
    monkeypatch.setenv(DISABLE_ENV, "1")
    get_client = AsyncMock(return_value=client)
    monkeypatch.setattr(_handlers_google_ads, "_get_client", get_client)

    result = await _handlers_google_ads.handle_ads_create_display(dict(_DISPLAY_AD))

    _assert_curated(result[0].text, f"RDA image upload failed: {_CURATED}")
