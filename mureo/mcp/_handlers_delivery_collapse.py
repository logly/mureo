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
    last_reported_day,
)
from mureo.analysis.delivery_collapse_config import load_collapse_thresholds
from mureo.core import clock
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


def _coerce_int(value: Any, field: str) -> int:
    """Accept an integer; reject bools and non-numerics.

    ``bool`` is an ``int`` subclass, so a bare ``int(value)`` silently
    turns ``true`` into 1. ``analysis_anomalies_check`` already rejects
    booleans on its numeric fields and is documented as doing so — these
    tools sit beside it and must not disagree.
    """
    if isinstance(value, bool):
        raise ValueError(f"'{field}' must be an integer, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"'{field}' must be an integer, got {value!r}") from exc
    raise ValueError(f"'{field}' must be an integer, got {type(value).__name__}")


def _parse_date_arg(arguments: dict[str, Any], field: str) -> date | None:
    """Parse an optional ``YYYY-MM-DD`` argument. ``None`` when absent."""
    raw = arguments.get(field)
    if not raw:
        return None
    from datetime import datetime

    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()  # noqa: DTZ007
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {raw!r}") from exc


def _parse_as_of(arguments: dict[str, Any]) -> date | None:
    return _parse_date_arg(arguments, "as_of")


def _series_from_arguments(arguments: dict[str, Any]) -> tuple[DeliverySeries, ...]:
    rows = _require(arguments, "rows")
    if not isinstance(rows, list):
        raise ValueError("'rows' must be an array of day-grain delivery rows")
    return delivery_series_from_rows(
        rows,
        platform=str(_require(arguments, "platform")),
        reported_through=_parse_date_arg(arguments, "reported_through"),
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
    reported = last_reported_day(series)
    evaluated_through = as_of or clock.server_now().date()
    return _json_result(
        {
            "platform": arguments.get("platform"),
            "evaluated_campaigns": len(series),
            "baseline_source": BASELINE_SOURCE,
            "thresholds": _jsonable(thresholds),
            "thresholds_source": source,
            # The one state the detector has no opinion on: when every
            # campaign stops reporting at once, a total outage and a
            # reporting failure are indistinguishable. Reported, not
            # guessed at — an empty `signals` with a climbing
            # `unreported_days` is NOT an all-clear.
            "reported_through": reported.isoformat() if reported else "",
            "unreported_days": (
                max(0, (evaluated_through - reported).days - 1) if reported else 0
            ),
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
            change_lookback_days=_coerce_int(
                _opt(arguments, "change_lookback_days", DEFAULT_CHANGE_LOOKBACK_DAYS),
                "change_lookback_days",
            ),
            timeline_days=_coerce_int(
                _opt(arguments, "timeline_days", DEFAULT_TIMELINE_DAYS),
                "timeline_days",
            ),
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
