Refresh ad creatives based on strategy context and performance data.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run `/onboard` first)

## Steps

1. **Load context**: Read STRATEGY.md (Persona, USP, Brand Voice) and STATE.json.

2. **Audit current RSA assets** for each active campaign:
   - Run `google_ads.rsa_assets.audit` to find LOW/POOR performing assets
   - Run `google_ads.ads.list` to see current ad copy

3. **Analyze landing pages**:
   - For each campaign's final URL, run `google_ads.landing_page.analyze`
   - Extract key selling points, CTAs, and features from the LP

4. **Generate new ad copy**:
   Using Persona pain points + USP + LP selling points + Brand Voice rules, draft:
   - 5 new headline candidates (max 30 characters each)
   - 3 new description candidates (max 90 characters each)

   Each headline/description should:
   - Address a specific Persona pain point OR highlight a USP
   - Match the Brand Voice guidelines
   - Include keywords from top-performing search terms

5. **Validate**: Run each through mureo's RSA validation rules:
   - No prohibited expressions (superlatives, guarantees)
   - Within character limits
   - No duplicate headlines

6. **Present recommendations** with rationale for each.

7. **Ask for approval** before creating/updating any ads.

8. **Execute approved changes**:
   - `google_ads.ads.create` for new ads
   - `google_ads.ads.update` to replace underperforming assets

9. **Update STATE.json** with notes.

IMPORTANT: Every headline/description must have a clear rationale tied to Persona, USP, or LP content. Never generate generic ad copy.
