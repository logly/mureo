# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-04-10

### Fixed
- Google Ads OAuth setup fails with "Address already in use" when port 8085 is occupied. The local OAuth callback server now picks an available port automatically (port=0), matching the Meta Ads setup behavior.

## [0.3.0] - 2026-04-06

### Added
- Evidence-based learning feedback loop with `mureo-learning` skill
- `ActionLogEntry.metrics_at_action` field for recording metrics at action time
- `ActionLogEntry.observation_due` field for scheduling outcome evaluation
- Statistical thinking framework: observation windows, minimum sample sizes, evidence lifecycle (OBSERVING → CANDIDATE → VALIDATED)
- Noise guards in all 10 workflow commands to prevent premature optimization
- Google Search Console API client with 10 MCP tools, bringing total to 169
- Japanese README (README.ja.md)

### Changed
- All 10 workflow commands transformed to platform-agnostic orchestration (no hardcoded tool names)
- Commands now discover platforms at runtime from STATE.json `platforms` dict
- Search Console and GA4 integrated as data sources across all commands
- STATE.json format updated to v2 with multi-platform `platforms` dict
- SKILL.md version bumped to 0.3.0 with orchestration paradigm
- Workflow skill count increased from 5 to 6

### Fixed
- CONTEXT.md tool count corrected from 42 to 169
- Search Console tool reference pointed to correct documentation file

## [0.2.0] - 2026-03-31

### Added
- 78 new MCP tools (53 Google Ads + 25 Meta Ads), bringing total from 81 to 159
- Google Ads: sitelinks, callouts, conversion tracking, device/location/schedule targeting, recommendations, bid adjustments, change history, performance analysis, budget analysis, RSA asset analysis, B2B optimizations, creative research, landing page analysis, monitoring & goal evaluation, screenshot capture
- Meta Ads: campaign/ad set/ad pause & enable, audience get/delete/lookalike, creative list/create/dynamic, pixel management, performance analysis, audience analysis, placement analysis, cost investigation, ad comparison, creative improvement suggestions
- Handler tests for all 159 MCP tools (92 new tests, 1257 total)
- Project logo in README

### Changed
- Broadened project description from "Ad operations" to "Marketing operations" for multi-platform future
- Default branch renamed from `master` to `main`
- Split MCP tool definitions into category-based sub-modules for maintainability
- Split MCP handler files by domain (extensions, analysis, extended, other)

### Fixed
- All ruff lint errors (A002, F541, TC002, TC003, SIM102, SIM103, SIM105, SIM401, E402, E741, F811, F841, I001, UP037)
- All mypy type checking errors across Python 3.10 and 3.12
- Black formatting applied to all source files
- Bandit security warning (false-positive B104 on SSRF blocklist)
- Input validation: customer_id format, account_id prefix, file path traversal protection, URL scheme validation

### Security
- Added file extension validation on image/video upload handlers
- Added URL scheme validation on screenshot capture handler
- Added customer_id numeric format validation
- Added account_id `act_` prefix validation

## [0.1.0] - 2026-03-31

### Added
- Google Ads API client with 29 MCP tools (campaigns, ad groups, ads, keywords, budget, performance analysis, diagnostics, image upload)
- Meta Ads API client with 52 MCP tools (campaigns, ad sets, ads, creatives, audiences, pixels, insights, Conversions API, Lead Ads, Product Catalog, A/B testing, Ad Rules, videos, carousel, collection, Instagram, page posts)
- MCP server (stdio transport) for integration with AI agents
- CLI (Typer-based) with 15 commands for Google Ads, Meta Ads, and auth management
- Interactive setup wizard (`mureo auth setup`) with browser-based OAuth and account selection
- File-based strategy context (STRATEGY.md / STATE.json)
- Credential management (~/.mureo/credentials.json + environment variable fallback)
- Automatic MCP configuration placement (global or project-level)
- Comprehensive documentation (architecture, authentication, MCP server, CLI, strategy context, contributing)
- SKILL.md files for AI agent integration
