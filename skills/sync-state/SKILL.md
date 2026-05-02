---
name: sync-state
description: "Sync STATE.json with current campaign data from all platforms. Use when the user asks to refresh state, sync campaigns, update STATE.json from live data, or pull latest campaign snapshots."
metadata:
  version: 0.7.1
---

# Sync State

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Synchronize STATE.json with the current state of all marketing platforms.

## Prerequisites
- STRATEGY.md and STATE.json should exist in the current directory (run the `onboard` skill first if not)

## Steps

1. **Read current STATE.json** (if exists) to track changes.

2. **Discover platforms**: Identify all platforms registered in STATE.json `platforms`.

3. **Fetch platform data**: For each registered platform:
   - **Google Ads**: Call `google_ads_campaigns_list`, then `google_ads_performance_report` for the current period (last 30 days). Both work in BYOD and Live API modes.
   - **Meta Ads**: Call `meta_ads_campaigns_list`, then `meta_ads_insights_report` for the current period — capture `result_indicator` per campaign so STATE.json reflects whether each campaign's "results" are clicks or real leads.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through MCP tools — do **not** look for raw CSVs in the project directory.

4. **Check data sources**: If Search Console is configured, verify site access is still valid. If GA4 is available, verify connectivity.

5. **Detect new platforms**: If new platform credentials exist but have no entry in `platforms`, prompt the user to run `/onboard` to add them.

6. **Verify STRATEGY.md Data Sources**: If STRATEGY.md is missing a `## Data Sources` section (older setup), prompt the user to add it listing all configured platforms.

7. **Update STATE.json** with all campaign snapshots.

8. **Show diff**: Compare old vs new state and highlight changes:
   - New campaigns added
   - Campaigns removed/paused
   - Budget changes
   - Status changes
   - Bidding strategy changes

9. **Update `last_synced_at`** timestamp.

If STATE.json doesn't exist yet, suggest running `/onboard` first.
