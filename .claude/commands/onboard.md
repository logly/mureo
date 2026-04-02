Guide me through setting up mureo for a new advertising account.

## Steps

1. **Check authentication**: Run `mureo auth status` to verify credentials are configured. If not, guide through `mureo auth setup`.

2. **Create STRATEGY.md**: Ask me about my business to fill in each section:
   - **Persona**: Who is the target customer? (role, age, goals, pain points)
   - **USP**: What makes the product/service unique? (3-5 bullet points)
   - **Target Audience**: Demographics, geography, budget range
   - **Brand Voice**: Tone and style guidelines for ad copy
   - **Market Context**: Competitors, market trends, competitive advantages
   - **Operation Mode**: Start with `ONBOARDING_LEARNING` for new accounts
   Write the completed STRATEGY.md to the current directory.

3. **Discover accounts**:
   - Google Ads: Use `google_ads.accounts.list` to list accessible accounts, then `google_ads.campaigns.list` for the selected account
   - Meta Ads: Use `meta_ads.campaigns.list` for the configured account

4. **Initialize STATE.json**: Snapshot all campaigns with their current status, budgets, and bidding strategies into STATE.json.

5. **Initial diagnosis**: Run `google_ads.health_check.all` and report any immediate issues.

6. **Summary**: Show what was set up and recommend next steps.

IMPORTANT: Ask me questions interactively — don't assume answers. Each STRATEGY.md section should reflect MY actual business, not generic examples.
