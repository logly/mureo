Run a daily health check on all marketing accounts using the strategy context.

## Prerequisites
- STRATEGY.md and STATE.json must exist in the current directory (run `/onboard` first if not)

## Steps

1. **Load context**: Read STRATEGY.md (especially Operation Mode, Data Sources, and all Goal sections) and STATE.json.

2. **Discover available platforms**: Identify all configured platforms from STATE.json `platforms` and check which data sources (Search Console, GA4) are accessible.

3. **Sync state**: For each platform in STATE.json `platforms`, fetch current campaign data via `google_ads.campaigns.list` / `meta_ads.campaigns.list` and update STATE.json. Both tools work in BYOD mode — do **not** look for raw CSVs in the project directory; mureo BYOD data is centralized under `~/.mureo/byod/` and is only accessible through MCP tools.

4. **Platform health checks**: Run health diagnostics on each configured ad platform:
   - **Google Ads**: `google_ads.performance.report` (campaign-level metrics — works in BYOD), `google_ads.health_check.all` (returns `[]` in BYOD; only meaningful with real-API), `google_ads.cost_increase.investigate` (per-campaign anomaly check), `google_ads.zero_conversions.diagnose` (per-campaign).
   - **Meta Ads**: `meta_ads.insights.report` — surfaces a `result_indicator` field per campaign (`actions:link_click` vs `actions:offsite_conversion.fb_pixel_lead`); use this to detect CV-definition mismatches across campaigns where one campaign's "results" are clicks while another's are real leads.
   - In BYOD some tools return `[]` for unsupported features (auction insights, ad performance) — that's by design, not missing data; carry on with the rest of the diagnostics.
   - Present a unified health summary across all platforms.

5. **Mode-specific checks** based on Operation Mode:
   - **ONBOARDING_LEARNING**: Check learning status on each platform. Warn against making changes.
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
   - For entries whose observation window has passed: collect current metrics for the same campaign, compare with `metrics_at_action`, and evaluate the outcome. Report findings with confidence level (see `mureo-learning` skill).
   - For entries still within their observation window: note them as "pending observation" and do NOT recommend further changes to those campaigns.
   - Do NOT attribute metric movements to specific actions without checking sample sizes and observation windows.

10. **Report**: Summarize findings as:
    - Healthy — no action needed
    - Watch — minor issues to monitor
    - Action needed — requires immediate attention

    For each issue, suggest specific actions aligned with the current Operation Mode. Do NOT recommend actions based on single-day fluctuations — at least 7 consecutive days of critical metrics (>30% off target) before suggesting rescue.

11. **Update STATE.json**: Update campaign snapshots, add notes for flagged issues, and log this daily check to the `action_log` with a summary of findings.
