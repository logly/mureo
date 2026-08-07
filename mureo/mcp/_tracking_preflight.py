"""Enforced tracking-parameter pre-flight on native ad creation (#550).

`analysis_tracking_consistency_check` is the tool an agent *can* call.
This module is what runs whether it does or not: the native Google Ads
ad-create handlers call :func:`google_ads_create_preflight` before the
mutation, and refuse the create when the ad about to be uploaded
carries another campaign's tracking identity.

**Why not a PolicyGate.** :class:`mureo.core.policy.PolicyGate` is the
dispatch-level hook for write tools, and it is the wrong shape for this
check on two counts that are stated in its own ABI contract: the v1
Protocol is *synchronous by design* ("gates that need to await network
I/O are out of scope"), and gates "MUST be pure and fast" because they
run on every tool call. This check is inherently neither — it can only
compare the planned ad against the ads already in the account, which
means one platform read. A gate also never sees the campaign: the
arguments to ``google_ads_ads_create`` carry ``ad_group_id``, not
``campaign_id``, and no siblings, so a pure gate would have nothing to
compare and would enforce nothing. The handler is the first point that
has both a client and an await.

**Failure policy: fail open, never fail closed.** A tracking check that
cannot read the account must not block an operator from shipping an ad.
Any error in the pre-flight is logged and the create proceeds. The one
thing that blocks is a positive finding.

**Override.** A finding is a refusal the operator can overrule by
re-issuing the call with ``acknowledge_tracking_findings=true`` (the
same shape as ``rollback_apply``'s ``confirm``). Set
``MUREO_DISABLE_TRACKING_PREFLIGHT=1`` to switch the pre-flight off
entirely for an account whose tracking mureo cannot model.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from mureo.analysis.tracking import (
    AdTrackingRecord,
    preflight_tracking_consistency,
    records_from_google_ads_ads,
)
from mureo.mcp._helpers import _json_result

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mcp.types import TextContent

    from mureo.analysis.tracking import TrackingFinding

logger = logging.getLogger(__name__)

#: Env var that disables the enforced pre-flight entirely.
DISABLE_ENV = "MUREO_DISABLE_TRACKING_PREFLIGHT"

#: Placeholder ad id for the ad that does not exist yet.
PLANNED_AD_ID = "(the ad you are creating)"


def preflight_disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip() not in ("", "0", "false", "False")


def _finding_to_dict(finding: TrackingFinding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "delivery_state": finding.delivery_state.value,
        "campaign_id": finding.campaign_id,
        "message": finding.message,
        "recommended_action": finding.recommended_action,
        "evidence": dict(finding.evidence),
    }


def _refusal(findings: Sequence[TrackingFinding]) -> list[TextContent]:
    return _json_result(
        {
            "error": "tracking_preflight_failed",
            "message": (
                "The ad was NOT created. Its tracking parameters disagree with "
                "the campaign it would land in — a defect that is silent once "
                "live, because delivery and spend stay healthy while reporting "
                "is wrong. Show these findings to the operator and confirm "
                "which campaign the ad belongs to."
            ),
            "findings": [_finding_to_dict(f) for f in findings],
            "how_to_proceed": (
                "Fix the final URL, or — if the tagging is deliberate — re-issue "
                "the same call with acknowledge_tracking_findings=true. Do not "
                "acknowledge without asking the operator."
            ),
        }
    )


async def _resolve_campaign_id(
    client: Any, rows: Sequence[dict[str, Any]], ad_group_id: str
) -> str:
    """Campaign the target ad group belongs to, or "" when unresolvable."""
    for row in rows:
        if str(row.get("ad_group_id")) == ad_group_id:
            return str(row.get("campaign_id") or "")
    # A brand-new ad group has no ads to join through — ask directly.
    for group in await client.list_ad_groups():
        if str(group.get("id")) == ad_group_id:
            return str(group.get("campaign_id") or "")
    return ""


async def google_ads_create_preflight(
    client: Any,
    *,
    ad_group_id: str,
    final_url: str | None,
    acknowledged: bool,
) -> list[TextContent] | None:
    """Refuse a Google Ads ad create whose tracking is inconsistent.

    Returns a refusal payload to return to the caller instead of
    creating the ad, or ``None`` to let the create proceed. Never
    raises: any failure to run the check is a reason to proceed, not to
    block.
    """
    if acknowledged or preflight_disabled() or not final_url:
        return None
    try:
        rows = await client.list_ads()
        campaign_id = await _resolve_campaign_id(client, rows, ad_group_id)
        if not campaign_id:
            # Without the target campaign there is nothing to compare
            # against; say so in the log rather than pretending it passed.
            logger.info(
                "tracking pre-flight skipped: could not resolve the campaign for "
                "the target ad group"
            )
            return None
        existing = records_from_google_ads_ads(rows)
        planned = AdTrackingRecord(
            ad_id=PLANNED_AD_ID,
            campaign_id=campaign_id,
            final_urls=(final_url,),
            platform="google_ads",
            planned=True,
        )
        report = preflight_tracking_consistency([planned], existing)
    except Exception:  # noqa: BLE001 - a read failure must not block a create
        logger.warning("tracking pre-flight could not run; proceeding", exc_info=True)
        return None
    if not report.findings:
        return None
    return _refusal(report.findings)


__all__ = [
    "DISABLE_ENV",
    "PLANNED_AD_ID",
    "google_ads_create_preflight",
    "preflight_disabled",
]
