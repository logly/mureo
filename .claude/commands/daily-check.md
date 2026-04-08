Run a daily health check on all marketing accounts using the strategy context.

## Prerequisites
- STRATEGY.md and STATE.json must exist in the current directory (run `/onboard` first if not)

## Steps

1. **Load context**: Read STRATEGY.md (especially Operation Mode, Data Sources, and all Goal sections) and STATE.json.

2. **Discover available platforms**: Identify all configured platforms from STATE.json `platforms` and check which data sources (Search Console, GA4) are accessible.

3. **Sync state**: For each platform in STATE.json `platforms`, fetch current campaign data and update STATE.json.

4. **Structural health check** (apply learned insights from `mureo-pro-diagnosis` skill if available): Before analyzing metrics, evaluate account structure health:
   - Calculate budget-per-ad-group and budget-per-keyword ratios for each campaign
   - Flag ad groups averaging < 5 clicks/day (7-day average)
   - Flag campaigns with < 30 conversions/month using smart bidding
   - Flag budget dispersion issues (too many ad groups/campaigns for the budget)
   - If structural issues are found, prioritize them above metric-level findings

5. **Platform health checks**: Run health diagnostics on each configured ad platform. Use the platform's health check, performance analysis, and cost anomaly detection tools. Present a unified health summary across all platforms.

6. **Mode-specific checks** based on Operation Mode:
   - **ONBOARDING_LEARNING**: Check learning status on each platform. Warn against making changes.
   - **EFFICIENCY_STABILIZE**: Analyze CPA trends across all platforms. Flag if CPA increased >10% on any platform.
   - **TURNAROUND_RESCUE**: Identify zero-conversion campaigns and cost spikes across all platforms.
   - **SCALE_EXPANSION**: Check budget utilization across all platforms. Flag underspending campaigns.
   - **COMPETITOR_DEFENSE**: Run auction/competitive insights on key campaigns. Flag impression share drops >5%.
   - **CREATIVE_TESTING**: Audit ad asset performance across all platforms. Flag underperforming creatives.
   - **LTV_QUALITY_FOCUS**: Review search term quality and audience alignment across all platforms.

7. **Organic search pulse** (if Search Console is available): Check top organic queries for the site. Identify any organic ranking drops that may need paid coverage, or organic gains where paid spend can be reduced.

8. **On-site behavior check** (if GA4 is available): Correlate ad platform metrics with on-site behavior — LP conversion rates, bounce rates, session quality. Flag discrepancies between ad platform and GA4 conversion data.

9. **Goal progress check**: For each Goal in STRATEGY.md, gather current metric values from all relevant platforms and data sources (ad platforms, GA4, Search Console) based on each Goal's declared platform/source. Present a Goal progress summary:
   ```
   Goal: CPA < 5,000 -- Platform A: 4,800 OK, Platform B: 6,200 OVER TARGET
   Goal: CV >= 100/month -- Platform A: 62, Platform B: 28, Total: 90 AT RISK
   Goal: Organic clicks +20% -- Search Console: +12% IN PROGRESS
   ```

10. **Evidence check**: Review `action_log` entries that have `observation_due` dates:
   - For entries whose observation window has passed: collect current metrics for the same campaign, compare with `metrics_at_action`, and evaluate the outcome. Report findings with confidence level (see `mureo-learning` skill).
   - For entries still within their observation window: note them as "pending observation" and do NOT recommend further changes to those campaigns.
   - Do NOT attribute metric movements to specific actions without checking sample sizes and observation windows.

11. **Proactive alerts** (apply learned insights from `mureo-pro-diagnosis` skill if available): Check for and flag these issues without being asked:
    - Conversion tracking adequacy: Are there enough conversions for the bidding strategy? If not, recommend micro-conversions.
    - Self-cannibalization: Multiple campaigns targeting similar keywords
    - Conversion tracking discrepancies: Platform vs GA4 conversion gaps > 20%
    - Learning period violations: Pending changes on campaigns still in learning
    - CPC trend + impression share context: Rising CPCs may indicate competition, not ad quality issues

12. **Report**: Summarize findings as:
    - Healthy — no action needed
    - Watch — minor issues to monitor
    - Action needed — requires immediate attention

    For each issue, suggest specific actions aligned with the current Operation Mode. Do NOT recommend actions based on single-day fluctuations — at least 7 consecutive days of critical metrics (>30% off target) before suggesting rescue.

13. **Update STATE.json**: Update campaign snapshots, add notes for flagged issues, and log this daily check to the `action_log` with a summary of findings.

14. **Diagnosis learning**: If during this workflow the user corrected your analysis or pointed out something you missed (e.g., "that's wrong because...", "you should also check...", "in this situation, the correct approach is..."), propose saving the insight to `skills/mureo-pro-diagnosis/SKILL.md` under the "Learned Insights" section. Use the format documented in that file. Ask for approval before writing. Do NOT save to memory — save to the skill file so it is available in future sessions.
