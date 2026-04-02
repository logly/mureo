Generate a weekly marketing operations report.

## Prerequisites
- STRATEGY.md with Goals (run `/onboard` first)
- STATE.json with action_log (actions must have been logged during the week)

## Steps

1. **Load context**: Read STRATEGY.md and STATE.json.

2. **Period**: Determine the reporting period (last 7 days from today).

3. **Goal progress**: For each Goal, compare current metrics vs. last week:
   - Google Ads: Use `google_ads.performance.report` with date range for current and previous week
   - Meta Ads: Use `meta_ads.insights.report` with date range for current and previous week
   - Show week-over-week change for each Goal metric

4. **Actions taken**: Read `action_log` from STATE.json, filter to the reporting period.
   Present as a timeline:
   | Date | Command | Action | Platform | Summary |
   |------|---------|--------|----------|---------|

5. **Impact assessment**: For each action taken, evaluate if it had the expected effect:
   - Compare metrics before and after the action date
   - Use `google_ads.performance.analyze` and `meta_ads.analysis.performance` for trend data
   - Example: "Added 5 negative keywords on Mon -> CPA decreased 8% by Thu"
   - Example: "Shifted 20% budget to Google on Tue -> impressions increased 15%"

6. **Next week recommendations**:
   - Based on Goal trajectory, suggest focus areas
   - Recommend specific commands to run (`/rescue`, `/budget-rebalance`, `/creative-refresh`, `/goal-review`)
   - Suggest Operation Mode change if appropriate (e.g., "Goals on track -- consider switching from TURNAROUND_RESCUE to EFFICIENCY_STABILIZE")

7. **Present report** in a structured format suitable for sharing with stakeholders:
   - Executive summary (2-3 sentences)
   - Goal progress table
   - Key actions and their impact
   - Recommendations for next week

8. **Log to action_log** in STATE.json that a weekly report was generated, including the reporting period.
