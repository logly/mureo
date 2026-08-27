"""mureo's STRATEGY.md / STATE.json MCP tool surface.

Thirteen tools that expose mureo's context layer over MCP, so any MCP host
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

from mureo.context.models import DAILY_DATE_KEY_PATTERN
from mureo.context.state import DAILY_RETENTION_DAYS
from mureo.core.display_contract import (
    ACTION_LOG_DISPLAY_RULE,
    ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS,
    ACTION_LOG_DISPLAY_TITLE_MAX_CHARS,
    BREAKDOWN_NOTE_MAX_CHARS,
    BREAKDOWN_STATES,
    DISPLAY_CONTRACT_RULE,
    DISPLAY_OVERWRITE_RULE,
    DISPLAY_SECTIONS,
    DISPLAY_SOURCE_MAX_CHARS,
    HIGHLIGHT_TEXT_MAX_CHARS,
    HIGHLIGHT_TONES,
    HIGHLIGHTS_MAX_ITEMS,
    NAV_MESSAGE_MAX_CHARS,
    PROPOSAL_BODY_MAX_CHARS,
    PROPOSAL_DATE_MAX_CHARS,
    PROPOSAL_STATUSES,
    PROPOSAL_TITLE_MAX_CHARS,
    STATED_VALUE_LABEL_MAX_CHARS,
    STATED_VALUE_MAX_CHARS,
)
from mureo.core.metrics_windows import (
    CANONICAL_METRICS_WINDOWS,
    METRICS_WINDOW_RULE,
)
from mureo.core.report_kinds import REPORT_KIND_DESCRIPTION, REPORT_KINDS
from mureo.core.report_summary import REPORT_SUMMARY_RULE
from mureo.mcp._handlers_mureo_context import (
    handle_outcome_evaluate,
    handle_state_action_log_append,
    handle_state_display_set,
    handle_state_get,
    handle_state_platform_daily_set,
    handle_state_platform_metrics_set,
    handle_state_platform_not_collected_set,
    handle_state_report_set,
    handle_state_set_conversion_events,
    handle_state_upsert_campaign,
    handle_state_workspace_not_collected_set,
    handle_strategy_get,
    handle_strategy_set,
)

if TYPE_CHECKING:
    from mcp.types import TextContent


# The windows a metrics rollup may be filed under (#659). Stated as an
# allow-list, not an example: "e.g. ``LAST_30_DAYS``" gave an agent no way to
# know the vocabulary is CLOSED, so one analysing "the last 8 days" wrote
# ``LAST_8_DAYS`` — a bucket no default view reads. The write then succeeded,
# the agent truthfully reported success, and the dashboard truthfully kept
# reading stale, with nothing naming the contradiction.
#
# The ``enum`` is the load-bearing half and it fires EARLY: the dispatcher
# schema-validates before any handler runs, so an agent sending
# ``SINCE_LAUNCH_17D`` sees ``'SINCE_LAUNCH_17D' is not one of [...]`` and
# never reaches mureo's own message. The allowed values survive that path;
# the REASON only does if it is already in the description the model read
# before calling — which is why ``METRICS_WINDOW_RULE`` is pasted below
# rather than restated in the raiser alone.
_METRICS_WINDOWS: list[str] = list(CANONICAL_METRICS_WINDOWS)

_PERIOD_BUCKET_PROPERTY = {
    "type": "object",
    "description": (
        "Totals-shaped rollup for this window (spend, impressions, clicks, "
        "conversions, cpa, ctr, result_indicator, fetched_at)."
    ),
}


# One day's rollup in ``mureo_state_platform_daily_set`` (#690). Same shape as
# a window bucket — the vocabulary does not change with the grain — declared
# separately because it is the schema for EVERY property of a date-keyed
# object rather than for one named window.
_DAILY_BUCKET_PROPERTY = {
    "type": "object",
    "description": (
        "Totals-shaped rollup for that ONE day (spend, impressions, clicks, "
        "conversions, cpa, ctr, result_indicator, fetched_at)."
    ),
}


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
        "batch_id (normally stamped by the server — see the field), the "
        "provenance trio origin / external_id / occurred_at for a change "
        "mureo did NOT make (see those fields), and display_title / "
        "display_summary — the one line the dashboard shows for this entry."
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
        "origin": {
            "type": "string",
            "enum": ["external"],
            "description": (
                "OMIT for anything mureo did — that is what an absent origin "
                "means. Set 'external' ONLY for a change mureo did not make, "
                "which you read out of a platform's own change history "
                "(typically a hosted connector mureo cannot poll itself; "
                "native and plugin platforms are covered by "
                "mureo_external_changes_import). An external entry is "
                "permanently marked as observed rather than performed: mureo "
                "will refuse to plan a rollback for it, because it never saw "
                "the prior value. Never use it to record a change you made "
                "through mureo."
            ),
        },
        "external_id": {
            "type": "string",
            "minLength": 1,
            "description": (
                "The change feed's own identifier for an external change, so "
                "recording it twice is a no-op. Requires origin='external'. "
                "Namespace it with the platform key (e.g. "
                "'tiktok_ads|<change id>'). Omit only when the feed exposes "
                "no id — the entry is then recorded, but a later pass cannot "
                "recognise it and will record it again."
            ),
        },
        "occurred_at": {
            "type": "string",
            "minLength": 1,
            "description": (
                "ISO 8601 time the PLATFORM says the change happened — "
                "history, never 'now'. Unlike ``timestamp`` (which the server "
                "always stamps) this is accepted, because the change's own "
                "date is not something the server can know. The observation "
                "window anchors on it, so a change made two weeks ago is "
                "already due for review rather than due in a fortnight."
            ),
        },
        "display_title": {
            "type": "string",
            "minLength": 1,
            "maxLength": ACTION_LOG_DISPLAY_TITLE_MAX_CHARS,
            "description": (
                "What this action WAS, in a few words an operator reads on a "
                "dashboard row — 'Paused two losing ad groups'. "
                + ACTION_LOG_DISPLAY_RULE
            ),
        },
        "display_summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS,
            "description": (
                "One sentence under the title, still for the operator. Plain "
                "text — no markdown: ``**bold**`` is shown to a person as "
                "asterisks. Keep the full reasoning in ``summary``, which "
                "nothing here shortens. " + ACTION_LOG_DISPLAY_RULE
            ),
        },
    },
    "required": ["action", "platform"],
    "dependentRequired": {
        "entity_type": ["entity_id"],
        "entity_id": ["entity_type"],
        # An external_id on a mureo-originated entry would poison change-import
        # dedup — the next import would treat mureo's own action as something
        # it had already imported. Refused at the schema and again in the model.
        "external_id": ["origin"],
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
                "``google_ads`` / ``meta_ads`` / ``tiktok_ads``, a platform "
                "an installed plugin registered (its provider name), or a "
                "plugin bridge ``plugin:<dist>:<provider>``. Use the SAME key "
                "the account is already stored under — one ad account has "
                "exactly one platform key, and a second key for an account "
                "another key already holds is REJECTED (the reporting view "
                "sums the entries, so it would double-count). A NEW key that "
                "is none of the three is REJECTED too: do not invent or "
                "abbreviate a platform name."
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
        "bidding_strategy_type": {
            "type": "string",
            "description": (
                "Bid strategy as the platform itself names it, verbatim. "
                "Omit it for a platform that does not select delivery by a "
                "bid — never borrow another platform's strategy name."
            ),
        },
        "bidding_details": {
            "type": "object",
            "description": (
                "Free-form bidding detail in the platform's own vocabulary "
                "(e.g. {'target_cpa': 5000}); omit it alongside "
                "bidding_strategy_type where the platform has neither. One "
                "key is read by mureo: for Google Ads, "
                "'bidding_strategy_system_status' — the value "
                "google_ads_campaigns_get / google_ads_campaigns_diagnose "
                "returns — is what the learning-period pre-flight "
                "(mureo_learning_reset_preflight, and the "
                "block_learning_resets* guardrails) uses to tell whether the "
                "campaign is already re-learning. Without it that state is "
                "reported 'unknown', never 'steady'."
            ),
        },
        "daily_budget": {"type": "number"},
        "monthly_budget": {
            "type": "number",
            "description": (
                "The campaign's own MONTHLY budget, on a platform that has "
                "that concept alongside the daily one. Omit it entirely for "
                "a platform configured per day (Google Ads, Meta) — do not "
                "send a daily budget multiplied out, which is an implied cap "
                "and not what the campaign is set to spend. mureo never "
                "stores a total over these: it sums them on read, and only "
                "where every campaign of a declaring platform carries one."
            ),
        },
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


# One breakdown table's rows (#706). Declared once and used for both
# ``campaigns`` and ``adgroups``: the two are the same shape at two levels,
# and a second copy is how they would start disagreeing about what a row is.
_BREAKDOWN_ROW_ITEMS = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "description": "The campaign / ad group as the platform names it.",
        },
        "spend": {"type": "number", "description": "Spend, as a raw number."},
        "mcpa": {
            "type": "number",
            "description": (
                "Measured cost per acquisition, as a raw number. OMIT it "
                "where there were no conversions — 0 states a perfect CPA "
                "rather than the absence of one."
            ),
        },
        "target_cpa": {
            "type": "number",
            "description": "The CPA this row is judged against, as a raw number.",
        },
        "state": {
            "type": "string",
            "enum": list(BREAKDOWN_STATES),
            "description": (
                "How this row is doing, from a closed set: target_met / "
                "improving need no action, watch / worsening do, and no_data "
                "is too little delivery to judge. Omit rather than inventing "
                "a word — each value is rendered as a colour."
            ),
        },
        "note": {
            "type": "string",
            "maxLength": BREAKDOWN_NOTE_MAX_CHARS,
            "description": (
                "One table cell of context, at most "
                f"{BREAKDOWN_NOTE_MAX_CHARS} characters. Text in a table "
                "steals the width the figures need."
            ),
        },
    },
    "required": ["name"],
    "additionalProperties": False,
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
            "dashboard can render the latest report without re-running the "
            "agent. ``report`` selects the kind — one per skill, listed "
            "below; ``summary`` carries generated_at (ISO "
            "8601), period, totals (headline figures), flags (one entry per "
            "finding) and narrative (the judgement and the proposal). Each "
            "part is rendered as what it is — figures as figures, flags as "
            "chips, narrative as prose — so a summary that folds all of it "
            "into the narrative renders as one unreadable paragraph, and the "
            "narrative bound below is enforced. Other report kinds are "
            "preserved. Best-effort: a skill should skip this silently where "
            "the context MCP is unavailable. Returns the updated state "
            "document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "report": {
                    "type": "string",
                    # The vocabulary and this list are one thing (#671): the
                    # schema layer rejects a kind before any handler runs, so
                    # an enum narrower than what the skills instruct refuses a
                    # skill's own instructions.
                    "enum": list(REPORT_KINDS),
                    "description": REPORT_KIND_DESCRIPTION,
                },
                "summary": {
                    "type": "object",
                    "description": (
                        # The rule is pasted rather than restated (#662). No
                        # ``enum`` can constrain prose, so the description IS
                        # the constraint an agent meets before it composes the
                        # report — the refusal only repeats it.
                        REPORT_SUMMARY_RULE + " Fields: generated_at (ISO "
                        "8601), period, totals (the headline figures above), "
                        "kpis (the OPTIONAL per-platform split — the "
                        "breakdown, not the headline row), flags, narrative. "
                        "Each flag is either a legacy snake_case string OR a "
                        "structured object {code, severity, params}: code is a "
                        "canonical vocabulary key (e.g. goals_met, "
                        "invalid_traffic_suspected, budget_drift, "
                        "zero_cv_adspots, spend_spike, anomaly_baseline_"
                        "insufficient), severity is action|watch|info|positive "
                        "(defaulted from code if omitted), and params holds the "
                        "detail (adspot ids, yen, ctr) — keep detail in "
                        "params, NOT in the code and NOT in the narrative. "
                        "For a finding outside "
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
        name="mureo_state_display_set",
        description=(
            "Write what the DASHBOARD shows for this client — a small, "
            "strictly bounded surface, separate from everything else you "
            "store. STATE.json is your working memory and is prose-heavy by "
            "design; the dashboard reads THIS section and nothing else, so "
            "your reasoning keeps going exactly where it already goes and "
            "stops reaching the screen. Call it in the same pass as "
            "mureo_state_report_set, from the same figures. **The whole "
            "section is replaced by what this call states** — an omitted "
            "section is written as absent, not kept from the last run, "
            "because these five describe one client at one moment and mixing "
            "two runs on one screen is worse than showing a section fewer. A "
            "call that states nothing CLEARS the contract. **Do NOT write "
            "the KPI funnel (spend / impressions / clicks / conversions, "
            "CPM / CPC / CPA) or the daily chart**: mureo computes both from "
            "the stored totals and the day-grain history, so there is "
            "nothing for you to get wrong there. Every bound below REFUSES "
            "the write rather than truncating it — a sentence cut in half "
            "reads like a bug and nobody can tell what was removed. Returns "
            "the updated state document. "
            # The rule is pasted rather than restated (#659 / #662): the
            # bounds fire at the schema layer, before this tool's handler
            # runs, so a caller who only ever sees the JSON-Schema refusal
            # learns the number and none of the reasoning unless the reason
            # was already in the description it read before calling.
            + DISPLAY_CONTRACT_RULE + " "
            # The overwrite rule is the half no schema can enforce: whether
            # another skill's proposal is still live is a judgement about
            # today's findings, which only the caller holds. So it has to be
            # in the description or it is nowhere.
            + DISPLAY_OVERWRITE_RULE
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": DISPLAY_SOURCE_MAX_CHARS,
                    "description": (
                        "The skill writing this screen — 'daily-check', "
                        "'weekly-report', your own name. REQUIRED whenever "
                        "you state any section: the contract is replaced "
                        "wholesale by whoever writes it last, so without this "
                        "the card cannot say whose answer it is showing. "
                        "``generated_at`` is stamped by the server — do not "
                        "compute it."
                    ),
                },
                "nav_message": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": NAV_MESSAGE_MAX_CHARS,
                    "description": (
                        "The single operator-facing line at the top of the "
                        "report (運用ナビ): what to do next, in at most "
                        f"{NAV_MESSAGE_MAX_CHARS} characters. One line — a "
                        "second sentence here is a paragraph by tomorrow."
                    ),
                },
                "highlights": {
                    "type": "array",
                    "maxItems": HIGHLIGHTS_MAX_ITEMS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "tone": {
                                "type": "string",
                                "enum": list(HIGHLIGHT_TONES),
                                "description": (
                                    "How the chip is coloured: good / watch / bad."
                                ),
                            },
                            "text": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": HIGHLIGHT_TEXT_MAX_CHARS,
                                "description": (
                                    "The chip's words, at most "
                                    f"{HIGHLIGHT_TEXT_MAX_CHARS} characters."
                                ),
                            },
                        },
                        "required": ["tone", "text"],
                        "additionalProperties": False,
                    },
                    "description": (
                        f"At most {HIGHLIGHTS_MAX_ITEMS} chips — what this "
                        "client's card says at a glance. A fourth is not "
                        "extra information on screen; it is the point at "
                        "which none of them is read, so choose."
                    ),
                },
                "proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": PROPOSAL_TITLE_MAX_CHARS,
                                "description": (
                                    "The row an operator scans, at most "
                                    f"{PROPOSAL_TITLE_MAX_CHARS} characters."
                                ),
                            },
                            "body": {
                                "type": "string",
                                "maxLength": PROPOSAL_BODY_MAX_CHARS,
                                "description": (
                                    "One line under the title, at most "
                                    f"{PROPOSAL_BODY_MAX_CHARS} characters. "
                                    "The reasoning behind the proposal is "
                                    "long and belongs in your own prose."
                                ),
                            },
                            "status": {
                                "type": "string",
                                "enum": list(PROPOSAL_STATUSES),
                                "description": (
                                    "proposed (awaiting a decision) or done "
                                    "(carried out)."
                                ),
                            },
                            "date": {
                                "type": "string",
                                "maxLength": PROPOSAL_DATE_MAX_CHARS,
                                "description": (
                                    "When it was proposed or done. PREFER "
                                    "YYYY-MM-DD; free text like 'last week' "
                                    "is allowed, but keep it consistent "
                                    "within a client — two spellings in one "
                                    "list read as two different kinds of "
                                    "fact. Displayed exactly as written: "
                                    "mureo enforces the length and no format, "
                                    "so nothing here is re-derived or "
                                    "reformatted."
                                ),
                            },
                        },
                        "required": ["title"],
                        "additionalProperties": False,
                    },
                    "description": (
                        "What you propose doing, or have done — one entry "
                        "each, never one paragraph listing several."
                    ),
                },
                "breakdown": {
                    "type": "object",
                    "properties": {
                        "campaigns": {
                            "type": "array",
                            "items": dict(_BREAKDOWN_ROW_ITEMS),
                            "description": "One row per campaign.",
                        },
                        "adgroups": {
                            "type": "array",
                            "items": dict(_BREAKDOWN_ROW_ITEMS),
                            "description": "One row per ad group / ad set.",
                        },
                    },
                    "additionalProperties": False,
                    "description": (
                        "The two per-entity tables: ``campaigns`` and "
                        "``adgroups``, each an array of {name, spend, mcpa, "
                        "target_cpa, state, note}. Figures are raw numbers, "
                        "``state`` comes from a closed set, and a figure you "
                        "do not have is OMITTED rather than written as 0."
                    ),
                },
                "stated_values": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": STATED_VALUE_LABEL_MAX_CHARS,
                                "description": (
                                    "The chip's caption, at most "
                                    f"{STATED_VALUE_LABEL_MAX_CHARS} "
                                    "characters."
                                ),
                            },
                            "value": {
                                "description": (
                                    "A raw number, or a string of at most "
                                    f"{STATED_VALUE_MAX_CHARS} characters "
                                    "where a number cannot carry it "
                                    "('3 of 7', '未設定'). A SENTENCE IS "
                                    "REFUSED: this is a numeric column, and "
                                    "prose in it is the defect this contract "
                                    "exists to remove."
                                ),
                            },
                        },
                        "required": ["label", "value"],
                        "additionalProperties": False,
                    },
                    "description": (
                        "Labelled figures this report states that are not "
                        "one of mureo's headline metrics — a CVR, a target, "
                        "a count. Chips, not a table of prose."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            # Nothing is required outright: a call that states no section
            # clears the contract, which is the only way to take a stale
            # screen down, and it has nothing left to attribute.
            "required": [],
            # …but stating ANY section requires naming yourself. Expressed as
            # dependentRequired so the dispatcher refuses an unattributed
            # screen before the handler runs — the same layer that catches
            # every other bound here. The guard repeats it for callers that
            # bypass the schema.
            "dependentRequired": {section: ["source"] for section in DISPLAY_SECTIONS},
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
            "fields preserve their existing value. **The window vocabulary "
            "is closed** — see ``metrics_period``. Every rollup you pass "
            "without a usable ``fetched_at`` — omitted, null or blank — is "
            "stamped with the write time, so the dashboard can state an age "
            'instead of "update time unknown"; pass your own only when the '
            "figures were pulled at some other time (a historical window). "
            "Campaigns and every other "
            "platform are preserved. ``account_id`` is required and always "
            "written onto the entry. **If this platform carries a "
            "``not_collected`` note (a previous collection failure), clear it "
            "in the same pass** — call mureo_state_platform_not_collected_set "
            "with ``reason`` omitted; this call preserves the note rather "
            "than guessing that one window's rollup means the platform "
            "recovered. Returns the updated state document."
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
                        "``ga4``), a platform an installed plugin registered "
                        "(its provider name), or a plugin bridge "
                        "``plugin:<dist>:<provider>``. Use the SAME key the "
                        "account is already stored under — one ad account has "
                        "exactly one platform key, and a second key for an "
                        "account another key already holds is REJECTED (the "
                        "reporting view sums the entries, so it would "
                        "double-count). A NEW key that is none of the three "
                        "is REJECTED too: do not invent or abbreviate a "
                        "platform name."
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
                        "preserve the existing value. ``fetched_at`` (ISO "
                        "8601) is stamped with the write time when you leave "
                        "it out — or send it null/blank; supply a real one "
                        "only for figures pulled at some other time."
                    ),
                },
                "metrics_period": {
                    "type": "string",
                    "enum": _METRICS_WINDOWS,
                    "description": (
                        "The window ``totals`` covers — the only windows "
                        "mureo reports on. " + METRICS_WINDOW_RULE + " Omit "
                        "to preserve the existing value."
                    ),
                },
                "periods": {
                    "type": "object",
                    "properties": {
                        window: dict(_PERIOD_BUCKET_PROPERTY)
                        for window in _METRICS_WINDOWS
                    },
                    "additionalProperties": False,
                    "description": (
                        "Per-window rollups keyed by period token; each value "
                        "is a totals-shaped object. The keys are the same "
                        "closed set as ``metrics_period``, under the same "
                        "rule: any other key is refused, never rounded onto a "
                        "neighbouring window. Merged per key into the "
                        "existing map. Omit to preserve the existing map. "
                        "Each bucket you pass without a ``fetched_at`` is "
                        "stamped with the write time; a bucket this call "
                        "merely preserves is never re-stamped."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["platform", "account_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_platform_daily_set",
        description=(
            "Add DAY-GRAIN history to a platform in STATE.json's v2 "
            "``platforms`` section, keyed by calendar date — the trend line "
            "and day-over-day delta the reporting dashboard cannot show from "
            "the window rollups alone. Distinct from "
            "mureo_state_platform_metrics_set, which holds ONE rollup per "
            "window (YESTERDAY / LAST_7_DAYS / LAST_30_DAYS) and overwrites "
            "it on every collection, so the value it replaces is gone; this "
            "map accumulates instead, merged PER DATE KEY. Re-writing a day "
            "replaces that day only, and every other stored day survives. "
            "**Write the daily rows you already fetched** (the delivery "
            "report a health check pulls) — never fire an extra platform API "
            "call to fill this in. **A day you did not collect is OMITTED, "
            "never written as zeros**: a zero-filled day is indistinguishable "
            "from an account that stopped spending, and the readers render a "
            "gap as a gap. **Only complete PAST days are accepted** — today "
            "is still being spent into, and half a day filed as a day is a "
            "false low forever, because nothing revisits a day already in the "
            "map. Each bucket you pass without a usable ``fetched_at`` is "
            "stamped with the write time; a day this call merely preserves is "
            "never re-stamped. mureo keeps the most recent "
            f"{DAILY_RETENTION_DAYS} days and drops older ones on write. "
            "Campaigns, the window rollups, the conversion override, any "
            "``not_collected`` note and every other platform are preserved. "
            "Returns the updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    # No enum: see mureo_state_platform_metrics_set.
                    "minLength": 1,
                    "description": (
                        "Platform key: a built-in (``google_ads`` / "
                        "``meta_ads`` / …), a platform an installed plugin "
                        "registered, or ``plugin:<dist>:<provider>``. Use the "
                        "SAME key the account is already stored under."
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
                "days": {
                    "type": "object",
                    # Date keys cannot be enumerated the way window tokens
                    # can, so the shape is stated as a pattern over the
                    # property NAMES. It fires at the dispatcher, before this
                    # tool's handler runs, so the RULE is spelled out in the
                    # description below — a caller who only ever sees the
                    # JSON-Schema refusal ("does not match '^\\d{4}-...'")
                    # learns the shape and none of the reasoning.
                    "propertyNames": {"pattern": DAILY_DATE_KEY_PATTERN},
                    "additionalProperties": dict(_DAILY_BUCKET_PROPERTY),
                    "minProperties": 1,
                    "description": (
                        "Day-grain rollups keyed by calendar date in "
                        "**YYYY-MM-DD** (zero-padded — ``2026-08-05``, not "
                        "``2026-8-5``), one key per day, each value a "
                        "totals-shaped object. Any other key shape is "
                        "refused. Every key must be a day that has ENDED: "
                        "today and any later date are refused, because a "
                        "part-spent day stored as a whole one is a false low "
                        "nothing ever corrects. Pass only the days you "
                        "actually collected — omit a day you have no figures "
                        "for rather than sending zeros for it. Merged per "
                        "date key into the stored history."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["platform", "account_id", "days"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_platform_not_collected_set",
        description=(
            "Record WHY a platform's figures could not be collected — or "
            "CLEAR that note once collection succeeds again. Without it, "
            '"not collected" and "collected, and the answer was zero" are the '
            "same STATE.json, so an operator looking at a card whose numbers "
            "have not moved cannot tell a stopped ad account from a stopped "
            "collector, and has nothing to act on. Call this when a sync / "
            "daily-check fails for one platform (expired token, permissions "
            "error, API outage) INSTEAD of writing zeros: the stored figures "
            "are left untouched, because they are still the last ones truly "
            "collected — this note says they were not UPDATED, never that "
            "they are wrong. ``attempted_at`` is stamped by the server — do "
            "not compute it. **Omit ``reason`` (or send null / blank) to "
            "CLEAR the note, and do that on the very next successful "
            "collection**: nothing else retires it, and a note that outlives "
            "its failure is permanently stale information stated with "
            "confidence. Campaigns, rollups, the conversion override and "
            "every other platform are preserved, and ``last_synced_at`` is "
            "NOT re-stamped (a failed collection is not a sync). Returns the "
            "updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    # No enum: see mureo_state_platform_metrics_set.
                    "minLength": 1,
                    "description": (
                        "Platform key: a built-in (``google_ads`` / "
                        "``meta_ads`` / …), a platform an installed plugin "
                        "registered, or ``plugin:<dist>:<provider>``. Use the "
                        "SAME key the account is already stored under."
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
                "reason": {
                    "type": "string",
                    "description": (
                        "What happened, in words an operator can act on — "
                        '"the Meta access token expired", "the sync did not '
                        'run". Not a stack trace: it is rendered on the '
                        "client card, and long text is truncated. Omit / null "
                        "/ blank CLEARS the note."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["platform", "account_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="mureo_state_workspace_not_collected_set",
        description=(
            "Record WHY THIS WHOLE WORKSPACE could not be collected — or "
            "CLEAR that note once a collection succeeds again. Use this when "
            "the run failed BEFORE any platform was reached (no credentials, "
            "the workspace could not be opened, the collector never ran), "
            "which is exactly when there is no platform key and no account id "
            "to name: this tool asks for neither. Use "
            "mureo_state_platform_not_collected_set instead when ONE "
            "platform failed and others were collected — the two are "
            "different facts calling for different actions, and neither is "
            "written as the other. Nothing else in the document is touched: "
            "the platforms, their own notes and every stored figure are left "
            "as they were, because they are still the last ones truly "
            "collected. ``attempted_at`` is stamped by the server — do not "
            "compute it. **Omit ``reason`` (or send null / blank) to CLEAR "
            "the note, and do that on the very next successful collection**: "
            "a note that outlives its failure is permanently stale "
            "information stated with confidence. ``last_synced_at`` is NOT "
            "re-stamped (a failed collection is not a sync). Returns the "
            "updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "What happened, in words an operator can act on — "
                        '"the credentials file could not be read", "the '
                        'nightly collection did not run". Not a stack trace: '
                        "it is rendered on the client card, and long text is "
                        "truncated. Omit / null / blank CLEARS the note."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": [],
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
                        "it would double-count). A NEW key naming no platform "
                        "mureo knows is REJECTED too."
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
    "mureo_state_display_set": handle_state_display_set,
    "mureo_state_platform_metrics_set": handle_state_platform_metrics_set,
    "mureo_state_platform_daily_set": handle_state_platform_daily_set,
    "mureo_state_platform_not_collected_set": handle_state_platform_not_collected_set,
    "mureo_state_workspace_not_collected_set": (
        handle_state_workspace_not_collected_set
    ),
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
