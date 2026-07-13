---
name: budget-pacing
description: "Month-to-date spend vs the monthly budget target, projected month-end landing, and pace alerts across all configured platforms. Use when the user asks about pacing, burn rate, whether they will overspend or underspend this month, monthly-budget tracking, landing/forecast, 'are we on budget', or requests 予算ペーシング / 着地予測 / 予算消化ペース. DISTINCT from /budget-rebalance (which reallocates budget between campaigns) — this manages total-spend trajectory toward a monthly target. Reads STRATEGY.md Guardrails / a Monthly Budget section and STATE.json."
metadata:
  version: 0.10.23
---

# Budget Pacing

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Track month-to-date spend against the monthly budget target, project the month-end landing, and raise pace alerts so the month neither blows the budget nor leaves it unspent.

**This is trajectory management, not allocation.** If the question is *"how should I split budget across campaigns?"* that is `/budget-rebalance`. This skill answers *"at this rate, where does total spend land, and how do I steer it onto the target?"* — cross-reference `/budget-rebalance` when the fix is reallocation rather than a total-spend nudge.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

1. **Load context**: Read STRATEGY.md (Operation Mode, `## Guardrails`, any `## Custom: Monthly Budget` section, Goal sections) and STATE.json.

2. **Discover platforms**: Identify all configured platforms from STATE.json `platforms`. Also include any **hosted official-MCP connector** present in the session (e.g. TikTok, key `tiktok_ads`) and `mcp__mureo__<plugin>_*` plugin platforms — drive each via its own tools, best-effort; see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms* and *Plugin platforms*.

3. **Determine the monthly budget target** — in this precedence:
   - **`## Custom: Monthly Budget`** section in STRATEGY.md, if present — the operator's explicit monthly figure (and optional per-platform sub-targets). This wins; it is the intended monthly spend, not a safety ceiling.
   - **`## Guardrails` → `max_total_daily_budget`** — a daily ceiling. Multiply by the number of days in the current calendar month to derive an *implied* monthly cap. Treat this as a **ceiling, not a target** (it is the most you may spend per day, not the plan) — say so in the output, and prefer it only when no explicit Monthly Budget exists.
   - **Neither present** → **ask the operator** for the monthly budget target (total, and optionally per-platform). Offer to **persist** it as a new `## Custom: Monthly Budget` section so future pacing runs are self-serve, e.g.:
     ```markdown
     ## Custom: Monthly Budget
     - total: 300000
     - google_ads: 180000
     - meta_ads: 120000
     ```
     Persisting STRATEGY.md is a write — confirm before saving (Write / Edit on Code, `mureo_strategy_set` on Desktop / Cowork).

4. **Fetch month-to-date spend per platform** — use the **true month-to-date presets** the tools actually support (no approximation needed on the built-ins):
   - **Google Ads**: `google_ads_performance_report` with `period="THIS_MONTH"` — a real calendar-month-to-date window. If mureo's Google Ads tools are unavailable (`MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP's performance report over its equivalent month-to-date range.
   - **Meta Ads**: `meta_ads_insights_report` with `period="this_month"` — the equivalent MTD window. If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP over the same window.
   - **Hosted connector / plugin**: use the connector's own reporting tools. **If it has no true month-to-date preset, use the closest supported window and be explicit about the approximation** (e.g. "TikTok: last_30d used as an MTD proxy — overstates MTD early in the month"). **Never silently mislabel** a wider window as MTD.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only reachable through mureo MCP tools — do **not** look for raw CSVs in the project directory.

5. **Compute pacing** per platform and in total:
   - **MTD spend** — from step 4.
   - **Elapsed days** — completed days this month. **Exclude today**: today's numbers are a partial, still-accumulating day and would bias the run-rate downward. Daily run-rate = MTD spend ÷ elapsed (completed) days.
   - **Projected month-end landing** = MTD spend + run-rate × (days remaining, counting today forward).
   - **% vs target** = projected landing ÷ monthly target.

6. **Seasonality / confidence caution**: early-month run-rates are noisy — a single big-spend or zero-spend day swings the projection hard. When **fewer than 5 days have elapsed**, label the projection **low confidence** and lead with that caveat; prefer *watch* over *act*. Also note known intra-month seasonality from STRATEGY.md (e.g. a `## Custom` seasonal ramp, weekend dips) that makes a flat run-rate misleading.

7. **Pacing table** — per platform and a total row:
   | Platform | Monthly Target | MTD Spend | Run-rate/day | Projected Landing | % vs Target | Status |
   |----------|----------------|-----------|--------------|-------------------|-------------|--------|
   - **Status**: `on-pace` (projected within **±10 %** of target), `overpacing` (> +10 %, will overshoot), `underpacing` (< −10 %, will underspend). Carry the low-confidence flag from step 6 into the status when it applies.

8. **Recommendations to land on target** (do not execute yet):
   - Compute the daily-budget change that brings the projected landing back onto target: `required daily spend for the rest of the month = (monthly target − MTD spend) ÷ days remaining`, then translate to the per-campaign / per-platform daily-budget adjustment.
   - **Respect `## Guardrails`**: never propose a per-campaign daily budget above `max_daily_budget_per_campaign`, a raise beyond `max_daily_budget_increase_pct`, or a total above `max_total_daily_budget`. If landing on target would require breaching a guardrail, say so and stop at the guardrail — surface the conflict to the operator instead of proposing an illegal change.
   - **Smart-bidding learning warning**: flag any single budget change **> 20 %** — on Google Ads Smart Bidding / Meta CBO a large step can reset the learning phase. Prefer staged changes (e.g. two ≤ 20 % steps) when the required move is large.
   - **Hand off to `/budget-rebalance`** when the right move is shifting spend *between* campaigns/platforms (one overpacing + one underpacing) rather than changing the *total* — pacing sets the envelope; `/budget-rebalance` allocates within it.
   - **Mode guard**: if Operation Mode is `ONBOARDING_LEARNING` or `CREATIVE_TESTING`, warn that budget changes are discouraged in this mode and ask whether to proceed.

9. **Ask for approval** before any budget change. Before each budget mutation, retrieve and display the **current** value (`google_ads_budget_get`, or the campaign/ad-set record) alongside the proposed value and the % change (per the *Budget Changes Require Current Value Display* rule in `../_mureo-shared/SKILL.md`).

10. **Execute approved changes** with each platform's budget tools:
    - **Google Ads**: `google_ads_budget_update`.
    - **Meta Ads**: `meta_ads_campaigns_update` (CBO / campaign-level budget) or `meta_ads_ad_sets_update` (ad-set-level budget).
    - **Hosted / official / plugin writes**: self-apply the `## Guardrails` rules yourself first (mureo's PolicyGate does not see off-path calls) and confirm — see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

11. **Record outcome context**: for each campaign modified, log to `action_log` (via `mureo_state_action_log_append`) with `metrics_at_action` (current MTD spend, run-rate, daily budget, projected landing) and `observation_due` **7 days** from today, so daily-check's evidence step verifies the change actually bent the trajectory toward target.

12. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="pacing"` and a concise `summary` object so the read-only dashboard can render pacing without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run
    - `period`: the pacing month (e.g. `"2026-07"`) and elapsed/total days
    - `kpis`: per-platform + total `{monthly_target, mtd_spend, run_rate, projected_landing, pct_vs_target}`
    - `flags`: notable items (e.g. `["google_ads_overpacing_18pct", "low_confidence_early_month"]`)
    - `narrative`: the 1-2 sentence pacing verdict (on-pace / overpacing / underpacing, with confidence)

    **Reflect the FINAL state, and persist this LAST** — after every `action_log` entry and any budget change you applied this run. This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
