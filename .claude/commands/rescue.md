Run an emergency performance rescue workflow for underperforming campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (including Goal sections and Data Sources) and STATE.json. Set Operation Mode to `TURNAROUND_RESCUE` in STRATEGY.md.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`.

3. **Diagnose: platform-side or site-side?** (if GA4 is available): Before making ad changes, check if the performance problem is platform-side or site-side. If LP conversion rates dropped in GA4 too, the issue may be the landing page, not the ads. Recommend LP investigation before ad changes.

4. **Identify problem campaigns across all platforms**: For each configured ad platform, use the platform's health check, zero-conversion detection, and cost anomaly tools to find unhealthy campaigns.

5. **Evaluate severity against Goals**: For each problem campaign, reference Goal targets from STRATEGY.md:
   - Calculate how far off the campaign is from the Goal
   - Prioritize rescue actions by impact on Goal achievement
   - Flag campaigns that are the biggest blockers to reaching Goals

6. **Search term cleanup** (for platforms that support search term data):
   - Review search terms for waste on each problem campaign
   - Cross-reference with Persona from STRATEGY.md — flag terms that don't match target audience
   - If Search Console is available, identify terms better served by organic
   - Suggest negative keywords to add
   - **Ask for my approval before adding any negative keywords**

7. **Budget efficiency**: Analyze budget efficiency across all platforms. Identify campaigns wasting budget (high spend, low/zero conversions). Suggest budget reallocation from wasteful to efficient campaigns.
   - **Ask for my approval before changing any budgets**

8. **Platform-specific optimizations**: For each platform, run the platform's specialized analysis (device performance, placement analysis, audience analysis, etc.) on problem campaigns. Suggest specific optimizations.
   - **Ask for my approval before making changes**

9. **Execute approved actions**: Only after I approve each recommendation, execute the changes using each platform's update tools.

10. **Update STATE.json**: Record all changes made in campaign notes with timestamps. Log all rescue actions to the `action_log` with platform, action type, and expected impact.

11. **Summary**: List all changes made per platform with expected impact on Goal metrics.

IMPORTANT: Never make changes without explicit approval. Present each action as a recommendation first.
