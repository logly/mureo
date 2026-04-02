Run an emergency performance rescue workflow for underperforming campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md and STATE.json. Set Operation Mode to `TURNAROUND_RESCUE` in STRATEGY.md.

2. **Identify problem campaigns**:
   - Run `google_ads.health_check.all` to find unhealthy campaigns
   - Run `google_ads.monitoring.zero_conversions` on campaigns with 0 CVs
   - Run `google_ads.cost_increase.investigate` on campaigns with rising costs

3. **Search term cleanup** (for each problem campaign):
   - Run `google_ads.search_terms.review` with target CPA from STATE.json
   - Cross-reference with Persona from STRATEGY.md -- flag terms that don't match target audience
   - Suggest negative keywords to add
   - **Ask for my approval before adding any negative keywords**

4. **Budget efficiency**:
   - Run `google_ads.budget.efficiency` across all campaigns
   - Identify campaigns wasting budget (high spend, low/zero conversions)
   - Suggest budget reallocation from wasteful to efficient campaigns
   - **Ask for my approval before changing any budgets**

5. **Device analysis**:
   - Run `google_ads.device.analyze` on problem campaigns
   - If a device has 0 conversions with significant spend, suggest bid adjustment
   - **Ask for my approval before changing bid adjustments**

6. **Meta Ads** (if applicable):
   - Run `meta_ads.analysis.cost` on underperforming campaigns
   - Run `meta_ads.analysis.placements` to find wasteful placements

7. **Execute approved actions**: Only after I approve each recommendation, execute the changes.

8. **Update STATE.json**: Record all changes made in campaign notes with timestamps.

9. **Summary**: List all changes made and expected impact.

IMPORTANT: Never make changes without explicit approval. Present each action as a recommendation first.
