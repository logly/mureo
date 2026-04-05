Review and clean up search terms and keywords across all platforms.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Persona, USP, Target Audience, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured platforms that support search term data from STATE.json `platforms`.

3. **Review search terms**: For each ad platform that supports search term data, review search terms using the platform's search term analysis tools. Analyze N-gram patterns and user intent.

4. **Paid/organic cross-reference** (if Search Console is available):
   - Pull top organic queries for the site
   - Cross-reference with paid search terms to identify overlap
   - For terms ranking well organically (position 1-3), consider reducing paid bids or pausing paid keywords
   - For terms with strong paid performance but weak organic ranking, flag as SEO opportunity
   - Present a paid/organic overlap matrix

5. **Landing page quality check** (if GA4 is available): Check landing page performance for key search terms. Terms driving traffic to high-bounce-rate pages may need LP improvements rather than keyword changes.

6. **Score candidates** against strategy:
   - **Exclude candidates**: Terms with 0 conversions + high cost, informational-only queries, terms misaligned with Persona
   - **Add candidates**: High-converting terms not yet added as keywords, terms matching USP themes
   - **Reduce candidates**: Terms well-covered by organic rankings

7. **Present recommendations** in a table:
   | Term | Platform | Action | Reason | Score | Campaign |
   |------|----------|--------|--------|-------|----------|

   Group by platform and campaign. Show estimated cost savings from exclusions.

8. **Ask for approval**: Let me select which recommendations to apply.

9. **Check pending observations**: Before executing, check `action_log` for this campaign. If a previous action is still within its observation window, warn that stacking changes will make outcome evaluation difficult. Recommend waiting if possible.

10. **Execute**: Use each platform's keyword management tools to apply approved changes (add negative keywords, add positive keywords, adjust bids).

11. **Record outcome context**: For each campaign modified, log to `action_log` with `metrics_at_action` (current CPA, conversions, clicks, CTR, impressions, cost) and `observation_due` (14 days from today). This enables evidence-based evaluation later.

12. **Update STATE.json** with notes about the cleanup.

IMPORTANT: Always explain WHY a term should be excluded/added, referencing the Persona or USP from STRATEGY.md. Consult past action_log entries — if a similar cleanup was previously evaluated, reference whether it was effective.
