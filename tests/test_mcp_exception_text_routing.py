"""MCP handlers turn a caught exception into text through ``exception_text`` (#865).

``mureo.mcp._helpers.exception_text`` is the one formatting point: for an
exception shaped like a platform failure (``failure.errors``) it returns
the curated server-side message and never ``str(exc)``, which can carry the
request metadata (#603); for any other exception it returns the message, or
the class name when the message is empty. Each handler below used to put
``str(exc)`` in the failure envelope's ``detail``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mureo.context.batch import BatchError
from mureo.context.errors import ContextFileError
from mureo.core import tool_failure
from mureo.creative_studio.providers import NotSupportedError
from mureo.mcp import (
    _auto_evaluation_hook,
    _handlers_analysis,
    _handlers_batch,
    _handlers_delivery_collapse,
    _handlers_rollback,
    tools_creative_studio,
)
from mureo.mcp._helpers import exception_text
from mureo.rollback import RollbackExecutionError
from tests.test_mcp_tools_delivery_collapse import AS_OF, _rows

_SECRET = "authorization: Bearer SECRET-1234"
_CURATED = "The campaign could not be read."


def _platform_shaped(base: type[Exception]) -> Exception:
    """A ``base`` whose text is a secret and whose curated message is not."""
    exc = type(f"Shaped{base.__name__}", (base,), {})(_SECRET)
    exc.failure = SimpleNamespace(  # type: ignore[attr-defined]
        errors=[SimpleNamespace(message=_CURATED)]
    )
    return exc


def _raiser(exc: Exception) -> Any:
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return _raise


def _detail(result: list[Any], exc: Exception) -> str:
    payload = json.loads(result[0].text)
    assert payload["detail"] == exception_text(exc) == _CURATED
    assert _SECRET not in result[0].text
    return str(payload["error"])


@pytest.mark.unit
async def test_delivery_collapse_check_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(
        _handlers_delivery_collapse, "_series_from_arguments", _raiser(exc)
    )

    result = await _handlers_delivery_collapse.handle_delivery_collapse_check({})

    assert _detail(result, exc) == "invalid_arguments"


@pytest.mark.unit
async def test_delivery_collapse_diagnose_arguments_route_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(
        _handlers_delivery_collapse, "_series_from_arguments", _raiser(exc)
    )

    result = await _handlers_delivery_collapse.handle_delivery_collapse_diagnose({})

    assert _detail(result, exc) == "invalid_arguments"


@pytest.mark.unit
async def test_delivery_collapse_diagnosis_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(_handlers_delivery_collapse, "diagnose_collapse", _raiser(exc))

    result = await _handlers_delivery_collapse.handle_delivery_collapse_diagnose(
        {
            "platform": "google_ads",
            "campaign_id": "c-1",
            "rows": _rows(),
            "as_of": AS_OF.isoformat(),
        }
    )

    assert _detail(result, exc) == "invalid_arguments"


@pytest.mark.unit
async def test_creative_compose_unavailable_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exc = _platform_shaped(RuntimeError)
    visual = tmp_path / "visual.png"
    monkeypatch.setattr(
        tools_creative_studio, "validate_image_file", lambda *_a, **_k: visual
    )
    monkeypatch.setattr(tools_creative_studio, "create_run_dir", lambda: tmp_path)
    monkeypatch.setattr(
        tools_creative_studio.composer, "compose", AsyncMock(side_effect=exc)
    )

    result = await tools_creative_studio._handle_compose(
        {"visual_path": str(visual), "headline": "H", "cta": "Buy"}
    )

    assert _detail(result, exc) == "provider_unavailable"


@pytest.mark.unit
async def test_rollback_plan_arguments_route_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(_handlers_rollback, "_resolve_state_file", _raiser(exc))

    result = await _handlers_rollback.handle_plan_get({})

    assert _detail(result, exc) == "invalid_arguments"


@pytest.mark.unit
async def test_rollback_plan_unreadable_state_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exc = _platform_shaped(ContextFileError)
    state_file = tmp_path / "STATE.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        _handlers_rollback, "_resolve_state_file", lambda _a: state_file
    )
    monkeypatch.setattr(_handlers_rollback, "_selector", lambda _a: ("index", 0))
    monkeypatch.setattr(_handlers_rollback, "read_state_file", _raiser(exc))

    result = await _handlers_rollback.handle_plan_get({})

    assert _detail(result, exc) == "state_file_unreadable"


@pytest.mark.unit
async def test_rollback_apply_arguments_route_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(_handlers_rollback, "_resolve_state_file", _raiser(exc))

    result = await _handlers_rollback.handle_apply({"index": 0, "confirm": True})

    assert _detail(result, exc) == "invalid_arguments"


@pytest.mark.unit
async def test_rollback_apply_refusal_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exc = _platform_shaped(RollbackExecutionError)
    state_file = tmp_path / "STATE.json"
    monkeypatch.setattr(
        _handlers_rollback, "_resolve_state_file", lambda _a: state_file
    )
    monkeypatch.setattr(_handlers_rollback, "_get_dispatcher", lambda: AsyncMock())
    monkeypatch.setattr(
        _handlers_rollback, "execute_rollback", AsyncMock(side_effect=exc)
    )

    result = await _handlers_rollback.handle_apply({"index": 0, "confirm": True})

    assert _detail(result, exc) == "rollback_refused"


@pytest.mark.unit
async def test_anomalies_check_arguments_route_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(_handlers_analysis, "_resolve_state_file", _raiser(exc))

    result = await _handlers_analysis.handle_anomalies_check({})

    assert _detail(result, exc) == "invalid_arguments"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("handler", "call", "arguments"),
    [
        ("handle_batch_begin", "begin_batch", {"label": "Q3 restructure"}),
        ("handle_batch_end", "end_batch", {}),
    ],
)
async def test_batch_refusal_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    handler: str,
    call: str,
    arguments: dict[str, Any],
) -> None:
    exc = _platform_shaped(BatchError)
    state_file = tmp_path / "STATE.json"
    monkeypatch.setattr(
        _handlers_batch, "resolve_workspace_path", lambda *_a, **_k: state_file
    )
    monkeypatch.setattr(_handlers_batch, call, _raiser(exc))

    result = await getattr(_handlers_batch, handler)(arguments)

    assert _detail(result, exc) == "batch_refused"


def _prefixed(result: list[Any], prefix: str) -> str:
    """The envelope's ``detail`` is ``prefix`` + the curated text, no secret."""
    payload = json.loads(result[0].text)
    assert payload["detail"] == f"{prefix}{_CURATED}"
    assert _SECRET not in result[0].text
    return str(payload["error"])


@pytest.mark.unit
async def test_creative_edit_invalid_path_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(tools_creative_studio, "validate_image_file", _raiser(exc))

    result = await tools_creative_studio._handle_edit_visual(
        {"path": "in.png", "instruction": "brighter"}
    )

    assert _prefixed(result, "invalid image path: ") == "invalid_arguments"


def _edit_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, edit: AsyncMock
) -> Path:
    """Wire one fake edit-capable provider; return the validated input path."""
    in_path = tmp_path / "in.png"
    in_path.write_bytes(b"png")
    provider = SimpleNamespace(name="fake", edit=edit)
    monkeypatch.setattr(
        tools_creative_studio, "_resolve_edit_provider", lambda _arg: provider
    )
    monkeypatch.setattr(
        tools_creative_studio, "_THROTTLER", SimpleNamespace(acquire=AsyncMock())
    )
    return in_path


@pytest.mark.unit
async def test_creative_edit_not_supported_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exc = _platform_shaped(NotSupportedError)
    in_path = _edit_provider(monkeypatch, tmp_path, AsyncMock(side_effect=exc))
    monkeypatch.setattr(
        tools_creative_studio, "validate_image_file", lambda *_a, **_k: in_path
    )

    result = await tools_creative_studio._handle_edit_visual(
        {"path": str(in_path), "instruction": "brighter"}
    )

    prefix = "provider 'fake' does not support image editing: "
    assert _prefixed(result, prefix) == "invalid_arguments"


@pytest.mark.unit
async def test_creative_edited_image_validation_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exc = _platform_shaped(ValueError)
    in_path = _edit_provider(monkeypatch, tmp_path, AsyncMock(return_value=b"png"))
    validate = MagicMock(side_effect=[in_path, exc])
    monkeypatch.setattr(tools_creative_studio, "validate_image_file", validate)
    monkeypatch.setattr(tools_creative_studio, "write_bytes", lambda p, _d: p)

    result = await tools_creative_studio._handle_edit_visual(
        {"path": str(in_path), "instruction": "brighter"}
    )

    assert _prefixed(result, "edited image failed validation: ") == "provider_failed"


@pytest.mark.unit
async def test_creative_compose_invalid_visual_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _platform_shaped(ValueError)
    monkeypatch.setattr(tools_creative_studio, "validate_image_file", _raiser(exc))

    result = await tools_creative_studio._handle_compose(
        {"visual_path": "visual.png", "headline": "H", "cta": "Buy"}
    )

    assert _prefixed(result, "invalid visual path: ") == "invalid_arguments"


@pytest.mark.unit
def test_auto_evaluation_error_routes_through_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exc = _platform_shaped(RuntimeError)
    monkeypatch.setattr(_auto_evaluation_hook, "close_due_observations", _raiser(exc))
    monkeypatch.setattr(_auto_evaluation_hook, "load_outcome_thresholds", lambda: None)

    with caplog.at_level(logging.WARNING):
        fragment = _auto_evaluation_hook._auto_evaluate(tmp_path / "STATE.json", {})

    name = type(exc).__name__
    assert fragment["auto_evaluation_error"] == f"{name}: {_CURATED}"
    assert any(f"({name})" in r.getMessage() for r in caplog.records)
    assert all(_SECRET not in r.getMessage() for r in caplog.records)
    assert all(r.exc_info is None for r in caplog.records)


@pytest.mark.unit
def test_exception_text_is_the_core_function_re_exported() -> None:
    """One function, defined in core and re-exported by the MCP helpers."""
    assert exception_text is tool_failure.exception_text
