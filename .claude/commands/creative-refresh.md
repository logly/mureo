Refresh ad creatives based on strategy context and performance data across all platforms.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Persona, USP, Brand Voice, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured ad platforms from STATE.json `platforms`.

3. **Audit current creatives**: For each ad platform, audit current ad creative performance using the platform's creative analysis tools. Identify underperforming assets (LOW/POOR ratings for search ads, low CTR/engagement for social ads).

4. **Analyze landing pages**: For each campaign's final URL, analyze the landing page to extract key selling points, CTAs, and features. If GA4 is available, pull engagement metrics (time on page, scroll depth, bounce rate) to inform creative direction.

5. **Organic keyword insights** (if Search Console is available): Incorporate top-performing organic search queries into ad copy. Terms that drive organic clicks likely resonate with users.

6. **Generate platform-appropriate creative recommendations**:
   Using Persona pain points + USP + LP selling points + Brand Voice rules, draft:
   - **Search ads**: Headlines and descriptions aligned with character limits and ad format requirements
   - **Social ads**: Primary text, headline, description, CTA suggestions
   - Consider platform-specific best practices and format requirements

   Each creative must:
   - Address a specific Persona pain point OR highlight a USP
   - Match the Brand Voice guidelines
   - Include keywords from top-performing search terms (paid and organic)

7. **Validate**: Run each through the relevant platform's ad validation rules (character limits, prohibited expressions, no duplicates).

8. **Present recommendations** with rationale for each. Group by platform.

9. **Ask for approval** before creating/updating any ads.

10. **Check pending observations**: Before executing, check `action_log` for campaigns being modified. If a previous creative change is still within its observation window, warn about stacking changes.

11. **Execute approved changes**: Use each platform's ad creation/update tools to apply changes.

12. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CTR, CPA, conversions, impressions, clicks) and `observation_due` (14 days from today).

13. **Update STATE.json** with notes.

14. **Diagnosis learning**: If during this workflow the user corrected your analysis or pointed out something you missed, propose saving the insight to `skills/mureo-pro-diagnosis/SKILL.md` under the "Learned Insights" section. Use the format documented in that file. Ask for approval before writing. Do NOT save to memory — save to the skill file.

IMPORTANT: Every headline/description must have a clear rationale tied to Persona, USP, or LP content. Never generate generic ad copy. Consult past action_log — if previous creative refreshes have evaluated outcomes, reference what worked.
