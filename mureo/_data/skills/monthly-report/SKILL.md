---
name: monthly-report
description: "Stakeholder / client-facing monthly digest across all configured platforms: the previous full calendar month with month-over-month comparison, per-Goal attainment, an action-log recap grouped by command with outcome verdicts, budget utilization, and next-month recommendations. Use when the user asks for a monthly report, month-end summary, client report, monthly recap / digest, or requests 月次レポート / 月次まとめ / クライアント向けレポート. Written in plain language for a client audience."
metadata:
  version: 0.16.0
---

# Monthly Report

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Generate a client-facing monthly marketing operations report. This mirrors `/weekly-report` but over a calendar month, with month-over-month comparison, a goal-attainment verdict, and language written for the **client/stakeholder** who receives it — not internal shorthand.

## Prerequisites
- STRATEGY.md with Goals (run the `onboard` skill first)
- STATE.json with action_log (actions must have been logged during the month)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

0. **Establish today**: call `mureo_state_get` **first, on every host** (including Claude Code, where you would otherwise `Read` the file) and take `server_now` from its response — ISO 8601 with UTC offset, e.g. `2026-07-28T10:12:33+09:00`. Its date is the **only source of the current date** for this run, and this report is entirely calendar-driven: it decides which month is "the previous full month", the MTD cut-off date, the explicit `YYYY-MM-DD..YYYY-MM-DD` range you build for the month-before-last, and whether an `observation_due` window has closed. Do not shell out (this skill must run in Bash-less headless hosts) and do not read the date off STATE.json — `last_synced_at`, `reports.*.period` and `action_log` timestamps are **history**, never evidence of what day it is now; reporting a month late is exactly the failure this step prevents. **Never write `server_now` into STATE.json**: it is a response field, and a persisted copy becomes tomorrow's stale "today".

1. **Load context**: Read STRATEGY.md (Goals, Operation Mode, Persona, any `## Custom: Monthly Budget`) and STATE.json (the same `mureo_state_get` response from step 0 on MCP hosts).

2. **Discover platforms**: Identify all configured platforms and available data sources — built-in, `mcp__mureo__<plugin>_*` plugin platforms, and any **hosted official-MCP connector** present in the session (e.g. TikTok's `tt-ads-*` tools, key `tiktok_ads`). See `../_mureo-shared/SKILL.md` → *Plugin platforms* and *Hosted-connector platforms*; pull a hosted connector's numbers from its own reporting tools and omit mureo-only value-adds.

3. **Reporting window**: Default to the **previous full calendar month** — the month before `server_now`'s month, named from `server_now` and never inferred from a stored `reports.*.period`. If the user explicitly asks for a mid-month / month-to-date view, use MTD instead — and **state clearly at the top of the report which window it is** (a partial month is not comparable to a full one).
   - **Previous full month**: Google Ads `google_ads_performance_report` with `period="LAST_MONTH"`; Meta Ads `meta_ads_insights_report` with `period="last_month"`.
   - **Month-to-date** (only when explicitly asked): Google Ads `period="THIS_MONTH"`; Meta Ads `period="this_month"`. Label it "MTD (through <date>)" — that date is `server_now`'s date.
   - Native-preferred with official fallback: if mureo's Google Ads / Meta Ads tools are unavailable (`MUREO_DISABLE_GOOGLE_ADS=1` / `MUREO_DISABLE_META_ADS=1` after `mureo providers add …-official`), fall back to the official `google-ads-official` / `meta-ads-official` MCP over the equivalent window; note that mureo-only value-adds (`result_indicator` CV-mismatch) are absent from the official surface.

4. **Month-over-month (MoM) comparison** — the reporting month vs the month **before** it, using only windows the tools genuinely support (same honesty rule as the period above):
   - **Meta Ads**: `meta_ads_insights_report` supports an explicit `'YYYY-MM-DD..YYYY-MM-DD'` range, so pull the month-before with its exact date range — computed by stepping back two months from `server_now`'s month, not from any date found in STATE.json — and compare against `last_month`. A true Meta MoM is available.
   - **Google Ads**: `google_ads_performance_report`'s `period` is a **fixed enum** (`LAST_MONTH`, `THIS_MONTH`, `LAST_30/90_DAYS`, …) with **no custom date range and no "month-before-last" preset**. So a native Google Ads figure for the month-before-last is **not directly available**. Use, in order: (a) STATE.json's persisted prior-month rollup (`platforms[<p>].periods[...]`) or the previous monthly report's `kpis` (from `mureo_state_report_set` history) as the MoM baseline; (b) if neither exists, **state that the Google Ads MoM comparison is unavailable this month** rather than mislabel `LAST_90_DAYS` (a 3-month blend) as "the prior month". Never silently substitute a different window.
   - Show MoM change (absolute and %) for spend, conversions, CPA, and CTR per platform.
   - **Auth failure is not data — it is a hole in the report.** Any tool result carrying `"status": "auth_error"` in steps 3–4 means mureo could not read that platform for this month at all: `auth_cause` is `no_credentials` (nothing is configured) or `token_invalid` (a credential exists and the platform rejected it — typically an expired token), and `detail` is the operator-facing sentence. **Never render `detail` where a metric belongs, and never read that platform's missing or empty numbers as "quiet"** — unreadable and quiet are different facts. Record the platform name with its `auth_cause` and carry both into steps 11, 12 and 14, then keep going for every other platform: one platform's credentials failing degrades the report, it never aborts the run.
   - **A partial month is not comparable to a complete one** — the same rule the MTD window already carries in step 3, and it bites harder here. A platform that answered `auth_error` contributes nothing to *either* month — the same credential failed both pulls — so its MoM line is **unknown**, not flat and not a decline: render it as unread with its `auth_cause`, never as `0`, never as `-100%`, never as a blank cell a reader fills in as zero. The baseline in (a) is the sharp edge: STATE.json's persisted rollup and the previous monthly report's `kpis` were written when that platform *was* readable, so a MoM built from them sets a month missing a platform against a month that had it and manufactures a decline out of a credential problem — in a document a client reads. Either restate both months over the **same set of platforms** that answered this month, labelling the total with that set, or withhold the comparison and name the platform whose absence blocks it. Never silently substitute a differently-scoped figure.

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

    **Partial report — this goes FIRST, above the executive summary.** If any platform came back `"status": "auth_error"` in steps 3–4, this report is **partial**: open it by saying so, naming each affected platform with its `auth_cause` and the recovery (`no_credentials` → configure the credential via `mureo configure` / `mureo auth setup`; `token_invalid` → re-authorize, the credential is present and dead). Say it in the client's language too — "we could not read <platform> this month, so its figures are missing rather than zero" — since the step-11 summary is written for a non-technical reader who will otherwise take the gap for a result. Then **withhold every goal-attainment verdict, MoM comparison, budget-utilization line and recommendation that depends on that platform's numbers** — an unreadable platform has no performance to judge, and cross-platform advice (budget shifts, "scale here, cut there") derived only from the platforms that did answer is not the advice you would give with all of them. Report the platforms that did answer as usual, and make clear which is which.

    - Executive summary (client-facing, plain language)
    - Reporting window (and whether full-month or MTD)
    - Goal attainment table (met / missed / partial)
    - Cross-platform performance with MoM comparison
    - Key actions and their outcomes (with confidence level)
    - Budget utilization (if a Monthly Budget is configured)
    - Recommendations for next month

    This report is **read-only — it never mutates platform state**. If a recommendation calls for a change, run the relevant skill (`/rescue`, `/budget-rebalance`, `/budget-pacing`), which applies its own **approval gate** and confirms with the operator before any write; monthly-report itself only reads and summarizes.

13. **Log to action_log** (via `mureo_state_action_log_append`) that a monthly report was generated, including the reporting month. **Give every entry a display line**: `display_title` (at most 40 characters) and `display_summary` (at most 120) — what this action WAS, in the operator's words, as plain text with no markdown (`**bold**` reaches a person as asterisks). The dashboard row shows those two and stops there; the full `summary` is drill-down only, so keep writing it as fully as the next agent needs and let the display line be the short one. Over either bound the append is refused, never truncated.

14. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="monthly"` and a concise `summary` object so the read-only dashboard can render this report without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run — use `server_now`
    - `period`: the reporting month (e.g. `"2026-06"`), and whether full-month or MTD
    - `totals`: the account's headline figures, using the canonical metric vocabulary — `spend`, `conversions`, `cpa`, `ctr`, `clicks`, `impressions`. This is the block the dashboard renders **as figures**. **Raw numbers only**: `773957`, not `"¥773,957"`; `0.0466`, not `"4.66%"` — one of those keys carrying a string is refused, because it sits where the view reads a figure and renders as nothing. A key outside the vocabulary may ride along: it is stored, just not shown as a headline number. Omit `totals` entirely if this run gathered no account-level figures.
    - `kpis`: the per-platform split (spend, conversions, cpa, MoM change) — the breakdown, not the headline row
    - `flags`: notable items (e.g. `["cv_goal_missed", "meta_cpa_up_12pct_mom"]`)
    - `narrative`: the client-facing executive summary in plain language — the verdict and what you propose next, **at most 400 characters** — the tool refuses a longer one rather than truncating it (a sentence cut in half is worse than a long one). Do not restate the figures and do not list the findings here: numbers belong in `totals`, findings in `flags`.

    **Never persist a number you did not read.** For a platform that came back `"status": "auth_error"`, omit its `kpis` entry entirely rather than writing `0` — step 4(a) reads this rollup as NEXT month's MoM baseline, so a fabricated zero turns one month's credential problem into two months of phantom movement. Omit it from the blended totals too, or label those totals with the platforms they cover. Add a flag naming the partial read (e.g. `"partial_read_<platform>_<auth_cause>"`) and say so in `narrative`.

    **Reflect the FINAL state, and persist this LAST.** This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.

15. **Persist the display contract** (best-effort): Call `mureo_state_display_set` with what the DASHBOARD shows. This is a different audience from the summary above — STATE.json is written for the next agent, and this small bounded section is the only thing the operator's screen reads. Write it in the SAME pass as the report, from the SAME figures, and **reach no new verdict here**: every value below is one you already decided, and this step only renders it.
    - `source`: your own skill name — REQUIRED whenever you write any section, at most 24 characters. The contract is replaced wholesale by whoever writes it last, so this is what lets the card say whose answer it is showing. `generated_at` is stamped by the server — do not compute it.
    - `nav_message`: the ONE line the operator should act on today — what next month turns on, e.g. `"CPA improved 14% MoM — reinvest the saving in Brand Search"`. One line, not a summary of the report.
    - `highlights`: at most 3 chips, and the `tone` must match the verdict you already gave — `good` for a target met or a clear win, `watch` for something to keep an eye on, `bad` for something deteriorating. Choose the three that matter; a fourth is refused and nothing is dropped for you. Map a finding's severity to a chip tone: action → bad / watch → watch / positive → good. info does NOT become a highlight — a neutral note would spend one of the 3 chips an action or a win needed, and it is still in the report for whoever wants it.
    - `breakdown.campaigns` / `.adgroups`: one row per entity you judged, carrying figures you ALREADY hold — `spend`, `mcpa` (the measured CPA) and `target_cpa` — plus `state` from the closed set (`target_met` / `improving` / `watch` / `worsening` / `no_data`) and a `note` of at most 40 characters. Use `campaigns` for the month's campaigns and `adgroups` where you broke the month down that far. **Omit a figure you do not have**: `0` states a perfect CPA rather than the absence of one, and `no_data` is the state for an entity with too little delivery to judge.
    - `proposals`: the recommendations you did NOT carry out, one entry each — `title` (what to do) plus `body` (why, in one line) plus `date` = `server_now`'s date as `YYYY-MM-DD`. Something you DID apply this run is the same entry with `status: "done"`.
    - `stated_values`: label + figure chips ONLY (`{"label": "…", "value": …}`) — the month's headline comparisons: `{"label": "MoM CPA", "value": "-14%"}`, `{"label": "goals met", "value": "3 of 4"}`. **No prose notes here.** A sentence lands in a numeric column and the tool refuses it; anything that needs a sentence stays in the report's `narrative` above, exactly where it goes today.

    The bounds, verbatim from the tool: The dashboard reads THIS section and nothing else — keep your reasoning where it already goes. Every bound below refuses the write rather than truncating it, because a sentence cut in half is worse than a long one. nav_message: one line, at most 80 characters. highlights: at most 3 items of {tone, text}, tone one of good/watch/bad, text at most 60 characters. proposals: {title, body, status, date}, title at most 30 and body at most 80 characters, status one of proposed/done. breakdown.campaigns / breakdown.adgroups: rows of {name, spend, mcpa, target_cpa, state, note} — the three figures are raw numbers, state is one of target_met/improving/watch/worsening/no_data, note at most 40 characters. stated_values: {label, value}, label at most 24 characters and value a raw number or a string of at most 12 characters — a sentence there is refused, because it lands in a numeric column. Do NOT write the KPI funnel or the daily chart: mureo computes both from the stored totals.

    **Over a bound the write is REFUSED — shorten and rewrite, do not re-send the same sentence trimmed.** Lead with the point and drop the connectives; a noun phrase is fine (`CPA 12% over target`, not `The CPA is currently running about 12% above the target we agreed`). Trimming one character at a time and calling again spends the run's context on a bound one rewrite would have met.

    **You may not be the first writer today.** ``display`` is REPLACED WHOLE and the last writer wins — there is no merge. Before you write it, read the current one (``mureo_state_get``). Of what another skill wrote TODAY, carry exactly one thing into your own write: its ``proposals`` that are still live — not yet done, and not contradicted by what you just found. Everything else you write from your own run alone, because a screen assembled from two runs shows a moment that never happened. And carry over NOTHING ELSE: never copy another skill's ``nav_message``, ``highlights``, ``breakdown`` or ``stated_values``, which would put its judgement under your name when you cannot vouch for it. Name yourself in ``source`` so the screen says whose answer it is.

    This is best-effort: if `mureo_state_display_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
