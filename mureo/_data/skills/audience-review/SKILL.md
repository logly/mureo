---
name: audience-review
description: "Audit who your ads actually target and where they run, compare it against the STRATEGY.md Persona, and surface exclusions, bid adjustments, lookalikes, and placement pruning tied to that Persona. Use when the user asks to review targeting, audiences, demographics, placements, or device performance, to check whether spend matches the Persona, to find wasted placements (e.g. Audience Network with no conversions), or requests オーディエンスレビュー / 配置レビュー / ターゲティング見直し / ペルソナと配信のズレを確認 / 除外設定を提案して. Reads Persona + Target Audience from STRATEGY.md and drives the read-only targeting tools."
metadata:
  version: 0.10.22
---

# Audience Review

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Reconcile **who you say you want** (the STRATEGY.md Persona / Target Audience) with **who you are actually paying to reach** (the live targeting and the segments where spend lands). Accounts drift: a broad audience quietly spends on a segment the Persona excludes, a placement like Audience Network burns budget with zero conversions, or the Persona implies a lookalike that was never built. This skill inventories current targeting, scores performance by segment, flags the mismatches, and proposes Persona-anchored changes.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

1. **Load context**: Read STRATEGY.md — especially the **Persona** and **Target Audience** (age, gender, interests, geography, device intent, exclusions the Persona implies) and each Goal's success metric — and STATE.json. The Persona is the yardstick for every judgement below; if STRATEGY.md has no Persona, say so and offer to capture one via `/onboard` rather than inventing demographics.

2. **Discover platforms**: Identify configured platforms from STATE.json `platforms`. Also include any **hosted official-MCP connector** in the session (e.g. TikTok, key `tiktok_ads`) and `mcp__mureo__<plugin>_*` plugin platforms — for those, report only the targeting surface their own tools expose and emit `analytics_not_available_for_<platform>` for the segment-scoring value-adds below; do not fabricate targeting verdicts from an integration's tool schemas (see `../_mureo-shared/SKILL.md` → *Plugin platforms* / *Hosted-connector platforms*).

3. **Inventory current targeting — Google Ads** (prefer mureo native):
   - **Demographics**: `google_ads_demographic_targeting_list` — explicit age / gender / parental-status / income criteria and their `negative` (excluded) flag. Remember an **empty result means "all demographics, no exclusions"**, not "nothing targeted" — segments with no explicit criterion are targeted by default.
   - **Audiences**: `google_ads_audience_targeting_list` — affinity / in-market interests, remarketing & customer-match user lists, custom / combined audiences, with their `negative` flag.
   - **Devices**: `google_ads_device_analyze` for per-device (Desktop / Mobile / Tablet) spend, CPA, CVR and its built-in insights, plus `google_ads_device_targeting_get` / `google_ads_bid_adjustments_get` for the current device bid modifiers in place.
   - If mureo's Google Ads tools are unavailable (`MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP for the targeting-listing surface it exposes; note the segment-scoring heuristics below still apply.

4. **Inventory current targeting — Meta Ads** (prefer mureo native):
   - **Custom Audiences**: `meta_ads_audiences_list` — id, name, subtype (WEBSITE / CUSTOM / LOOKALIKE / …), approximate_count, retention_days.
   - **Ad-set targeting**: `meta_ads_ad_sets_list` — each ad set's `targeting_summary`, budget, and optimization_goal (targeting lives at the ad-set level on Meta).
   - **Placement & segment analysis**: `meta_ads_analysis_placements` (per-placement spend / CPA / CTR with keep / exclude / scale recommendations) and `meta_ads_analysis_audience` (age × gender efficiency scoring). For raw slices use `meta_ads_insights_breakdown` with `breakdown` = `age,gender`, `publisher_platform`, `placement`, or `device_platform`.
   - If mureo's Meta tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for its targeting / breakdown surface, and self-apply the guardrail/confirm rules yourself.

5. **Performance by segment**: For each platform, pull the demographic / placement / device breakdowns the tools support (step 3–4) and compute spend, conversions, CPA, and CVR per segment. Respect sample-size discipline from `../_mureo-learning/SKILL.md` — a segment with a handful of clicks is not evidence of "poor CVR"; note thin segments as *insufficient data*, not as waste.

6. **Mismatch analysis vs Persona**: Cross-read the segment table against the Persona and flag three failure shapes:
   - **Contradicts the Persona**: a segment spending meaningfully with poor CVR that the Persona did *not* call for (e.g. a 55–64 bucket eating budget when the Persona is 25–34) — a candidate exclusion or negative bid.
   - **Missing what the Persona implies**: a high-intent segment the Persona describes that has **no** targeting or lookalike behind it — a coverage gap.
   - **Placement waste**: a placement with spend and **zero (or far-below-average) conversions** — classically Audience Network / Search Partners — that is diluting the average.

7. **Recommendations table** — each row tied to a Persona/Goal rationale (do not execute yet):

   | Platform | Segment / Placement | Current | Signal | Recommendation | Persona/Goal rationale |
   |----------|---------------------|---------|--------|----------------|------------------------|
   | Meta | Audience Network | on, ¥18k spend | 0 conv | Exclude placement | Persona converts on IG Feed; AN is waste |
   | Google | Mobile | +0% modifier | CPA 1.8× Desktop | −20% device bid | Protect Goal CPA |
   | Meta | (Persona lookalike) | none | — | Create 1% LAL of purchasers | Persona = past-buyer profile |

   Recommendation types: **exclusions**, **bid adjustments**, **lookalike creation**, **placement pruning**. Reference past `action_log` outcomes — if a device bid adjustment was previously REJECTED as no-impact, note that before proposing it again.

8. **Approval gate before ANY write**: Apply the *Confirm Before Write Operations* rule from `../_mureo-shared/SKILL.md` — show current-vs-proposed for every change and get explicit **approval**. Respect Operation Mode and `## Guardrails`; a targeting change during `ONBOARDING_LEARNING` / `CREATIVE_TESTING` is discouraged — warn and ask before proceeding.

9. **Execute — only the mutations mureo actually supports; everything else is an honest manual step**:
   - **Google Ads device bid adjustments**: `google_ads_bid_adjustments_update` (bid_modifier 0.1–10.0; use `google_ads_device_targeting_set` to toggle a device fully on/off at 0.0).
   - **Meta lookalike creation**: `meta_ads_audiences_create_lookalike` (source_audience_id, country, ratio 0.01–0.20).
   - **Meta ad-set targeting edits** (add an exclusion, narrow a facet, swap an audience): `meta_ads_ad_sets_update` with a `targeting` object — by default it is a safe read-modify-write (supplied keys merge onto the current spec; omitted keys preserved); set `replace_targeting` true only to replace the whole spec.
   - **Google Ads demographic/audience criterion add/exclude and Meta placement exclusions** have **no dedicated mureo mutation tool** — present these as a **manual step in the platform UI** (exact segment + action), honestly, rather than referencing a tool that does not exist. Do not fabricate a `*_targeting_update` for demographics/audiences.

10. **Record outcome context**: For each change executed, append to `action_log` via `mureo_state_action_log_append` with `metrics_at_action` (the segment's current spend / conversions / cpa / cvr / reach) and `observation_due` **14 days** out (the targeting-change window from `../_mureo-learning/SKILL.md`), so daily-check's evidence step verifies the change helped. A pure audit with no changes still logs a summary entry (findings + mismatch table), with no `observation_due`.

11. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="audience"` and a concise `summary` object so the read-only dashboard can render this review without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run
    - `period`: the window analysed (e.g. `"LAST_30_DAYS"`)
    - `kpis`: per-platform segment counts (targeted / excluded) and the worst-CPA segments vs Persona
    - `flags`: notable items (e.g. `["meta_audience_network_zero_conv", "google_mobile_cpa_1.8x", "persona_lookalike_missing"]`)
    - `narrative`: the 1-2 sentence verdict (targeting matches Persona / drift found)

    **Reflect the FINAL state, and persist this LAST** — after every `action_log` entry and any change you applied this run. This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.
