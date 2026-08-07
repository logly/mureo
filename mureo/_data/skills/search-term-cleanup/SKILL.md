---
name: search-term-cleanup
description: "Audit and clean up search terms (negative keywords, intent classification, query hygiene). Use when the user asks to clean up search queries, add negative keywords, review search term reports, or improve match quality. Cross-references Search Console, GA4, and ad platform data. Also use when the user asks in Japanese (検索語句のクリーンアップ / 除外キーワードを追加して / 無駄な検索クエリを止めたい)."
metadata:
  version: 0.10.43
---

# Search Term Cleanup

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Review and clean up search terms and keywords across all platforms.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.


0. **Establish today**: call `mureo_state_get` **first, on every host** (including Claude Code, where you would otherwise `Read` the file) and take `server_now` from its response — ISO 8601 with UTC offset, e.g. `2026-07-28T10:12:33+09:00`. Its date is the **only source of the current date** for this run: the `observation_due` you write in step 11, and every "is a previous action still inside its observation window?" check in step 9, are measured from it. Do not shell out (this skill must run in Bash-less headless hosts) and do not read the date off STATE.json — `last_synced_at`, `reports.*.period` and `action_log` timestamps are **history**, never evidence of what day it is now. **Never write `server_now` into STATE.json**: it is a response field, and a persisted copy becomes tomorrow's stale "today".

1. **Load context**: Read STRATEGY.md (Persona, USP, Target Audience, Data Sources) and STATE.json (the same `mureo_state_get` response from step 0 on MCP hosts).

2. **Discover platforms**: Identify all configured platforms that support search term data from STATE.json `platforms`. Also include any **hosted official-MCP connector** present in the session (e.g. TikTok, key `tiktok_ads`) where it exposes search-term data — drive it via its own tools and skip mureo-only value-adds; see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

3. **Review search terms**: For each ad platform that supports search term data:
   - **Google Ads**: prefer mureo native — call `google_ads_search_terms_report` for the raw query rows, then `google_ads_search_terms_review` (rule-based scoring) and `google_ads_search_terms_analyze` (intent classification) per campaign. **These tools work in both Live API and BYOD mode.** In BYOD they read from `~/.mureo/byod/google_ads/search_terms.csv` (the Apps Script bundle output) — do **not** look for raw CSVs in the project directory; mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools. If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP's search-terms report tool for the raw rows, then **skip the mureo-only rule-based scoring and intent-classification tools** (`google_ads_search_terms_review`, `google_ads_search_terms_analyze`) and do the scoring/classification yourself using the rules described in step 6 below; note to the user that mureo's automated scoring is only available with the native MCP (install or re-enable via `mureo setup claude-code`).
   - **Meta Ads**: Skip — Meta is interest/audience-targeted and has no search-query data (this applies to both mureo native and the official Meta MCP).
   - Analyze N-gram patterns and user intent across the returned rows.

4. **Paid/organic cross-reference** (if Search Console is available):
   - Pull top organic queries for the site
   - Cross-reference with paid search terms to identify overlap
   - For terms ranking well organically (position 1-3), consider reducing paid bids or pausing paid keywords
   - For terms with strong paid performance but weak organic ranking, flag as SEO opportunity
   - Present a paid/organic overlap matrix

5. **Landing page quality check** (if GA4 is available): Check landing page performance for key search terms. Terms driving traffic to high-bounce-rate pages may need LP improvements rather than keyword changes.

6. **Score candidates** against strategy:
   - **Exclude candidates**: Terms with 0 conversions + high cost, informational-only queries, terms misaligned with Persona
   - **Add candidates**: High-converting terms not yet added as keywords, terms matching USP themes
   - **Reduce candidates**: Terms well-covered by organic rankings

   **Negative keywords are a marginal decision, not an average ranking.** Distinguish **systematic waste** — an n-gram or intent pattern that is wrong for the Persona at any volume, where a negative genuinely removes future spend — from a **low-volume term with a bad average**, where a handful of clicks and zero conversions is a sample-size fact, not evidence of waste. Excluding the long tail one term at a time mostly narrows match reach without saving meaningful spend. Prefer pattern-level negatives with a stated marginal saving; leave thin terms to accumulate. See `../_mureo-pro-diagnosis/SKILL.md` → *Allocation & Learning-State Discipline*.

7. **Present recommendations** in a table:
   | Term | Platform | Action | Reason | Score | Campaign |
   |------|----------|--------|--------|-------|----------|

   Group by platform and campaign. Show estimated cost savings from exclusions.

8. **Ask for approval**: Let me select which recommendations to apply.

9. **Check pending observations**: Before executing, check `action_log` for this campaign. If a previous action is still within its observation window, warn that stacking changes will make outcome evaluation difficult. Recommend waiting if possible.

10. **Open a batch**: call `mureo_batch_begin` with a `label` naming this pass (e.g. `"search-term cleanup 2026-08-07"`). A cleanup changes many entities across possibly several platforms, and the batch is what makes it one reviewable, plannable unit instead of a set of entries nobody can re-identify later. See `../_mureo-shared/SKILL.md` → *Bulk changes are one revertible unit*.

11. **Execute**: Use each platform's keyword management tools to apply approved changes (add negative keywords, add positive keywords, adjust bids).

12. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CPA, conversions, clicks, CTR, impressions, cost) and `observation_due` (14 days from `server_now`'s date). This enables evidence-based evaluation later. Keyword and negative-keyword changes are **not** auto-recorded, so this step is what puts them in the batch at all — an entry you do not append is invisible to any later revert.

13. **Close the batch**: call `mureo_batch_end` and report the returned `batch_id` and member count to the operator, so undoing this pass later is `rollback_plan_get` with that id rather than a reconstruction from memory.

14. **Update STATE.json** with notes about the cleanup.

IMPORTANT: Always explain WHY a term should be excluded/added, referencing the Persona or USP from STRATEGY.md. Consult past action_log entries — if a similar cleanup was previously evaluated, reference whether it was effective.
