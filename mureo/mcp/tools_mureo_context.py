"""mureo's STRATEGY.md / STATE.json MCP tool surface.

Seven tools that expose mureo's context layer over MCP, so any MCP host
(Claude Desktop chat, claude.ai web, Codex/Cursor, …) can read and
update STRATEGY.md / STATE.json without direct filesystem access.

The Claude Code path keeps working through its built-in ``Read`` tool;
these MCP tools are additive — they unlock the same capability for
hosts that lack ``Read``. Workflow skills can be migrated to call
these tools (Phase 2/3) so a single skill prompt runs everywhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.mcp._handlers_mureo_context import (
    handle_outcome_evaluate,
    handle_state_action_log_append,
    handle_state_get,
    handle_state_platform_metrics_set,
    handle_state_report_set,
    handle_state_set_conversion_events,
    handle_state_upsert_campaign,
    handle_strategy_get,
    handle_strategy_set,
)

if TYPE_CHECKING:
    from mcp.types import TextContent


_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional path to the file. Defaults to STRATEGY.md / STATE.json "
        "in the MCP server's current working directory. Paths outside "
        "cwd are refused."
    ),
}


_ACTION_LOG_ENTRY_PROPERTY = {
    "type": "object",
    "description": (
        "An action_log entry. Required: action (short description), "
        "platform (google_ads / meta_ads / etc.). The ``timestamp`` is "
        "stamped by the server — do not compute it. Optional: campaign_id, "
        "ad_id, entity_type, entity_id, summary, command, metrics_at_action, "
        "observation_due, reversible_params, rollback_of, evaluation_of, "
        "batch_id (normally stamped by the server — see the field)."
    ),
    "properties": {
        "timestamp": {
            "type": "string",
            "description": (
                "IGNORED — the server stamps the entry with its own clock "
                "(ISO 8601 with UTC offset). Accepted only for backward "
                "compatibility with existing callers; any value supplied "
                "here is discarded, so a drifted client date can never be "
                "persisted and later read back as evidence of 'today'."
            ),
        },
        "action": {"type": "string"},
        "platform": {"type": "string"},
        "campaign_id": {"type": "string"},
        "ad_id": {
            "type": "string",
            "description": (
                "The ad this action targeted, for ad-level actions (pause / "
                "enable / creative swap). Record it so a later run can tell "
                "an ad mureo stopped from one an operator stopped by hand."
            ),
        },
        "entity_type": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Generic target kind for a sub-campaign action, such as "
                "ad_group, ad_set, or placement. Use together with entity_id."
            ),
        },
        "entity_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Platform id of the entity_type target. Record the pair so a "
                "later run can avoid repeating a change to that same entity."
            ),
        },
        "summary": {"type": "string"},
        "command": {"type": "string"},
        "metrics_at_action": {"type": "object"},
        "observation_due": {"type": "string"},
        "reversible_params": {"type": "object"},
        "rollback_of": {
            "type": "integer",
            "description": (
                "Positional index (into the full action_log) of the action "
                "this entry reverses. Normally written by the rollback surface "
                "(``rollback_apply``), not by hand. Must point at an existing "
                "entry."
            ),
        },
        "evaluation_of": {
            "type": "integer",
            "description": (
                "Positional index (into the full action_log) of the action "
                "whose ``observation_due`` this entry evaluates and CLOSES. "
                "Append this after running ``mureo_outcome_evaluate`` on a "
                "past-due observation so the source entry leaves the pending "
                "set (``mureo_outcome_evaluate`` is pure and records nothing "
                "itself). Must point at an existing entry — the daily-check's "
                "pending scope reads the returned ``index`` field to fill it."
            ),
        },
        "batch_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Normally OMIT this. While a batch is open (mureo_batch_begin) "
                "the server stamps the entry with it automatically, so a bulk "
                "pass groups itself. Supplying it is an explicit ASSERTION "
                "that this entry belongs to that batch, and it is validated: "
                "the id must name a declared batch that is still open. An "
                "unknown id, or one whose batch has been closed, is REFUSED — "
                "membership cannot be invented, and a closed batch's reported "
                "member count cannot be made false after the fact. To group "
                "imported or backfilled history, open a batch for the import "
                "rather than reattaching to an old one."
            ),
        },
    },
    "required": ["action", "platform"],
    "dependentRequired": {
        "entity_type": ["entity_id"],
        "entity_id": ["entity_type"],
    },
}


_ADS_PROPERTY = {
    "type": "array",
    "description": (
        "Ad-level (creative-level) delivery state for this campaign. Send it "
        "so a change made OUTSIDE mureo — an ad paused by hand in the "
        "platform UI, stopped by its ad set/campaign, or rejected by policy "
        "— is recorded as fact and can be diffed on the next run. "
        "``status`` is what the ad is configured as; ``effective_status`` is "
        "whether it is actually delivering, and the two disagreeing is the "
        "signal. Omit the whole field when you did not fetch ad-level status "
        "(that is different from sending an empty list, which means "
        "'fetched, this campaign has no ads')."
    ),
    "items": {
        "type": "object",
        "properties": {
            "ad_id": {"type": "string", "description": "Platform ad id."},
            "name": {"type": "string", "description": "Ad name."},
            "status": {
                "type": "string",
                "description": "Configured status (e.g. ACTIVE / PAUSED).",
            },
            "effective_status": {
                "type": "string",
                "description": (
                    "Actual delivery status where the platform exposes one "
                    "(Meta: ACTIVE / ADSET_PAUSED / CAMPAIGN_PAUSED / "
                    "DISAPPROVED / …). Omit when the platform does not "
                    "report it rather than copying ``status`` into it."
                ),
            },
            "as_of": {
                "type": "string",
                "description": (
                    "IGNORED — the server stamps each ad with its own clock "
                    "(ISO 8601 with UTC offset), so a drifted client date "
                    "can never be persisted and later read back as when the "
                    "status was observed."
                ),
            },
        },
        "required": ["ad_id"],
    },
}


_CAMPAIGN_PROPERTY = {
    "type": "object",
    "description": (
        "A CampaignSnapshot for STATE.json plus its platform context. "
        "Required: campaign_id, campaign_name, status, platform, "
        "account_id. The platform + account_id populate the per-platform "
        "``platforms`` section the dashboard reads (omit them and the "
        "client renders as inactive). Optional fields mirror the snapshot "
        "schema in docs/strategy-context.md, including ``metrics`` "
        "(spend / impressions / clicks / conversions / cpa / ctr / "
        "result_indicator / period / fetched_at) for dashboard KPIs."
    ),
    "properties": {
        "campaign_id": {"type": "string"},
        "campaign_name": {"type": "string"},
        "status": {"type": "string"},
        "platform": {
            "type": "string",
            # No enum: a valid key includes ``plugin:<dist>`` for any installed
            # bridge, which no fixed list can enumerate. minLength is the
            # constraint that IS always true.
            "minLength": 1,
            "description": (
                "Platform key this campaign belongs to, e.g. "
                "``google_ads`` / ``meta_ads`` / ``tiktok_ads``, or a plugin "
                "bridge ``plugin:<dist>``. Use the SAME key the account is "
                "already stored under — one ad account has exactly one "
                "platform key, and a second key for an account another key "
                "already holds is REJECTED (the reporting view sums the "
                "entries, so it would double-count)."
            ),
        },
        "account_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Platform account id (Google ``customer_id`` / Meta "
                "``act_*``) written onto the platform entry, and used to "
                "detect a second entry for the same account."
            ),
        },
        "bidding_strategy_type": {"type": "string"},
        "bidding_details": {"type": "object"},
        "daily_budget": {"type": "number"},
        "device_targeting": {"type": "array"},
        "campaign_goal": {"type": "string"},
        "notes": {"type": "string"},
        "metrics": {
            "type": "object",
            "description": (
                "Optional performance metrics for the reporting dashboard: "
                "spend, impressions, clicks, conversions, cpa, ctr, "
                "result_indicator (Meta: clicks vs leads), period (e.g. "
                "``LAST_30_DAYS``), fetched_at (ISO 8601)."
            ),
        },
        "ads": _ADS_PROPERTY,
    },
    "required": [
        "campaign_id",
        "campaign_name",
        "status",
        "platform",
        "account_id",
    ],
}


TOOLS: list[Tool] = [
    Tool(
        name="mureo_strategy_get",
        description=(
            "Read STRATEGY.md and return its raw markdown text plus an "
            "exists flag and ``server_now`` (the server's clock as ISO 8601 "
            "with UTC offset). Returns empty markdown when the file is "
            "absent (skills should treat that as 'no strategy yet', "
            "not as an error). Use this when the host has no direct "
            "filesystem access (Claude Desktop chat, web, remote MCP). "
            "Treat ``server_now`` as the current date — never infer today "
            "from dates found inside the context files."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_strategy_set",
        description=(
            "Atomically replace STRATEGY.md with the provided markdown. "
            "The content is parsed via parse_strategy() before writing "
            "to ensure it is well-formed; a malformed input raises "
            "rather than corrupts the file. Use this to update goals, "
            "constraints, or operation mode from a chat-only host."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "markdown": {
                    "type": "string",
                    "description": "The full new content of STRATEGY.md.",
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["markdown"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_get",
        description=(
            "Read STATE.json and return its parsed v2 document: "
            "version, last_synced_at, platforms (per-platform "
            "campaigns), legacy v1 campaigns, and action_log. Returns "
            "an empty default doc when the file is absent. The response "
            "also carries ``server_now`` — the server's clock as ISO 8601 "
            "with UTC offset (e.g. 2026-07-28T10:12:33+09:00). It is the "
            "authoritative current date: every OTHER date in the document "
            "(last_synced_at, reports.*.period, action_log timestamps) is "
            "history and must never be read as 'today'. ``server_now`` is a "
            "response field only — do not write it back into STATE.json. "
            "``action_log`` scopes the returned log to cut context cost: "
            "``all`` (default) returns the full history unchanged; "
            "``pending`` returns only entries with an OPEN ``observation_due`` "
            "— past-due ones you still owe an outcome evaluation, and "
            "future-due ones still under observation — dropping plain log "
            "entries and entries a later rollback (``rollback_of``) or "
            "evaluation record (``evaluation_of``) already closed; ``none`` "
            "omits the log entirely. Each ``pending`` entry carries an "
            "``index`` field (its position in the FULL log) so you can close "
            "it after evaluating — append an entry with "
            "``evaluation_of: <index>`` — without ever loading the whole "
            "history. When filtered (``pending`` / ``none``) the response "
            "carries ``action_log_scope`` (the mode) and ``action_log_total`` "
            "(the full pre-filter entry count) so the log you were shown is "
            "never mistaken for the complete history."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "action_log": {
                    "type": "string",
                    "enum": ["all", "pending", "none"],
                    "description": (
                        "Scope of the returned action_log. ``all`` (default) "
                        "= the full history, byte-identical to the legacy "
                        "behaviour. ``pending`` = only entries with an open "
                        "``observation_due`` (past-due + future-due), for the "
                        "daily-check evidence loop. ``none`` = omit the log. "
                        "Filtered responses add ``action_log_scope`` + "
                        "``action_log_total`` markers."
                    ),
                },
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_action_log_append",
        description=(
            "Atomically append a single action_log entry to STATE.json. "
            "Use this whenever a workflow takes an action that should "
            "be evaluable later (budget changes, campaign pauses, "
            "negative-keyword adds). Returns the updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "entry": _ACTION_LOG_ENTRY_PROPERTY,
                "path": _PATH_PROPERTY,
            },
            "required": ["entry"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_upsert_campaign",
        description=(
            "Atomically upsert a CampaignSnapshot into STATE.json (root "
            "campaigns array). Use this to keep STATE.json in sync with "
            "campaign metadata changes the agent observes via vendor "
            "MCPs or BYOD imports. Pass the optional ``metrics`` object to "
            "persist the campaign's performance numbers (spend, clicks, "
            "conversions, cpa, ctr, …) so the reporting dashboard can "
            "render KPIs from STATE.json. Pass the optional ``ads`` array to "
            "persist ad-level delivery status, so a pause applied outside "
            "mureo is recorded and can be diffed on the next run."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "campaign": _CAMPAIGN_PROPERTY,
                "path": _PATH_PROPERTY,
            },
            "required": ["campaign"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_report_set",
        description=(
            "Atomically persist a structured analysis report summary into "
            "STATE.json's ``reports`` section so the read-only configure "
            "dashboard can render the latest daily / weekly / goal report "
            "without re-running the agent. ``report`` selects the kind "
            "(daily / weekly / goal); ``summary`` is a free-form object — by "
            "convention generated_at (ISO 8601), period, kpis (per-platform "
            "/ totals headline numbers), flags (notable items), narrative "
            "(short text). Other report kinds are preserved. Best-effort: a "
            "skill should skip this silently where the context MCP is "
            "unavailable. Returns the updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "report": {
                    "type": "string",
                    "enum": ["daily", "weekly", "goal"],
                    "description": (
                        "Report kind: ``daily`` (daily-check), ``weekly`` "
                        "(weekly-report), or ``goal`` (goal-review)."
                    ),
                },
                "summary": {
                    "type": "object",
                    "description": (
                        "Free-form summary object. Convention: generated_at "
                        "(ISO 8601), period, kpis (per-platform / totals "
                        "headline numbers), flags, narrative (short text). "
                        "Each flag is either a legacy snake_case string OR a "
                        "structured object {code, severity, params}: code is a "
                        "canonical vocabulary key (e.g. goals_met, "
                        "invalid_traffic_suspected, budget_drift, "
                        "zero_cv_adspots, spend_spike, anomaly_baseline_"
                        "insufficient), severity is action|watch|info|positive "
                        "(defaulted from code if omitted), and params holds the "
                        "detail (adspot ids, yen, ctr) — keep detail in params "
                        "/ narrative, NOT in the code. For a finding outside "
                        "the vocabulary use {code:'custom', severity, label} "
                        "where label is a string or {locale: text} map. Unknown "
                        "non-custom codes are rejected."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["report", "summary"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_platform_metrics_set",
        description=(
            "Atomically set a platform's metric ROLLUP in STATE.json's v2 "
            "``platforms`` section so the read-only reporting dashboard can "
            "render per-platform KPIs (and the YESTERDAY / LAST_30_DAYS period "
            "toggle) without re-querying. This writes the PLATFORM-LEVEL "
            "rollup — distinct from mureo_state_upsert_campaign, which writes "
            "per-campaign metrics. Pass ``totals`` + ``metrics_period`` for the "
            "single most-recent window, and/or ``periods`` "
            '({"YESTERDAY": {…}, "LAST_30_DAYS": {…}}) for the per-window '
            "rollups the toggle reads. ``periods`` is merged per window key "
            "(a YESTERDAY write keeps a prior LAST_30_DAYS bucket); omitted "
            "fields preserve their existing value. Campaigns and every other "
            "platform are preserved. ``account_id`` is required and always "
            "written onto the entry. Returns the updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    # No enum: a valid key includes ``plugin:<dist>`` for any
                    # installed bridge, which no fixed list can enumerate.
                    # minLength is the constraint that IS always true.
                    "minLength": 1,
                    "description": (
                        "Platform key: a built-in (``google_ads`` / "
                        "``meta_ads`` / ``tiktok_ads`` / ``search_console`` / "
                        "``ga4``) or a plugin bridge ``plugin:<dist>``. Use "
                        "the SAME key the account is already stored under — "
                        "one ad account has exactly one platform key, and a "
                        "second key for an account another key already holds "
                        "is REJECTED (the reporting view sums the entries, so "
                        "it would double-count)."
                    ),
                },
                "account_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "The platform account id (Google customer_id / Meta "
                        "act_*). Always written onto the platform entry, and "
                        "used to detect a second entry for the same account."
                    ),
                },
                "totals": {
                    "type": "object",
                    "description": (
                        "Single-rollup totals for the most recent window "
                        "(spend, impressions, clicks, conversions, cpa, ctr, "
                        "result_indicator, period, fetched_at). Omit to "
                        "preserve the existing value."
                    ),
                },
                "metrics_period": {
                    "type": "string",
                    "description": (
                        "The window ``totals`` covers (e.g. ``LAST_30_DAYS``). "
                        "Omit to preserve the existing value."
                    ),
                },
                "periods": {
                    "type": "object",
                    "description": (
                        "Per-window rollups keyed by period token "
                        "(``YESTERDAY`` / ``LAST_30_DAYS`` / …); each value is "
                        "a totals-shaped object. Merged per key into the "
                        "existing map. Omit to preserve the existing map."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["platform", "account_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_set_conversion_events",
        description=(
            "Declare which Meta Insights ``action_type`` rows count as THIS "
            "account's conversions, overriding mureo's built-in deduped generic "
            "set (lead / purchase / complete_registration). Use this when an "
            "advertiser's real conversion is a CUSTOM pixel event "
            "(``offsite_conversion.custom.<id>``) — otherwise it reports 0 "
            "conversions — or when their account only emits a component row "
            "(e.g. ``offsite_conversion.fb_pixel_lead``) with no generic "
            "aggregate. Replacement semantics: the listed action_types are the "
            "COMPLETE conversion set (never summed on top of the defaults), so "
            "overlapping alias rows can't double-count. Tip: to avoid typos, "
            "first call meta_ads_insights_report / _breakdown to see the "
            "account's real action_type labels, confirm with the operator, then "
            "set the exact string(s) here. Pass an empty list (or omit "
            "``conversion_action_types``) to CLEAR the override and restore the "
            "default. Stored on ``platforms[platform]`` and preserved across "
            "syncs. Returns the updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    # No enum: see mureo_state_platform_metrics_set.
                    "minLength": 1,
                    "description": (
                        "Platform key — normally ``meta_ads`` (the override "
                        "only affects the Meta conversion counters). Use the "
                        "SAME key the account is already stored under — one "
                        "ad account has exactly one platform key, and a "
                        "second key for an account another key already holds "
                        "is REJECTED (the reporting view sums the entries, so "
                        "it would double-count)."
                    ),
                },
                "account_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "The Meta ad account id (``act_*``). Always written "
                        "onto the platform entry, and used to detect a second "
                        "entry for the same account. The override applies "
                        "ONLY to this account."
                    ),
                },
                "conversion_action_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Exact Meta ``action_type`` strings to count as "
                        "conversions (e.g. "
                        '["offsite_conversion.custom.123"]). Empty / omitted '
                        "clears the override."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["platform", "account_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_outcome_evaluate",
        description=(
            "Deterministically evaluate whether a logged action's outcome "
            "improved, regressed, or is inconclusive — the reproducible verdict "
            "the observation-window review (daily-check) and /learn rely on, "
            "instead of eyeballing the numbers. Pass ``before`` (typically the "
            "action_log entry's ``metrics_at_action``) and ``after`` (the "
            "current numbers). Pure calculation — works for ANY platform "
            "(google_ads / meta_ads / tiktok_ads / plugins) as long as you feed "
            "comparable metric names. Direction is built in: cpa/cpc/cpl/cpm "
            "lower-is-better; conversions/ctr/cvr/roas higher-is-better; "
            "cost/spend/clicks/impressions are volume-only (reported, never "
            "scored). A change within ±noise_pct (default 10%) or a zero/absent "
            "baseline is 'inconclusive' (no fabricated swing)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "before": {
                    "type": "object",
                    "description": (
                        "Baseline metrics — metric name → number (e.g. "
                        '{"cpa": 5000, "conversions": 50}). Usually the '
                        "action_log entry's metrics_at_action."
                    ),
                },
                "after": {
                    "type": "object",
                    "description": "Current metrics, same shape as ``before``.",
                },
                "noise_pct": {
                    "type": "number",
                    "description": (
                        "Noise band in percent (default 10). A change smaller "
                        "than this is 'inconclusive' (day-to-day variance)."
                    ),
                },
            },
            "required": ["before", "after"],
            "additionalProperties": False,
        },
    ),
]


_HANDLERS = {
    "mureo_strategy_get": handle_strategy_get,
    "mureo_strategy_set": handle_strategy_set,
    "mureo_state_get": handle_state_get,
    "mureo_state_action_log_append": handle_state_action_log_append,
    "mureo_state_upsert_campaign": handle_state_upsert_campaign,
    "mureo_state_report_set": handle_state_report_set,
    "mureo_state_platform_metrics_set": handle_state_platform_metrics_set,
    "mureo_state_set_conversion_events": handle_state_set_conversion_events,
    "mureo_outcome_evaluate": handle_outcome_evaluate,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a tool call to its handler.

    Raises:
        ValueError: when the tool name is unknown or required parameters
            are missing.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)
