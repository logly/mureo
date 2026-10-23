"""Library logs name a caught exception by its class only (#865, #603).

``GoogleAdsException`` does not curate its ``__str__``: formatting it prints
the request metadata (developer token, ``authorization`` header). A log line
built with ``%s, exc`` or ``exc_info=True`` therefore copies that metadata
into the log. Each site below now logs ``type(exc).__name__`` instead.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.analysis.lp_analyzer import LPAnalyzer
from mureo.google_ads import _creative
from mureo.learning.federation import search_one
from tests.test_advisor_federation import _patch_open_raises, _src
from tests.test_google_ads_analysis import MockAnalysisClient
from tests.test_mcp_exception_text_routing import _SECRET, _platform_shaped

_URL = "https://example.com/lp"


def _assert_class_name_only(
    caplog: pytest.LogCaptureFixture, exc: Exception, level: int = logging.WARNING
) -> None:
    """A ``level`` record names ``exc``'s class; none carries its text or traceback."""
    logged = [r.getMessage() for r in caplog.records if r.levelno == level]
    assert any(f"({type(exc).__name__})" in message for message in logged)
    assert all(_SECRET not in r.getMessage() for r in caplog.records)
    assert all(r.exc_info is None for r in caplog.records)


@pytest.mark.unit
async def test_auction_insights_failure_logs_class_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _platform_shaped(RuntimeError)
    client = MockAnalysisClient()
    client._search = AsyncMock(side_effect=exc)

    with caplog.at_level(logging.WARNING):
        await client.get_auction_insights("123")

    _assert_class_name_only(caplog, exc)


@pytest.mark.unit
async def test_landing_page_analysis_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exc = _platform_shaped(RuntimeError)

    class _RaisingAnalyzer:
        async def analyze(self, _url: str) -> Any:
            raise exc

    monkeypatch.setattr(_creative, "LPAnalyzer", _RaisingAnalyzer)

    with caplog.at_level(logging.WARNING):
        result = await _creative._CreativeMixin().analyze_landing_page(_URL)

    assert _SECRET not in str(result)
    _assert_class_name_only(caplog, exc)


@pytest.mark.unit
async def test_lp_url_validation_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exc = _platform_shaped(ValueError)
    analyzer = LPAnalyzer()
    monkeypatch.setattr(analyzer, "_fetch_html", AsyncMock(side_effect=exc))

    with caplog.at_level(logging.WARNING):
        await analyzer.analyze(_URL)

    _assert_class_name_only(caplog, exc)


@pytest.mark.unit
async def test_lp_fetch_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exc = _platform_shaped(RuntimeError)
    analyzer = LPAnalyzer()
    monkeypatch.setattr(analyzer, "_fetch_html", AsyncMock(side_effect=exc))

    with caplog.at_level(logging.WARNING):
        result = await analyzer.analyze(_URL)

    assert _SECRET not in str(result)
    _assert_class_name_only(caplog, exc)


@pytest.mark.unit
async def test_lp_parse_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exc = _platform_shaped(RuntimeError)
    analyzer = LPAnalyzer()
    monkeypatch.setattr(analyzer, "_fetch_html", AsyncMock(return_value="<html/>"))

    def _raise(*_args: Any) -> Any:
        raise exc

    monkeypatch.setattr(analyzer, "_parse_html", _raise)

    with caplog.at_level(logging.WARNING):
        result = await analyzer.analyze(_URL)

    assert _SECRET not in str(result)
    _assert_class_name_only(caplog, exc)


@pytest.mark.unit
async def test_advisor_search_failure_logs_class_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _platform_shaped(RuntimeError)

    with _patch_open_raises(exc), caplog.at_level(logging.WARNING):
        fragments = await search_one(_src(), query="q", top_k=3)

    assert fragments == ()
    _assert_class_name_only(caplog, exc)
