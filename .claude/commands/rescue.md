Run an emergency performance rescue workflow for underperforming campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (including Goal sections and Data Sources) and STATE.json. Set Operation Mode to `TURNAROUND_RESCUE` in STRATEGY.md.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`.

3. **Diagnose: platform-side or site-side?** (if GA4 is available): Before making ad changes, check if the performance problem is platform-side or site-side. If LP conversion rates dropped in GA4 too, the issue may be the landing page, not the ads. Recommend LP investigation before ad changes.

4. **Structural diagnosis first** (apply learned insights from `mureo-pro-diagnosis` skill if available): Before optimizing metrics, diagnose root causes top-down:
   - **Level 1 — Structure**: Is the account structure appropriate for the budget? Calculate budget-per-ad-group ratios. If ad groups are starving (<5 clicks/day avg), recommend consolidation BEFORE keyword or bid changes.
   - **Level 2 — Data adequacy**: Are there enough conversions for the bidding strategy? If < 30 conversions/month with smart bidding, recommend micro-conversions or bid strategy change.
   - **Level 3 — Targeting**: Only after structure is sound, evaluate keyword relevance, geo, device, schedule.
   - **Level 4 — Creative/Bids**: Only after targeting is sound, optimize ads and bids.
   Present findings with root cause, evidence, impact, and priority-ordered actions.

5. **Identify problem campaigns across all platforms**: For each configured ad platform, use the platform's health check, zero-conversion detection, and cost anomaly tools to find unhealthy campaigns.

6. **Evaluate severity against Goals**: For each problem campaign, reference Goal targets from STRATEGY.md:
   - Calculate how far off the campaign is from the Goal
   - Prioritize rescue actions by impact on Goal achievement
   - Flag campaigns that are the biggest blockers to reaching Goals

7. **Search term cleanup** (for platforms that support search term data):
   - Review search terms for waste on each problem campaign
   - Cross-reference with Persona from STRATEGY.md — flag terms that don't match target audience
   - If Search Console is available, identify terms better served by organic
   - Suggest negative keywords to add
   - **Ask for my approval before adding any negative keywords**

8. **Budget efficiency**: Analyze budget efficiency across all platforms. Identify campaigns wasting budget (high spend, low/zero conversions). Suggest budget reallocation from wasteful to efficient campaigns.
   - **Ask for my approval before changing any budgets**

9. **Platform-specific optimizations**: For each platform, run the platform's specialized analysis (device performance, placement analysis, audience analysis, etc.) on problem campaigns. Suggest specific optimizations.
   - **Ask for my approval before making changes**

10. **Execute approved actions**: Only after I approve each recommendation, execute the changes using each platform's update tools.

11. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CPA, conversions, clicks, cost, impressions) and `observation_due` (7 days for budget changes, 14 days for keyword/creative changes).

12. **Update STATE.json**: Record all changes made in campaign notes with timestamps. Log all rescue actions to the `action_log` with platform, action type, and expected impact.

13. **Summary**: List all changes made per platform with expected impact on Goal metrics.

14. **Diagnosis learning**: If during this workflow the user corrected your analysis or pointed out something you missed, propose saving the insight to `skills/mureo-pro-diagnosis/SKILL.md` under the "Learned Insights" section. Use the format documented in that file. Ask for approval before writing. Do NOT save to memory — save to the skill file.

IMPORTANT: Never make changes without explicit approval. Present each action as a recommendation first. Do NOT trigger rescue based on a single bad day — at least 7 consecutive days of critical metrics (>30% off target) before recommending rescue actions.
