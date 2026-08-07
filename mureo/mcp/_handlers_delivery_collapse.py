"""MCP handlers for the delivery-collapse tools (#546).

Thin composition over the pure
:mod:`mureo.analysis.delivery_collapse` /
:mod:`mureo.analysis.collapse_diagnosis` modules. These two tools are
the platform-agnostic half of the feature: any platform that can produce
day-grain rows — a hosted connector such as ``tiktok_ads``, an
official-MCP bridge such as Amazon, or a plugin platform — gets the same
detection and the same elimination ladder without mureo owning a client
for it. Native platforms (google_ads / meta_ads) get the same core
automatically through ``mureo_analytics_run``.

No filesystem input: thresholds come from the workspace's STRATEGY.md
``## Guardrails`` (resolved through the runtime context, never from a
caller-supplied path), and the delivery rows come in as arguments.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from mureo.analysis.collapse_diagnosis import (
    DEFAULT_CHANGE_LOOKBACK_DAYS,
    DEFAULT_TIMELINE_DAYS,
    ChangeEvent,
    CheckOutcome,
    EvidenceCheck,
    diagnose_collapse,
)
from mureo.analysis.delivery_collapse import (
    BASELINE_SOURCE,
    delivery_series_from_rows,
    detect_delivery_collapse,
    detect_delivery_collapses,
)
from mureo.analysis.delivery_collapse_config import load_collapse_thresholds
from mureo.mcp._helpers import _json_result, _opt, _require

if TYPE_CHECKING:
    from datetime import date

    from mcp.types import TextContent

    from mureo.analysis.delivery_collapse import DeliverySeries


def _jsonable(value: Any) -> Any:
    """Frozen dataclasses -> dicts, enums -> values, tuples -> lists."""
    import enum

    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _parse_as_of(arguments: dict[str, Any]) -> date | None:
    raw = arguments.get("as_of")
    if not raw:
        return None
    from datetime import datetime

    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()  # noqa: DTZ007
    except ValueError as exc:
        raise ValueError(f"as_of must be YYYY-MM-DD, got {raw!r}") from exc


def _series_from_arguments(arguments: dict[str, Any]) -> tuple[DeliverySeries, ...]:
    rows = _require(arguments, "rows")
    if not isinstance(rows, list):
        raise ValueError("'rows' must be an array of day-grain delivery rows")
    return delivery_series_from_rows(
        rows, platform=str(_require(arguments, "platform"))
    )


async def handle_delivery_collapse_check(
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Detect collapsed campaigns in a normalised day-grain report."""
    try:
        series = _series_from_arguments(arguments)
        as_of = _parse_as_of(arguments)
    except ValueError as exc:
        return _json_result({"error": str(exc), "signals": []})

    thresholds, source = load_collapse_thresholds()
    signals = detect_delivery_collapses(series, thresholds=thresholds, as_of=as_of)
    return _json_result(
        {
            "platform": arguments.get("platform"),
            "evaluated_campaigns": len(series),
            "baseline_source": BASELINE_SOURCE,
            "thresholds": _jsonable(thresholds),
            "thresholds_source": source,
            "signals": _jsonable(signals),
        }
    )


def _changes_from_arguments(arguments: dict[str, Any]) -> tuple[ChangeEvent, ...]:
    raw = _opt(arguments, "changes", []) or []
    if not isinstance(raw, list):
        raise ValueError("'changes' must be an array of change events")
    return tuple(
        ChangeEvent(
            occurred_at=str(item.get("occurred_at") or ""),
            source=str(item.get("source") or ""),
            resource_type=str(item.get("resource_type") or ""),
            summary=str(item.get("summary") or ""),
            actor=str(item.get("actor") or ""),
        )
        for item in raw
        if isinstance(item, dict)
    )


def _checks_from_arguments(arguments: dict[str, Any]) -> tuple[EvidenceCheck, ...]:
    raw = _opt(arguments, "evidence", []) or []
    if not isinstance(raw, list):
        raise ValueError("'evidence' must be an array of check results")
    checks: list[EvidenceCheck] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        outcome = str(item.get("outcome") or "")
        try:
            parsed = CheckOutcome(outcome)
        except ValueError as exc:
            raise ValueError(
                f"unknown evidence outcome {outcome!r}; expected one of "
                f"{', '.join(o.value for o in CheckOutcome)}"
            ) from exc
        checks.append(
            EvidenceCheck(
                name=str(item.get("check") or ""),
                outcome=parsed,
                detail=str(item.get("detail") or ""),
            )
        )
    return tuple(checks)


async def handle_delivery_collapse_diagnose(
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Overlay the change feed on delivery and walk the elimination ladder.

    Returns ``status="no_collapse_detected"`` when the campaign does not
    currently qualify — a diagnosis of a collapse that is not happening
    would be fabricated reasoning.

    ``change_lookback_days`` and ``timeline_days`` are caller-settable:
    a cause with a delayed effect (a billing hold placed five days before
    delivery stopped) falls outside the 3-day default, and asking the
    operator to supply everything they know and then narrowing it
    silently is the wrong trade.
    """
    try:
        series = _series_from_arguments(arguments)
        as_of = _parse_as_of(arguments)
        campaign_id = str(_require(arguments, "campaign_id"))
        changes = _changes_from_arguments(arguments)
        checks = _checks_from_arguments(arguments)
    except ValueError as exc:
        return _json_result({"error": str(exc)})

    target = next((s for s in series if s.campaign_id == campaign_id), None)
    if target is None:
        return _json_result(
            {
                "status": "campaign_not_in_rows",
                "campaign_id": campaign_id,
            }
        )

    thresholds, _source = load_collapse_thresholds()
    signal = detect_delivery_collapse(target, thresholds=thresholds, as_of=as_of)
    if signal is None:
        return _json_result(
            {"status": "no_collapse_detected", "campaign_id": campaign_id}
        )

    try:
        diagnosis = diagnose_collapse(
            signal,
            target,
            changes=changes,
            checks=checks,
            change_lookback_days=int(
                _opt(arguments, "change_lookback_days", DEFAULT_CHANGE_LOOKBACK_DAYS)
            ),
            timeline_days=int(_opt(arguments, "timeline_days", DEFAULT_TIMELINE_DAYS)),
        )
    except ValueError as exc:
        return _json_result({"error": str(exc)})

    payload = _jsonable(diagnosis)
    payload["status"] = "ok"
    payload["signal"] = _jsonable(signal)
    return _json_result(payload)


__all__ = [
    "handle_delivery_collapse_check",
    "handle_delivery_collapse_diagnose",
]
