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
   - **Google Ads**: Call `google_ads_auction_insights_get` (raw impression-share / overlap rows) and `google_ads_auction_insights_analyze` (rule-based summary), then `google_ads_cpc_detect_trend` (CPC drift) and `google_ads_device_analyze` (device-level breakdown). **BYOD limitation**: Apps Script does not expose `auction_insight_domain` (GAQL) — auction insight tools return `[]` in BYOD mode. The remaining tools (CPC trend, device breakdown) work in BYOD against the bundle.
   - **Meta Ads**: No direct competitor-share API; surface `meta_ads_analysis_placements` and `meta_ads_analysis_cost` to detect placement-level cost shifts that indicate competitive pressure.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through MCP tools — do **not** look for raw CSVs in the project directory.
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
