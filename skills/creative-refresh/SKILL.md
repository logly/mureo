---
name: creative-refresh
description: "Refresh ad copy and creative assets based on performance signals and brand voice. Use when the user asks to refresh creative, propose new ad copy, A/B test creatives, update RSA assets, or rotate underperformers."
metadata:
  version: 0.7.1
---

# Creative Refresh

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Refresh ad creatives based on strategy context and performance data across all platforms.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

1. **Load context**: Read STRATEGY.md (Persona, USP, Brand Voice, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`.

3. **Audit current creatives**: For each ad platform:
   - **Google Ads**: Call `google_ads_ad_performance_report` per campaign, plus `google_ads_rsa_assets_audit` (per-asset CTR/CVR ratings) and `google_ads_rsa_assets_analyze` (LOW/POOR detection). In BYOD mode, the Apps Script bundle does not include per-asset ratings — these tools return `[]`; fall back to `google_ads_ads_list` for headline/description text and use `ad_performance.report` for ad-level CTR/conv only.
   - **Meta Ads**: Call `meta_ads_creatives_list`, `meta_ads_analysis_compare_ads`, and `meta_ads_analysis_suggest_creative`. In BYOD mode, creative URLs / headlines / body / CTA may be present in `~/.mureo/byod/meta_ads/creatives.csv` (best-effort, populated only when those columns were in the export).
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through MCP tools — do **not** look for raw CSVs in the project directory.
   - Identify underperforming assets (LOW/POOR ratings for search ads, low CTR/engagement for social ads).

4. **Analyze landing pages**: For each campaign's final URL, analyze the landing page to extract key selling points, CTAs, and features. If GA4 is available, pull engagement metrics (time on page, scroll depth, bounce rate) to inform creative direction.

5. **Organic keyword insights** (if Search Console is available): Incorporate top-performing organic search queries into ad copy. Terms that drive organic clicks likely resonate with users.

6. **Generate platform-appropriate creative recommendations**:
   Using Persona pain points + USP + LP selling points + Brand Voice rules, draft:
   - **Search ads**: Headlines and descriptions aligned with character limits and ad format requirements
   - **Social ads**: Primary text, headline, description, CTA suggestions
   - Consider platform-specific best practices and format requirements

   Each creative must:
   - Address a specific Persona pain point OR highlight a USP
   - Match the Brand Voice guidelines
   - Include keywords from top-performing search terms (paid and organic)

7. **Validate**: Run each through the relevant platform's ad validation rules (character limits, prohibited expressions, no duplicates).

8. **Present recommendations** with rationale for each. Group by platform.

9. **Ask for approval** before creating/updating any ads.

10. **Check pending observations**: Before executing, check `action_log` for campaigns being modified. If a previous creative change is still within its observation window, warn about stacking changes.

11. **Execute approved changes**: Use each platform's ad creation/update tools to apply changes.

12. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CTR, CPA, conversions, impressions, clicks) and `observation_due` (14 days from today).

13. **Update STATE.json** with notes.

IMPORTANT: Every headline/description must have a clear rationale tied to Persona, USP, or LP content. Never generate generic ad copy. Consult past action_log — if previous creative refreshes have evaluated outcomes, reference what worked.
