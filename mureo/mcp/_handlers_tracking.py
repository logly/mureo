"""MCP handler for ``analysis_tracking_consistency_check``.

Thin composition layer over the pure detector in
:mod:`mureo.analysis.tracking`. The handler takes ad records the caller
already assembled — from mureo's own ``google_ads_ads_list`` /
``meta_ads_ads_list``, from a plugin platform's own tools, or from a
bridged MCP — so a platform mureo cannot fetch ads for is still
auditable whenever the agent can list them. Nothing here talks to a
platform API, and nothing here mutates.

The ``## Tracking Convention`` section of STRATEGY.md is parsed by
mureo, not interpreted by the agent: an LLM deciding on the fly what
"consistent" means is exactly the failure this check exists to replace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.analysis.tracking import (
    AdTrackingRecord,
    check_tracking_consistency,
    parse_tracking_convention,
    preflight_tracking_consistency,
)
from mureo.mcp._helpers import _json_result, _opt, _require

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mcp.types import TextContent

    from mureo.analysis.tracking import TrackingConsistencyReport, TrackingFinding


def _coerce_impressions(raw: Any, ad_id: str) -> int | None:
    """``None`` means "not supplied" and is NOT the same as ``0``."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError(f"ads[{ad_id}].impressions must be an integer, got bool")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"ads[{ad_id}].impressions must be an integer, got {raw!r}"
        ) from exc


def _build_record(raw: Any, *, field: str, planned: bool) -> AdTrackingRecord:
    if not isinstance(raw, dict):
        raise ValueError(f"Every entry in '{field}' must be an object")
    ad_id = raw.get("ad_id")
    if not isinstance(ad_id, str) or not ad_id:
        raise ValueError(f"Every entry in '{field}' must carry a non-empty 'ad_id'")
    urls = raw.get("final_urls") or []
    if not isinstance(urls, list) or any(not isinstance(u, str) for u in urls):
        raise ValueError(f"ads[{ad_id}].final_urls must be a list of strings")
    return AdTrackingRecord(
        ad_id=ad_id,
        campaign_id=str(raw.get("campaign_id") or ""),
        final_urls=tuple(urls),
        platform=str(raw.get("platform") or ""),
        campaign_name=str(raw.get("campaign_name") or ""),
        status=str(raw.get("status") or ""),
        impressions=_coerce_impressions(raw.get("impressions"), ad_id),
        planned=planned,
    )


def _build_records(
    raw: Any, *, field: str, planned: bool = False
) -> tuple[AdTrackingRecord, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"'{field}' must be a list of ad objects")
    return tuple(_build_record(item, field=field, planned=planned) for item in raw)


def _finding_to_dict(finding: TrackingFinding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "delivery_state": finding.delivery_state.value,
        "platform": finding.platform,
        "campaign_id": finding.campaign_id,
        "ad_ids": list(finding.ad_ids),
        "message": finding.message,
        "recommended_action": finding.recommended_action,
        "evidence": dict(finding.evidence),
    }


def _report_to_dict(
    report: TrackingConsistencyReport, *, mode: str, convention_declared: bool
) -> dict[str, Any]:
    return {
        "mode": mode,
        "convention_declared": convention_declared,
        "findings": [_finding_to_dict(f) for f in report.findings],
        "ads_examined": report.ads_examined,
        "campaigns_examined": report.campaigns_examined,
        "ads_without_readable_url": list(report.ads_without_readable_url),
        "notes": list(report.notes),
    }


def _run(
    ads: Sequence[AdTrackingRecord],
    planned: Sequence[AdTrackingRecord],
    convention: Any,
) -> tuple[TrackingConsistencyReport, str]:
    if planned:
        return (
            preflight_tracking_consistency(planned, ads, convention=convention),
            "preflight",
        )
    return check_tracking_consistency(ads, convention=convention), "audit"


async def handle_tracking_consistency_check(
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Audit (or pre-flight) tracking-parameter consistency. Read-only."""
    ads = _build_records(_require(arguments, "ads"), field="ads")
    planned = _build_records(
        _opt(arguments, "planned_ads", []) or [], field="planned_ads", planned=True
    )
    markdown = _opt(arguments, "convention_markdown")
    convention = parse_tracking_convention(markdown) if markdown else None
    report, mode = _run(ads, planned, convention)
    return _json_result(
        _report_to_dict(report, mode=mode, convention_declared=convention is not None)
    )


__all__ = ["handle_tracking_consistency_check"]
