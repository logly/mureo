---
name: weekly-report
description: "Generate a weekly summary report across all platforms. Use when the user asks for a weekly report, summary, recap, end-of-week review, or weekly digest. Also use when the user asks in Japanese (週次レポート / 今週のまとめ / 週報を作成して)."
metadata:
  version: 0.13.0
---

# Weekly Report

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Generate a weekly marketing operations report.

## Prerequisites
- STRATEGY.md with Goals (run the `onboard` skill first)
- STATE.json with action_log (actions must have been logged during the week)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

0. **Establish today**: call `mureo_state_get` **first, on every host** (including Claude Code, where you would otherwise `Read` the file) and take `server_now` from its response — ISO 8601 with UTC offset, e.g. `2026-07-28T10:12:33+09:00`. Its date is the **only source of the current date** for this run: it fixes the 7-day reporting window in step 3, which `action_log` entries fall inside it, and every observation-window comparison below. Do not shell out (this skill must run in Bash-less headless hosts) and do not read the date off STATE.json — `last_synced_at`, `reports.*.period` and `action_log` timestamps are **history**, never evidence of what day it is now. **Never write `server_now` into STATE.json**: it is a response field, and a persisted copy becomes tomorrow's stale "today".

1. **Load context**: Read STRATEGY.md and STATE.json (the same `mureo_state_get` response from step 0 on MCP hosts).

2. **Discover platforms**: Identify all configured platforms and available data sources — built-in, `mcp__mureo__<plugin>_*` plugin platforms, and any **hosted official-MCP connector** present in the session (e.g. TikTok's `tt-ads-*` tools, key `tiktok_ads`). See `../_mureo-shared/SKILL.md` → *Plugin platforms* and *Hosted-connector platforms*; pull a hosted connector's numbers from its own reporting tools and omit mureo-only value-adds.

3. **Period**: Determine the reporting period — the last 7 days ending on `server_now`'s date from step 0, never on a date inferred from STATE.json.

4. **Goal progress**: For each Goal, pull performance data from the relevant platforms:
   - **Google Ads**: prefer mureo native `google_ads_performance_report` (with `period: "LAST_7_DAYS"` then `period: "LAST_14_DAYS"` and subtract the first 7 from the next 7 for previous-week comparison). If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP's equivalent performance-report tool over the same two windows and perform the WoW subtraction the same way.
   - **Meta Ads**: prefer mureo native `meta_ads_insights_report` similarly. When summing Meta "results" across campaigns, group by `result_indicator` — never aggregate `link_click` totals together with `pixel_lead` totals (PR #61). If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for the raw insights over the same two windows; the official MCP does not surface a `result_indicator` field, so you must inspect each campaign's optimization goal / actions list yourself and avoid aggregating `link_click`-optimized totals with `offsite_conversion.fb_pixel_lead`-optimized totals — note this caveat in the report.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.
   - **Auth failure is not data — it is a hole in the report.** Any tool result carrying `"status": "auth_error"` means mureo could not read that platform for this period at all: `auth_cause` is `no_credentials` (nothing is configured) or `token_invalid` (a credential exists and the platform rejected it — typically an expired token), and `detail` is the operator-facing sentence. **Never render `detail` where a metric belongs, and never read that platform's missing or empty numbers as "quiet"** — unreadable and quiet are different facts. Record the platform name with its `auth_cause` and carry both into steps 10 and 12, then keep going for every other platform: one platform's credentials failing degrades the report, it never aborts the run.
   - Show week-over-week change for each Goal metric. If GA4 is available, include website-level metrics (sessions, conversion rate, revenue) for a holistic view.
   - **A partial week is not comparable to a complete one.** A platform that answered `auth_error` contributes nothing to *either* window — the same credential failed both pulls — so its week-over-week line is **unknown**, not flat and not a decline: render it as unread with its `auth_cause`, never as `0`, never as `-100%`, never as a blank cell a reader fills in as zero. And never set a cross-platform or blended total computed **without** that platform beside a prior week's total that **included** it, whether that prior total comes from the previous `reports.weekly` `kpis` or from a fresh pull: that arithmetic manufactures a decline out of a credential problem, and this report is quoted onward. Either restate both weeks over the **same set of platforms** that answered this week — and label the total with that set — or withhold the comparison and name the platform whose absence blocks it.

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
   - List actions with `observation_due` dates that passed this week — "this week" is the step-3 window derived from `server_now`, so compare each `observation_due` against `server_now`'s date, never against another `action_log` timestamp — then evaluate their outcomes by comparing `metrics_at_action` with current metrics
   - List actions still in observation — note them as "pending, do not draw conclusions"
   - Rate confidence in reported improvements: low (< 1 week data), medium (1 observation period), high (2+ consistent periods)
   - Do NOT present pending observations as confirmed wins

10. **Present report** in a structured format suitable for sharing with stakeholders:

    **Partial report — this goes FIRST, above the executive summary.** If any platform came back `"status": "auth_error"` in step 4, this report is **partial**: open it by saying so, naming each affected platform with its `auth_cause` and the recovery (`no_credentials` → configure the credential via `mureo configure` / `mureo auth setup`; `token_invalid` → re-authorize, the credential is present and dead). Then **withhold every goal-progress verdict, week-over-week comparison and recommendation that depends on that platform's numbers** — an unreadable platform has no performance to judge, and cross-platform advice (budget shifts, "scale here, cut there") derived only from the platforms that did answer is not the advice you would give with all of them. Report the platforms that did answer as usual, and make clear which is which. Because this report is shared with stakeholders and its totals get quoted onward, the partial marking must appear in the executive summary itself, not only in a footnote.

    - Executive summary (2-3 sentences)
    - Goal progress table
    - Cross-platform performance comparison
    - Key actions and their impact (with confidence level)
    - Evidence pipeline summary
    - Recommendations for next week

11. **Log to action_log** in STATE.json that a weekly report was generated, including the reporting period.

12. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="weekly"` and a concise `summary` object so the read-only dashboard can render this report without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run — use `server_now`
    - `period`: the reporting window from step 3 (e.g. `"LAST_7_DAYS"` or an explicit date range ending on `server_now`'s date)
    - `totals`: the account's headline figures, using the canonical metric vocabulary — `spend`, `conversions`, `cpa`, `ctr`, `clicks`, `impressions`. This is the block the dashboard renders **as figures**. **Raw numbers only**: `773957`, not `"¥773,957"`; `0.0466`, not `"4.66%"` — one of those keys carrying a string is refused, because it sits where the view reads a figure and renders as nothing. A key outside the vocabulary may ride along: it is stored, just not shown as a headline number. Omit `totals` entirely if this run gathered no account-level figures.
    - `kpis`: the per-platform split (spend, conversions, cpa, week-over-week change) — the breakdown, not the headline row
    - `flags`: a list of **structured** flags — each a small object `{code, severity, params}` so the dashboard renders a coarse, localizable chip with the numbers on drill-down:
        - `code`: a canonical vocabulary key — one of `goals_met`, `cpa_over_target`, `cpa_under_target`, `cv_below_target`, `cv_above_target`, `spend_spike`, `cpa_spike`, `invalid_traffic_suspected`, `zero_cv_adspots`, `budget_overspend`, `budget_drift`, `tracking_suspect`, `zero_conversions`, `supply_tools_unconfigured`, `anomaly_baseline_insufficient`, `pending_observations`, `search_console_no_property`, `ga4_not_configured`.
        - `severity`: one of `action`/`watch`/`info`/`positive` (omit to take the code's default — `info`/`positive` keep informational and good-news flags visually distinct from alarms).
        - `params`: an object holding the DETAIL (platform, yen, cpa, week-over-week change). Keep detail in `params`, **NOT baked into the code** — write `{"code":"cpa_over_target","params":{"cpa":15200}}`, never a slug like `meta_ads_cpa_up_15pct`.
        - For a finding outside the vocabulary use `{code:"custom", severity, label}` where `label` is a string or a `{"ja":…,"en":…}` map. Unknown non-`custom` codes are rejected. (A legacy bare-string flag still works but renders without the drill-down — prefer the object form.)
        - Example: `[{"code":"cpa_over_target","params":{"cpa":15200}}, {"code":"goals_met"}]`
    - `narrative`: the executive summary — the verdict and what you propose next, **at most 400 characters** — the tool refuses a longer one rather than truncating it (a sentence cut in half is worse than a long one). Do not restate the figures and do not list the findings here: numbers belong in `totals`, findings in `flags`.

    **Never persist a number you did not read.** For a platform that came back `"status": "auth_error"`, omit its `kpis` entry entirely rather than writing `0` — this rollup is the baseline the NEXT weekly run compares against, so a fabricated zero turns one week's credential problem into two weeks of phantom movement. Omit it from the blended totals too, or label those totals with the platforms they cover. Record the partial read as a flag — `{"code":"custom","severity":"action","label":"<platform> not read: <auth_cause>"}` — which is where a finding goes; the `narrative` states the verdict, not the list.

    This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
