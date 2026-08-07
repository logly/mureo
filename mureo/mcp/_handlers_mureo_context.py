"""MCP handlers for mureo's STRATEGY.md / STATE.json surface.

These handlers expose the context layer as MCP tools so that hosts
without direct filesystem access (Claude Desktop chat, claude.ai web,
remote MCP connectors) can read and update mureo's strategic context.

All file paths are resolved against the **active workspace** —
``getattr(get_runtime_context().state_store, "workspace", Path.cwd())``
— and refused if they escape it. The active workspace is CWD by
default (preserving today's single-workspace behaviour), or whatever
filesystem-backed :class:`mureo.core.state_store.StateStore` an
alternate backend registers via the ``mureo.runtime_context_factory``
entry-point group.

The security guard is symmetric with the rollback surface's
``_resolve_state_file`` guard: a prompt-injected agent must not be
able to point mureo at an attacker-crafted file elsewhere on the
filesystem. ``Path.resolve()`` follows symlinks, so a STRATEGY.md
inside the workspace that symlinks to /etc/passwd resolves to the
target and is correctly refused.

Atomic write semantics come from ``mureo.context.state._atomic_write``
and the equivalent path in ``context.strategy``: write to a temp file
in the same directory, then ``os.replace`` over the target. A failure
mid-flight leaves the original intact.

Server clock (#460)
-------------------
The two read entry points (``mureo_strategy_get`` / ``mureo_state_get``)
carry a ``server_now`` field — the host's clock as ISO 8601 with a UTC
offset. Skills use it as their only source of "today"; a Bash-less
headless host cannot shell out to ``date``, and the dates *inside*
STATE.json are history, not now. ``server_now`` lives on the RESPONSE
envelope only: ``parse_state`` ignores unknown top-level keys and
``render_state`` emits only the known ones, so a stray ``server_now``
echoed back into STATE.json is dropped by the next mureo write rather
than becoming a fossilised "today". Symmetrically,
``mureo_state_action_log_append`` stamps the entry ``timestamp``
server-side: a model-supplied value is ignored, so a drifted date can no
longer be persisted and read back later as fact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.analysis.report_flags import normalize_flags
from mureo.context.batch import BatchError
from mureo.context.errors import ContextFileError
from mureo.context.models import (
    ActionLogEntry,
    AdState,
    CampaignSnapshot,
    StateDocument,
)
from mureo.context.state import (
    append_action_log,
    read_state_file,
    render_state,
    set_conversion_action_types,
    set_platform_metrics,
    set_report,
    upsert_campaign,
)
from mureo.context.strategy import RAW_HEADING_TYPE, parse_strategy, write_strategy_file
from mureo.core.clock import server_now_iso
from mureo.fsutil import backup_file
from mureo.mcp._helpers import _json_result, _require, resolve_workspace_path

if TYPE_CHECKING:
    from mcp.types import TextContent


# ---------------------------------------------------------------------------
# STRATEGY.md
# ---------------------------------------------------------------------------


async def handle_strategy_get(arguments: dict[str, Any]) -> list[TextContent]:
    path = resolve_workspace_path(arguments, "STRATEGY.md", store_attr="strategy_path")
    # ``server_now`` on both branches: a skill that starts from STRATEGY.md
    # (or runs before onboarding, when neither file exists) must still be
    # able to establish the current date without a second call.
    if not path.exists():
        return _json_result(
            {
                "markdown": "",
                "exists": False,
                "path": str(path),
                "server_now": server_now_iso(),
            }
        )
    text = path.read_text(encoding="utf-8")
    return _json_result(
        {
            "markdown": text,
            "exists": True,
            "path": str(path),
            "server_now": server_now_iso(),
        }
    )


async def handle_strategy_set(arguments: dict[str, Any]) -> list[TextContent]:
    markdown = _require(arguments, "markdown")
    # Refuse empty / whitespace-only content: a full-replacement write of it
    # would reduce STRATEGY.md to a bare "# Strategy", which a prompt-injected
    # agent could use to wipe the strategy (issue #276). ``_require`` already
    # rejects "" / None; this also catches whitespace-only payloads.
    if not markdown.strip():
        raise ValueError("markdown must not be empty or whitespace-only")
    path = resolve_workspace_path(arguments, "STRATEGY.md", store_attr="strategy_path")
    # Round-trip through parse so callers can't write a STRATEGY.md
    # whose subsequent parse_strategy() call breaks downstream skills.
    # Unrecognized headings are preserved (raw passthrough), not dropped.
    entries = parse_strategy(markdown)
    # Keep a timestamped .bak before this full replacement so a bad
    # round-trip is recoverable.
    backup_file(path, timestamped=True)
    write_strategy_file(path, entries)
    rewritten = path.read_text(encoding="utf-8")
    unrecognized = sum(1 for e in entries if e.context_type == RAW_HEADING_TYPE)
    return _json_result(
        {
            "markdown": rewritten,
            "entries_count": len(entries),
            "unrecognized": unrecognized,
            "path": str(path),
        }
    )


# ---------------------------------------------------------------------------
# STATE.json
# ---------------------------------------------------------------------------


def _state_to_dict(doc: StateDocument) -> dict[str, Any]:
    """Serialize a StateDocument back to the dict shape callers expect."""
    import json as _json

    parsed: dict[str, Any] = _json.loads(render_state(doc))
    return parsed


#: Fields whose value is the positional index of an entry they CLOSE — a
#: later rollback reverses the action, a later evaluation record reviews its
#: outcome. Either takes the target out of the pending set. Shared by the
#: pending filter and the append-time index validation so the two can never
#: disagree about what "closes" an observation.
_CLOSURE_INDEX_FIELDS = ("rollback_of", "evaluation_of")


def _closed_indices(entries: list[dict[str, Any]]) -> set[int]:
    """Positional indices closed by a later ``rollback_of`` / ``evaluation_of``.

    ``entries`` is the full rendered list, so positional indices here match
    the indices the rollback executor and the daily-check evaluation records
    write.
    """
    closed: set[int] = set()
    for entry in entries:
        for field_name in _CLOSURE_INDEX_FIELDS:
            value = entry.get(field_name)
            if isinstance(value, int) and not isinstance(value, bool):
                closed.add(value)
    return closed


def _pending_action_log(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the OPEN observation entries from a rendered action_log.

    "Pending" is defined truthfully from the fields the model actually
    carries (there is no separate "evaluated" flag to read):

    - the entry has a non-null ``observation_due`` — the only field marking
      an action as one whose outcome is meant to be reviewed later. Both a
      past-due window (the daily-check still owes it an evaluation) and a
      future-due window (still under observation) count.
    - the entry has NOT been closed. ``mureo_outcome_evaluate`` is pure, so a
      past-due observation only leaves the set once a LATER entry records its
      closure: a rollback (``rollback_of=<index>``, see rollback.executor) or
      an evaluation record (``evaluation_of=<index>``, appended by daily-check
      after it evaluates the outcome). Without the latter a past-due entry
      would be re-evaluated on every run and the pending set would grow
      without bound.

    Each returned entry gains an ``index`` field — its position in the FULL
    log — so a caller working from the pending subset can close it (append an
    entry with ``evaluation_of=<index>``) without loading the whole history.
    ``index`` is a response-only field: ``_parse_action_log_entry`` never reads
    it, so an echoed copy is dropped on the next write.
    """
    closed = _closed_indices(entries)
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if entry.get("observation_due") is not None and index not in closed:
            result.append({**entry, "index": index})
    return result


def _apply_action_log_scope(payload: dict[str, Any], scope: Any) -> None:
    """Filter ``payload['action_log']`` in place per the requested scope.

    ``all`` (the default) is a no-op, so the response stays byte-identical to
    the legacy behaviour. ``pending`` / ``none`` add ``action_log_scope`` +
    ``action_log_total`` markers so a filtered log is never mistaken for the
    complete history.
    """
    if scope == "all":
        return
    if scope not in ("pending", "none"):
        raise ValueError("action_log must be one of 'all', 'pending', 'none'")
    entries = payload.get("action_log") or []
    payload["action_log_scope"] = scope
    payload["action_log_total"] = len(entries)
    if scope == "none":
        payload.pop("action_log", None)
    else:  # pending
        payload["action_log"] = _pending_action_log(entries)


async def handle_state_get(arguments: dict[str, Any]) -> list[TextContent]:
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    # read_state_file already returns an empty default StateDocument when
    # the file is absent; round-trip through render_state to keep the
    # missing-file and present-file branches in lockstep.
    doc = read_state_file(path)
    payload = _state_to_dict(doc)
    # Response-envelope only (#460). ``_state_to_dict`` renders the parsed
    # document, so this key is added AFTER serialization and is never part of
    # what gets written back: ``parse_state`` ignores unknown top-level keys
    # and ``render_state`` emits only known ones, so an agent that echoes this
    # response into STATE.json loses the key on the next mureo write instead
    # of leaving a stale "today" behind.
    payload["server_now"] = server_now_iso()
    # Optional action_log scoping (context weight-reduction). Applied AFTER
    # server_now, and only ``pending`` / ``none`` mutate the payload — ``all``
    # (the default) keeps the response byte-identical to the legacy shape.
    _apply_action_log_scope(payload, arguments.get("action_log", "all"))
    return _json_result(payload)


def _validate_closure_index(raw: dict[str, Any], key: str, log_len: int) -> None:
    """Validate a ``rollback_of`` / ``evaluation_of`` index when supplied.

    These fields now carry behavioral weight — either takes its target out of
    the pending set — so a stray index would silently hide an OPEN observation
    from the daily-check evidence loop. Require a non-negative integer that
    points at an existing entry (``bool`` is rejected even though it is an
    ``int`` subclass). Absent is fine — the field is optional.
    """
    value = raw.get(key)
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer index into action_log")
    if value >= log_len:
        raise ValueError(
            f"{key}={value} is out of range (action_log has {log_len} entries)"
        )


async def handle_state_action_log_append(
    arguments: dict[str, Any],
) -> list[TextContent]:
    raw = _require(arguments, "entry")
    if not isinstance(raw, dict):
        raise ValueError("entry must be an object")
    # Required per ActionLogEntry contract.
    action = _require(raw, "action")
    platform = _require(raw, "platform")
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    # Validate the closure indices against the CURRENT log length before the
    # append. The log is append-only so its length only grows; an index that
    # is valid now stays valid, and reading once here avoids a stray value
    # silently hiding an open observation. (A benign race can only make a
    # just-appended sibling entry un-referenceable, never mis-close another.)
    log_len = len(read_state_file(path).action_log)
    _validate_closure_index(raw, "rollback_of", log_len)
    _validate_closure_index(raw, "evaluation_of", log_len)
    # ``timestamp`` is stamped SERVER-side (#460). A model-supplied value is
    # accepted by the schema (dropping the property would break existing
    # callers under ``additionalProperties: false``) but deliberately ignored:
    # it is exactly how a drifted date used to get persisted and then read
    # back out of the action_log as evidence of "today".
    entry = ActionLogEntry(
        timestamp=server_now_iso(),
        action=action,
        platform=platform,
        campaign_id=raw.get("campaign_id"),
        ad_id=raw.get("ad_id"),
        entity_type=raw.get("entity_type"),
        entity_id=raw.get("entity_id"),
        summary=raw.get("summary"),
        command=raw.get("command"),
        metrics_at_action=raw.get("metrics_at_action"),
        observation_due=raw.get("observation_due"),
        reversible_params=raw.get("reversible_params"),
        rollback_of=raw.get("rollback_of"),
        evaluation_of=raw.get("evaluation_of"),
        # #549: normally omitted — the open batch is stamped on by
        # ``append_action_log``, which also VALIDATES an explicit value
        # against the declared batches. A caller cannot invent a batch id or
        # reattach to a closed one.
        batch_id=raw.get("batch_id"),
    )
    try:
        doc = append_action_log(path, entry)
    except BatchError as exc:
        # A refused batch_id is caller error, not a server fault: report it as
        # the tool's own refusal rather than as an unhandled exception.
        raise ValueError(str(exc)) from exc
    return _json_result(_state_to_dict(doc))


def _parse_ads_argument(raw: Any) -> tuple[AdState, ...] | None:
    """Build the ad-level state from an upsert payload (#468).

    ``as_of`` is stamped SERVER-side for every ad, mirroring how
    ``mureo_state_action_log_append`` stamps its ``timestamp`` (#460): a
    model-supplied value is accepted by the schema but discarded, so a
    drifted client date cannot be persisted and then read back later as when
    the status was actually observed.

    ``None`` (key absent) means "ad-level status was not fetched" and is kept
    distinct from ``[]`` ("fetched, no ads") — the two justify different
    advice, and only the former should be silent.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("ads must be an array of ad objects")
    observed_at = server_now_iso()
    ads: list[AdState] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each entry in ads must be an object")
        ad_id = item.get("ad_id")
        if not ad_id or not isinstance(ad_id, str):
            raise ValueError("each entry in ads requires a non-empty ad_id")
        ads.append(
            AdState(
                ad_id=ad_id,
                name=item.get("name"),
                status=item.get("status"),
                effective_status=item.get("effective_status"),
                as_of=observed_at,
            )
        )
    return tuple(ads)


async def handle_state_upsert_campaign(
    arguments: dict[str, Any],
) -> list[TextContent]:
    raw = _require(arguments, "campaign")
    if not isinstance(raw, dict):
        raise ValueError("campaign must be an object")
    # Platform context is required so the v2 ``platforms`` section (the
    # shape the dashboard reads) is always populated with the account id;
    # without it a per-account override is silently dropped and the
    # client renders as inactive.
    platform = _require(raw, "platform")
    account_id = _require(raw, "account_id")
    device_targeting = (
        tuple(raw["device_targeting"]) if raw.get("device_targeting") else None
    )
    campaign = CampaignSnapshot(
        campaign_id=_require(raw, "campaign_id"),
        campaign_name=_require(raw, "campaign_name"),
        status=_require(raw, "status"),
        bidding_strategy_type=raw.get("bidding_strategy_type"),
        bidding_details=raw.get("bidding_details"),
        daily_budget=raw.get("daily_budget"),
        device_targeting=device_targeting,
        campaign_goal=raw.get("campaign_goal"),
        notes=raw.get("notes"),
        metrics=raw.get("metrics"),
        ads=_parse_ads_argument(raw.get("ads")),
    )
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    try:
        doc = upsert_campaign(path, campaign, platform=platform, account_id=account_id)
    except ContextFileError as exc:
        # Surface as ValueError so the MCP dispatcher's standard error
        # path translates this into a clean tool-error response rather
        # than a 500-style server error.
        raise ValueError(str(exc)) from exc
    return _json_result(_state_to_dict(doc))


async def handle_state_report_set(
    arguments: dict[str, Any],
) -> list[TextContent]:
    report = _require(arguments, "report")
    summary = _require(arguments, "summary")
    # The free-form summary must be a JSON object so it round-trips into the
    # reports section and the dashboard can render it. Reject anything else
    # (string / list / number) before it reaches the file.
    if not isinstance(summary, dict):
        raise ValueError("summary must be an object")
    # Validate + normalize the structured flags (fills default severities,
    # rejects unknown codes) before they reach STATE.json. Bare-string flags
    # pass through untouched; a ``summary`` without ``flags`` is left as-is.
    if "flags" in summary:
        summary = {**summary, "flags": normalize_flags(summary.get("flags"))}
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    doc = set_report(path, report, summary)
    return _json_result(_state_to_dict(doc))


async def handle_state_platform_metrics_set(
    arguments: dict[str, Any],
) -> list[TextContent]:
    # Platform context is required so the v2 ``platforms`` entry (the shape the
    # dashboard reads) always carries the account id, mirroring upsert_campaign.
    platform = _require(arguments, "platform")
    account_id = _require(arguments, "account_id")
    totals = arguments.get("totals")
    metrics_period = arguments.get("metrics_period")
    periods = arguments.get("periods")
    # Validate the optional shapes before they reach the file: each rollup must
    # be a JSON object (and each ``periods`` bucket too) so a malformed payload
    # is rejected cleanly rather than corrupting STATE.json.
    if totals is not None and not isinstance(totals, dict):
        raise ValueError("totals must be an object")
    if metrics_period is not None and not isinstance(metrics_period, str):
        raise ValueError("metrics_period must be a string")
    if periods is not None:
        if not isinstance(periods, dict):
            raise ValueError("periods must be an object")
        for window, bucket in periods.items():
            if not isinstance(bucket, dict):
                raise ValueError(f"periods[{window!r}] must be an object")
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    try:
        doc = set_platform_metrics(
            path,
            platform,
            account_id,
            totals=totals,
            metrics_period=metrics_period,
            periods=periods,
        )
    except ContextFileError as exc:
        # Surface as ValueError so the MCP dispatcher returns a clean tool
        # error rather than a 500-style server error (matches upsert_campaign).
        raise ValueError(str(exc)) from exc
    return _json_result(_state_to_dict(doc))


async def handle_state_set_conversion_events(
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Set/clear an account's operator conversion override (#342)."""
    platform = _require(arguments, "platform")
    account_id = _require(arguments, "account_id")
    raw = arguments.get("conversion_action_types")
    if raw is not None and not isinstance(raw, list):
        raise ValueError("conversion_action_types must be a list of strings")
    if isinstance(raw, list) and not all(isinstance(x, str) for x in raw):
        raise ValueError("conversion_action_types entries must be strings")
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    try:
        doc = set_conversion_action_types(path, platform, account_id, raw)
    except ContextFileError as exc:
        raise ValueError(str(exc)) from exc
    return _json_result(_state_to_dict(doc))


async def handle_outcome_evaluate(arguments: dict[str, Any]) -> list[TextContent]:
    """Deterministically evaluate a before→after metric change.

    Pure calculation (no state I/O), so it works for ANY platform — the caller
    supplies the two metric maps (typically an action_log entry's
    ``metrics_at_action`` as ``before`` and the current numbers as ``after``).
    Returns per-metric and overall improved/regressed/inconclusive verdicts.
    """
    from mureo.analysis.outcome_eval import evaluate_outcome

    before = _require(arguments, "before")
    after = _require(arguments, "after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("before and after must be objects (metric name -> number)")
    raw_noise = arguments.get("noise_pct", 10.0)
    try:
        noise_pct = float(raw_noise)
    except (TypeError, ValueError) as exc:
        raise ValueError("noise_pct must be a number") from exc

    report = evaluate_outcome(before, after, noise_pct=noise_pct)
    return _json_result(
        {
            "overall": report.overall.value,
            "summary": report.summary,
            "metrics": [
                {
                    "metric": m.metric,
                    "before": m.before,
                    "after": m.after,
                    "delta_pct": m.delta_pct,
                    "verdict": m.verdict.value,
                    "note": m.note,
                }
                for m in report.metrics
            ],
        }
    )
