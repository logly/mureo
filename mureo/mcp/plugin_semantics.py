"""Phase 2 of #114: derive safety semantics for plugin MCP tools and
promote *mutating* plugin calls into STATE.json's ``action_log``.

A plugin opts into richer treatment purely through **standard MCP**
metadata — no new mureo Protocol surface:

- ``Tool.annotations.readOnlyHint is True`` → the tool is a read; it
  stays in the dedicated plugin audit log only (no STATE.json write).
- Anything else (no annotations, ``readOnlyHint`` absent/false, or
  ``destructiveHint``) is treated as **mutating** (conservative
  default — undeclared ⇒ mutating, matching Phase 1).
- Optional ``Tool.meta["mureo"]``:
    - ``reversal``: a dict recorded verbatim into the action_log
      entry's ``reversible_params`` so ``rollback_plan_get`` can see
      the intent. NOTE: the rollback *planner* only builds an actual
      reversal when ``reversal["operation"]`` is in its built-in
      allow-list — arbitrary plugin operations are recorded for audit
      but not auto-reversible. Honest scope, documented.
    - ``throttle``: ``{"rate": float, "burst": int}`` → a dedicated
      Throttler for that tool; invalid/absent ⇒ shared default.

Mutations are promoted to the action_log **only when a STATE.json
already exists in cwd** — we never litter an arbitrary working
directory with a new STATE.json just because a plugin tool ran. The
plugin audit log (Phase 1) always captures the call regardless.
Promotion is best-effort and never raises (auditing/strategy
visibility must not break the tool call).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.throttle import ThrottleConfig

if TYPE_CHECKING:
    from mcp.types import Tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSemantics:
    """Safety classification derived from a plugin tool's MCP metadata."""

    mutating: bool
    reversal: dict[str, Any] | None = None
    throttle: ThrottleConfig | None = None


def _meta_mureo(tool: Tool) -> dict[str, Any]:
    """Return ``meta["mureo"]`` if present, else ``{}``.

    MCP's ``Tool.meta`` field is aliased ``_meta``; a plugin author who
    builds ``Tool(meta=...)`` (the intuitive spelling) does NOT populate
    the real field — pydantic ``extra="allow"`` stashes it in
    ``__pydantic_extra__`` instead. Accept both so the documented and
    the intuitive spelling behave identically.
    """
    meta = getattr(tool, "meta", None)
    if not isinstance(meta, dict):
        extra = getattr(tool, "__pydantic_extra__", None)
        meta = extra.get("meta") if isinstance(extra, dict) else None
    if isinstance(meta, dict):
        section = meta.get("mureo")
        if isinstance(section, dict):
            return section
    return {}


def derive_semantics(tool: Tool) -> ToolSemantics:
    """Classify one plugin tool from standard MCP annotations + meta."""
    ann = getattr(tool, "annotations", None)
    read_only = bool(getattr(ann, "readOnlyHint", False) is True)
    mutating = not read_only

    section = _meta_mureo(tool)
    reversal = section.get("reversal")
    reversal = reversal if isinstance(reversal, dict) else None

    throttle: ThrottleConfig | None = None
    raw = section.get("throttle")
    if isinstance(raw, dict):
        try:
            throttle = ThrottleConfig(
                rate=float(raw["rate"]),
                burst=int(raw["burst"]),
                hourly_limit=(
                    int(raw["hourly_limit"])
                    if raw.get("hourly_limit") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            throttle = None  # malformed hint → fall back to shared default

    return ToolSemantics(mutating=mutating, reversal=reversal, throttle=throttle)


def record_mutation_action_log(
    *, tool: str, source: str, reversal: dict[str, Any] | None
) -> None:
    """Append a plugin mutation to STATE.json's action_log. Never raises.

    No-op (jsonl audit still has it) when there is no STATE.json in cwd.
    Called only after a *successful* call; a failed mutation did not
    change platform state, so it is intentionally NOT promoted here —
    failed attempts live in the Phase 1 jsonl audit only (by design).
    """
    try:
        state_path = Path.cwd() / "STATE.json"
        if not state_path.is_file():
            return
        from mureo.context.models import ActionLogEntry
        from mureo.context.state import append_action_log

        entry = ActionLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            action=tool,
            platform=f"plugin:{source or 'unknown'}",
            summary=f"plugin tool {tool} (mutating)",
            command=tool,
            reversible_params=reversal,
        )
        append_action_log(state_path, entry)
    except Exception:  # noqa: BLE001 — must never break the tool call
        logger.warning(
            "plugin action_log promotion failed for tool %r", tool, exc_info=True
        )
