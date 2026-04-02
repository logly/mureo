Review progress toward all marketing goals across all platforms.

## Prerequisites
- STRATEGY.md with at least one Goal section (run `/onboard` first)
- STATE.json (run `/sync-state` first)

## Steps

1. **Load context**: Read STRATEGY.md (all Goal sections) and STATE.json.

2. **For each Goal**, gather current metrics from all relevant platforms:
   - If Goal mentions Google Ads: get performance data via `google_ads.performance.report` and `google_ads.performance.analyze`
   - If Goal mentions Meta Ads: get performance data via `meta_ads.analysis.performance` and `meta_ads.insights.report`
   - If GA4 MCP is available: include website conversion data for LP-related Goals

3. **Evaluate progress** for each Goal:
   - Compare current value against target
   - Calculate % of target achieved
   - Calculate days remaining until deadline
   - Assess trajectory: on-track / at-risk / off-track

4. **Present Goal dashboard**:
   | Goal | Target | Current | Progress | Deadline | Status |
   |------|--------|---------|----------|----------|--------|

   Status indicators:
   - On track -- current value meets or exceeds the pace needed to hit target by deadline
   - At risk -- current value is within 20% of target but trajectory is concerning
   - Off track -- current value is more than 20% away from target pace

5. **Recommend actions** for off-track Goals:
   - Suggest specific commands to run (`/rescue`, `/budget-rebalance`, `/creative-refresh`)
   - Tie recommendations to the Goal context (e.g., "CPA is 24% over target on Meta -- run `/rescue` focused on Meta Ads")
   - Prioritize recommendations by Goal priority (P0 > P1 > P2)

6. **Update STATE.json**:
   - Log the review to `action_log` with a summary of Goal statuses
   - Update Current values in STRATEGY.md Goal sections if approved

IMPORTANT: When updating Goal "Current" values in STRATEGY.md, ask for approval first.
