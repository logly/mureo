"""Build a context-rich query string for advisor consultation.

Reads the local ``StateStore`` for the requested campaign's metrics
+ recent action log, plus the workspace's ``STRATEGY.md`` entries,
and folds them into the operator's natural-language question. The
advisor server's vector search has more to match against than just
"why is CPA up?" — it sees the campaign name / status / recent
mutations / business goal too.

The builder is intentionally tolerant: any failure reading state
collapses to "just the question" so a corrupted ``STATE.json`` never
breaks the diagnostic flow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.core.state_store import StateStore

logger = logging.getLogger(__name__)

_MAX_ACTION_LOG_ENTRIES = 5


def build_query(
    *,
    state_store: StateStore,
    question: str,
    campaign_id: str | None = None,
) -> str:
    """Compose the query string sent to advisor vector-search tools.

    Layout::

        Question: <question>
        Campaign: <name> [<status>] (budget <n>)
        Recent actions:
        - <ts> <action>: <summary>
        Strategy:
        - <title>: <content>

    Missing pieces are silently dropped. The question is always
    included even on full state-read failure so the advisor still has
    something to match against.
    """
    parts: list[str] = [f"Question: {question}"]

    try:
        state = state_store.read_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug("context_builder: state read failed (%s)", exc)
        state = None

    if state is not None and campaign_id:
        snap = next(
            (c for c in state.campaigns if c.campaign_id == campaign_id),
            None,
        )
        if snap is not None:
            line = f"Campaign: {snap.campaign_name} [{snap.status}]"
            if snap.daily_budget is not None:
                line += f" (daily_budget={snap.daily_budget})"
            parts.append(line)

        recent = [e for e in state.action_log if e.campaign_id == campaign_id][
            -_MAX_ACTION_LOG_ENTRIES:
        ]
        if recent:
            parts.append("Recent actions:")
            for entry in recent:
                summary = entry.summary or ""
                parts.append(
                    f"- {entry.timestamp} {entry.action}: {summary}".rstrip(": ")
                )

    try:
        strategy = state_store.read_strategy()
    except Exception as exc:  # noqa: BLE001
        logger.debug("context_builder: strategy read failed (%s)", exc)
        strategy = []

    if strategy:
        parts.append("Strategy:")
        for s_entry in strategy:
            parts.append(f"- {s_entry.title}: {s_entry.content}")

    return "\n".join(parts)


__all__ = ["build_query"]
