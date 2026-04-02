Analyze budget allocation and suggest rebalancing across all campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Operation Mode, Market Context) and STATE.json.

2. **Analyze budget efficiency**:
   - Google Ads: Run `google_ads.budget.efficiency`
   - Google Ads: Run `google_ads.performance.report` for each campaign
   - Meta Ads: Run `meta_ads.analysis.performance`

3. **Rank campaigns** by efficiency (CPA, ROAS, or CVR depending on campaign goals in STATE.json).

4. **Mode guard**: If Operation Mode is `ONBOARDING_LEARNING` or `CREATIVE_TESTING`, warn that budget changes are discouraged in this mode and ask whether to proceed.

5. **Generate reallocation plan** based on Operation Mode:
   - **EFFICIENCY_STABILIZE**: Shift budget from high-CPA to low-CPA campaigns
   - **SCALE_EXPANSION**: Increase budget for campaigns not limited by budget but performing well
   - **TURNAROUND_RESCUE**: Cut budget from campaigns with 0 conversions
   - **COMPETITOR_DEFENSE**: Increase budget on core brand/keyword campaigns under competitive pressure
   - **LTV_QUALITY_FOCUS**: Prioritize campaigns with highest conversion quality
   - **ONBOARDING_LEARNING**: Minimal changes only if user confirmed in step 4
   - **CREATIVE_TESTING**: Minimal changes only if user confirmed in step 4

6. **Present plan** as a table:
   | Campaign | Current Budget | Proposed Budget | Change | Reason |
   |----------|---------------|-----------------|--------|--------|

7. **Risk assessment**: Flag any budget changes >20% (smart bidding learning risk).

8. **Ask for approval** before any changes.

9. **Execute**: `google_ads.budget.update` for approved changes.

10. **Update STATE.json** with new budget values and notes.
