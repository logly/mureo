"""MCP-layer logs name a caught exception by its class only (#865, #603).

A traceback (``logger.exception`` / ``exc_info=True``) prints the exception's
text and every ``__cause__`` under it. For a ``GoogleAdsException`` that text
is the request metadata (developer token, ``authorization`` header); for a
Creative Studio provider error the redacted ``RuntimeError`` is raised
``from`` the ``httpx.HTTPStatusError`` whose URL carries the Gemini API key
(``?key=``). Each site below now logs ``type(exc).__name__`` (and, for
``api_error_handler``, the curated ``exception_text``) without a traceback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from mureo.analysis.exclusion_impact import DeliverySample, ExclusionSurface
from mureo.mcp import (
    _handlers_rollback,
    _tracking_preflight,
    exclusion_preflight,
    tools_creative_studio,
)
from mureo.mcp._helpers import api_error_handler
from tests.test_mcp_exception_text_routing import (
    _CURATED,
    _SECRET,
    _edit_provider,
    _platform_shaped,
    _raiser,
)
from tests.test_platform_exception_logs import _assert_class_name_only
from tests.test_tracking_preflight_enforced import _client, _url

#: Stands in for the Gemini API key a provider sends as ``?key=``.
_KEY = "gemini-key-SECRET-5678"


def _chained(base: type[Exception]) -> Exception:
    """A redacted provider error raised from an HTTP error whose URL has the key."""
    request = httpx.Request("POST", f"https://images.example/v1:generate?key={_KEY}")
    response = httpx.Response(400, request=request)
    cause = httpx.HTTPStatusError(
        f"Client error '400 Bad Request' for url '{request.url}'",
        request=request,
        response=response,
    )
    exc = base("fake image API error (HTTP 400): bad request")
    exc.__cause__ = cause
    return exc


def _assert_key_not_logged(caplog: pytest.LogCaptureFixture, exc: Exception) -> None:
    _assert_class_name_only(caplog, exc)
    assert _KEY not in caplog.text


# ---------------------------------------------------------------------------
# Creative Studio provider failures
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_visual_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _chained(RuntimeError)
    provider = SimpleNamespace(name="fake")
    monkeypatch.setattr(
        tools_creative_studio, "_resolve_providers", lambda _arg: [provider]
    )
    monkeypatch.setattr(tools_creative_studio, "create_run_dir", lambda: tmp_path)
    monkeypatch.setattr(
        tools_creative_studio, "_generate_into", AsyncMock(side_effect=exc)
    )

    with caplog.at_level(logging.DEBUG):
        result = await tools_creative_studio._handle_generate_visual({"prompt": "p"})

    assert _KEY not in result[0].text
    _assert_key_not_logged(caplog, exc)


@pytest.mark.unit
async def test_edit_visual_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _chained(RuntimeError)
    in_path = _edit_provider(monkeypatch, tmp_path, AsyncMock(side_effect=exc))
    monkeypatch.setattr(
        tools_creative_studio, "validate_image_file", lambda *_a, **_k: in_path
    )

    with caplog.at_level(logging.DEBUG):
        result = await tools_creative_studio._handle_edit_visual(
            {"path": str(in_path), "instruction": "brighter"}
        )

    assert _KEY not in result[0].text
    _assert_key_not_logged(caplog, exc)


@pytest.mark.unit
async def test_compose_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Not a RuntimeError: that one is the "missing extra" branch, which logs
    # nothing.
    exc = _chained(OSError)
    visual = tmp_path / "visual.png"
    monkeypatch.setattr(
        tools_creative_studio, "validate_image_file", lambda *_a, **_k: visual
    )
    monkeypatch.setattr(tools_creative_studio, "create_run_dir", lambda: tmp_path)
    monkeypatch.setattr(
        tools_creative_studio.composer, "compose", AsyncMock(side_effect=exc)
    )

    with caplog.at_level(logging.DEBUG):
        result = await tools_creative_studio._handle_compose(
            {"visual_path": str(visual), "headline": "H", "cta": "Buy"}
        )

    assert _KEY not in result[0].text
    _assert_key_not_logged(caplog, exc)


# ---------------------------------------------------------------------------
# api_error_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_api_error_handler_logs_class_and_curated_text_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _platform_shaped(RuntimeError)

    @api_error_handler
    async def handle_probe(_arguments: dict[str, Any]) -> Any:
        raise exc

    with caplog.at_level(logging.DEBUG):
        result = await handle_probe({})

    assert _SECRET not in result[0].text
    _assert_class_name_only(caplog, exc, logging.ERROR)
    messages = [r.getMessage() for r in caplog.records]
    assert f"handle_probe failed (ShapedRuntimeError): {_CURATED}" in messages


# ---------------------------------------------------------------------------
# Pre-flights and rollback
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_tracking_preflight_read_failure_logs_class_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _platform_shaped(RuntimeError)
    client = _client(list_ads=AsyncMock(side_effect=exc))
    _tracking_preflight.reset_preflight_cache()
    try:
        with caplog.at_level(logging.DEBUG):
            outcome = await _tracking_preflight.google_ads_create_preflight(
                client,
                ad_group_id="ag-b",
                final_url=_url(1, "sega01"),
                acknowledged=False,
            )
    finally:
        _tracking_preflight.reset_preflight_cache()

    assert outcome.note is not None
    logged = [r for r in caplog.records if r.name == _tracking_preflight.logger.name]
    assert "ShapedRuntimeError while reading the account" in logged[0].getMessage()
    assert all(r.exc_info is None for r in caplog.records)
    assert _SECRET not in caplog.text


def _surface(delivery: Any) -> ExclusionSurface:
    return ExclusionSurface(
        tool="fake_exclude", platform="fake", targets=lambda _a: (), delivery=delivery
    )


@pytest.mark.unit
async def test_exclusion_delivery_read_failure_logs_class_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _platform_shaped(RuntimeError)

    async def _delivery(_arguments: Any, _days: int) -> DeliverySample:
        raise exc

    with caplog.at_level(logging.DEBUG):
        sample = await exclusion_preflight._sample(_surface(_delivery), {}, 7)

    assert sample.records is None
    _assert_class_name_only(caplog, exc)
    assert _SECRET not in caplog.text


@pytest.mark.unit
async def test_exclusion_preflight_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exc = _platform_shaped(RuntimeError)
    monkeypatch.delenv(exclusion_preflight.DISABLE_ENV_VAR, raising=False)
    monkeypatch.setattr(
        exclusion_preflight,
        "exclusion_surface_for",
        lambda _name: _surface(AsyncMock()),
    )
    monkeypatch.setattr(exclusion_preflight, "load_guardrails", _raiser(exc))

    with caplog.at_level(logging.DEBUG):
        preflight = await exclusion_preflight.exclusion_impact_preflight(
            "fake_exclude", {}
        )

    assert not preflight.checked
    _assert_class_name_only(caplog, exc)
    assert _SECRET not in caplog.text


@pytest.mark.unit
async def test_rollback_dispatch_failure_logs_class_name_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _platform_shaped(RuntimeError)
    state_file = tmp_path / "STATE.json"
    monkeypatch.setattr(
        _handlers_rollback, "_resolve_state_file", lambda _a: state_file
    )
    monkeypatch.setattr(_handlers_rollback, "_get_dispatcher", lambda: AsyncMock())
    monkeypatch.setattr(
        _handlers_rollback, "execute_rollback", AsyncMock(side_effect=exc)
    )

    with caplog.at_level(logging.DEBUG):
        result = await _handlers_rollback.handle_apply({"index": 0, "confirm": True})

    assert _SECRET not in result[0].text
    _assert_class_name_only(caplog, exc, logging.ERROR)
    assert _SECRET not in caplog.text
