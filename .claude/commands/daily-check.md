Run a daily health check on all advertising accounts using the strategy context.

## Prerequisites
- STRATEGY.md and STATE.json must exist in the current directory (run `/onboard` first if not)

## Steps

1. **Load context**: Read STRATEGY.md (especially Operation Mode and all Goal sections) and STATE.json.

2. **Sync state**: Fetch current campaign data and update STATE.json.
   - Google Ads: `google_ads.campaigns.list` -> update STATE.json
   - Meta Ads: `meta_ads.campaigns.list` -> update STATE.json

3. **Google Ads health check**: Run `google_ads.health_check.all` for Google Ads accounts.

4. **Meta Ads health check**: Run `meta_ads.analysis.performance` for Meta accounts. Also run `meta_ads.analysis.cost` to check for cost anomalies.

5. **Mode-specific checks** based on Operation Mode:
   - **ONBOARDING_LEARNING**: Check `google_ads.campaigns.diagnose` for learning status. Warn against making changes.
   - **EFFICIENCY_STABILIZE**: Check CPA trends via `google_ads.performance.analyze`. Flag if CPA increased >10%. Run `meta_ads.insights.report` for Meta CPA trends.
   - **TURNAROUND_RESCUE**: Run `google_ads.monitoring.zero_conversions` and `google_ads.cost_increase.investigate` on flagged campaigns. Run `meta_ads.analysis.cost` on Meta campaigns.
   - **SCALE_EXPANSION**: Check budget utilization via `google_ads.budget.efficiency`. Flag underspending campaigns. Run `meta_ads.analysis.performance` for Meta utilization.
   - **COMPETITOR_DEFENSE**: Run `google_ads.auction_insights.get` on key campaigns. Flag impression share drops >5%.
   - **CREATIVE_TESTING**: Run `google_ads.rsa_assets.audit` on active campaigns. Flag LOW/POOR assets. Run `meta_ads.analysis.compare_ads` for Meta creative performance.
   - **LTV_QUALITY_FOCUS**: Review search terms quality via `google_ads.search_terms.review`. Run `meta_ads.analysis.audience` for Meta audience quality.

6. **GA4 conversion check** (if GA4 MCP is available): Check LP conversion rates to correlate ad performance with on-site behavior.

7. **Goal progress check**: For each Goal section in STRATEGY.md:
   - Gather current metric values from the relevant platforms (Google Ads and/or Meta Ads)
   - Compare current value against the Goal target
   - Present a Goal progress summary, e.g.:
     ```
     Goal: CPA < 5,000 -- Google: 4,800 OK, Meta: 6,200 OVER TARGET
     Goal: CV >= 100/month -- Google: 62, Meta: 28, Total: 90 AT RISK
     ```

8. **Report**: Summarize findings as:
   - Healthy -- no action needed
   - Watch -- minor issues to monitor
   - Action needed -- requires immediate attention

   For each issue, suggest specific actions aligned with the current Operation Mode.

9. **Update STATE.json**: Update campaign snapshots, add notes for flagged issues, and log this daily check to the `action_log` with a summary of findings.
