"""Load delivery-collapse thresholds from the operator's STRATEGY.md.

Kept out of :mod:`mureo.analysis.delivery_collapse` so that module stays
pure (no filesystem, no runtime context). Every caller that runs the
detector for a real account — the built-in analytics adapters and the
``analysis_delivery_collapse_*`` MCP tools — resolves thresholds through
here, so a ``## Guardrails`` edit changes detection everywhere at once
instead of on one surface.

Fail-open: an unreadable or unparseable STRATEGY.md yields the built-in
defaults. A guardrail file the operator broke must not silently disable
outage detection.
"""

from __future__ import annotations

import logging
from pathlib import Path

from mureo.analysis.delivery_collapse import (
    CollapseThresholds,
    collapse_thresholds_from_strategy_text,
)

logger = logging.getLogger(__name__)

#: ``thresholds_source`` values reported alongside the thresholds.
SOURCE_DEFAULTS = "defaults"
SOURCE_GUARDRAILS = "strategy_guardrails"


def resolve_strategy_path() -> Path:
    """Best-effort STRATEGY.md path for the active workspace.

    Mirrors :func:`mureo.policy.strategy_gate._resolve_strategy_path` so
    the guardrails the gate enforces and the guardrails the detector
    reads always come from the same file.
    """
    try:
        from mureo.core.runtime_context import get_runtime_context

        store = get_runtime_context().state_store
        strategy_path = getattr(store, "strategy_path", None)
        if strategy_path is not None:
            return Path(strategy_path)
        workspace = getattr(store, "workspace", None)
        if workspace is not None:
            return Path(workspace) / "STRATEGY.md"
    except Exception:  # noqa: BLE001 — resolution must never break detection
        logger.debug("delivery-collapse: STRATEGY.md path unresolved", exc_info=True)
    return Path.cwd() / "STRATEGY.md"


def load_collapse_thresholds() -> tuple[CollapseThresholds, str]:
    """Return ``(thresholds, source)`` for the active workspace."""
    path = resolve_strategy_path()
    try:
        if not path.exists():
            return CollapseThresholds(), SOURCE_DEFAULTS
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.debug("delivery-collapse: STRATEGY.md unreadable", exc_info=True)
        return CollapseThresholds(), SOURCE_DEFAULTS
    try:
        thresholds = collapse_thresholds_from_strategy_text(text)
    except Exception:  # noqa: BLE001 — a broken file must not mute detection
        logger.debug("delivery-collapse: STRATEGY.md unparseable", exc_info=True)
        return CollapseThresholds(), SOURCE_DEFAULTS
    if thresholds == CollapseThresholds():
        return thresholds, SOURCE_DEFAULTS
    return thresholds, SOURCE_GUARDRAILS


__all__ = [
    "SOURCE_DEFAULTS",
    "SOURCE_GUARDRAILS",
    "load_collapse_thresholds",
    "resolve_strategy_path",
]
