Run an emergency performance rescue workflow for underperforming campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (including Goal sections) and STATE.json. Set Operation Mode to `TURNAROUND_RESCUE` in STRATEGY.md.

2. **Identify problem campaigns across all platforms**:
   - Google Ads: Run `google_ads.health_check.all` to find unhealthy campaigns
   - Google Ads: Run `google_ads.monitoring.zero_conversions` on campaigns with 0 CVs
   - Google Ads: Run `google_ads.cost_increase.investigate` on campaigns with rising costs
   - Meta Ads: Run `meta_ads.analysis.performance` to identify underperforming campaigns
   - Meta Ads: Run `meta_ads.analysis.cost` to find campaigns with rising costs

3. **Evaluate severity against Goals**: For each problem campaign, reference Goal targets from STRATEGY.md:
   - Calculate how far off the campaign is from the Goal (e.g., "CPA 6,200 vs Goal 5,000 = 24% over target")
   - Prioritize rescue actions by impact on Goal achievement
   - Flag campaigns that are the biggest blockers to reaching Goals

4. **Google Ads search term cleanup** (for each problem campaign):
   - Run `google_ads.search_terms.review` with target CPA from STATE.json
   - Cross-reference with Persona from STRATEGY.md -- flag terms that don't match target audience
   - Suggest negative keywords to add
   - **Ask for my approval before adding any negative keywords**

5. **Budget efficiency**:
   - Run `google_ads.budget.efficiency` across all Google Ads campaigns
   - Run `meta_ads.analysis.performance` for Meta Ads budget utilization
   - Identify campaigns wasting budget (high spend, low/zero conversions) on both platforms
   - Suggest budget reallocation from wasteful to efficient campaigns
   - **Ask for my approval before changing any budgets**

6. **Device analysis**:
   - Run `google_ads.device.analyze` on problem campaigns
   - If a device has 0 conversions with significant spend, suggest bid adjustment
   - **Ask for my approval before changing bid adjustments**

7. **Meta Ads placement cleanup**:
   - Run `meta_ads.analysis.placements` to find wasteful placements
   - Run `meta_ads.analysis.audience` to check audience overlap or fatigue
   - Suggest placement exclusions or audience adjustments
   - **Ask for my approval before making changes**

8. **Execute approved actions**: Only after I approve each recommendation, execute the changes.

9. **Update STATE.json**: Record all changes made in campaign notes with timestamps. Log all rescue actions to the `action_log` with platform, action type, and expected impact.

10. **Summary**: List all changes made per platform with expected impact on Goal metrics.

IMPORTANT: Never make changes without explicit approval. Present each action as a recommendation first.
