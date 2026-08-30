---
name: goal-review
description: "Review Goal progress against STRATEGY.md targets. Use when the user asks to evaluate goal achievement, review KPI progress, assess strategy performance, or check if targets are being met. Also use when the user asks in Japanese (目標の進捗を確認 / KPIレビュー / ゴール達成状況は / 目標に届きそうか)."
metadata:
  version: 0.17.2
---

# Goal Review

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Review progress toward all marketing goals across all platforms.

## Prerequisites
- STRATEGY.md with at least one Goal section (run the `onboard` skill first)
- STATE.json (run `/sync-state` first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.


0. **Establish today**: call `mureo_state_get` **first, on every host** (including Claude Code, where you would otherwise `Read` the file) and take `server_now` from its response — ISO 8601 with UTC offset, e.g. `2026-07-28T10:12:33+09:00`. Its date is the **only source of the current date** for this run: every "days remaining until deadline" and required-pace calculation in step 4 is measured from it, so a stale date silently flips on-track / at-risk / off-track. Do not shell out (this skill must run in Bash-less headless hosts) and do not read the date off STATE.json — `last_synced_at`, `reports.*.period` and `action_log` timestamps are **history**, never evidence of what day it is now. **Never write `server_now` into STATE.json**: it is a response field, and a persisted copy becomes tomorrow's stale "today".

1. **Load context**: Read STRATEGY.md (all Goal sections, Data Sources) and STATE.json (the same `mureo_state_get` response from step 0 on MCP hosts).

2. **Discover platforms**: Identify all configured platforms and available data sources. Also include any **hosted official-MCP connector** present in the session (e.g. TikTok, key `tiktok_ads`) — drive it via its own tools and skip mureo-only value-adds; see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

3. **For each Goal**, gather current metrics from all relevant platforms and data sources:
   - Ad platforms: Use performance reporting tools for each platform
   - GA4 (if available): Website conversion data, user behavior metrics
   - Search Console (if available): Organic search metrics for SEO-related goals
   - CRM (if available): Lead quality, pipeline data for LTV-related goals

   For goals that span multiple data sources, synthesize a unified view. Example: "Total leads = Platform A 62 + Platform B 28 + Organic 15 = 105 total"

4. **Evaluate progress** for each Goal:
   - Compare current value against target
   - Calculate % of target achieved
   - Calculate days remaining until deadline — the Goal's `Deadline` minus `server_now`'s date
   - Assess trajectory: on-track / at-risk / off-track

5. **Present Goal dashboard**:
   | Goal | Target | Current | Progress | Deadline | Status |
   |------|--------|---------|----------|----------|--------|

   Status indicators:
   - On track — current value meets or exceeds the pace needed to hit target by deadline
   - At risk — current value is within 20% of target but trajectory is concerning
   - Off track — current value is more than 20% away from target pace

6. **Consult evidence**: Before recommending actions, check `action_log` for past actions with evaluated outcomes:
   - Reference validated findings when proposing similar actions ("Negative keyword cleanup has consistently improved CPA by 10-20% on this account")
   - Flag previously rejected actions ("Device bid adjustments had no significant impact in the last 2 attempts")
   - Do NOT attribute goal progress to specific actions without checking observation windows and sample sizes

7. **Recommend actions** for off-track Goals:
   - Tie recommendations to the specific platform(s) where the Goal is off-track
   - If cross-platform rebalancing could help, suggest it
   - Suggest specific commands to run (`/rescue`, `/budget-rebalance`, `/creative-refresh`)
   - Prioritize recommendations by Goal priority (P0 > P1 > P2)
   - Prefer actions backed by past validated evidence over unproven strategies

8. **Update STATE.json**:
   - Log the review to `action_log` with a summary of Goal statuses. **Give every entry a display line**: `display_title` (at most 40 characters) and `display_summary` (at most 120) — what this action WAS, in the operator's words, as plain text with no markdown (`**bold**` reaches a person as asterisks). The dashboard row shows those two and stops there; the full `summary` is drill-down only, so keep writing it as fully as the next agent needs and let the display line be the short one. Over either bound the append is refused, never truncated.
   - Update Current values in STRATEGY.md Goal sections if approved

9. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="goal"` and a concise `summary` object so the read-only dashboard can render this review without re-running you. Follow this convention:
   - `generated_at`: ISO 8601 timestamp of this run — use `server_now`
   - `period`: the assessment window or "as of" date — the "as of" date is `server_now`'s date
   - `totals`: the account's headline figures, using the canonical metric vocabulary — `spend`, `conversions`, `cpa`, `ctr`, `clicks`, `impressions`. This is the block the dashboard renders **as figures**. **Raw numbers only**: `773957`, not `"¥773,957"`; `0.0466`, not `"4.66%"` — one of those keys carrying a string is refused, because it sits where the view reads a figure and renders as nothing. A key outside the vocabulary may ride along: it is stored, just not shown as a headline number. Omit `totals` entirely if this run gathered no account-level figures.
   - `kpis`: per-Goal numbers (target, current, % of target achieved) — the breakdown, not the headline row
   - `flags`: a list of **structured** flags — each a small object `{code, severity, params}` so the dashboard renders a coarse, localizable chip with the numbers on drill-down:
       - `code`: a canonical vocabulary key — one of `goals_met`, `cpa_over_target`, `cpa_under_target`, `cv_below_target`, `cv_above_target`, `spend_spike`, `cpa_spike`, `invalid_traffic_suspected`, `zero_cv_adspots`, `budget_overspend`, `budget_drift`, `tracking_suspect`, `zero_conversions`, `supply_tools_unconfigured`, `anomaly_baseline_insufficient`, `pending_observations`, `search_console_no_property`, `ga4_not_configured`.
       - `severity`: one of `action`/`watch`/`info`/`positive` (omit to take the code's default — `info`/`positive` keep informational and good-news flags visually distinct from alarms).
       - `params`: an object holding the DETAIL (target, current, % of target). Keep detail in `params`, **NOT baked into the code** — write `{"code":"cpa_over_target","params":{"cpa":15200}}`, never a slug like `goal_cpa_off_track`.
       - For a finding outside the vocabulary use `{code:"custom", severity, label}` where `label` is a string or a `{"ja":…,"en":…}` map. Unknown non-`custom` codes are rejected. (A legacy bare-string flag still works but renders without the drill-down — prefer the object form.)
       - Example: `[{"code":"cpa_over_target","params":{"cpa":15200}}, {"code":"cv_below_target","params":{"cv":18}}]`
   - `narrative`: the overall Goal-health verdict (on-track / at-risk / off-track) and what you propose next, **at most 400 characters** — the tool refuses a longer one rather than truncating it (a sentence cut in half is worse than a long one). Do not restate the figures and do not list the findings here: numbers belong in `totals`, findings in `flags`.

   This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.

10. **Persist the display contract** (best-effort): Call `mureo_state_display_set` with what the DASHBOARD shows. This is a different audience from the summary above — STATE.json is written for the next agent, and this small bounded section is the only thing the operator's screen reads. Write it in the SAME pass as the report, from the SAME figures, and **reach no new verdict here**: every value below is one you already decided, and this step only renders it.
    - `source`: your own skill name — REQUIRED whenever you write any section, at most 24 characters. The contract is replaced wholesale by whoever writes it last, so this is what lets the card say whose answer it is showing. `generated_at` is stamped by the server — do not compute it.
    - `nav_message`: the ONE line the operator should act on today — the goal that needs attention, e.g. `"CPA goal is off track with 11 days left — cut the two worst ad groups"`. One line, not a summary of the report.
    - `highlights`: at most 3 chips, and the `tone` must match the verdict you already gave — `good` for a target met or a clear win, `watch` for something to keep an eye on, `bad` for something deteriorating. Choose the three that matter; a fourth is refused and nothing is dropped for you. Map a finding's severity to a chip tone: action → bad / watch → watch / positive → good. info does NOT become a highlight — a neutral note would spend one of the 3 chips an action or a win needed, and it is still in the report for whoever wants it.
    - `breakdown.campaigns` / `.adgroups`: one row per entity you judged, carrying figures you ALREADY hold — `spend`, `mcpa` (the measured CPA) and `target_cpa` — plus `state` from the closed set (`target_met` / `improving` / `watch` / `worsening` / `no_data`) and a `note` of at most 40 characters. Use `campaigns` for the campaigns carrying each goal and `adgroups` where you judged that level; a review that judged neither omits `breakdown` rather than inventing rows. **Omit a figure you do not have**: `0` states a perfect CPA rather than the absence of one, and `no_data` is the state for an entity with too little delivery to judge.
    - `proposals`: the recommendations you did NOT carry out, one entry each — `title` (what to do) plus `body` (why, in one line) plus `date` = `server_now`'s date as `YYYY-MM-DD`. Something you DID apply this run is the same entry with `status: "done"`.
    - `stated_values`: label + figure chips ONLY (`{"label": "…", "value": …}`) — the goal figures: `{"label": "goals on track", "value": "2 of 4"}`, `{"label": "days to deadline", "value": 11}`. **No prose notes here.** A sentence lands in a numeric column and the tool refuses it; anything that needs a sentence stays in the report's `narrative` above, exactly where it goes today.

    The bounds, verbatim from the tool: The dashboard reads THIS section and nothing else — keep your reasoning where it already goes. Every bound below refuses the write rather than truncating it, because a sentence cut in half is worse than a long one. nav_message: one line, at most 80 characters. highlights: at most 3 items of {tone, text}, tone one of good/watch/bad, text at most 60 characters. proposals: {title, body, status, date}, title at most 30 and body at most 80 characters, status one of proposed/done. breakdown.campaigns / breakdown.adgroups: rows of {name, spend, mcpa, target_cpa, state, note} — the three figures are raw numbers, state is one of target_met/improving/watch/worsening/no_data, note at most 40 characters. stated_values: {label, value}, label at most 24 characters and value a raw number or a string of at most 12 characters — a sentence there is refused, because it lands in a numeric column. Do NOT write the KPI funnel or the daily chart: mureo computes both from the stored totals.

    **Over a bound the write is REFUSED — shorten and rewrite, do not re-send the same sentence trimmed.** Lead with the point and drop the connectives; a noun phrase is fine (`CPA 12% over target`, not `The CPA is currently running about 12% above the target we agreed`). Trimming one character at a time and calling again spends the run's context on a bound one rewrite would have met.

    **You may not be the first writer today.** ``display`` is REPLACED WHOLE and the last writer wins — there is no merge. Before you write it, read the current one (``mureo_state_get``). Of what another skill wrote TODAY, carry exactly one thing into your own write: its ``proposals`` that are still live — not yet done, and not contradicted by what you just found. Everything else you write from your own run alone, because a screen assembled from two runs shows a moment that never happened. And carry over NOTHING ELSE: never copy another skill's ``nav_message``, ``highlights``, ``breakdown`` or ``stated_values``, which would put its judgement under your name when you cannot vouch for it. Name yourself in ``source`` so the screen says whose answer it is.

    This is best-effort: if `mureo_state_display_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.

IMPORTANT: When updating Goal "Current" values in STRATEGY.md, ask for approval first.
