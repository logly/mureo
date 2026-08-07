"""Enforced tracking-parameter pre-flight on native ad creation (#550).

`analysis_tracking_consistency_check` is the tool an agent *can* call.
This module is what runs whether it does or not: the native Google Ads
ad-create handlers call :func:`google_ads_create_preflight` before the
mutation, and refuse the create when the ad about to be uploaded
carries another campaign's tracking identity.

**The declared convention reaches this path too.** The operator's
``## Tracking Convention`` is read from ``STRATEGY.md`` in the active
workspace and applied here exactly as the advisory tool applies it. An
enforcement path running on defaults while the advisory path honours
``identify:`` / ``differentiate:`` would break the promise the feature
is built on — intent is declared, never inferred — in both directions
at once: the account that declared ``differentiate:`` to stop
legitimate variation being flagged would still be blocked (and would
learn to pass ``acknowledge_tracking_findings`` reflexively), while the
account that declared ``identify:`` because its segment marker lives in
``utm_content`` would get no enforcement on a genuine leak.

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
Any error is logged and the create proceeds — but never *silently*: the
create response carries a ``tracking_preflight`` note saying the
guardrail did not run, and repeated consecutive failures escalate to an
ERROR log, because a permanently broken guardrail and a quiet one look
identical from the outside otherwise.

**Override.** A finding is a refusal the operator can overrule by
re-issuing the call with ``acknowledge_tracking_findings=true`` (the
same shape as ``rollback_apply``'s ``confirm``). Set
``MUREO_DISABLE_TRACKING_PREFLIGHT=1`` to switch the pre-flight off
entirely for an account whose tracking mureo cannot model.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.analysis.tracking import (
    AdTrackingRecord,
    parse_tracking_convention,
    preflight_tracking_consistency,
    records_from_google_ads_ads,
)
from mureo.mcp._helpers import _json_result

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mcp.types import TextContent

    from mureo.analysis.tracking import TrackingConvention, TrackingFinding

logger = logging.getLogger(__name__)

#: Env var that disables the enforced pre-flight entirely.
DISABLE_ENV = "MUREO_DISABLE_TRACKING_PREFLIGHT"

#: Placeholder ad id for the ad that does not exist yet.
PLANNED_AD_ID = "(the ad you are creating)"

#: The file the operator's convention is declared in.
STRATEGY_FILENAME = "STRATEGY.md"

#: Seconds an account-wide ad snapshot is reused across creates.
#:
#: The cross-campaign check needs the WHOLE account — finding the
#: campaign a scheme was copied from is the point — so the read cannot
#: be narrowed to the target campaign without removing the check's
#: reason to exist. What it can avoid is re-reading once per ad during
#: a bulk upload, which is exactly the shape of the incident this
#: guards against (16 ads in one sitting).
SNAPSHOT_TTL_SECONDS = 60.0

#: Consecutive failures before the fail-open path escalates to ERROR.
_FAILURES_BEFORE_ALARM = 3

_snapshot_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_consecutive_failures = 0


@dataclass(frozen=True)
class PreflightOutcome:
    """What the handler should do with the create it was about to make.

    ``refusal`` is a payload to return *instead of* creating the ad.
    ``note`` is a line to attach to a successful create, used only to
    say that the guardrail did not actually run — silence and "checked,
    clean" must not look the same.
    """

    refusal: list[TextContent] | None = None
    note: str | None = None

    @property
    def refused(self) -> bool:
        return self.refusal is not None


def preflight_disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip() not in ("", "0", "false", "False")


def reset_preflight_cache() -> None:
    """Drop the cached account snapshots and the failure counter."""
    global _consecutive_failures
    _snapshot_cache.clear()
    _consecutive_failures = 0


def _workspace() -> Path:
    """The active workspace, matching how the other handlers resolve it."""
    from mureo.core.runtime_context import get_runtime_context

    store = get_runtime_context().state_store
    return Path(getattr(store, "workspace", Path.cwd()))


def load_workspace_convention() -> TrackingConvention | None:
    """Parse ``## Tracking Convention`` out of the workspace STRATEGY.md.

    The path is mureo's own (``<workspace>/STRATEGY.md``), never a
    caller-supplied string, so there is no traversal surface here.
    Returns ``None`` when the file or the section is absent, or when
    anything at all goes wrong — a convention that cannot be read falls
    back to the documented defaults rather than to no enforcement.
    """
    try:
        path = _workspace() / STRATEGY_FILENAME
        if not path.is_file():
            return None
        return parse_tracking_convention(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable STRATEGY.md is not fatal
        logger.warning(
            "tracking pre-flight: could not read %s; using default parameter sets",
            STRATEGY_FILENAME,
            exc_info=True,
        )
        return None


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


def _not_run(reason: str) -> PreflightOutcome:
    """Proceed with the create, but say the guardrail did not run."""
    return PreflightOutcome(
        note=(
            f"NOT CHECKED: the tracking-parameter pre-flight did not run "
            f"({reason}). This ad's tracking was not validated against its "
            f"campaign — run analysis_tracking_consistency_check on the "
            f"campaign, or /tracking-health on the account."
        )
    )


def _record_failure(exc: BaseException) -> None:
    """Count consecutive failures and escalate a persistent one."""
    global _consecutive_failures
    _consecutive_failures += 1
    if _consecutive_failures >= _FAILURES_BEFORE_ALARM:
        logger.error(
            "tracking pre-flight has failed %d times in a row — the create-time "
            "guardrail is effectively OFF; ads are being created unchecked",
            _consecutive_failures,
            exc_info=exc,
        )
    else:
        logger.warning("tracking pre-flight could not run; proceeding", exc_info=exc)


async def _account_snapshot(client: Any) -> list[dict[str, Any]]:
    """Account-wide ad rows, reused for ``SNAPSHOT_TTL_SECONDS``."""
    key = str(getattr(client, "_customer_id", "") or id(client))
    cached = _snapshot_cache.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < SNAPSHOT_TTL_SECONDS:
        return cached[1]
    rows = list(await client.list_ads())
    _snapshot_cache[key] = (now, rows)
    return rows


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
) -> PreflightOutcome:
    """Refuse a Google Ads ad create whose tracking is inconsistent.

    Never raises: any failure to run the check is a reason to proceed,
    not to block — but the outcome then carries a note so the create
    response says the guardrail did not run.
    """
    global _consecutive_failures
    if acknowledged or preflight_disabled() or not final_url:
        return PreflightOutcome()
    try:
        rows = await _account_snapshot(client)
        campaign_id = await _resolve_campaign_id(client, rows, ad_group_id)
        if not campaign_id:
            return _not_run("the campaign for the target ad group is unresolvable")
        planned = AdTrackingRecord(
            ad_id=PLANNED_AD_ID,
            campaign_id=campaign_id,
            final_urls=(final_url,),
            platform="google_ads",
            planned=True,
        )
        report = preflight_tracking_consistency(
            [planned],
            records_from_google_ads_ads(rows),
            convention=load_workspace_convention(),
        )
    except Exception as exc:  # noqa: BLE001 - a read failure must not block a create
        _record_failure(exc)
        return _not_run(f"{type(exc).__name__} while reading the account")
    _consecutive_failures = 0
    if not report.findings:
        return PreflightOutcome()
    return PreflightOutcome(refusal=_refusal(report.findings))


__all__ = [
    "DISABLE_ENV",
    "PLANNED_AD_ID",
    "SNAPSHOT_TTL_SECONDS",
    "STRATEGY_FILENAME",
    "PreflightOutcome",
    "google_ads_create_preflight",
    "load_workspace_convention",
    "preflight_disabled",
    "reset_preflight_cache",
]
