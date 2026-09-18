"""Append-only journal of every MCP tool call (#758, phase 1).

One line of JSON per call that enters
:func:`mureo.mcp.server.handle_call_tool` — every family (built-in and
plugin) and every outcome (``ok``, a platform error envelope, an
exception, a policy denial, an exclusion-preflight refusal, invalid
arguments). Nothing is sampled and nothing is filtered: "what did this
agent actually try" is the question the journal exists to answer, and a
trail that only records what succeeded cannot answer it.

Three trails, three jobs — this one is the complete record:

- **journal** (here) — every call, every outcome, arguments masked.
- **``action_log``** in STATE.json — the curated summary: mutations that
  carry strategy semantics (observation window, reversal plan, batch
  membership). Deliberately much smaller than the journal.
- **``plugin_audit.jsonl``** (:mod:`mureo.mcp.plugin_audit`) — the
  pre-#758 plugin trail, untouched for compatibility.

Contract, matching :func:`mureo.mcp.plugin_audit.record_plugin_call`:
**best-effort, never raises**. Any I/O or serialization failure is
swallowed and logged at WARNING, so a journal problem can never break or
mask a tool call. The file is created ``0600`` from the first write.
Masking is not re-implemented here — ``args`` go through
:func:`mureo.mcp.plugin_audit.mask_arguments` and ``reason`` through
:func:`mureo.mcp.plugin_audit.scrub_text` — so the journal cannot redact
less than the audit log does. The RESULT body is never stored, only the
outcome and a capped reason string.

Where the file lives
--------------------

A workspace's record must travel with the workspace: an operator who
copies, archives or reviews a workspace directory expects STATE.json,
STRATEGY.md and the journal of what was done there to be one unit. So
when the resolved :class:`~mureo.core.state_store.StateStore` is the
filesystem one AND its directory actually looks like a workspace (it
holds a ``STATE.json`` or a ``STRATEGY.md``), the journal is written
beside them.

A directory with neither marker is **not** a workspace — it is whatever
directory the MCP host happened to start the server in — and dropping a
``JOURNAL.jsonl`` there would litter arbitrary directories with files the
operator never asked for. Those calls fall back to
``~/.mureo/journal.jsonl``, the home directory ``plugin_audit`` already
uses, where they are still kept and still readable with ``mureo journal``.

Opt-out: ``MUREO_DISABLE_JOURNAL=1`` (the exact string ``"1"``, matching
every other ``MUREO_DISABLE_*`` gate in mureo) writes nothing at all.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mureo

# Re-exported below: the process identity moved to ``mureo.core.actor`` in
# #758 phase 2 so ``mureo.context.state`` can stamp it onto an ``action_log``
# entry without importing ``mureo.mcp``. Kept importable from here — this is
# where every existing caller looks for it.
from mureo.core.actor import client_info, session_id, set_client_info
from mureo.fsutil import secure_chmod
from mureo.mcp.plugin_audit import mask_arguments, scrub_text

logger = logging.getLogger(__name__)

#: Schema version of one record. Bumped only for a breaking change, so a
#: reader can tell one shape from another without guessing.
RECORD_VERSION = 1

#: Exact-string opt-out, mirroring ``mureo.mcp.server._is_disabled`` and
#: ``mureo.core.strategy_reminder._OPT_OUT_ENV_VAR``. Any other value
#: ("0", "", "true") leaves the journal enabled.
OPT_OUT_ENV_VAR = "MUREO_DISABLE_JOURNAL"

#: Filename inside a workspace directory, and inside ``~/.mureo``.
JOURNAL_FILENAME = "JOURNAL.jsonl"
HOME_JOURNAL_FILENAME = "journal.jsonl"

#: A directory holding either of these IS a workspace; see the module
#: docstring for why a directory holding neither is not.
WORKSPACE_MARKERS = ("STATE.json", "STRATEGY.md")

#: Hard cap on ``reason`` and ``rationale``: the audit log's budget — a
#: diagnostic, not a dump. A LINE-LENGTH cap, so over-long text is
#: truncated rather than refused; losing the record would be worse than
#: losing its tail. Not to be confused with
#: :data:`mureo.core.actor.ACTION_REASON_MAX_CHARS`, which is a write rule
#: on a value the CALLER supplies and refuses an over-long one outright.
MAX_REASON_CHARS = 512


def _state_path() -> Path | None:
    """The filesystem STATE.json this process is bound to, or ``None``.

    ``None`` for an alternate :class:`~mureo.core.state_store.StateStore`
    backend (it has no ``state_path``, and therefore no directory a journal
    could belong to) and for a runtime context that cannot be resolved at
    all — a misconfigured factory must not cost the record, it only costs
    the workspace location.
    """
    try:
        from mureo.core.runtime_context import get_runtime_context

        path = getattr(get_runtime_context().state_store, "state_path", None)
    except Exception:  # noqa: BLE001 — path resolution is best-effort
        logger.debug("journal: runtime context unavailable", exc_info=True)
        return None
    return path if isinstance(path, Path) else None


def journal_path() -> Path:
    """Resolve the journal file path (monkeypatched in tests).

    Beside ``STATE.json`` / ``STRATEGY.md`` when the bound directory is a
    real workspace, otherwise ``~/.mureo/journal.jsonl``. See the module
    docstring for the reasoning.
    """
    state_path = _state_path()
    if state_path is not None:
        workspace = state_path.parent
        if any((workspace / marker).exists() for marker in WORKSPACE_MARKERS):
            return workspace / JOURNAL_FILENAME
    return Path.home() / ".mureo" / HOME_JOURNAL_FILENAME


def _stat_signature(path: Path) -> tuple[str, int, int] | None:
    """Identity of ``path``'s current contents, or ``None`` if unstattable.

    Path, modification time and size together: every writer of STATE.json
    goes through an atomic replace, so a changed batch always changes the
    mtime, and the size is a second, free discriminator.
    """
    try:
        info = path.stat()
    except OSError:
        return None
    return (str(path), info.st_mtime_ns, info.st_size)


#: Single-entry memo for :func:`_open_batch_id`: the STATE.json signature
#: the answer was computed from, and the answer. One entry is enough — a
#: server process is bound to one workspace.
_batch_cache: tuple[tuple[str, int, int], str | None] | None = None


def _open_batch_id() -> str | None:
    """The id of the workspace's open batch, or ``None``.

    A plain read, so no lock is taken: the journal describes the call that
    just happened and a batch that opens or closes concurrently belongs to
    the next record, not this one. ``None`` on any failure — an unreadable
    STATE.json must not cost the record.

    Memoised on the file's ``stat`` signature, because this runs on the hot
    path of EVERY tool call and STATE.json changes far less often than a
    tool is called. A stat is cheap; a full parse per dispatch is not.
    """
    global _batch_cache
    state_path = _state_path()
    if state_path is None:
        return None
    signature = _stat_signature(state_path)
    if signature is None:  # no STATE.json (yet), or unreadable — never cached
        return None
    if _batch_cache is not None and _batch_cache[0] == signature:
        return _batch_cache[1]
    try:
        from mureo.context.batch import active_batch
        from mureo.context.state import read_state_file

        record = active_batch(read_state_file(state_path))
    except Exception:  # noqa: BLE001 — a broken STATE.json is not our problem
        logger.debug("journal: could not read the open batch", exc_info=True)
        return None
    batch_id = None if record is None else record.batch_id
    _batch_cache = (signature, batch_id)
    return batch_id


def _workspace_id() -> str:
    """The bound workspace identifier, or the default when unresolvable."""
    try:
        from mureo.core.runtime_context import get_runtime_context

        return get_runtime_context().workspace_id
    except Exception:  # noqa: BLE001
        from mureo.core.runtime_context import DEFAULT_WORKSPACE_ID

        logger.debug("journal: workspace_id unavailable", exc_info=True)
        return DEFAULT_WORKSPACE_ID


def build_record(
    *,
    tool: str,
    family: str,
    mutating: bool,
    arguments: dict[str, Any],
    outcome: str,
    duration_ms: int,
    reason: str | None = None,
    rationale: str | None = None,
    source: str | None = None,
    rollback: bool = False,
) -> dict[str, Any]:
    """Assemble one journal record. Key order is part of the format."""
    record: dict[str, Any] = {
        "v": RECORD_VERSION,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": session_id(),
        "client": client_info(),
        "mureo": mureo.__version__,
        "workspace_id": _workspace_id(),
        "tool": tool,
        "family": family,
    }
    if source is not None:
        record["source"] = source or "<unknown>"
    record["mutating"] = bool(mutating)
    record["args"] = mask_arguments(arguments if isinstance(arguments, dict) else {})
    # Beside ``args``, never inside it: ``args`` is what the agent asked the
    # TOOL to do, and an operator filtering on arguments must not find a
    # sentence sitting where a parameter belongs. Emitted only when given, so
    # a record without a rationale keeps the phase-1 shape and RECORD_VERSION
    # stays 1.
    if rationale is not None:
        record["rationale"] = scrub_text(str(rationale))[:MAX_REASON_CHARS]
    record["outcome"] = outcome
    if outcome != "ok" and reason is not None:
        record["reason"] = scrub_text(str(reason))[:MAX_REASON_CHARS]
    record["duration_ms"] = int(duration_ms)
    record["batch_id"] = _open_batch_id()
    if rollback:
        record["rollback"] = True
    return record


def _append_line(path: Path, line: str) -> None:
    """Append ``line`` to ``path``, creating it owner-only."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create the file 0600 from the start (no world-readable window between
    # create and a later chmod); chmod stays as belt-and-braces for a
    # pre-existing file with looser perms. Same trick as ``plugin_audit``.
    def _opener(target: str, flags: int) -> int:
        return os.open(target, flags | os.O_APPEND | os.O_CREAT, 0o600)

    with open(path, "a", encoding="utf-8", opener=_opener) as handle:
        handle.write(line)
    secure_chmod(path)


def record_call(
    *,
    tool: str,
    family: str,
    mutating: bool,
    arguments: dict[str, Any],
    outcome: str,
    duration_ms: int,
    reason: str | None = None,
    rationale: str | None = None,
    source: str | None = None,
    rollback: bool = False,
) -> None:
    """Append one journal line for a completed tool call. Never raises.

    ``outcome`` is one of ``ok`` / ``platform_error`` / ``exception`` /
    ``denied`` / ``refused`` / ``invalid_args``, and ``reason`` explains
    it (scrubbed, capped, and ignored for ``ok`` — a success has nothing
    to explain). ``rationale`` is the opposite half: WHY the agent made
    the call, supplied by the agent itself on a mutating tool's ``reason``
    parameter (#758 phase 2), recorded whatever the outcome was.
    ``source`` is the plugin distribution and is passed only
    for plugin tools; ``rollback`` marks a rollback's reversal leg. The
    classification of ``family`` and ``mutating`` belongs to the
    dispatcher — see :mod:`mureo.mcp._journal_hook`.
    """
    if os.environ.get(OPT_OUT_ENV_VAR) == "1":
        return
    try:
        record = build_record(
            tool=tool,
            family=family,
            mutating=mutating,
            arguments=arguments,
            outcome=outcome,
            duration_ms=duration_ms,
            reason=reason,
            rationale=rationale,
            source=source,
            rollback=rollback,
        )
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        _append_line(journal_path(), line)
    except Exception:  # noqa: BLE001 — the journal must never break a call
        logger.warning("journal write failed for tool %r", tool, exc_info=True)


__all__ = [
    "JOURNAL_FILENAME",
    "MAX_REASON_CHARS",
    "OPT_OUT_ENV_VAR",
    "RECORD_VERSION",
    "build_record",
    "client_info",
    "journal_path",
    "record_call",
    "session_id",
    "set_client_info",
]
