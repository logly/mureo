Review and clean up search terms across all Google Ads campaigns.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Persona, USP, Target Audience) and STATE.json.

2. **Review search terms** for each active campaign:
   - Run `google_ads.search_terms.review` with target CPA from STATE.json bidding_details
   - Run `google_ads.search_terms.analyze` for N-gram and intent analysis

3. **Score candidates** against strategy:
   - **Exclude candidates**: Terms with 0 conversions + high cost, informational-only queries, terms misaligned with Persona
   - **Add candidates**: High-converting terms not yet added as keywords, terms matching USP themes

4. **Present recommendations** in a table:
   | Term | Action | Reason | Score | Campaign |
   |------|--------|--------|-------|----------|

   Group by campaign. Show estimated cost savings from exclusions.

5. **Ask for approval**: Let me select which recommendations to apply.

6. **Execute**:
   - Add negative keywords: `google_ads.negative_keywords.add`
   - Add positive keywords: `google_ads.keywords.add`

7. **Update STATE.json** with notes about the cleanup.

IMPORTANT: Always explain WHY a term should be excluded/added, referencing the Persona or USP from STRATEGY.md.
