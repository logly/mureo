---
name: ad-fatigue-check
description: "Detect creative fatigue across active ads — rising frequency, declining CTR week-over-week, and CPM drift — score each ad FATIGUED / WATCH / FRESH, and hand the evidence to a creative refresh. Use when the user asks whether creatives are worn out, why CTR is falling, if frequency is too high, when to rotate or refresh ads, or requests クリエイティブ疲弊チェック / 広告の疲弊を確認 / フリークエンシーが高い / CTRが落ちてきた / そろそろ差し替え時か. Reads active ads per platform, applies documented fatigue thresholds with noise guards, and routes fatigued ads to /creative-generate or /creative-refresh."
metadata:
  version: 0.10.35
---

# Ad Fatigue Check

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Find the ads whose audience has seen them too many times. Creative fatigue is a slow leak — the same creative keeps spending while frequency climbs, CTR erodes, and CPM drifts up as the algorithm works harder to place a tiring ad. This skill reads active ads per platform, measures the fatigue signals the tools genuinely expose, scores each ad against documented thresholds (with noise guards so a single slow day never triggers a rotation), and hands the fatigued ones to a creative refresh with the evidence attached.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

0. **Establish today**: call `mureo_state_get` **first, on every host** (including Claude Code, where you would otherwise `Read` the file) and take `server_now` from its response — ISO 8601 with UTC offset, e.g. `2026-07-28T10:12:33+09:00`. Its date is the **only source of the current date** for this run: the `observation_due` you write in step 9 is `server_now`'s date + 14 days. (The week-over-week windows in step 3 are platform-side period tokens — `last_7d` / `LAST_7_DAYS` — so the platform resolves those against its own clock; do not hand-build date ranges for them.) Do not shell out (this skill must run in Bash-less headless hosts) and do not read the date off STATE.json — `last_synced_at`, `reports.*.period` and `action_log` timestamps are **history**, never evidence of what day it is now. **Never write `server_now` into STATE.json**: it is a response field, and a persisted copy becomes tomorrow's stale "today".

1. **Load context**: Read STRATEGY.md (Goals, Operation Mode) and STATE.json. Note any learning insights about fatigue thresholds — a VALIDATED insight ("this account tolerates frequency 5 before CTR drops") **overrides** the default rubric in step 4.

2. **Discover active ads per platform** — **not running is not fatigued**, on every platform. Before scoring anything, exclude each ad whose delivery-status field (`effective_status` when the platform reports one, otherwise `status`) is not that platform's active value, and **say so rather than scoring it**: a stopped ad has no fatigue to measure, and its soft numbers are the stop, not a worn-out creative. This exclusion is platform-independent — the bullets below only say which tool and which value each platform uses.
   - **Meta**: `meta_ads_ads_list`, and keep only ads whose `effective_status` is `ACTIVE` — that is the field that says an ad is really delivering. An ad can read `status: ACTIVE` while its `effective_status` is `PAUSED` / `ADSET_PAUSED` / `CAMPAIGN_PAUSED` / `DISAPPROVED`, and it is `effective_status` that decides. In BYOD mode this response is wrapped as `{"source": "byod_import", "as_of": <import time>, "data": [...]}` — take the rows from `data` and treat them as of `as_of`, not as live.
   - **Google Ads**: `google_ads_ad_performance_report` scoped to ENABLED ads.
   - Also include any **hosted connector** (TikTok, key `tiktok_ads`) / `mcp__mureo__<plugin>_*` plugin platform best-effort, reporting only what its own tools expose and emitting `analytics_not_available_for_<platform>` for the fatigue value-adds below — `<platform>` being the canonical platform key (`plugin:<dist>` for a plugin, `tiktok_ads` for the connector), never an analytics `registry_name` (see `../_mureo-shared/SKILL.md` → *Canonical platform key*). BYOD data is reachable only through mureo MCP tools — do not look for raw CSVs in the project directory.

3. **Measure fatigue signals — honestly, per what the tools expose**:
   - **Meta — frequency (derived, not a direct field).** mureo's insights tools do **not** return a `frequency` field — but `meta_ads_insights_report` returns both **`impressions`** and **`reach`**, and frequency is defined as impressions ÷ reach. Compute it yourself from `meta_ads_insights_report` (level `ad`, window `last_7d`): `frequency ≈ impressions / reach`. This is Meta's own definition, so it is an honest derivation, not a guess. If `reach` is 0 or absent for an ad, the frequency is undefined — say so, do not divide.
   - **Meta — CTR trend, week-over-week.** `meta_ads_insights_report` (level `ad`) exposes `ctr` but no built-in trend. Get two adjacent weeks the same way weekly-report does: pull `last_7d` (this week) and `last_14d`, then derive the prior week as **`last_14d` totals − `last_7d` totals**. Compute the CTR change % between prior-week and this-week.
   - **Meta — CPM drift.** `meta_ads_insights_report` returns `cpm`; compare this-week vs prior-week CPM (same subtraction technique). Rising CPM on a flat audience is a fatigue corroborator. `meta_ads_analysis_cost` also decomposes a campaign's cost change into CPM inflation / CTR drop / **creative fatigue** drivers — use it to corroborate at campaign level.
   - **Google Ads (Display / RSA whole-ad).** Ad-level CTR trend from `google_ads_ad_performance_report` over adjacent windows (`LAST_7_DAYS` vs `LAST_14_DAYS`, same subtraction); Google Ads exposes **no frequency** at the ad level here, so score Google display/RSA ads on the **CTR-trend signal only** and say so.
   - **Google Ads Search — RSA fatigue is asset-level, not ad-level.** A Responsive Search Ad tires one asset at a time; whole-ad CTR hides it. Reference the RSA audit tools instead: `google_ads_rsa_assets_audit` (replacement recommendations) and `google_ads_rsa_assets_analyze` (per-asset `performance_label` + CTR) to find LOW/POOR assets to swap.

4. **Fatigue scoring rubric** (document the thresholds; let learning insights override them):
   - **FATIGUED** — frequency **≥ 3.5** **AND** CTR decline **≥ 20% week-over-week** (both signals present).
   - **WATCH** — exactly **one** signal present (frequency ≥ 3.5 alone, or CTR decline ≥ 20% alone, or a clear rising-CPM + softening-CTR pair).
   - **FRESH** — neither signal.
   These are defaults, not laws — a VALIDATED learning insight for this account/Persona replaces them, and Google display/RSA ads (no frequency) can reach **WATCH** on CTR decline alone but not the two-signal **FATIGUED** bar unless corroborated by CPM drift.

5. **Noise guards (apply before assigning any verdict)**:
   - **Minimum impressions per window**: require **≥ 1,000 impressions in each** of the two adjacent windows before reading a CTR trend (the CTR sample floor from `../_mureo-learning/SKILL.md`). Below that, the ad is **insufficient-data**, not fatigued.
   - **Single-day dips never count** — the comparison is week-over-week on 7-day windows precisely so one bad Tuesday cannot trigger a rotation.
   - **Learning-state noise is not fatigue.** An ad whose ad set is in its Meta learning phase (new, or recently reset by a significant edit), or whose Google Ads bid strategy shows "Learning", has unstable delivery by design — soft CTR and drifting CPM there are the learning window, not a worn-out creative. Mark those **insufficient-data / re-check after the window**, never FATIGUED, and do not rotate creative on that basis (a creative swap resets the phase again). See `../_mureo-pro-diagnosis/SKILL.md` → *Allocation & Learning-State Discipline*.
   - Note confounders: a new competitor, a seasonal lull, or a landing-page change can mimic fatigue — flag them rather than blaming the creative.

6. **Ranked table** — worst first:

   | Ad | Campaign | Frequency | CTR w/w | CPM w/w | Impr (this/prior) | Verdict |
   |----|----------|-----------|---------|---------|-------------------|---------|
   | Ad A | Prospecting | 4.2 | −27% | +14% | 32k / 30k | FATIGUED |
   | Ad B | Retargeting | 3.6 | −8% | +3% | 18k / 17k | WATCH |
   | Ad C | Brand | 1.8 | −4% | +1% | 21k / 20k | FRESH |

7. **Recommendations — rotate / refresh, with the evidence as the brief**: For each FATIGUED (and borderline WATCH) ad, hand off to a creative workflow, passing the fatigue evidence (frequency, CTR decline, the tiring asset) as the input brief:
   - **New visuals + composed banners** → **`/creative-generate`**.
   - **Copy / headline refresh, RSA asset swaps** → **`/creative-refresh`**.
   Do not silently produce new creative here — this skill diagnoses and routes; the creative skills generate under their own approval gates.

8. **Pausing a clearly-fatigued ad — approval gate**: Pausing is a write. Apply the *Confirm Before Write Operations* rule from `../_mureo-shared/SKILL.md`: list the ad(s), their current spend/frequency/CTR, and confirm before pausing via `meta_ads_ads_pause` (Meta) or `google_ads_ads_update_status` (Google Ads). Prefer **rotate-in-a-replacement over pause-into-a-gap** unless the ad is actively harmful — pausing without a fresh creative ready starves delivery. Never bulk-pause without listing the total impact first.

9. **Record outcome context**: For each ad paused or queued for refresh, append to `action_log` via `mureo_state_action_log_append` with `metrics_at_action` (frequency, ctr, cpm, impressions, conversions, cpa) and `observation_due` **14 days** out from `server_now`'s date (the creative-change window from `../_mureo-learning/SKILL.md`). A pure diagnostic run with no writes still logs a summary entry (the verdict table), with no `observation_due`.

10. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="fatigue"` and a concise `summary` object so the read-only dashboard can render this check without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run — use `server_now`
    - `period`: the two adjacent windows compared (this week / prior week)
    - `kpis`: counts by verdict (fatigued / watch / fresh / insufficient-data) and the worst-frequency + worst-CTR-decline ads
    - `flags`: notable items (e.g. `["3_ads_fatigued", "meta_reach_missing_frequency_undefined", "google_display_ctr_only"]`)
    - `narrative`: the 1-2 sentence verdict (creatives fresh / rotation needed)

    **Reflect the FINAL state, and persist this LAST** — after every `action_log` entry and any pause you applied this run. This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
