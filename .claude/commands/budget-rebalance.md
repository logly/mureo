Analyze budget allocation and suggest rebalancing across all campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Operation Mode, Market Context, Goal sections, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`.

3. **Structural check before rebalancing** (apply learned insights from `mureo-pro-diagnosis` skill if available): Before shifting budgets, check if the problem is allocation or structural dispersion:
   - Calculate budget-per-ad-group ratios for each campaign
   - If ad groups are starving (< 5 clicks/day avg), recommend consolidation BEFORE reallocation
   - If a campaign has too many ad groups for its budget, consolidation may be more effective than increasing budget
   - For low-volume accounts (< 50 conversions/month total), recommend concentrating budget into 1-2 campaigns rather than spreading across many

4. **Analyze budget efficiency**: For each ad platform, analyze budget efficiency using the platform's budget and performance analysis tools.

5. **Rank campaigns** by efficiency (CPA, ROAS, or CVR depending on campaign goals) across all platforms to enable cross-platform comparison.

6. **Goal-driven prioritization**: Reference Goal sections from STRATEGY.md to guide allocation:
   - Identify which platform is closer to achieving each Goal
   - Consider shifting budget toward the platform with better Goal progress

7. **Cross-platform rebalancing**: Evaluate whether budget should move between any configured platforms:
   - Compare CPA/ROAS across all platforms
   - If one platform significantly outperforms, suggest cross-platform budget shift
   - Present cross-platform comparison before within-platform reallocation

8. **Organic intelligence** (if Search Console is available): If organic rankings are strong for certain keywords, consider reducing paid spend on those terms and reallocating to keywords without organic coverage.

9. **Conversion quality check** (if GA4 is available): Incorporate conversion quality data (bounce rate, pages/session, time on site by traffic source) into budget decisions. A platform with lower CPA but higher bounce rate may not be the better allocation.

10. **Mode guard**: If Operation Mode is `ONBOARDING_LEARNING` or `CREATIVE_TESTING`, warn that budget changes are discouraged in this mode and ask whether to proceed.

11. **Generate reallocation plan** based on Operation Mode:
    - **EFFICIENCY_STABILIZE**: Shift budget from high-CPA to low-CPA campaigns
    - **SCALE_EXPANSION**: Increase budget for campaigns not limited by budget but performing well
    - **TURNAROUND_RESCUE**: Cut budget from campaigns with 0 conversions
    - **COMPETITOR_DEFENSE**: Increase budget on core brand/keyword campaigns under competitive pressure
    - **LTV_QUALITY_FOCUS**: Prioritize campaigns with highest conversion quality
    - **ONBOARDING_LEARNING**: Minimal changes only if user confirmed in step 10
    - **CREATIVE_TESTING**: Minimal changes only if user confirmed in step 10

12. **Present plan** as a table:
    | Platform | Campaign | Current Budget | Proposed Budget | Change | Reason |
    |----------|----------|---------------|-----------------|--------|--------|

13. **Risk assessment**: Flag any budget changes >20% (smart bidding learning risk).

14. **Ask for approval** before any changes.

15. **Check pending observations**: Before executing, check `action_log` for campaigns being modified. If a previous budget change is still within its observation window, warn about stacking changes.

16. **Execute**: Use each platform's budget update tools to apply approved changes.

17. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current cost, impressions, clicks, conversions, CPA, budget utilization) and `observation_due` (7 days from today for budget changes).

18. **Update STATE.json** with new budget values, notes, and log the rebalancing action to `action_log`.

19. **Diagnosis learning**: If during this workflow the user corrected your analysis or pointed out something you missed, propose saving the insight to `skills/mureo-pro-diagnosis/SKILL.md` under the "Learned Insights" section. Use the format documented in that file. Ask for approval before writing. Do NOT save to memory — save to the skill file.
