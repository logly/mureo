Scan the competitive landscape and suggest strategic responses.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Market Context, USP) and STATE.json.

2. **Auction analysis** for each key campaign:
   - Run `google_ads.auction_insights.get`
   - Compare impression share, overlap rate, top-of-page rate

3. **CPC trends**:
   - Run `google_ads.cpc.detect_trend` for each campaign
   - Identify rising CPC (potential increased competition)

4. **Device landscape**:
   - Run `google_ads.device.analyze` for key campaigns
   - Identify devices where competitors may dominate

5. **Compare with Market Context** from STRATEGY.md:
   - Are known competitors gaining share?
   - Are new competitors appearing?
   - Has the competitive landscape changed since STRATEGY.md was last updated?

6. **Strategic recommendations**:
   Based on findings and USP, suggest:
   - Keyword adjustments to defend core terms
   - Budget shifts to counter competitive pressure
   - Platform mix changes (Google vs Meta) to leverage unique advantages

7. **Ask for my approval** before updating any files or making changes.

8. **Update STRATEGY.md** Market Context section if approved.

9. **Update STATE.json** with competitive insights in campaign notes.
