---
name: daily-check
description: "Run a daily health check on all configured ad accounts (Google Ads, Meta Ads, Search Console, GA4). Use when the user asks for a daily review, health check, status update, anomaly detection, or 'how are my campaigns doing today'. Reads STRATEGY.md and STATE.json, runs platform-specific health diagnostics, checks goal progress, evaluates pending action_log observations, and reports findings as Healthy / Watch / Action-needed."
metadata:
  version: 0.10.22
---

# Daily Check

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Run a daily health check on all marketing accounts using the strategy context.

## Prerequisites
- STRATEGY.md and STATE.json must exist in the current directory (run the `onboard` skill first if not)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.


1. **Load context**: Read STRATEGY.md (especially Operation Mode, Data Sources, and all Goal sections) and STATE.json.

2. **Discover available platforms**: Identify all configured platforms from STATE.json `platforms` and check which data sources (Search Console, GA4) are accessible. Also enumerate installed **plugin** platforms (`mcp__mureo__<plugin>_*` tools) and any **hosted official-MCP connector** present in the session (e.g. TikTok's `tt-ads-*` tools, STATE.json key `tiktok_ads`); include them best-effort — see `_mureo-shared` → *Plugin platforms* and *Hosted-connector platforms*.

3. **Sync state**: For each platform in STATE.json `platforms`, fetch current campaign data and update STATE.json.
   - **Google Ads**: prefer mureo native `google_ads_campaigns_list`. If mureo's Google Ads tools are unavailable (i.e. `MUREO_DISABLE_GOOGLE_ADS=1` was set when the user installed the official MCP via `mureo providers add google-ads-official`), fall back to the official `google-ads-official` MCP's equivalent campaign-list tool (typically `list_campaigns` or `report_campaigns`).
   - **Meta Ads**: prefer mureo native `meta_ads_campaigns_list`. If unavailable, fall back to the official `meta-ads-official` hosted MCP's campaign-list tool (the official MCP exposes the Marketing API surface, so basic listing is available).
   - **TikTok Ads (hosted connector, `tiktok_ads`)**: mureo has no native TikTok tools — call the TikTok connector's own campaign-list / reporting tools (e.g. `tt-ads-*`) for the current period, and write the per-campaign numbers to STATE.json via `mureo_state_upsert_campaign` (`platform="tiktok_ads"`). Skip mureo-only fields (`result_indicator`, anomaly, RSA audit). See `_mureo-shared` → *Hosted-connector platforms*.
   - mureo BYOD mode applies only to mureo native tools — do **not** look for raw CSVs in the project directory; mureo BYOD data is centralized in the workspace `byod/` directory (or `~/.mureo/byod/` for legacy CLI users) and is only accessible through mureo MCP tools.

4. **Platform health checks**: Run health diagnostics on each configured ad platform.
   - **Analytics-module check (external integrations only)**: Before running deep diagnostics on any platform that comes from a plugin or an official MCP, call `mureo_analytics_modules_list`. The response maps each platform to the set of advertised analytics capabilities (`detect_anomalies`, `diagnose_performance`, `audit_creative`, `analyze_budget_efficiency`). For each external-integration platform:
     - If a module is registered for the platform AND advertises the capability you need → run it (delegate to its `detect_anomalies` / `diagnose_performance` etc. via the platform-specific MCP tools it documents).
     - If no module is registered, or the registered module does not advertise the needed capability → report `analytics_not_available_for_<platform>` for the **module-specific** deep diagnostics (RSA audit, `result_indicator`, budget-efficiency), and do NOT fabricate heuristics from the integration's tool schemas (Issue #120). **BUT still run the generic, platform-agnostic `analysis_anomalies_check` per campaign** — pass the campaign's current metrics (from STATE.json / the connector's report, metric names normalized to `campaign_id`/`cost`/`clicks`/`impressions`/`conversions`/`cpa`/`ctr`). It builds a median baseline from `action_log` and flags zero-spend / CPA-spike / CTR-drop for TikTok, plugins, and official-MCP platforms too — this is a principled detector, not an auto-derived heuristic (see `_mureo-shared` → *analytics-module parity* → generic anomaly check).
   - **Google Ads** (built-in module — capabilities `detect_anomalies`, `diagnose_performance`): prefer mureo native — `google_ads_performance_report` (campaign-level metrics — works in BYOD), `google_ads_health_check_all` (returns `[]` in BYOD; only meaningful with Live API), `google_ads_cost_increase_investigate` (per-campaign anomaly check), `google_ads_monitoring_zero_conversions` (per-campaign). If mureo's Google Ads tools are unavailable, fall back to the official `google-ads-official` MCP for the basic performance report; **skip the mureo-only anomaly-detection tools** (`google_ads_health_check_all`, `google_ads_cost_increase_investigate`, `google_ads_monitoring_zero_conversions`) and note to the user that those checks require mureo's native MCP (install or re-enable via `mureo setup claude-code`).
   - **Meta Ads** (built-in module — capabilities `detect_anomalies`, `diagnose_performance`): prefer mureo native `meta_ads_insights_report` — surfaces a `result_indicator` field per campaign (`actions:link_click` vs `actions:offsite_conversion.fb_pixel_lead`); use this to detect CV-definition mismatches across campaigns where one campaign's "results" are clicks while another's are real leads. If mureo's Meta Ads tools are unavailable, fall back to the official `meta-ads-official` hosted MCP for the basic insights / campaign listing surface; note that the `result_indicator` analysis is a mureo-specific value-add and will not be present in the official MCP's responses.
   - In mureo BYOD some tools return `[]` for unsupported features (auction insights, ad performance) — that's by design, not missing data; carry on with the rest of the diagnostics.
   - Present a unified health summary across all platforms, including any `analytics_not_available_for_<platform>` notices.

5. **Mode-specific checks** based on Operation Mode:
   - **ONBOARDING_LEARNING**: This mode means the *campaign* is in its learning period — NOT merely that mureo was recently set up. First confirm it still applies: check each platform's learning status and the accumulated conversion history. If the campaigns are actually mature (well past the learning window, with accumulated conversions — common when mureo is added to an already long-running account), do **not** blindly warn "prioritize data accumulation". Instead proceed with the full analysis and proactively offer to switch the Operation Mode to a steady-state mode (e.g. `EFFICIENCY_STABILIZE`). Only hold back on changes when the data confirms a genuine learning period is still underway.
   - **EFFICIENCY_STABILIZE**: Analyze CPA trends across all platforms. Flag if CPA increased >10% on any platform.
   - **TURNAROUND_RESCUE**: Identify zero-conversion campaigns and cost spikes across all platforms.
   - **SCALE_EXPANSION**: Check budget utilization across all platforms. Flag underspending campaigns.
   - **COMPETITOR_DEFENSE**: Run auction/competitive insights on key campaigns. Flag impression share drops >5%.
   - **CREATIVE_TESTING**: Audit ad asset performance across all platforms. Flag underperforming creatives.
   - **LTV_QUALITY_FOCUS**: Review search term quality and audience alignment across all platforms.

6. **Organic search pulse** (if Search Console is available): Check top organic queries for the site. Identify any organic ranking drops that may need paid coverage, or organic gains where paid spend can be reduced.

7. **On-site behavior check** (if GA4 is available): Correlate ad platform metrics with on-site behavior — LP conversion rates, bounce rates, session quality. Flag discrepancies between ad platform and GA4 conversion data.

8. **Goal progress check**: For each Goal in STRATEGY.md, gather current metric values from all relevant platforms and data sources (ad platforms, GA4, Search Console) based on each Goal's declared platform/source. Present a Goal progress summary:
   ```
   Goal: CPA < 5,000 -- Platform A: 4,800 OK, Platform B: 6,200 OVER TARGET
   Goal: CV >= 100/month -- Platform A: 62, Platform B: 28, Total: 90 AT RISK
   Goal: Organic clicks +20% -- Search Console: +12% IN PROGRESS
   ```

9. **Evidence check**: Review `action_log` entries that have `observation_due` dates:
   - For entries whose observation window has passed: collect current metrics for the same campaign and call **`mureo_outcome_evaluate`** with `before` = the entry's `metrics_at_action` and `after` = the current metrics. It returns a deterministic per-metric + overall **improved / regressed / inconclusive** verdict (applying the ±noise band and metric directions for you) — use it instead of eyeballing the numbers, then report with the confidence it implies (see `_mureo-learning` skill). This tool is pure/platform-agnostic, so it works for **any** platform including hosted connectors and plugins — for those, first **normalize the connector's metric names to the standard keys** (`cpa`, `conversions`, `ctr`, `cost`, …) so they can be scored (unknown names are treated as neutral/no-verdict).
   - For entries still within their observation window: note them as "pending observation" and do NOT recommend further changes to those campaigns.
   - `platform="plugin:<dist>"` entries participate in this loop on equal footing with built-ins; they have no `metrics_at_action` baseline, so evaluate them **qualitatively/advisory** (see `_mureo-shared` → *Mutating plugin tools — structural strategy parity*).
   - Do NOT attribute metric movements to specific actions without checking sample sizes and observation windows.

10. **Report**: Summarize findings as:
    - Healthy — no action needed
    - Watch — minor issues to monitor
    - Action needed — requires immediate attention

    For each issue, suggest specific actions aligned with the current Operation Mode. Do NOT recommend actions based on single-day fluctuations — at least 7 consecutive days of critical metrics (>30% off target) before suggesting rescue.

11. **Update STATE.json**: Update campaign snapshots, add notes for flagged issues, and log this daily check to the `action_log` with a summary of findings. On the Code `Write` path, use the canonical STATE.json field names — `campaign_name` (NOT the tool-output `name`), `campaign_id`, and each platform's `account_id`; a snapshot/platform missing a required field is dropped by the reporting dashboard. On the Code `Write` path also **stamp the top-level `last_synced_at` to now** so the dashboard's "Synced N ago" freshness reflects this run (the `mureo_state_upsert_campaign` / `_platform_metrics_set` tools set it for you). See `../_mureo-shared/SKILL.md` → *STATE.json Schema*.

12. **Persist the report summary** (best-effort): Call `mureo_state_report_set` with `report="daily"` and a concise `summary` object so the read-only dashboard can render this report without re-running you. Follow this convention:
    - `generated_at`: ISO 8601 timestamp of this run
    - `period`: the day reviewed (e.g. `"2026-06-17"`)
    - `kpis`: per-platform and/or totals headline numbers (spend, conversions, cpa, ctr)
    - `flags`: a list of notable items (e.g. `["cpa_over_target_google_ads"]`)
    - `narrative`: a short text summary (the Healthy / Watch / Action-needed verdict in 1-2 sentences)

    **Reflect the FINAL state, and persist this LAST.** Write this summary
    AFTER every STATE change and `action_log` entry you made this run (it is
    the last persistence step — keep it after any Operation Mode switch,
    campaign pause, budget edit, etc.). If you changed something, the
    `narrative` + `flags` must describe the POST-change state (e.g.
    "switched to `EFFICIENCY_STABILIZE`", not "recommend switching"; flag
    `operation_mode_switched`, not a now-resolved recommendation). Stamp
    `generated_at` at the moment you write this — so the dashboard's
    "Latest report" is never an older snapshot that contradicts the action
    log or STRATEGY.md. (If you only *recommended* a change and did NOT make
    it, the recommendation wording is correct — and there is then no matching
    `action_log` entry, so nothing contradicts it.)

    This is best-effort: if `mureo_state_report_set` is unavailable (e.g. a pure file-mode host without the context MCP), skip it silently — the rest of this skill still works.

13. **Persist per-window per-platform rollups** (best-effort): so the reporting dashboard's KPI tiles AND its *Yesterday / Last 30 days* period toggle have data, write each platform's totals to `platforms[<platform>].periods[<window>]` using the canonical metric vocabulary (`spend`, `impressions`, `clicks`, `conversions`, `cpa`, `ctr`, the Meta `result_indicator` when present). Write **every window whose numbers you already gathered this run** — typically `YESTERDAY` (the prior-day totals) and `LAST_30_DAYS` (the trailing-30-day totals your step-4 health checks / step-8 goal progress already pulled). The period toggle only appears once **two** windows have data, so populating `LAST_30_DAYS` here — from numbers you already hold — is what makes the toggle show even when a separate `sync-state` run has not happened. On Code use `Write`; on Desktop / Cowork call `mureo_state_platform_metrics_set` (pass `platform`, `account_id`, and `periods={"YESTERDAY": {…}, "LAST_30_DAYS": {…}}` — include only the windows you actually have) — it merges per window key, so this never disturbs a window a prior `sync-state` wrote. **Honest scope / cost:** only write a window whose numbers you actually pulled; do **not** fire an extra API call solely to populate a window. If you only pulled one window, write just that one (and never mislabel a wider window as `YESTERDAY`). Best-effort: if `mureo_state_platform_metrics_set` is unavailable, skip silently.
