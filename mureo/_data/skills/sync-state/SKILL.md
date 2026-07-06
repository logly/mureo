---
name: sync-state
description: "Sync STATE.json with current campaign data from all platforms. Use when the user asks to refresh state, sync campaigns, update STATE.json from live data, or pull latest campaign snapshots."
metadata:
  version: 0.9.0
---

# Sync State

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Synchronize STATE.json with the current state of all marketing platforms.

## Prerequisites
- STRATEGY.md and STATE.json should exist in the current directory (run the `onboard` skill first if not)

## Steps

1. **Read current STATE.json** (if exists) to track changes.

2. **Discover platforms**: Identify all platforms registered in STATE.json `platforms` — built-in AND plugin/bridge platforms. Per `../_mureo-shared/SKILL.md` → *Plugin platforms*, also enumerate any installed entry-point plugin that exposes `mcp__mureo__<plugin>_*` tools; its STATE.json platform key is `plugin:<dist>` (the same convention mureo uses when promoting plugin mutations into `action_log`). Also enumerate any **hosted official-MCP connector** present in the session (e.g. TikTok's `tt-ads-*` tools) — its key is a first-class ad-platform key such as `tiktok_ads`; see `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.

3. **Fetch platform data**: For each registered platform:
   - **Google Ads**: prefer mureo native — call `google_ads_campaigns_list`, then `google_ads_performance_report` for the current period (last 30 days). Both work in BYOD and Live API modes. Keep the per-campaign numbers from the performance report — they become each campaign's `metrics` in step 7. If mureo's Google Ads tools are unavailable (e.g. `MUREO_DISABLE_GOOGLE_ADS=1` after `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP's equivalent campaign-list and performance-report tools for the same period.
   - **Meta Ads**: prefer mureo native — call `meta_ads_campaigns_list`, then `meta_ads_insights_report` for the current period — capture `result_indicator` per campaign so STATE.json reflects whether each campaign's "results" are clicks or real leads, and keep the per-campaign insight numbers for the `metrics` write in step 7. If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for the campaign list and insights; the `result_indicator` field is mureo-specific and will not be present — record the raw optimization goal / actions list per campaign in STATE.json instead and note that CV-definition disambiguation requires mureo's native MCP.
   - **Plugin / bridge platforms** (`plugin:<dist>`): where the plugin exposes a daily-report / insights / performance tool (infer from the live tool list — best-effort, not deterministic), call it for the current period and keep the per-campaign numbers for the `metrics` write in step 7. Honest scope per `../_mureo-shared/SKILL.md`: capture only the basic metrics the plugin's own tools return; **skip** mureo-only value-adds (`result_indicator` CV-mismatch, anomaly detection, RSA-asset audit, rule-based scoring) — they do not exist for plugins, so omit `result_indicator` for a plugin platform. If a plugin has no such reporting tool, leave its `metrics`/`totals` empty (it stays an advisory platform) and continue — never fail the whole sync because a plugin tool is missing.
   - **Hosted-connector platforms** (`tiktok_ads` etc.): call the hosted connector's own campaign-list / reporting tools (e.g. `tt-ads-*`) for the current period and keep the per-campaign numbers for the `metrics` write in step 7. Same honest scope as a plugin platform (basic metrics only; omit `result_indicator` and other mureo-only value-adds). If the connector has no reporting tool available, leave its `metrics`/`totals` empty and continue. See `../_mureo-shared/SKILL.md` → *Hosted-connector platforms*.
   - mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools — do **not** look for raw CSVs in the project directory.

4. **Check data sources**: If Search Console is configured, verify site access is still valid. If GA4 is available, verify connectivity.

5. **Detect new platforms**: If new platform credentials exist but have no entry in `platforms`, prompt the user to run `/onboard` to add them.

6. **Verify STRATEGY.md Data Sources**: If STRATEGY.md is missing a `## Data Sources` section (older setup), prompt the user to add it listing all configured platforms.

7. **Update STATE.json** with all campaign snapshots. **On the Code `Write` path, use the canonical STATE.json field names** — `campaign_name` (NOT the tool-output `name`), `campaign_id` (NOT `id`), and each platform's `account_id`; a snapshot/platform missing a required field is dropped by the reporting dashboard. See `../_mureo-shared/SKILL.md` → *STATE.json Schema*. For each campaign, also write the `metrics` you fetched in step 3 onto the snapshot: `spend`, `impressions`, `clicks`, `conversions`, `cpa`, `ctr`, the Meta `result_indicator` (when present), `period` (e.g. `LAST_30_DAYS`), and `fetched_at` (ISO 8601). On Code use `Write`; on Desktop / Cowork call `mureo_state_upsert_campaign` with the `metrics` object. Record the per-platform rollup on each `platforms[<platform>]` entry too — `totals` (summed `spend` / `clicks` / `conversions` / etc.), `metrics_period` (the period the totals cover, `LAST_30_DAYS` here), and the same totals under `periods["LAST_30_DAYS"]` (the per-window map the reporting dashboard's period toggle reads) — so the dashboard can render KPIs from STATE.json without re-querying. On Code write the rollup via `Write`; on Desktop / Cowork call `mureo_state_platform_metrics_set` (pass `platform`, `account_id`, `totals`, `metrics_period="LAST_30_DAYS"`, and `periods={"LAST_30_DAYS": {…}}`) — `mureo_state_upsert_campaign` writes per-campaign `metrics` only, never the platform rollup. `periods` merges per window key, so writing `LAST_30_DAYS` never clobbers a `YESTERDAY` bucket `daily-check` wrote. All metric fields are optional: omit any a platform doesn't provide rather than writing nulls. **Plugin / bridge platforms** use the SAME shape: persist their campaigns + best-effort `metrics` (canonical vocabulary, minus `result_indicator`) under platform key `plugin:<dist>` via `mureo_state_upsert_campaign` (pass `platform="plugin:<dist>"`), plus the per-platform `totals` / `metrics_period` / `periods["LAST_30_DAYS"]` via `mureo_state_platform_metrics_set` — so a bridge's KPIs land in the same `platforms` shape the dashboard reads. A plugin with no reporting tool keeps an entry with empty `metrics`/`totals` (advisory, no synced metrics).

8. **Show diff**: Compare old vs new state and highlight changes:
   - New campaigns added
   - Campaigns removed/paused
   - Budget changes
   - Status changes
   - Bidding strategy changes

9. **Update `last_synced_at`** timestamp.

If STATE.json doesn't exist yet, suggest running `/onboard` first.
