"""MCP handler for ``analysis_anomalies_check``.

Thin composition layer over the pure ``detect_anomalies`` +
``baseline_from_history`` functions in ``mureo.analysis.anomaly_detector``.
The handler:

1. Sandboxes ``state_file`` against the active workspace (the
   ``StateStore.workspace`` exposed by the resolved
   :class:`mureo.core.runtime_context.RuntimeContext`, defaulting to
   CWD): path traversal, absolute paths outside it, and symlinks
   that resolve outside are all refused so a prompt-injected agent
   cannot point the tool at an attacker-crafted STATE.json.
2. Builds a ``CampaignMetrics`` from the ``current`` argument.
3. Builds a median-based baseline from ``STATE.json``'s ``action_log``
   when available.
4. Returns anomalies as JSON with severity-ordered entries.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.analysis.anomaly_detector import (
    Anomaly,
    CampaignMetrics,
    baseline_from_history,
    detect_anomalies,
)
from mureo.context.errors import ContextFileError
from mureo.context.state import read_state_file
from mureo.mcp._helpers import _json_result, _opt, _require

if TYPE_CHECKING:
    from mcp.types import TextContent


logger = logging.getLogger(__name__)


def _resolve_state_file(arguments: dict[str, Any]) -> Path:
    """Sandbox ``state_file`` against the active workspace.

    The active workspace is
    ``getattr(get_runtime_context().state_store, "workspace", Path.cwd())``
    — CWD in the default file-backed configuration, or whatever
    filesystem-backed :class:`StateStore` an alternate backend
    registers via the ``mureo.runtime_context_factory`` entry-point
    group.

    A prompt-injected agent cannot point the tool at an attacker-crafted
    STATE.json elsewhere on disk. Rejects (a) paths that resolve outside
    the workspace, (b) symlinks whose target escapes the workspace,
    even when the link itself sits inside it. The symlink refusal is
    stricter than the rollback / mureo_context handlers because the
    analysis surface returns derived metrics that could leak file
    contents an attacker swaps in mid-call.
    """
    from mureo.core.runtime_context import get_runtime_context

    store = get_runtime_context().state_store
    workspace = getattr(store, "workspace", Path.cwd()).resolve()
    raw = arguments.get("state_file")
    if not raw:
        attr = getattr(store, "state_path", None)
        if attr is not None:
            # Backend-owned path: trusted output of an installed
            # ``StateStore``; the entry-point factory is host code,
            # not an untrusted MCP caller, so the symlink and
            # workspace-boundary checks below do not apply.
            return Path(attr).resolve()
        return workspace / "STATE.json"
    candidate = Path(raw)
    # strict=False so the file not yet existing is allowed (callers handle
    # missing-file with .exists()), but symlinks are still followed.
    target = (workspace / candidate) if not candidate.is_absolute() else candidate
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"state_file must resolve inside the active workspace "
            f"({workspace}); got {resolved}."
        ) from exc
    # Refuse symlinks even when both the link and its target live under
    # the workspace: a symlink is agent-writable and would let a future
    # STATE.json swap redirect the handler without changing the
    # argument it was called with.
    if target.is_symlink() or any(
        p.is_symlink()
        for p in target.parents
        if workspace in p.parents or p == workspace
    ):
        raise ValueError(f"state_file must not traverse a symlink; got {target}.")
    return resolved


def _coerce_float(value: Any, field: str) -> float:
    """Accept numerics (int/float) or numeric strings. Reject the rest.

    Keeps the handler robust against JSON clients that send ``"5000"``
    instead of ``5000``, without silently accepting garbage like ``"N/A"``.
    """
    if isinstance(value, bool):
        raise ValueError(f"'{field}' must be numeric, got bool")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"'{field}' must be numeric, got {value!r}") from exc
    raise ValueError(f"'{field}' must be numeric, got {type(value).__name__}")


def _coerce_int(value: Any, field: str) -> int:
    return int(_coerce_float(value, field))


def _build_current_metrics(current: dict[str, Any]) -> CampaignMetrics:
    """Validate the ``current`` payload and construct CampaignMetrics."""
    if not isinstance(current, dict):
        raise ValueError("'current' must be an object")
    campaign_id = current.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ValueError("Required parameter current.campaign_id is not specified")
    cost = _coerce_float(current.get("cost", 0), "current.cost")
    impressions = _coerce_int(current.get("impressions", 0), "current.impressions")
    clicks = _coerce_int(current.get("clicks", 0), "current.clicks")
    conversions = _coerce_float(current.get("conversions", 0), "current.conversions")
    cpa_raw = current.get("cpa")
    ctr_raw = current.get("ctr")
    cpa = _coerce_float(cpa_raw, "current.cpa") if cpa_raw is not None else None
    ctr = _coerce_float(ctr_raw, "current.ctr") if ctr_raw is not None else None
    return CampaignMetrics(
        campaign_id=campaign_id,
        cost=cost,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        cpa=cpa,
        ctr=ctr,
    )


def _anomaly_to_dict(anomaly: Anomaly) -> dict[str, Any]:
    data = dataclasses.asdict(anomaly)
    data["severity"] = anomaly.severity.value  # enum → plain string
    return data


def _baseline_to_dict(baseline: CampaignMetrics | None) -> dict[str, Any] | None:
    if baseline is None:
        return None
    return {
        "cost": baseline.cost,
        "impressions": baseline.impressions,
        "clicks": baseline.clicks,
        "conversions": baseline.conversions,
        "cpa": baseline.cpa,
        "ctr": baseline.ctr,
    }


async def handle_anomalies_check(arguments: dict[str, Any]) -> list[TextContent]:
    """Compose baseline-from-history + detect-anomalies behind one MCP call."""
    try:
        state_file = _resolve_state_file(arguments)
    except ValueError as exc:
        return _json_result({"error": str(exc), "anomalies": []})

    current_raw = _require(arguments, "current")
    current = _build_current_metrics(current_raw)

    had_prior_spend = bool(_opt(arguments, "had_prior_spend", True))
    min_entries = int(_opt(arguments, "min_baseline_entries", 7))
    if min_entries < 1:
        raise ValueError("min_baseline_entries must be >= 1")

    baseline: CampaignMetrics | None = None
    baseline_warning: str | None = None
    if state_file.exists():
        try:
            doc = read_state_file(state_file)
            baseline = baseline_from_history(
                current.campaign_id,
                doc.action_log,
                min_entries=min_entries,
            )
        except ContextFileError as exc:
            # Continue with zero-spend detection — a broken history shouldn't
            # silence a live outage — but surface a warning so the agent can
            # flag the unreliable baseline to the operator. %r on the path
            # fragment avoids log-injection via attacker-controlled filenames.
            logger.warning("Ignoring malformed STATE.json: %r", exc)
            baseline_warning = (
                f"Baseline unavailable: STATE.json could not be parsed "
                f"({type(exc).__name__})."
            )

    anomalies = detect_anomalies(current, baseline, had_prior_spend=had_prior_spend)

    response: dict[str, Any] = {
        "campaign_id": current.campaign_id,
        "baseline": _baseline_to_dict(baseline),
        "anomalies": [_anomaly_to_dict(a) for a in anomalies],
    }
    if baseline_warning is not None:
        response["baseline_warning"] = baseline_warning
    return _json_result(response)


__all__ = ["handle_anomalies_check"]
