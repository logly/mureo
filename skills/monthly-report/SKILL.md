---
name: monthly-report
description: "Stakeholder / client-facing monthly digest across all configured platforms: the previous full calendar month with month-over-month comparison, per-Goal attainment, an action-log recap grouped by command with outcome verdicts, budget utilization, and next-month recommendations. Use when the user asks for a monthly report, month-end summary, client report, monthly recap / digest, or requests 月次レポート / 月次まとめ / クライアント向けレポート. Written in plain language for a client audience."
metadata:
  version: 0.10.23
---

# Monthly Report

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Generate a client-facing monthly marketing operations report. This mirrors `/weekly-report` but over a calendar month, with month-over-month comparison, a goal-attainment verdict, and language written for the **client/stakeholder** who receives it — not internal shorthand.

## Prerequisites
- STRATEGY.md with Goals (run the `onboard` skill first)
- STATE.json with action_log (actions must have been logged during the month)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

1. **Load context**: Read STRATEGY.md (Goals, Operation Mode, Persona, any `## Custom: Monthly Budget`) and STATE.json.

2. **Discover platforms**: Identify all configured platforms and available data sources — built-in, `mcp__mureo__<plugin>_*` plugin platforms, and any **hosted official-MCP connector** present in the session (e.g. TikTok's `tt-ads-*` tools, key `tiktok_ads`). See `../_mureo-shared/SKILL.md` → *Plugin platforms* and *Hosted-connector platforms*; pull a hosted connector's numbers from its own reporting tools and omit mureo-only value-adds.

3. **Reporting window**: Default to the **previous full calendar month**. If the user explicitly asks for a mid-month / month-to-date view, use MTD instead — and **state clearly at the top of the report which window it is** (a partial month is not comparable to a full one).
   - **Previous full month**: Google Ads `google_ads_performance_report` with `period="LAST_MONTH"`; Meta Ads `meta_ads_insights_report` with `period="last_month"`.
   - **Month-to-date** (only when explicitly asked): Google Ads `period="THIS_MONTH"`; Meta Ads `period="this_month"`. Label it "MTD (through <date>)".
   - Native-preferred with official fallback: if mureo's Google Ads / Meta Ads tools are unavailable (`MUREO_DISABLE_GOOGLE_ADS=1` / `MUREO_DISABLE_META_ADS=1` after `mureo providers add …-official`), fall back to the official `google-ads-official` / `meta-ads-official` MCP over the equivalent window; note that mureo-only value-adds (`result_indicator` CV-mismatch) are absent from the official surface.

4. **Month-over-month (MoM) comparison** — the reporting month vs the month **before** it, using only windows the tools genuinely support (same honesty rule as the period above):
   - **Meta Ads**: `meta_ads_insights_report` supports an explicit `'YYYY-MM-DD..YYYY-MM-DD'` range, so pull the month-before with its exact date range and compare against `last_month`. A true Meta MoM is available.
   - **Google Ads**: `google_ads_performance_report`'s `period` is a **fixed enum** (`LAST_MONTH`, `THIS_MONTH`, `LAST_30/90_DAYS`, …) with **no custom date range and no "month-before-last" preset**. So a native Google Ads figure for the month-before-last is **not directly available**. Use, in order: (a) STATE.json's persisted prior-month rollup (`platforms[<p>].periods[...]`) or the previous monthly report's `kpis` (from `mureo_state_report_set` history) as the MoM baseline; (b) if neither exists, **state that the Google Ads MoM comparison is unavailable this month** rather than mislabel `LAST_90_DAYS` (a 3-month blend) as "the prior month". Never silently substitute a different window.
   - Show MoM change (absolute and %) for spend, conversions, CPA, and CTR per platform.

5. **Goal attainment summary (the month)**: For each Goal in STRATEGY.md, gather the month's metric from the relevant platforms / data sources and render a **met / missed / partial** verdict *with the numbers*:
   ```
   Goal: CPA < 5,000        -- Met      (Google 4,600 / Meta 4,900; blended 4,720)
   Goal: CV >= 100/month    -- Partial  (Google 71 / Meta 24; total 95, 95% of target)
   Goal: Organic clicks +20% -- Missed  (Search Console +11%)
   ```

6. **Actions taken — month recap grouped by command**: read `action_log`, filter to the reporting month, and **group by the command / skill that produced each entry** (`daily-check`, `budget-rebalance`, `rescue`, `creative-refresh`, `budget-pacing`, …). For each group summarize what was done and how often:
   | Command | # actions | What changed | Platforms |
   |---------|-----------|--------------|-----------|

7. **Outcome verdicts (evidence pipeline)**: for `action_log` entries whose `observation_due` window **closed within or before this month**, call `mureo_outcome_evaluate` with `before` = the entry's `metrics_at_action` and `after` = the current metrics for the same campaign — it returns a deterministic **improved / regressed / inconclusive** verdict per metric and overall. Report each action's outcome with the confidence it implies (low: <1 period, medium: 1 period, high: 2+ consistent periods). For entries **still within** their observation window, list them as "pending — not yet conclusive" and do **not** present them as wins. Normalize any hosted-connector / plugin metric names to the standard keys (`cpa`, `conversions`, `ctr`, `cost`, …) before scoring. When summing Meta "results" across campaigns, group by `result_indicator` — never aggregate `link_click` totals with `offsite_conversion.fb_pixel_lead` totals (PR #61).

8. **Budget utilization**: if a `## Custom: Monthly Budget` section exists in STRATEGY.md, compare **actual month spend vs the monthly target** (total and per-platform sub-targets) and report utilization %. Cross-link **`/budget-pacing`** for the in-month trajectory view and for landing-forecast mechanics. If no Monthly Budget section exists, report actual spend per platform and note that no monthly target is configured.

9. **Cross-platform insights**: compare the month's efficiency across platforms (CPA, CVR, ROAS); call out which platform gained or lost efficiency MoM; if Search Console is available, include the organic search trend (clicks, impressions, CTR MoM) and paid/organic overlap shifts; suggest cross-platform shifts if one platform is clearly outperforming toward Goal achievement.

10. **Next-month recommendations**:
    - Based on Goal trajectory, name the focus areas for next month.
    - Recommend specific commands to run (`/rescue`, `/budget-rebalance`, `/budget-pacing`, `/creative-refresh`, `/goal-review`).
    - **Operation Mode suggestion**: recommend a mode for next month if the data supports a change (e.g. "Goals met and stable — consider `TURNAROUND_RESCUE` → `EFFICIENCY_STABILIZE`"), with the reason.

11. **Executive summary — written for the CLIENT**: lead the report with a 3-5 sentence executive summary in **plain language for an agency's client audience**. No internal jargon, no tool names, no mode codenames — translate them ("we tightened targeting to protect your cost-per-lead", not "ran `/rescue`, switched to TURNAROUND_RESCUE"). State the headline result, whether goals were met, and the one thing to watch next month.

12. **Present the report** in a structured, shareable layout:
    - Executive summary (client-facing, plain language)
    - Reporting window (and whether full-month or MTD)
    - Goal attainment table (met / missed / partial)
    - Cross-platform performance with MoM comparison
    - Key actions and their outcomes (with confidence level)
    - Budget utilization (if a Monthly Budget is configured)
    - Recommendations for next month

    This report is **read-only — it never mutates platform state**. If a recommendation calls for a change, run the relevant skill (`/rescue`, `/budget-rebalance`, `/budget-pacing`), which applies its own **approval gate** and confirms with the operator before any write; monthly-report itself only reads and summarizes.

13. **Log to action_log** (via `mureo_state_action_log_append`) that a monthly report was generated, including the reporting month.

14. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="monthly"` and a concise `summary` object so the read-only dashboard can render this report without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run
    - `period`: the reporting month (e.g. `"2026-06"`), and whether full-month or MTD
    - `kpis`: per-platform + totals headline numbers (spend, conversions, cpa, MoM change)
    - `flags`: notable items (e.g. `["cv_goal_missed", "meta_cpa_up_12pct_mom"]`)
    - `narrative`: the client-facing executive summary (plain language)

    **Reflect the FINAL state, and persist this LAST.** This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
