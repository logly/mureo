"""Build a context-rich query string for advisor consultation.

Reads the local ``StateStore`` for the requested campaign's metrics
+ recent action log, plus the workspace's ``STRATEGY.md`` entries,
and folds them into the operator's natural-language question. The
advisor server's vector search has more to match against than just
"why is CPA up?" — it sees the platform, the campaign name / status /
type, recent mutations and the business goal too.

The builder is intentionally tolerant: any failure reading state
collapses to "just the question" so a corrupted ``STATE.json`` never
breaks the diagnostic flow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.context.models import CampaignSnapshot, StateDocument, StrategyEntry
    from mureo.core.state_store import StateStore

logger = logging.getLogger(__name__)

_MAX_ACTION_LOG_ENTRIES = 5


def build_query(
    *,
    state_store: StateStore,
    question: str,
    campaign_id: str | None = None,
    platform: str | None = None,
) -> str:
    """Compose the query string sent to advisor vector-search tools.

    Layout::

        Question: <question>
        Platform: <platform key>
        Campaign: <name> [<status>] (daily_budget=<n>)
        Campaign type: <campaign_type>
        Recent actions:
        - <ts> <action>: <summary>
        Strategy:
        - <title>: <content>

    ``Platform`` is the ``platform`` argument, else the ``platforms`` key
    the campaign was found under. Missing pieces are silently dropped.
    The question is always included even on full state-read failure so
    the advisor still has something to match against.
    """
    parts: list[str] = [f"Question: {question}"]

    try:
        state = state_store.read_state()
    except Exception as exc:  # noqa: BLE001 — missing context pieces are dropped
        logger.debug("context_builder: state read failed (%s)", exc)
        state = None

    snap: CampaignSnapshot | None = None
    if state is not None and campaign_id:
        found_under, snap = _find_campaign(state, campaign_id, platform)
        platform = platform or found_under
    if platform:
        parts.append(f"Platform: {platform}")
    if snap is not None:
        parts.extend(_campaign_lines(snap))
    if state is not None and campaign_id:
        parts.extend(_recent_action_lines(state, campaign_id, platform))

    try:
        strategy = state_store.read_strategy()
    except Exception as exc:  # noqa: BLE001 — missing context pieces are dropped
        logger.debug("context_builder: strategy read failed (%s)", exc)
        strategy = []

    parts.extend(_strategy_lines(strategy))
    return "\n".join(parts)


def _find_campaign(
    state: StateDocument, campaign_id: str, platform: str | None
) -> tuple[str | None, CampaignSnapshot | None]:
    """The campaign ``campaign_id`` and the ``platforms`` key it sits under.

    The v1 top-level ``campaigns`` comes first (no platform key). v2 moved
    campaigns under ``platforms.<key>.campaigns``, so those are searched
    next — only ``platforms[platform]`` when ``platform`` is given, because
    a campaign id is unique per platform, not across them.
    """
    for snap in state.campaigns:
        if snap.campaign_id == campaign_id:
            return None, snap
    for key, platform_state in (state.platforms or {}).items():
        if platform and key != platform:
            continue
        for snap in platform_state.campaigns:
            if snap.campaign_id == campaign_id:
                return key, snap
    return None, None


def _campaign_lines(snap: CampaignSnapshot) -> list[str]:
    """The ``Campaign:`` line and, when the snapshot has it, its type."""
    line = f"Campaign: {snap.campaign_name} [{snap.status}]"
    if snap.daily_budget is not None:
        line += f" (daily_budget={snap.daily_budget})"
    lines = [line]
    if snap.campaign_type is not None:
        lines.append(f"Campaign type: {snap.campaign_type}")
    return lines


def _recent_action_lines(
    state: StateDocument, campaign_id: str, platform: str | None
) -> list[str]:
    """The campaign's last few ``action_log`` entries.

    With a known platform an entry recorded for another platform is left
    out; an entry without a platform still matches, as it always has.
    """
    recent = [
        e
        for e in state.action_log
        if e.campaign_id == campaign_id
        and (not platform or not e.platform or e.platform == platform)
    ][-_MAX_ACTION_LOG_ENTRIES:]
    if not recent:
        return []
    lines = ["Recent actions:"]
    for entry in recent:
        summary = entry.summary or ""
        lines.append(f"- {entry.timestamp} {entry.action}: {summary}".rstrip(": "))
    return lines


def _strategy_lines(strategy: list[StrategyEntry]) -> list[str]:
    """Every STRATEGY.md entry as ``- <title>: <content>``."""
    if not strategy:
        return []
    return ["Strategy:", *(f"- {s.title}: {s.content}" for s in strategy)]


__all__ = ["build_query"]
