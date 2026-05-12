---
name: rescue
description: "Emergency performance fix when an ad account is in trouble. Use when the user reports a sudden CPA spike, conversion drop, runaway spend, or asks for an urgent performance rescue. Sets Operation Mode to TURNAROUND_RESCUE and applies stabilization actions."
metadata:
  version: 0.7.1
---

# Rescue

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Run an emergency performance rescue workflow for underperforming campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

1. **Load context**: Read STRATEGY.md (including Goal sections and Data Sources) and STATE.json. Set Operation Mode to `TURNAROUND_RESCUE` in STRATEGY.md.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`.

3. **Diagnose: platform-side or site-side?** (if GA4 is available): Before making ad changes, check if the performance problem is platform-side or site-side. If LP conversion rates dropped in GA4 too, the issue may be the landing page, not the ads. Recommend LP investigation before ad changes.

4. **Identify problem campaigns across all platforms**: For each configured ad platform:
   - **Google Ads**: prefer mureo native — call `google_ads_health_check_all` (eligibility / serving issues — meaningful only with Live API; returns `[]` in BYOD), then iterate campaigns from `google_ads_campaigns_list` and call `google_ads_monitoring_zero_conversions` and `google_ads_cost_increase_investigate` per campaign_id, plus `google_ads_campaigns_diagnose` for structural issues. If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP for the campaign list and performance numbers, then **skip the mureo-only anomaly-detection tools** (`google_ads_health_check_all`, `google_ads_monitoring_zero_conversions`, `google_ads_cost_increase_investigate`, `google_ads_campaigns_diagnose`) with a note: "anomaly detection and structural diagnostics require mureo's native MCP — install or re-enable via `mureo setup claude-code` for full rescue coverage." Identify zero-conversion / high-spend campaigns manually from the raw performance numbers in that case.
   - **Meta Ads**: prefer mureo native `meta_ads_insights_report` and inspect each campaign's `result_indicator` (PR #61): a `link_click`-optimized campaign with high "results" but zero `pixel_lead` is a tracking issue, not a creative one — flag for measurement fix before any rescue action. If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for raw insights; note that `result_indicator`-based CV-definition analysis is a mureo-specific value-add and will not be present — manually inspect the insights actions list for `link_click` vs `offsite_conversion.fb_pixel_lead` mismatches.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.

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

10. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CPA, conversions, clicks, cost, impressions) and `observation_due` (7 days for budget changes, 14 days for keyword/creative changes).

11. **Update STATE.json**: Record all changes made in campaign notes with timestamps. Log all rescue actions to the `action_log` with platform, action type, and expected impact.

12. **Summary**: List all changes made per platform with expected impact on Goal metrics.

IMPORTANT: Never make changes without explicit approval. Present each action as a recommendation first. Do NOT trigger rescue based on a single bad day — at least 7 consecutive days of critical metrics (>30% off target) before recommending rescue actions.
