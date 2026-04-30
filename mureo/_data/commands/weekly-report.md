Generate a weekly marketing operations report.

## Prerequisites
- STRATEGY.md with Goals (run `/onboard` first)
- STATE.json with action_log (actions must have been logged during the week)

## Steps

1. **Load context**: Read STRATEGY.md and STATE.json.

2. **Discover platforms**: Identify all configured platforms and available data sources.

3. **Period**: Determine the reporting period (last 7 days from today).

4. **Goal progress**: For each Goal, pull performance data from the relevant platforms:
   - **Google Ads**: Call `google_ads_performance_report` (with `period: "LAST_7_DAYS"` then `period: "LAST_14_DAYS"` and subtract the first 7 from the next 7 for previous-week comparison).
   - **Meta Ads**: Call `meta_ads_insights_report` similarly. When summing Meta "results" across campaigns, group by `result_indicator` — never aggregate `link_click` totals together with `pixel_lead` totals (PR #61).
   - mureo BYOD data is centralized under `~/.mureo/byod/` and is only accessible through MCP tools — do **not** look for raw CSVs in the project directory.
   - Show week-over-week change for each Goal metric. If GA4 is available, include website-level metrics (sessions, conversion rate, revenue) for a holistic view.

5. **Actions taken**: Read `action_log` from STATE.json, filter to the reporting period.
   Present as a timeline:
   | Date | Command | Action | Platform | Summary |
   |------|---------|--------|----------|---------|

6. **Impact assessment**: For each action taken, evaluate impact using the relevant platform's trend/analysis tools. Cross-reference with GA4 data if available to validate on-site impact.
   - Example: "Added 5 negative keywords on Mon → CPA decreased 8% by Thu"
   - Example: "Shifted 20% budget to Platform A on Tue → impressions increased 15%"

7. **Cross-platform insights**:
   - Compare performance across platforms (CPA, CVR, ROAS)
   - Identify platforms gaining or losing efficiency
   - If Search Console data is available, include organic search trend summary (clicks, impressions, CTR WoW change) and paid/organic keyword overlap changes
   - Suggest cross-platform shifts if one platform significantly outperforms others toward Goal achievement

8. **Next week recommendations**:
   - Based on Goal trajectory, suggest focus areas
   - Recommend specific commands to run (`/rescue`, `/budget-rebalance`, `/creative-refresh`, `/goal-review`)
   - Suggest Operation Mode change if appropriate (e.g., "Goals on track — consider switching from TURNAROUND_RESCUE to EFFICIENCY_STABILIZE")

9. **Evidence pipeline**: Include an evidence assessment section:
   - List actions with `observation_due` dates that passed this week — evaluate their outcomes by comparing `metrics_at_action` with current metrics
   - List actions still in observation — note them as "pending, do not draw conclusions"
   - Rate confidence in reported improvements: low (< 1 week data), medium (1 observation period), high (2+ consistent periods)
   - Do NOT present pending observations as confirmed wins

10. **Present report** in a structured format suitable for sharing with stakeholders:
    - Executive summary (2-3 sentences)
    - Goal progress table
    - Cross-platform performance comparison
    - Key actions and their impact (with confidence level)
    - Evidence pipeline summary
    - Recommendations for next week

11. **Log to action_log** in STATE.json that a weekly report was generated, including the reporting period.
