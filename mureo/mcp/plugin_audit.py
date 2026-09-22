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
  are replaced with ``"***"``; every surviving string value is then run
  through :func:`~mureo.core.scrub.scrub_text`, so a secret pasted into
  an ordinary free-text argument does not survive either (#779); and
  over-long strings are truncated so a plugin cannot bloat the log with
  a payload dump.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ``scrub_text`` is re-exported, not re-implemented: the passes moved down
# to :mod:`mureo.core.scrub` in #758 phase 2 so ``mureo.context.state`` can
# scrub a rationale without importing the MCP layer. It stays importable
# from here — this is where every existing caller looks for it. The
# redundant alias is what marks it an EXPLICIT re-export for strict mypy.
from mureo.core.scrub import scrub_text as scrub_text
from mureo.fsutil import secure_chmod

logger = logging.getLogger(__name__)

_MAX_STR = 512
_TRUNC = "…<truncated>"

#: How much of a string value the scrubber is allowed to look at.
#:
#: Masking runs on the asyncio event loop for EVERY tool call — twice for a
#: plugin call, since ``record_plugin_call`` runs inside ``journal_call`` —
#: and nothing upstream bounds the size of an MCP argument. Scrubbing the
#: whole value made that an unbounded O(n): ~250 ms per megabyte, 12 s for
#: fifty 1 MB arguments, all of it blocking the loop.
#:
#: Nothing is lost by the window: the result is truncated to ``_MAX_STR``
#: anyway, so text past it never reaches the file. The 64 characters of
#: slack are for a credential that STRADDLES the cut — a match has to start
#: before the cut to leave anything behind, and 64 more characters is enough
#: to recognise every shape the scrubber knows (the longest key,
#: ``developer_token`` plus quoting and separator, is ~20; ``Basic `` plus
#: its 16-character minimum base64 value is 22). A value longer than that is
#: still matched, because every pattern's value class is a ``+`` / ``{n,}``
#: that happily matches the part inside the window.
SCRUB_WINDOW = _MAX_STR + 64

#: Argument KEY names whose value is replaced with ``"***"`` unread. Matched
#: as a SUBSTRING, so ``client_secret``, ``app_secret`` and ``appsecret_proof``
#: all land on ``secret`` and no prefix needs listing.
#:
#: ``private[_-]?key``, ``pwd`` and ``signature`` joined for #779. Substring
#: matching hid the gap: ``secret_key`` looked covered by a root list that
#: does not contain ``key``, and it is — via ``secret`` — but
#: ``private_key`` has no such luck, because ``api[_-]?key`` needs the
#: literal ``api``. That is the field name in a Google service-account JSON
#: and its value is a PEM private key, so it was landing in the journal in
#: cleartext. ``pwd`` is not a substring of ``passwd``. The ``[_-]?`` on
#: ``private[_-]?key`` is the #528 rule: ``privateKey`` is how the same
#: field is spelled one surface over.
#:
#: ``sig`` is deliberately NOT a root. A substring match would take
#: ``design``, ``assign`` and ``signal`` with it and collapse three ordinary
#: arguments to ``"***"`` — the whole value, unread. ``signature`` in full
#: costs nothing and catches the field that matters.
_SENSITIVE_KEY = re.compile(
    r"(token|secret|password|passwd|pwd|credential|api[_-]?key"
    r"|private[_-]?key|signature|authorization"
    r"|access[_-]?token|refresh[_-]?token|client[_-]?secret|bearer|cookie)",
    re.IGNORECASE,
)


def _audit_path() -> Path:
    """Resolve the audit file path (monkeypatched in tests)."""
    return Path.home() / ".mureo" / "plugin_audit.jsonl"


def mask_arguments(value: Any, *, _depth: int = 0) -> Any:
    """Recursively mask secrets and truncate over-long strings.

    Public since #758 for the same reason as :func:`scrub_text`: the
    dispatcher journal masks its ``args`` with this exact function, so the
    two trails cannot drift apart on what counts as a secret.

    Three steps, in this order:

    1. KEY masking — a sensitivity-suggesting key yields ``"***"`` and its
       value is never inspected at all.
    2. :func:`scrub_text` over the first :data:`SCRUB_WINDOW` characters of
       every surviving string VALUE (#779). Masking by key name alone let a
       secret pasted into an ordinary free-text argument through verbatim,
       while the same sentence WAS scrubbed on its way into ``STATE.json``
       — two stores, two rules.
    3. Truncation to :data:`_MAX_STR`.

    Scrubbing before truncating is deliberate, and ``Basic <base64>`` is
    the shape that makes it so: its value class is base64 only, so a
    credential cut by the truncation marker is unrecognisable and would be
    written in cleartext. (``api_key=…`` would survive either order — its
    value class matches ``…<truncated>`` too.) The hard cap is unchanged —
    the result is never longer than ``_MAX_STR``.

    The ``code=`` pass is switched OFF here: it is a rule for error prose,
    and in an argument the same shape is an ordinary URL parameter. See
    :func:`~mureo.core.scrub.scrub_text`. Every ``reason`` / ``rationale``
    calls that function directly and keeps the pass.
    """
    if _depth > 4:
        return "<...>"
    if isinstance(value, str):
        scrubbed = scrub_text(value[:SCRUB_WINDOW], mask_code_key_value=False)
        if len(value) <= SCRUB_WINDOW and len(scrubbed) <= _MAX_STR:
            return scrubbed
        return scrubbed[: _MAX_STR - len(_TRUNC)] + _TRUNC  # hard cap == _MAX_STR
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            out[key] = (
                "***"
                if _SENSITIVE_KEY.search(key)
                else mask_arguments(v, _depth=_depth + 1)
            )
        return out
    if isinstance(value, (list, tuple)):
        return [mask_arguments(v, _depth=_depth + 1) for v in list(value)[:50]]
    return value


#: Pre-#758 private spellings. Kept as aliases, not as re-implementations:
#: ``mureo.web.handlers``, ``mureo.amazon_ads.session_auth``,
#: ``mureo.cli.amazon_cmd`` and ``tests/test_mcp_plugin_audit.py`` import
#: them, and a second definition is a second answer to "what is a secret".
_mask = mask_arguments
_scrub = scrub_text


def record_plugin_call(
    *,
    tool: str,
    arguments: dict[str, Any],
    source: str,
    ok: bool,
    error: str | None = None,
    platform_ok: bool | None = None,
) -> None:
    """Append one masked JSON-Lines audit record. Never raises.

    Two independent outcomes, because they genuinely differ (#528):

    - ``ok`` — did the dispatch complete without raising. Unchanged meaning.
    - ``platform_ok`` — did the PLATFORM accept the call. A provider can
      return a refusal as ordinary content (the canonical ``API error:``
      envelope), which does not raise and so leaves ``ok`` True. Recorded as
      ``platform_ok: false`` so this operator-facing trail does not read as a
      success for a call that changed nothing, matching the ``action_log``
      entry that is correctly skipped for it. Written ONLY when a failure is
      known, so an ordinary record keeps its existing shape.
    """
    try:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            # Capped like every other field: no part of a line is unbounded.
            "tool": tool[:_MAX_STR],
            "source": (source or "<unknown>")[:_MAX_STR],
            "ok": ok,
            "args": mask_arguments(arguments if isinstance(arguments, dict) else {}),
        }
        if platform_ok is False:
            rec["platform_ok"] = False
        if error is not None:
            rec["error"] = scrub_text(error)[:_MAX_STR]
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
