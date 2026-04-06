Guide me through setting up mureo for a new marketing account.

## Steps

1. **Check installation**: Verify mureo is installed by running `mureo --help`. If not found, guide the user to run `pip install mureo`.

2. **Check authentication**: Run `mureo auth status` to verify credentials are configured. If no credentials are found, run `mureo auth setup` to walk through Google Ads and/or Meta Ads OAuth authentication. This step is interactive — it requires the user to enter tokens and authenticate in a browser.

3. **Create STRATEGY.md**: Ask me about my business to fill in each section:
   - **Persona**: Who is the target customer? (role, age, goals, pain points)
   - **USP**: What makes the product/service unique? (3-5 bullet points)
   - **Target Audience**: Demographics, geography, budget range
   - **Brand Voice**: Tone and style guidelines for ad copy
   - **Market Context**: Competitors, market trends, competitive advantages
   - **Operation Mode**: Start with `ONBOARDING_LEARNING` for new accounts
   Write the completed STRATEGY.md to the current directory.

4. **Discover platforms and data sources**:
   - For each advertising platform with configured credentials, discover accessible accounts and list campaigns
   - Check if Search Console credentials are available — if so, run site discovery and list verified sites
   - Check if GA4 MCP is available by probing for analytics tools
   - Record all available platforms and data sources in STRATEGY.md under a `## Data Sources` section

5. **Initialize STATE.json**: For each discovered platform, snapshot campaigns into STATE.json under the corresponding `platforms` key.

6. **Set up Goals**: Ask about quantitative marketing goals:
   - "What are your key marketing goals? (e.g., CPA target, lead volume, ROAS target, organic traffic growth)"
   - For each goal, ask for: target value, deadline, and which platforms/data sources it applies to
   - For goals involving website conversions or user behavior, note that GA4 data will be used for tracking
   - For goals involving organic search, note Search Console as the data source
   - Create `## Goal: <title>` sections in STRATEGY.md with Target, Deadline, Current (TBD), Platform, and Priority fields

7. **Initial diagnosis**: Run health checks on each configured ad platform using the platform's diagnostic tools. If Search Console is available, run a top-queries check to establish an organic baseline. If GA4 is available, check overall site conversion metrics.

8. **Summary**: Show what was set up — platforms discovered, data sources available, goals defined — and recommend next steps.

IMPORTANT: Ask me questions interactively — don't assume answers. Each STRATEGY.md section should reflect MY actual business, not generic examples.
