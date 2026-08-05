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
# Secret-shaped *values* that can appear in a free-text error string
# (``error`` is not key/value-masked like ``args``). Covers HTTP bearer
# headers and Amazon LwA access/refresh tokens (Atza|… / Atzr|…). The
# Amazon bridge is the first credentialed plugin path, so this is
# defense-in-depth for every plugin's recorded exception text.
#
# Every alternative stops at whitespace OR a quote. ``Bearer\s+\S+`` used to
# run past the closing quote of a JSON string and swallow the rest of the
# document, leaving structurally broken text for whoever reads the record.
# A bearer token cannot contain a quote, so stopping there cannot leak.
_SECRET_VALUE = re.compile(
    r"(Bearer\s+[^\s'\"]+|Atza\|[^\s'\"]+|Atzr\|[^\s'\"]+)",
    re.IGNORECASE,
)

# Second shape: ``key=value`` / ``key: value`` credential leaks. An HTTP
# client that echoes the form body it POSTed spills the client secret in
# plain text, which the token-prefix patterns above do not match (an LwA
# client secret has no distinguishing prefix). The KEY and separator are
# kept so the diagnostic still reads "client_secret=***" rather than
# losing the context of what failed.
#
# The value stops at the first separator that cannot be part of a token
# (whitespace, quote, comma, ``&``, or a closing bracket), so only the
# credential — not the rest of the sentence — is redacted.
# The optional quotes around the separator catch the dict/JSON rendering
# an exception's ``repr`` produces (``{'client_secret': 'shh'}``) as well
# as the bare form-encoded one.
#
# EVERY key word separator is optional (``[_-]?``), so ``client_secret``,
# ``client-secret`` and ``clientSecret`` are all masked. Three of the five
# alternatives once required a literal underscore, which meant the camelCase
# spelling leaked in cleartext (#528) — and camelCase is not exotic here:
# Amazon's own surface is camelCase throughout (``advertiserAccountId``,
# ``adProductFilter``, ``authorizationCode``), and this scrubber's whole job
# is redacting error bodies from surfaces like it. Matches ``_SENSITIVE_KEY``
# above, which was already spelled this way.
_SECRET_KEY_VALUE = re.compile(
    r"((?:client[_-]?secret|refresh[_-]?token|access[_-]?token"
    r"|api[_-]?key|password)"
    r"['\"]?\s*[:=]\s*['\"]?)[^\s,;&'\"}\])]+",
    re.IGNORECASE,
)

# ``code`` on its own is far too common in ordinary error prose ("status
# code = 400", "error code: 17"), so it gets a deliberately narrow rule.
# Only two shapes count:
#   - ``code=…`` with NO space before the ``=`` (the query-string /
#     form-body shape an authorization code actually leaks in), and
#   - the QUOTED dict-key shape ``'code': '…'`` that an exception repr
#     produces.
# Bare ``code: 12345678`` prose is deliberately NOT matched. The value
# must also be at least _MIN_CODE_VALUE_LEN token characters — Amazon's
# authorization codes are long alphanumerics; status codes and errnos
# are not.
#
# The key may END in ``code`` rather than BE it (``authorizationCode``,
# ``authCode``, ``oauth_code``): the same credential lands in whatever field
# name a platform picked, and the original word-boundary lookbehind let those
# through in full (#528). Dropping the lookbehind is all that takes — the
# pattern simply matches the ``code`` at the END of the key and leaves the
# prefix untouched, so ``authorizationCode": "…"`` becomes
# ``authorizationCode": "***"``. Broadening the KEY is the safe direction: the
# length rule still keeps ``status_code=400`` and friends readable, and
# over-masking costs legibility while under-masking costs a credential.
#
# Deliberately NOT written as a ``[\w-]*code`` prefix: that form backtracks
# quadratically on a long non-matching string (a 2 MB error body hung the
# test suite), and this scrubber runs on attacker-influenceable text.
#
# Not covered, deliberately: a bare NUMERIC code is never masked (an LwA
# authorization code is a long alphanumeric string, never an integer), so the
# asymmetry with string codes is a legibility quirk, not a leak.
_MIN_CODE_VALUE_LEN = 8
_CODE_KEY_VALUE = re.compile(
    r"((?:code=['\"]?|code['\"]\s*:\s*['\"]))[^\s,;&'\"}\])]{"
    + str(_MIN_CODE_VALUE_LEN)
    + r",}",
    re.IGNORECASE,
)


def _scrub(text: str) -> str:
    """Redact secret-shaped substrings from a free-text error string.

    Three passes, all value-only: token prefixes (``Bearer …``,
    ``Atza|…``, ``Atzr|…``), ``key=value`` credential pairs, and the
    narrowly-anchored ``code=<authorization code>``. Everything else —
    HTTP status, exception type, the failing operation — survives, so a
    scrubbed message is still a usable diagnostic.
    """
    scrubbed = _SECRET_VALUE.sub("***", text)
    scrubbed = _SECRET_KEY_VALUE.sub(r"\1***", scrubbed)
    return _CODE_KEY_VALUE.sub(r"\1***", scrubbed)


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
            "tool": tool,
            "source": source or "<unknown>",
            "ok": ok,
            "args": _mask(arguments if isinstance(arguments, dict) else {}),
        }
        if platform_ok is False:
            rec["platform_ok"] = False
        if error is not None:
            rec["error"] = _scrub(error)[:_MAX_STR]
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
