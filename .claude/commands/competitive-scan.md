Scan the competitive landscape and suggest strategic responses across all channels.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Market Context, USP, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured platforms from STATE.json `platforms`.

3. **Paid competitive analysis**: For each ad platform that provides competitive/auction data, run competitive analysis using the platform's auction insights and trend detection tools. Compare impression share, overlap rate, CPC trends, and device landscape.

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

7. **Strategic recommendations**: Based on findings and USP, suggest responses across all channels:
   - Paid adjustments (bid, budget, targeting) per platform
   - Organic content gaps to address (from Search Console data)
   - Cross-channel coordination opportunities

8. **Ask for my approval** before updating any files or making changes.

9. **Update STRATEGY.md** Market Context section if approved.

10. **Update STATE.json** with competitive insights in campaign notes.
