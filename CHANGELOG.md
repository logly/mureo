# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
