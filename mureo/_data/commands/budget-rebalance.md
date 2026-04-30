Analyze budget allocation and suggest rebalancing across all campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Operation Mode, Market Context, Goal sections, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`.

3. **Analyze budget efficiency**: For each ad platform:
   - **Google Ads**: Call `google_ads_budget_efficiency` (campaign × budget × spend × conv ratio) and `google_ads_performance_report` for the period. In BYOD mode, `budget.efficiency` may return `[]` because daily budgets aren't carried in the Apps Script bundle — fall back to `performance.report` cost / conv numbers and rank by CPA.
   - **Meta Ads**: Call `meta_ads_insights_report` and `meta_ads_analysis_cost`. In BYOD mode, daily budgets aren't surfaced — rank by spend × `result_indicator`-aware conversions instead.
   - mureo BYOD data is centralized under `~/.mureo/byod/` and is only accessible through MCP tools — do **not** look for raw CSVs in the project directory.

4. **Rank campaigns** by efficiency (CPA, ROAS, or CVR depending on campaign goals) across all platforms to enable cross-platform comparison.

5. **Goal-driven prioritization**: Reference Goal sections from STRATEGY.md to guide allocation:
   - Identify which platform is closer to achieving each Goal
   - Consider shifting budget toward the platform with better Goal progress

6. **Cross-platform rebalancing**: Evaluate whether budget should move between any configured platforms:
   - Compare CPA/ROAS across all platforms
   - If one platform significantly outperforms, suggest cross-platform budget shift
   - Present cross-platform comparison before within-platform reallocation

7. **Organic intelligence** (if Search Console is available): If organic rankings are strong for certain keywords, consider reducing paid spend on those terms and reallocating to keywords without organic coverage.

8. **Conversion quality check** (if GA4 is available): Incorporate conversion quality data (bounce rate, pages/session, time on site by traffic source) into budget decisions. A platform with lower CPA but higher bounce rate may not be the better allocation.

9. **Mode guard**: If Operation Mode is `ONBOARDING_LEARNING` or `CREATIVE_TESTING`, warn that budget changes are discouraged in this mode and ask whether to proceed.

10. **Generate reallocation plan** based on Operation Mode:
    - **EFFICIENCY_STABILIZE**: Shift budget from high-CPA to low-CPA campaigns
    - **SCALE_EXPANSION**: Increase budget for campaigns not limited by budget but performing well
    - **TURNAROUND_RESCUE**: Cut budget from campaigns with 0 conversions
    - **COMPETITOR_DEFENSE**: Increase budget on core brand/keyword campaigns under competitive pressure
    - **LTV_QUALITY_FOCUS**: Prioritize campaigns with highest conversion quality
    - **ONBOARDING_LEARNING**: Minimal changes only if user confirmed in step 9
    - **CREATIVE_TESTING**: Minimal changes only if user confirmed in step 9

11. **Present plan** as a table:
    | Platform | Campaign | Current Budget | Proposed Budget | Change | Reason |
    |----------|----------|---------------|-----------------|--------|--------|

12. **Risk assessment**: Flag any budget changes >20% (smart bidding learning risk).

13. **Ask for approval** before any changes.

14. **Check pending observations**: Before executing, check `action_log` for campaigns being modified. If a previous budget change is still within its observation window, warn about stacking changes.

15. **Execute**: Use each platform's budget update tools to apply approved changes.

16. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current cost, impressions, clicks, conversions, CPA, budget utilization) and `observation_due` (7 days from today for budget changes).

17. **Update STATE.json** with new budget values, notes, and log the rebalancing action to `action_log`.
