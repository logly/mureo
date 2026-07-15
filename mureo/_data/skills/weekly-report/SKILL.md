---
name: weekly-report
description: "Generate a weekly summary report across all platforms. Use when the user asks for a weekly report, summary, recap, end-of-week review, or weekly digest. Also use when the user asks in Japanese (週次レポート / 今週のまとめ / 週報を作成して)."
metadata:
  version: 0.10.26
---

# Weekly Report

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Generate a weekly marketing operations report.

## Prerequisites
- STRATEGY.md with Goals (run the `onboard` skill first)
- STATE.json with action_log (actions must have been logged during the week)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

1. **Load context**: Read STRATEGY.md and STATE.json.

2. **Discover platforms**: Identify all configured platforms and available data sources — built-in, `mcp__mureo__<plugin>_*` plugin platforms, and any **hosted official-MCP connector** present in the session (e.g. TikTok's `tt-ads-*` tools, key `tiktok_ads`). See `../_mureo-shared/SKILL.md` → *Plugin platforms* and *Hosted-connector platforms*; pull a hosted connector's numbers from its own reporting tools and omit mureo-only value-adds.

3. **Period**: Determine the reporting period (last 7 days from today).

4. **Goal progress**: For each Goal, pull performance data from the relevant platforms:
   - **Google Ads**: prefer mureo native `google_ads_performance_report` (with `period: "LAST_7_DAYS"` then `period: "LAST_14_DAYS"` and subtract the first 7 from the next 7 for previous-week comparison). If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP's equivalent performance-report tool over the same two windows and perform the WoW subtraction the same way.
   - **Meta Ads**: prefer mureo native `meta_ads_insights_report` similarly. When summing Meta "results" across campaigns, group by `result_indicator` — never aggregate `link_click` totals together with `pixel_lead` totals (PR #61). If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for the raw insights over the same two windows; the official MCP does not surface a `result_indicator` field, so you must inspect each campaign's optimization goal / actions list yourself and avoid aggregating `link_click`-optimized totals with `offsite_conversion.fb_pixel_lead`-optimized totals — note this caveat in the report.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.
   - Show week-over-week change for each Goal metric. If GA4 is available, include website-level metrics (sessions, conversion rate, revenue) for a holistic view.

5. **Actions taken**: Read `action_log` from STATE.json, filter to the reporting period.
   Present as a timeline:
   | Date | Command | Action | Platform | Summary |
   |------|---------|--------|----------|---------|

6. **Impact assessment**: For each action taken, evaluate impact using the relevant platform's trend/analysis tools. Cross-reference with GA4 data if available to validate on-site impact.
   - Example: "Added 5 negative keywords on Mon → CPA decreased 8% by Thu"
   - Example: "Shifted 20% budget to Platform A on Tue → impressions increased 15%"

7. **Cross-platform insights**:
   - Compare performance across platforms (CPA, CVR, ROAS)
   - Identify platforms gaining or losing efficiency
   - If Search Console data is available, include organic search trend summary (clicks, impressions, CTR WoW change) and paid/organic keyword overlap changes
   - Suggest cross-platform shifts if one platform significantly outperforms others toward Goal achievement

8. **Next week recommendations**:
   - Based on Goal trajectory, suggest focus areas
   - Recommend specific commands to run (`/rescue`, `/budget-rebalance`, `/creative-refresh`, `/goal-review`)
   - Suggest Operation Mode change if appropriate (e.g., "Goals on track — consider switching from TURNAROUND_RESCUE to EFFICIENCY_STABILIZE")

9. **Evidence pipeline**: Include an evidence assessment section:
   - List actions with `observation_due` dates that passed this week — evaluate their outcomes by comparing `metrics_at_action` with current metrics
   - List actions still in observation — note them as "pending, do not draw conclusions"
   - Rate confidence in reported improvements: low (< 1 week data), medium (1 observation period), high (2+ consistent periods)
   - Do NOT present pending observations as confirmed wins

10. **Present report** in a structured format suitable for sharing with stakeholders:
    - Executive summary (2-3 sentences)
    - Goal progress table
    - Cross-platform performance comparison
    - Key actions and their impact (with confidence level)
    - Evidence pipeline summary
    - Recommendations for next week

11. **Log to action_log** in STATE.json that a weekly report was generated, including the reporting period.

12. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="weekly"` and a concise `summary` object so the read-only dashboard can render this report without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run
    - `period`: the reporting window (e.g. `"LAST_7_DAYS"` or an explicit date range)
    - `kpis`: per-platform and/or totals headline numbers (spend, conversions, cpa, week-over-week change)
    - `flags`: a list of notable items (e.g. `["meta_ads_cpa_up_15pct"]`)
    - `narrative`: the 2-3 sentence executive summary

    This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
