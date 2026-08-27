---
name: rescue
description: "Emergency performance fix when an ad account is in trouble. Use when the user reports a sudden CPA spike, conversion drop, runaway spend, or asks for an urgent performance rescue. Sets Operation Mode to TURNAROUND_RESCUE and applies stabilization actions. Also use when the user asks in Japanese (CPAが急に悪化した / CVが激減した / 広告費が暴走している / 緊急で立て直して)."
metadata:
  version: 0.16.0
---

# Rescue

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Run an emergency performance rescue workflow for underperforming campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.


0. **Establish today**: call `mureo_state_get` **first, on every host** (including Claude Code, where you would otherwise `Read` the file) and take `server_now` from its response — ISO 8601 with UTC offset, e.g. `2026-07-28T10:12:33+09:00`. Its date is the **only source of the current date** for this run: the `observation_due` you write in step 10 is `server_now`'s date + 7 or 14 days, and "how long has this been going on?" is measured from it. Do not shell out (this skill must run in Bash-less headless hosts) and do not read the date off STATE.json — `last_synced_at`, `reports.*.period` and `action_log` timestamps are **history**, never evidence of what day it is now. **Never write `server_now` into STATE.json**: it is a response field, and a persisted copy becomes tomorrow's stale "today".

1. **Load context**: Read STRATEGY.md (including Goal sections and Data Sources) and STATE.json (the same `mureo_state_get` response from step 0 on MCP hosts). Set Operation Mode to `TURNAROUND_RESCUE` in STRATEGY.md.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`. Also include any **hosted official-MCP connector** present in the session (e.g. TikTok, key `tiktok_ads`) — drive it via its own tools and skip mureo-only value-adds; see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

3. **Diagnose: platform-side or site-side?** (if GA4 is available): Before making ad changes, check if the performance problem is platform-side or site-side. If LP conversion rates dropped in GA4 too, the issue may be the landing page, not the ads. Recommend LP investigation before ad changes.

4. **Identify problem campaigns across all platforms**: For each configured ad platform:
   - **Analytics-module check (external integrations only)**: For every external-integration platform (plugin or official MCP), call `mureo_analytics_modules_list` first. When the platform's module advertises `detect_anomalies`, run it via `mureo_analytics_run` (`capability: detect_anomalies`, with `window_days`) and fold the structured `result` into the rescue summary; a non-`ok` `status` means treat it as unavailable. Otherwise emit `analytics_not_available_for_<platform>` in the rescue summary rather than fabricating heuristics from the integration's tool schemas (Issue #120).
   - **Google Ads**: prefer mureo native — call `google_ads_health_check_all` (eligibility / serving issues — meaningful only with Live API; returns `[]` in BYOD), then iterate campaigns from `google_ads_campaigns_list` and call `google_ads_monitoring_zero_conversions` and `google_ads_cost_increase_investigate` per campaign_id, plus `google_ads_campaigns_diagnose` for structural issues. If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP for the campaign list and performance numbers, then **skip the mureo-only anomaly-detection tools** (`google_ads_health_check_all`, `google_ads_monitoring_zero_conversions`, `google_ads_cost_increase_investigate`, `google_ads_campaigns_diagnose`) with a note: "anomaly detection and structural diagnostics require mureo's native MCP — install or re-enable via `mureo setup claude-code` for full rescue coverage." Identify zero-conversion / high-spend campaigns manually from the raw performance numbers in that case.
   - **Meta Ads**: prefer mureo native `meta_ads_insights_report` and inspect each campaign's `result_indicator` (PR #61): a `link_click`-optimized campaign with high "results" but zero `pixel_lead` is a tracking issue, not a creative one — flag for measurement fix before any rescue action. If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for raw insights; note that `result_indicator`-based CV-definition analysis is a mureo-specific value-add and will not be present — manually inspect the insights actions list for `link_click` vs `offsite_conversion.fb_pixel_lead` mismatches.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.

4b. **Delivery collapse — when a campaign stopped serving rather than got worse.** Use this branch when impressions or spend went to (or near) zero while the campaign's status still says ENABLED / ACTIVE. It is a different problem from a CPA spike and needs a different path: there is nothing to optimise, something is blocking delivery.

   1. **Confirm it.** Run the detector rather than eyeballing a chart: `mureo_analytics_run` with `capability="detect_delivery_collapse"` on Google Ads / Meta Ads, or `analysis_delivery_collapse_check` with day-grain rows for any other platform (see `/daily-check` step 4 for the row shape). It reports the cliff date and the baseline the campaign fell from — you need both. If it reports **no** collapse, this is an efficiency problem, not a delivery one: go back to step 4.
   2. **Build the change × metric timeline.** Gather what changed in the days before the cliff — `google_ads_change_history_list` for Google Ads, `action_log` entries for the campaign on every platform, and any change feed the platform itself offers — then call **`analysis_delivery_collapse_diagnose`** with the same rows, the `campaign_id`, and those `changes`. The tool treats the 3 days before the cliff as "immediately before"; widen `change_lookback_days` when you suspect a cause with a delayed effect (a billing hold or a policy review can stop delivery days after the change that caused it). Changes outside the window still appear on the timeline — only the `changes_before_cliff` shortlist narrows.
   3. **Walk the elimination ladder** and feed each result back in as `evidence`. The tool's `next_checks` names the mureo tool for each open step (Google Ads: `google_ads_ads_policy_details`, `google_ads_budget_get`, `google_ads_auction_insights_get`, `google_ads_campaigns_diagnose`, `google_ads_campaigns_get`; Meta: `meta_ads_ads_list`, `meta_ads_campaigns_get`, `meta_ads_ad_sets_get`). An empty tool string means **mureo has no tool for that step** — check it in the platform UI and supply the answer, or record it as `unavailable`. Report each step as `implicated` / `ruled_out` / `unavailable` / `inconclusive`, with the evidence in `detail`. Only report what you actually checked: a step you did not run comes back as an open question, which is the honest state.
   4. **Report the cause AND the open questions.** Take the tool's verdict as given. `confidence: undetermined` with `most_likely_cause: null` means *nobody knows yet* — say that, list the `unresolved` items and the `limitations`, and do NOT nominate a cause the evidence does not support. This is the common outcome, not a failure of the workflow: a real week-long, two-campaign outage was worked with full API access and never closed. Several things no read API on any platform exposes — serving-side suppression, billing state, learning-phase internals — are in `limitations` for exactly this reason.
   5. **Then act.** Fix an implicated cause directly. When nothing is implicated, escalate to platform support with the timeline and the ruled-out list attached, and treat a rebuild as the **last** resort — it destroys the evidence and the learning history along with the problem. Log whatever you do to `action_log` per step 10 so the next collapse has a change axis to read.

5. **Evaluate severity against Goals**: For each problem campaign, reference Goal targets from STRATEGY.md:
   - Calculate how far off the campaign is from the Goal
   - Prioritize rescue actions by impact on Goal achievement
   - Flag campaigns that are the biggest blockers to reaching Goals

6. **Search term cleanup** (for platforms that support search term data):
   - Review search terms for waste on each problem campaign
   - Cross-reference with Persona from STRATEGY.md — flag terms that don't match target audience
   - If Search Console is available, identify terms better served by organic
   - Suggest negative keywords to add
   - **Ask for my approval before adding any negative keywords**

7. **Budget efficiency**: Analyze budget efficiency across all platforms. Identify campaigns wasting budget (high spend, low/zero conversions). Suggest budget reallocation from wasteful to efficient campaigns.
   - **Ask for my approval before changing any budgets**

8. **Platform-specific optimizations**: For each platform, run the platform's specialized analysis (device performance, placement analysis, audience analysis, etc.) on problem campaigns. Suggest specific optimizations.
   - **Ask for my approval before making changes**

9. **Execute approved actions**: Only after I approve each recommendation, execute the changes using each platform's update tools.

10. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CPA, conversions, clicks, cost, impressions) and `observation_due` (from `server_now`'s date: 7 days for budget changes, 14 days for keyword/creative changes).

11. **Update STATE.json**: Record all changes made in campaign notes with timestamps. Log all rescue actions to the `action_log` with platform, action type, and expected impact.

12. **Summary**: List all changes made per platform with expected impact on Goal metrics.

IMPORTANT: Never make changes without explicit approval. Present each action as a recommendation first. Do NOT trigger rescue based on a single bad day — at least 7 consecutive days of critical metrics (>30% off target) before recommending rescue actions.
