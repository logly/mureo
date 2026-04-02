Run a daily health check on all advertising accounts using the strategy context.

## Prerequisites
- STRATEGY.md and STATE.json must exist in the current directory (run `/onboard` first if not)

## Steps

1. **Load context**: Read STRATEGY.md (especially Operation Mode) and STATE.json.

2. **Sync state**: Fetch current campaign data and update STATE.json.
   - Google Ads: `google_ads.campaigns.list` -> update STATE.json
   - Meta Ads: `meta_ads.campaigns.list` -> update STATE.json

3. **Health check**: Run `google_ads.health_check.all` for Google Ads accounts.

4. **Mode-specific checks** based on Operation Mode:
   - **ONBOARDING_LEARNING**: Check `google_ads.campaigns.diagnose` for learning status. Warn against making changes.
   - **EFFICIENCY_STABILIZE**: Check CPA trends via `google_ads.performance.analyze`. Flag if CPA increased >10%.
   - **TURNAROUND_RESCUE**: Run `google_ads.monitoring.zero_conversions` and `google_ads.cost_increase.investigate` on flagged campaigns.
   - **SCALE_EXPANSION**: Check budget utilization via `google_ads.budget.efficiency`. Flag underspending campaigns.
   - **COMPETITOR_DEFENSE**: Run `google_ads.auction_insights.get` on key campaigns. Flag impression share drops >5%.
   - **CREATIVE_TESTING**: Run `google_ads.rsa_assets.audit` on active campaigns. Flag LOW/POOR assets.
   - **LTV_QUALITY_FOCUS**: Review search terms quality via `google_ads.search_terms.review`.

5. **Meta Ads check**: Run `meta_ads.analysis.performance` for Meta accounts.

6. **Report**: Summarize findings as:
   - Healthy -- no action needed
   - Watch -- minor issues to monitor
   - Action needed -- requires immediate attention

   For each issue, suggest specific actions aligned with the current Operation Mode.

7. **Update STATE.json** with latest campaign snapshots and add notes for any flagged issues.
