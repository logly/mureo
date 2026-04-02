Analyze budget allocation and suggest rebalancing across all campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Operation Mode, Market Context, Goal sections) and STATE.json.

2. **Analyze budget efficiency across platforms**:
   - Google Ads: Run `google_ads.budget.efficiency`
   - Google Ads: Run `google_ads.performance.report` for each campaign
   - Meta Ads: Run `meta_ads.analysis.performance`
   - Meta Ads: Run `meta_ads.analysis.cost` for cost efficiency

3. **Rank campaigns** by efficiency (CPA, ROAS, or CVR depending on campaign goals in STATE.json). Rank across both platforms to enable cross-platform comparison.

4. **Goal-driven prioritization**: Reference Goal sections from STRATEGY.md to guide allocation:
   - Identify which platform is closer to achieving each Goal
   - Consider shifting budget toward the platform with better Goal progress
   - Example: "Google CPA 4,800 (below Goal 5,000) vs Meta CPA 6,200 (above Goal) -- recommend shifting budget toward Google"

5. **Cross-platform rebalancing**: Evaluate whether budget should move between platforms:
   - Compare CPA/ROAS across Google Ads and Meta Ads
   - If one platform significantly outperforms, suggest cross-platform budget shift
   - Present cross-platform comparison before within-platform reallocation

6. **Mode guard**: If Operation Mode is `ONBOARDING_LEARNING` or `CREATIVE_TESTING`, warn that budget changes are discouraged in this mode and ask whether to proceed.

7. **Generate reallocation plan** based on Operation Mode:
   - **EFFICIENCY_STABILIZE**: Shift budget from high-CPA to low-CPA campaigns
   - **SCALE_EXPANSION**: Increase budget for campaigns not limited by budget but performing well
   - **TURNAROUND_RESCUE**: Cut budget from campaigns with 0 conversions
   - **COMPETITOR_DEFENSE**: Increase budget on core brand/keyword campaigns under competitive pressure
   - **LTV_QUALITY_FOCUS**: Prioritize campaigns with highest conversion quality
   - **ONBOARDING_LEARNING**: Minimal changes only if user confirmed in step 6
   - **CREATIVE_TESTING**: Minimal changes only if user confirmed in step 6

8. **Present plan** as a table:
   | Platform | Campaign | Current Budget | Proposed Budget | Change | Reason |
   |----------|----------|---------------|-----------------|--------|--------|

9. **Risk assessment**: Flag any budget changes >20% (smart bidding learning risk).

10. **Ask for approval** before any changes.

11. **Execute**: `google_ads.budget.update` for approved Google Ads changes. For Meta Ads, use `meta_ads.campaigns.update` or `meta_ads.ad_sets.update` as appropriate.

12. **Update STATE.json** with new budget values, notes, and log the rebalancing action to `action_log`.
