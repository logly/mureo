Guide me through setting up mureo for a new marketing account.

## Steps

1. **Check installation**: Verify mureo is installed by running `mureo --help`. If not found, guide the user to run `pip install mureo`.

2. **Check data mode (BYOD first, then auth)**:

   **Always run `mureo byod status` first.** If any platform shows
   `BYOD (N rows, ...)`, that platform is in **BYOD mode** — do NOT prompt
   the user to run `mureo auth setup` for it, do NOT call `mureo auth
   status` to "verify" it (that command reads `credentials.json` directly
   and ignores BYOD), and do NOT report it as "未認証". For BYOD platforms,
   announce: "Using BYOD CSV data (N rows, <date range>)."

   For the **remaining** platforms (those showing `not configured` or `real
   API`), then run `mureo auth status` to see which have OAuth credentials.
   If a platform is `not configured` for BYOD AND has no credentials, offer
   `mureo auth setup` (interactive — user runs it themselves) **or** offer
   the BYOD path: "Export a CSV from <platform> and run `mureo byod import
   <file>` instead."

   Never claim a platform is unauthenticated when `mureo byod status` shows
   it in BYOD mode. BYOD takes priority over OAuth and is sufficient on its
   own for analysis.

   Note: When calling MCP tools, you do NOT need to specify customer_id or
   account_id — they are automatically loaded from credentials.json (real
   API mode) or routed to the BYOD client (BYOD mode). Just omit them.

3. **Create STRATEGY.md**: Ask me about my business to fill in each section:
   - **Persona**: Who is the target customer? (role, age, goals, pain points)
   - **USP**: What makes the product/service unique? (3-5 bullet points)
   - **Target Audience**: Demographics, geography, budget range
   - **Brand Voice**: Tone and style guidelines for ad copy
   - **Market Context**: Competitors, market trends, competitive advantages
   - **Operation Mode**: Start with `ONBOARDING_LEARNING` for new accounts

   If I don't know the answers to any of the above sections (Persona, USP,
   Target Audience, Brand Voice, Market Context — Operation Mode always
   defaults to `ONBOARDING_LEARNING`), offer an alternative: ask me for the
   **product / landing-page URL** (or corporate site / competitor URLs).
   Then fetch the URL with WebFetch, read the page content, and draft a
   first-pass for **every** unknown section — Persona, USP, Target Audience,
   Brand Voice, and Market Context — from what's on the site. Show me the
   draft for each section and ask me to confirm or correct it before writing
   STRATEGY.md. If multiple URLs are relevant (LP + corporate + competitor),
   fetch each and consolidate; competitor URLs are especially useful for
   Market Context. If the site is behind login or returns no useful content,
   fall back to interactive Q&A. Apply this URL-fallback per-section: the
   user may know some sections (e.g., Brand Voice) but need help drafting
   others (e.g., Persona, USP) — only fetch and draft the ones I'm unsure
   about.

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

7. **Initial diagnosis**: Run health checks on each configured ad platform:
   - **Google Ads**: `google_ads.performance.report` (LAST_30_DAYS), `google_ads.campaigns.list`, `google_ads.health_check.all`. Iterate the campaigns and call `google_ads.zero_conversions.diagnose` per campaign_id for any with conv = 0.
   - **Meta Ads**: `meta_ads.insights.report` (LAST_30_DAYS) — surface `result_indicator` per campaign so the operator sees up front whether any campaigns are optimizing for `link_click` instead of true leads.
   - mureo BYOD data is centralized under `~/.mureo/byod/` and is only accessible through MCP tools — do **not** look for raw CSVs in the project directory.
   - If Search Console is available, run a top-queries check to establish an organic baseline. If GA4 is available, check overall site conversion metrics.

8. **Summary**: Show what was set up — platforms discovered, data sources available, goals defined — and recommend next steps.

IMPORTANT: Ask me questions interactively — don't assume answers. Each STRATEGY.md section should reflect MY actual business, not generic examples.
