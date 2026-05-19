"""Append-only audit trail for third-party plugin MCP tool calls.

Plugin tools (entry-point providers implementing ``MCPToolProvider``)
dispatch straight to the plugin and bypass the per-handler audit that
built-in platforms perform. This module records every plugin tool
invocation to a dedicated JSON-Lines log under ``~/.mureo/`` so
operators have a trail even though the plugin opted into nothing.

Design:

- **Dedicated channel.** We do NOT write into ``STATE.json``'s
  ``action_log`` (that is reserved for meaningful, selectively-recorded
  mutations/observations with strategy semantics). A future phase may
  *promote* declared mutations into ``action_log``; until then plugin
  calls live here so they cannot bloat or muddle STATE semantics.
- **Best-effort, never raises.** Auditing must never break or mask a
  tool call: any I/O / serialization failure is swallowed (logged at
  WARNING) so the plugin result still flows.
- **Secret-masked.** Argument values under sensitivity-suggesting keys
  are replaced with ``"***"``; over-long strings are truncated so a
  plugin cannot bloat the log with a payload dump.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mureo.fsutil import secure_chmod

logger = logging.getLogger(__name__)

_MAX_STR = 512
_TRUNC = "…<truncated>"
_SENSITIVE_KEY = re.compile(
    r"(token|secret|password|passwd|credential|api[_-]?key|authorization"
    r"|access[_-]?token|refresh[_-]?token|client[_-]?secret|bearer|cookie)",
    re.IGNORECASE,
)


def _audit_path() -> Path:
    """Resolve the audit file path (monkeypatched in tests)."""
    return Path.home() / ".mureo" / "plugin_audit.jsonl"


def _mask(value: Any, *, _depth: int = 0) -> Any:
    """Recursively mask secrets and truncate over-long strings."""
    if _depth > 4:
        return "<...>"
    if isinstance(value, str):
        if len(value) <= _MAX_STR:
            return value
        return value[: _MAX_STR - len(_TRUNC)] + _TRUNC  # hard cap == _MAX_STR
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            out[key] = (
                "***" if _SENSITIVE_KEY.search(key) else _mask(v, _depth=_depth + 1)
            )
        return out
    if isinstance(value, (list, tuple)):
        return [_mask(v, _depth=_depth + 1) for v in list(value)[:50]]
    return value


def record_plugin_call(
    *,
    tool: str,
    arguments: dict[str, Any],
    source: str,
    ok: bool,
    error: str | None = None,
) -> None:
    """Append one masked JSON-Lines audit record. Never raises."""
    try:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "source": source or "<unknown>",
            "ok": ok,
            "args": _mask(arguments if isinstance(arguments, dict) else {}),
        }
        if error is not None:
            rec["error"] = error[:_MAX_STR]
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"

        # Create the file 0600 from the start (no world-readable window
        # between create and a later chmod); keep chmod as belt-and-
        # braces for a pre-existing file with looser perms.
        def _opener(p: str, flags: int) -> int:
            return os.open(p, flags | os.O_APPEND | os.O_CREAT, 0o600)

        with open(path, "a", encoding="utf-8", opener=_opener) as fh:
            fh.write(line)
        secure_chmod(path)
    except Exception:  # noqa: BLE001 — audit must never break the tool call
        logger.warning("plugin audit write failed for tool %r", tool, exc_info=True)
