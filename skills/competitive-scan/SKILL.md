---
name: competitive-scan
description: "Scan competitor activity using auction insights and market signals. Use when the user asks about competitors, market dynamics, impression share changes, competitor moves, or competitive positioning."
metadata:
  version: 0.7.1
---

# Competitive Scan

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Scan the competitive landscape and suggest strategic responses across all channels.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

1. **Load context**: Read STRATEGY.md (Market Context, USP, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured platforms from STATE.json `platforms`.

3. **Paid competitive analysis**: For each ad platform that provides competitive/auction data:
   - **Google Ads**: prefer mureo native — call `google_ads_auction_insights_get` (raw impression-share / overlap rows) and `google_ads_auction_insights_analyze` (rule-based summary), then `google_ads_cpc_detect_trend` (CPC drift) and `google_ads_device_analyze` (device-level breakdown). **BYOD limitation**: Apps Script does not expose `auction_insight_domain` (GAQL) — auction insight tools return `[]` in BYOD mode. The remaining tools (CPC trend, device breakdown) work in BYOD against the bundle. If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP for auction insights and per-device performance queries (the official MCP exposes the GAQL surface, so raw auction-insights rows are obtainable when not blocked by the Apps Script limitation), then **skip the mureo-only analysis layers** (`google_ads_auction_insights_analyze`, `google_ads_cpc_detect_trend`, `google_ads_device_analyze`); perform the rule-based summary / CPC trend regression / device CPA-gap analysis yourself from the raw rows, and note: "mureo's automated competitive-analysis layers (rule-based auction summary, CPC trend regression, device CPA-gap detection) require the native MCP — install via `mureo setup claude-code` for full coverage."
   - **Meta Ads**: No direct competitor-share API on either side. Prefer mureo native — surface `meta_ads_analysis_placements` and `meta_ads_analysis_cost` to detect placement-level cost shifts that indicate competitive pressure. If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP's insights breakdown (e.g. by `publisher_platform` / `platform_position`) for the raw placement numbers, then **skip the mureo-only analysis tools** and infer placement-level competitive pressure yourself from cost-per-result trends; note that the mureo-specific placement and cost-trend analyses are not available in the fallback path.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.
   - Compare impression share, overlap rate, CPC trends, and device landscape across the returned data.

4. **Organic competitive landscape** (if Search Console is available):
   - Compare organic search performance trends (impressions, clicks, CTR, average position)
   - Identify queries where organic position is declining (potential competitor content gains)
   - Cross-reference paid auction competitors with organic ranking competitors
   - Present a unified paid + organic competitive picture

5. **On-site competitive signals** (if GA4 is available): Check referral traffic and direct/brand traffic trends. Declining brand search or direct traffic may indicate competitors capturing mind share.

6. **Compare with Market Context** from STRATEGY.md:
   - Are known competitors gaining share?
   - Are new competitors appearing?
   - Has the competitive landscape changed since STRATEGY.md was last updated?

7. **Noise guard**: Look at trends over 4+ weeks, not week-to-week changes. A single week's impression share dip is not a competitive threat — it may be seasonality or auction noise. Only flag competitive changes that are consistent over multiple weeks.

8. **Strategic recommendations**: Based on findings and USP, suggest responses across all channels:
   - Paid adjustments (bid, budget, targeting) per platform
   - Organic content gaps to address (from Search Console data)
   - Cross-channel coordination opportunities

9. **Ask for my approval** before updating any files or making changes.

10. **Update STRATEGY.md** Market Context section if approved.

11. **Update STATE.json** with competitive insights in campaign notes.
