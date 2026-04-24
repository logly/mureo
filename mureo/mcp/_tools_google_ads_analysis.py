"""Google Ads tool definitions — Performance analysis, search terms, auctions, monitoring, capture.

Tool descriptions follow ``docs/tdqs-style-guide.md``: specific verb, returned
fields, side effects, and differentiation from sibling tools. See the guide
before adding a new tool or rewriting an existing one.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments — keep descriptions consistent across tools.
_CUSTOMER_ID_PARAM = {
    "type": "string",
    "description": (
        "Google Ads customer ID as a 10-digit string without dashes "
        "(e.g. '1234567890'). Optional — falls back to "
        "GOOGLE_ADS_CUSTOMER_ID / GOOGLE_ADS_LOGIN_CUSTOMER_ID from the "
        "configured credentials when omitted."
    ),
}

_PERIOD_PARAM = {
    "type": "string",
    "enum": [
        "TODAY",
        "YESTERDAY",
        "LAST_7_DAYS",
        "LAST_14_DAYS",
        "LAST_30_DAYS",
        "LAST_90_DAYS",
        "THIS_MONTH",
        "LAST_MONTH",
    ],
    "description": (
        "Reporting window for the metrics. Default 'LAST_30_DAYS'. Use a "
        "shorter window (LAST_7_DAYS / LAST_14_DAYS) when diagnosing recent "
        "changes; use LAST_90_DAYS for trend baselines."
    ),
}

_CAMPAIGN_ID_PARAM = {
    "type": "string",
    "description": (
        "Campaign ID as a numeric string without dashes "
        "(e.g. '23743184133'). Obtain via google_ads.campaigns.list."
    ),
}

_CAMPAIGN_ID_FILTER_PARAM = {
    "type": "string",
    "description": (
        "Optional campaign ID as a numeric string (e.g. '23743184133') to "
        "restrict the report to a single campaign. Omit to aggregate across "
        "every campaign in the account."
    ),
}

_AD_GROUP_ID_FILTER_PARAM = {
    "type": "string",
    "description": (
        "Optional ad group ID as a numeric string (e.g. '145680123456') to "
        "restrict results to a single ad group. Omit to include every ad "
        "group matching the campaign filter."
    ),
}

_SHORT_PERIOD_PARAM = {
    "type": "string",
    "enum": [
        "TODAY",
        "YESTERDAY",
        "LAST_7_DAYS",
        "LAST_14_DAYS",
        "LAST_30_DAYS",
        "LAST_90_DAYS",
        "THIS_MONTH",
        "LAST_MONTH",
    ],
    "description": (
        "Reporting window for the metrics. Default 'LAST_7_DAYS' — this tool "
        "is tuned for short-horizon comparison. Use LAST_14_DAYS or "
        "LAST_30_DAYS for longer baselines."
    ),
}


TOOLS: list[Tool] = [
    # === Analysis ===
    Tool(
        name="google_ads.performance.report",
        description=(
            "Aggregate campaign-level performance metrics for a Google Ads "
            "account over a reporting window. Returns one row per campaign "
            "shaped as {campaign_id, campaign_name, metrics}, where the "
            "metrics object contains impressions, clicks, cost_micros, cost "
            "(currency-formatted), conversions, ctr, average_cpc_micros, "
            "average_cpc, cost_per_conversion_micros, and "
            "cost_per_conversion. Read-only; no mutation. Use this for "
            "campaign-level totals. For per-ad breakdowns use "
            "google_ads.ad_performance.report; for Google Search vs. "
            "Search Partners splits use "
            "google_ads.network_performance.report; for query-level detail "
            "use google_ads.search_terms.report; for conversion-action "
            "slicing use google_ads.conversions.performance."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict the report to a single campaign by numeric "
                        "ID (e.g. '23743184133'). Omit to aggregate across "
                        "every campaign in the account."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.search_terms.report",
        description=(
            "List actual user search queries that triggered ads in the "
            "account over a reporting window. Returns one row per search "
            "term shaped as {search_term, metrics}, where the metrics "
            "object contains impressions, clicks, cost_micros, cost "
            "(currency-formatted), conversions, and ctr. The rows are "
            "filterable by campaign_id and/or ad_group_id but those IDs "
            "are NOT echoed back in the output — scope your query before "
            "calling. Read-only. Use this for raw query logs when you need "
            "to eyeball the terms yourself. For rule-based add/exclude "
            "candidates use google_ads.search_terms.review; for "
            "intent-class distribution use google_ads.search_terms.analyze; "
            "for campaign-level aggregates without query breakdown use "
            "google_ads.performance.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Restrict results to a single campaign by numeric "
                        "ID. Omit to include all campaigns."
                    ),
                },
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Restrict results to a single ad group by numeric "
                        "ID. Omit to include all ad groups under the "
                        "campaign filter (or the entire account if "
                        "campaign_id is also omitted)."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.search_terms.review",
        description=(
            "Score every search term in a Google Ads campaign against six "
            "hardcoded rules and split them into add / exclude / watch "
            "buckets. Returns {campaign_id, ad_group_id, period, "
            "target_cpa, target_cpa_source, add_candidates, "
            "exclude_candidates, watch_candidates, summary:{"
            "total_search_terms, add_count, exclude_count, watch_count}, "
            "intent_analysis?}. Each candidate has {search_term, action, "
            "match_type ('EXACT'|'PHRASE'), score (40-90), reason, "
            "metrics:{conversions, clicks, cost, ctr}}. target_cpa is "
            "resolved from the explicit argument first, then the "
            "campaign's bidding strategy, then last-30-days actual CPA; "
            "target_cpa_source reports which path ('explicit'|"
            "'bidding_strategy'|'actual'|'none'). New terms absent from "
            "the previous period are routed to watch_candidates. "
            "Read-only — emits candidates but does not add or exclude "
            "anything. Default period is LAST_7_DAYS. For keyword/N-gram "
            "overlap stats use google_ads.search_terms.analyze; for the "
            "raw query log use google_ads.search_terms.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _SHORT_PERIOD_PARAM,
                "target_cpa": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Optional explicit target CPA in account currency "
                        "(e.g. 3000 = ¥3,000). Exclusion rule 4 fires at "
                        "cost >= target_cpa * 2. Falls back to the "
                        "campaign's bidding strategy target, then "
                        "last-30-days actual CPA; if none can be resolved, "
                        "CPA-gated rules are skipped."
                    ),
                },
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.auction_insights.analyze",
        description=(
            "Interpret a campaign's impression-share metrics and surface "
            "human-readable insights about competitive position. Returns "
            "{campaign_id, campaign_name, period, impression_share_metrics:"
            "{search_impression_share, search_rank_lost_is, "
            "search_budget_lost_is, search_top_is, search_abs_top_is, "
            "note}, insights:[strings], note}. Each impression-share "
            "value is a percentage (0-100, rounded to 1 decimal) or None. "
            "Insights fire when IS < 50/70%, rank-lost > 20%, "
            "budget-lost > 20%, or abs-top-IS < 20%. Read-only. Note: "
            "Google Ads API v23 removed competitor-level auction_insight "
            "(domain overlap, outranking share); only impression-share "
            "proxies are returned. For the raw metrics without insights "
            "use google_ads.auction_insights.get; full competitor data is "
            "only available in the Google Ads UI."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.cpc.detect_trend",
        description=(
            "Detect rising/falling CPC trends in a Google Ads campaign "
            "over a reporting window using daily segmentation and linear "
            "regression. Returns {campaign_id, campaign_name, period, "
            "data_points, daily_data:[{date, average_cpc, clicks, "
            "impressions, cost}], trend:{direction "
            "('rising'|'falling'|'stable'|'insufficient_data'), "
            "slope_per_day, change_rate_per_day_pct? (present only "
            "when direction is not 'insufficient_data' — i.e. when "
            "at least 2 daily data points are available), avg_cpc, "
            "min_cpc, max_cpc}, insights:[strings]}. Direction is "
            "'rising' when "
            "daily change > +1%, 'falling' when < -1%. Days with zero "
            "clicks are excluded from the GAQL. Insights call out "
            "week-over-week surges >15% and days exceeding 2x average "
            "CPC. Read-only. For device or auction-share investigation "
            "use google_ads.device.analyze or "
            "google_ads.auction_insights.analyze."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.device.analyze",
        description=(
            "Compare Google Ads campaign performance across device "
            "segments (Desktop / Mobile / Tablet). Returns {campaign_id, "
            "campaign_name, period, devices:[{device_type, impressions, "
            "clicks, cost, conversions, ctr (percent), average_cpc, cpa, "
            "cvr (percent)}], insights:[strings]}, sorted by cost "
            "descending. cpa is None when conversions == 0. Insights "
            "fire for devices with spend and zero conversions, "
            "worst/best CPA ratios > 1.5x, and Mobile CTR less than half "
            "of Desktop CTR. Read-only. Returns a 'message' field and "
            "empty devices list when no device-segmented data exists. "
            "For applying device bid modifiers use "
            "google_ads.bid_adjustments.update or "
            "google_ads.device_targeting.set; for the raw "
            "ad-schedule criteria (hour-of-day targeting config, "
            "NOT performance segmentation by hour) use "
            "google_ads.schedule_targeting.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    # === Network performance report ===
    Tool(
        name="google_ads.network_performance.report",
        description=(
            "Report Google Ads performance split by ad network — Google "
            "Search vs. Search Partners. Returns one row per (campaign, "
            "network) shaped as {campaign_id, campaign_name, "
            "network_type ('SEARCH'|'SEARCH_PARTNERS'), network_label "
            "('Google Search'|'Search Partners'), impressions, clicks, "
            "cost, conversions, ctr (percent), average_cpc, "
            "cost_per_conversion}. Display, YouTube, and Discover rows "
            "are filtered out. ctr, average_cpc, and cost_per_conversion "
            "are rounded to whole-unit currency. Read-only. Use this to "
            "decide whether to toggle Search Partners. For overall "
            "campaign totals use google_ads.performance.report; for "
            "per-ad breakdowns use google_ads.ad_performance.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_FILTER_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    # === Per-ad report ===
    Tool(
        name="google_ads.ad_performance.report",
        description=(
            "Report per-ad performance across Google Ads ad_group_ad "
            "rows. Returns one row per ad shaped as {ad_id, ad_type, "
            "status ('ENABLED'|'PAUSED'|'REMOVED'), ad_group_id, "
            "ad_group_name, campaign_id, campaign_name, metrics} where "
            "metrics contains impressions, clicks, cost_micros, cost "
            "(currency), conversions, ctr, average_cpc_micros, "
            "average_cpc, cost_per_conversion_micros, "
            "cost_per_conversion. Filterable by ad_group_id and/or "
            "campaign_id (both optional, both numeric). Read-only; no "
            "mutation. For ENABLED-only A/B comparison within a single "
            "ad group with WINNER/LOSER verdicts use "
            "google_ads.ad_performance.compare; for campaign-level "
            "aggregates use google_ads.performance.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": _AD_GROUP_ID_FILTER_PARAM,
                "campaign_id": _CAMPAIGN_ID_FILTER_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    # === Search Term Analysis ===
    Tool(
        name="google_ads.search_terms.analyze",
        description=(
            "Analyze keyword/search-term overlap and N-gram distribution "
            "for a Google Ads campaign. Returns {campaign_id, period, "
            "registered_keywords_count, search_terms_count, overlap_rate "
            "(0.0-1.0), ngram_distribution:{unigrams, bigrams, trigrams} "
            "(each top-10 of {text, count, cost, conversions}), "
            "keyword_candidates:[{search_term, conversions, cost, "
            "clicks}] (CV>0 and not yet registered), "
            "negative_candidates:[{search_term, cost, clicks, "
            "impressions}] (top 20 by cost with cost>0 and "
            "conversions=0), insights:[strings]}. Read-only. For "
            "rule-scored add/exclude/watch buckets use "
            "google_ads.search_terms.review; for the raw unscored term "
            "log use google_ads.search_terms.report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    # === Performance analysis ===
    Tool(
        name="google_ads.performance.analyze",
        description=(
            "Diagnose a single Google Ads campaign by composing "
            "current-vs-previous comparison, top search terms, Google "
            "recommendations, and recent change history. Returns "
            "{campaign_id, period, campaign (get_campaign shape), "
            "performance_current, performance_previous, changes:{"
            "impressions_change_pct, clicks_change_pct, cost_change_pct, "
            "conversions_change_pct}, cpa_current? (only when "
            "current-period conversions > 0), cpa_previous? (only when "
            "previous-period conversions > 0), cpa_change_pct? (only "
            "when both above are present), top_search_terms (top 20 by "
            "cost), "
            "recommendations_from_google (up to 10), recent_changes (up "
            "to 10), issues:[strings], insights:[strings], "
            "recommendations:[strings]}. Any subcomponent that fails is "
            "replaced with the string 'Retrieval failed' rather than "
            "aborting the call. Read-only. Default period is "
            "LAST_7_DAYS. For cost-spike root-cause analysis use "
            "google_ads.cost_increase.investigate; for account-wide "
            "health use google_ads.health_check.all."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _SHORT_PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.cost_increase.investigate",
        description=(
            "Investigate the root cause of a Google Ads cost spike or "
            "CPA deterioration by comparing the last 7 days against the "
            "prior 7 days. Returns {campaign_id, "
            "performance_current_7d, performance_previous_7d, changes, "
            "cost_breakdown:{cpc_current, cpc_previous, cpc_change_pct, "
            "clicks_current, clicks_previous, clicks_change_pct}, "
            "new_search_terms (top 20 by cost), wasteful_search_terms "
            "(top 20 zero-CV terms with cost), bid_budget_changes (up "
            "to 10 CAMPAIGN/CAMPAIGN_BUDGET/AD_GROUP/"
            "CAMPAIGN_BID_MODIFIER events from change history), "
            "existing_negative_keywords_count, "
            "negative_keyword_candidates (up to 10), findings:[strings], "
            "recommended_actions:[strings]}. The comparison window is "
            "hardcoded to LAST_7_DAYS. Read-only. For a broader "
            "diagnostic composite use google_ads.performance.analyze; "
            "for CPA-vs-target monitoring use "
            "google_ads.monitoring.cpa_goal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.health_check.all",
        description=(
            "Screen every campaign in the Google Ads account by "
            "primary_status and run detailed delivery diagnostics on up "
            "to 5 problem/warning campaigns. Returns {total_campaigns, "
            "enabled_count, paused_count, removed_count, "
            "healthy_campaigns (ELIGIBLE), warning_campaigns (other "
            "primary_status among ENABLED), problem_campaigns "
            "(NOT_ELIGIBLE/ENDED/REMOVED among ENABLED — each: "
            "{campaign_id, name, primary_status}), detailed_diagnostics:"
            "[{campaign_id, name, issues, warnings, recommendations}] "
            "(up to 5; problem-first, then warning), summary:"
            "{total_enabled, healthy, warning, problem, message}}. "
            "Read-only. For single-campaign delivery diagnosis use "
            "google_ads.campaigns.diagnose; for CPA-goal monitoring use "
            "google_ads.monitoring.cpa_goal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.ad_performance.compare",
        description=(
            "Rank ENABLED ads within a single Google Ads ad group and "
            "assign WINNER / LOSER / INSUFFICIENT_DATA verdicts. Returns "
            "{ad_group_id, period, ads:[{ad_id, impressions, clicks, "
            "conversions, cost, ctr, cvr, cpa, score (ctr*cvr, or ctr "
            "when conversions=0), rank, verdict, headlines?, "
            "descriptions?}], winner, recommendation, "
            "insights:[strings]}. Ads with impressions < 100 are flagged "
            "INSUFFICIENT_DATA; all ads tied at the top score receive "
            "WINNER, the rest LOSER. Read-only — does not pause or "
            "rotate ads. For cross-ad-group per-ad reporting use "
            "google_ads.ad_performance.report; for RSA asset-level "
            "splits use google_ads.rsa_assets.analyze."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "ad_group_id": {
                    "type": "string",
                    "description": (
                        "Ad group ID as a numeric string "
                        "(e.g. '145680123456'). Required — comparison "
                        "is always scoped to one ad group so the ads "
                        "share targeting. Obtain via "
                        "google_ads.ad_groups.list."
                    ),
                },
                "period": _PERIOD_PARAM,
            },
            "required": ["ad_group_id"],
        },
    ),
    # === Budget analysis ===
    Tool(
        name="google_ads.budget.efficiency",
        description=(
            "Score budget allocation efficiency across every ENABLED "
            "Google Ads campaign. Returns {period, total_cost, "
            "total_conversions, campaigns:[{campaign_id, name, cost, "
            "conversions, cost_share, cv_share, efficiency_ratio "
            "(cv_share / cost_share), verdict ('EFFICIENT' when ratio "
            "> 1.2, 'INEFFICIENT' when < 0.8, 'NORMAL' otherwise, "
            "'NO_COST' when cost==0), cpa}], recommendations:[strings], "
            "insights:[strings]}. Per-campaign cost/conversions come "
            "from get_performance_report — individual failures are "
            "silently treated as zero. Read-only. For a concrete "
            "DECREASE/INCREASE reallocation plan use "
            "google_ads.budget.reallocation; to change a single budget "
            "use google_ads.budget.update."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    Tool(
        name="google_ads.budget.reallocation",
        description=(
            "Propose a budget reallocation plan by cutting up to 20% "
            "from INEFFICIENT campaigns and distributing the freed "
            "amount equally across EFFICIENT campaigns. Returns the "
            "full google_ads.budget.efficiency payload plus "
            "{reallocation_plan:[{campaign_id, campaign_name, action "
            "('DECREASE'|'INCREASE'), current_daily_budget, "
            "proposed_daily_budget, change_amount, reason}], "
            "total_freed, summary}. When the account has no campaigns "
            "with spend in the window, the response short-circuits to "
            "just {...efficiency payload, reallocation_plan:[], "
            "summary:'No campaigns with spend in period'} and the "
            "total_freed key is omitted — parse defensively. Reductions "
            "below 100 (currency units) are skipped. Current daily "
            "budgets are fetched via get_budget — failures fall back "
            "to 0. Read-only — emits a "
            "plan only, does not apply any budget changes. To actually "
            "apply a change use google_ads.budget.update; for the "
            "efficiency scoring alone use google_ads.budget.efficiency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": [],
        },
    ),
    # === Auction insights ===
    Tool(
        name="google_ads.auction_insights.get",
        description=(
            "Fetch raw impression-share metrics for one Google Ads "
            "campaign. Returns a list with a single entry: {campaign_id, "
            "campaign_name, search_impression_share, "
            "search_rank_lost_is, search_budget_lost_is, search_top_is, "
            "search_abs_top_is, note} — every IS field is a percentage "
            "(0-100, float, rounded to 1 decimal) or None. On failure "
            "returns a single-element list with {error:"
            "'auction_insights_unavailable'|'no_data', reason, hint}. "
            "Read-only. Note: Google Ads API v23 removed "
            "competitor-level auction_insight (domain, overlap, "
            "outranking); only impression-share proxies are returned. "
            "For a version with human-readable insights layered on top "
            "use google_ads.auction_insights.analyze."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    # === RSA analysis ===
    Tool(
        name="google_ads.rsa_assets.analyze",
        description=(
            "Split Responsive Search Ad asset performance within a "
            "Google Ads campaign into headlines and descriptions. "
            "Returns {campaign_id, period, headlines:[{text, "
            "performance_label ('BEST'|'GOOD'|'LOW'|'POOR'|"
            "'LEARNING'|'PENDING'|'UNKNOWN'), impressions, clicks, "
            "conversions, cost, ctr (percent)}], descriptions (same "
            "shape), best_headlines (performance_label == 'BEST'), "
            "worst_headlines ('LOW'|'POOR'), best_descriptions, "
            "worst_descriptions, insights:[strings]}. Rows sorted by "
            "impressions descending. Read-only. For an audit version "
            "with replacement recommendations use "
            "google_ads.rsa_assets.audit; for ad-level A/B use "
            "google_ads.ad_performance.compare."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.rsa_assets.audit",
        description=(
            "Audit Responsive Search Ad assets against Google's "
            "quantity and quality guidance and emit replacement "
            "recommendations. Returns {campaign_id, period, "
            "headline_count, description_count, label_distribution:{"
            "<label>:count}, best_headlines, worst_headlines, "
            "best_descriptions, worst_descriptions, recommendations:[{"
            "type ('add_headlines'|'add_descriptions'|"
            "'replace_headline'|'replace_description'|'wait_for_data'), "
            "priority ('HIGH'|'MEDIUM'|'LOW'), message, asset_text?, "
            "performance_label?}], recommendation_count}. HIGH "
            "priorities fire when headlines < 8 or descriptions < 3. "
            "LOW 'wait_for_data' fires when LEARNING+UNKNOWN > 50% of "
            "assets. Read-only; does not modify any assets. For the "
            "raw per-asset performance breakdown use "
            "google_ads.rsa_assets.analyze."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    # === BtoB ===
    Tool(
        name="google_ads.btob.optimizations",
        description=(
            "Run three B2B-specific optimization checks (ad schedule, "
            "device CPA disparity, informational-query ratio) against a "
            "Google Ads campaign. Returns {campaign_id, campaign_name, "
            "period, suggestion_count, suggestions:[{category "
            "('schedule'|'device'|'search_terms'), priority ('HIGH'|"
            "'MEDIUM'|'LOW'), message}]}. Schedule fires HIGH when no "
            "ad schedule is set, MEDIUM for weekend delivery. Device "
            "fires MEDIUM when Mobile CPA > Desktop CPA * 1.3, LOW when "
            "Tablet has zero conversions with spend. Search-terms fires "
            "MEDIUM when informational patterns exceed 20% of queries. "
            "Read-only. Use this when the advertiser self-identifies as "
            "B2B. For general campaign diagnosis use "
            "google_ads.performance.analyze."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "period": _PERIOD_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    # === Creative ===
    Tool(
        name="google_ads.landing_page.analyze",
        description=(
            "Fetch a landing page over HTTP(S) and extract structured "
            "content for ad-copy alignment. Returns title, meta_description, "
            "h1_texts, h2_texts, main_text (truncated to 1500 chars), "
            "cta_texts, features (list-item snippets, capped at 30), "
            "prices (JP yen patterns), brand_name, industry_hints, "
            "og_title, og_description, and structured_data (up to 5 "
            "JSON-LD blocks). On fetch or parse failure, returns the same "
            "shape with an ``error`` field set instead of raising. Side "
            "effect: issues one outbound HTTP GET to the URL with a 15s "
            "timeout, a 500KB body cap, up to 5 redirects, and a "
            "'MarketingAgent/1.0' User-Agent; SSRF-protected against "
            "localhost, private / link-local / reserved IP ranges, and "
            "cloud metadata endpoints (redirect targets are re-validated). "
            "The Google Ads customer context is unused by the analysis "
            "itself — passing customer_id only scopes credential routing. "
            "Use this for ad-copy vs. LP message-match and "
            "keyword-extraction workflows. For Google's indexing/coverage "
            "view of the same URL use search_console.url_inspection.inspect; "
            "for a batched workflow that combines LP analysis with "
            "existing ads, search terms, and keyword suggestions use "
            "google_ads.creative.research."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "Absolute landing page URL to fetch (http:// or "
                        "https:// scheme only, e.g. "
                        "'https://example.com/lp/offer'). Private-range, "
                        "loopback, and cloud-metadata hosts are rejected."
                    ),
                },
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="google_ads.creative.research",
        description=(
            "Collect every input an LLM needs to draft or refresh "
            "Google Ads creative for a single campaign. Returns "
            "{campaign_id, url, lp_analysis (same shape as "
            "google_ads.landing_page.analyze), existing_ads:[{ad_id, "
            "headlines, descriptions, final_urls, impressions, clicks, "
            "conversions, ctr}] (top 5 RSA ads by impressions, REMOVED "
            "excluded), search_term_insights:{high_cv_terms (top 10 by "
            "conversions), high_click_terms (top 10 by clicks), "
            "total_terms}, keyword_suggestions (KeywordPlanIdeaService "
            "output for up to 5 seeds derived from LP title + h1 + "
            "meta_description), existing_keywords (list_keywords "
            "output), context_summary (string)}. Any failing sub-step "
            "is replaced with the literal string '取得失敗' so the "
            "envelope never raises. Side effect: one outbound LP fetch "
            "(same SSRF policy as google_ads.landing_page.analyze) plus "
            "several GAQL queries. For just the LP use "
            "google_ads.landing_page.analyze; for just RSA asset "
            "diagnostics use google_ads.rsa_assets.analyze."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "Absolute landing page URL to analyze (http:// "
                        "or https:// only, e.g. "
                        "'https://example.com/lp/'). SSRF-protected — "
                        "private-range, loopback, and cloud-metadata "
                        "hosts are rejected."
                    ),
                },
                "ad_group_id": _AD_GROUP_ID_FILTER_PARAM,
            },
            "required": ["campaign_id", "url"],
        },
    ),
    # === Monitoring ===
    Tool(
        name="google_ads.monitoring.delivery_goal",
        description=(
            "Check whether a Google Ads campaign is actively delivering "
            "yesterday by composing campaign info, delivery diagnostics, "
            "and yesterday's performance. Returns {campaign_id, "
            "campaign, diagnosis:{issues, warnings, recommendations, "
            "...}, performance (list of yesterday rows with metrics), "
            "status ('critical'|'warning'|'healthy'), issues:[strings], "
            "summary, suggested_workflow?}. 'critical' fires when "
            "delivery diagnostics have issues, the campaign is not "
            "ENABLED, or yesterday impressions == 0. 'warning' fires "
            "for diagnostic warnings or impressions 1-9. "
            "suggested_workflow is set to 'delivery_fix' when status != "
            "'healthy'. Read-only. For the raw diagnostics without the "
            "yesterday composite use google_ads.campaigns.diagnose; for "
            "CPA-target evaluation use google_ads.monitoring.cpa_goal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    Tool(
        name="google_ads.monitoring.cpa_goal",
        description=(
            "Evaluate a Google Ads campaign's last-7-days CPA against a "
            "user-supplied target and integrate cost-increase analysis. "
            "Returns {campaign_id, target_cpa, current_cpa (float or "
            "None when conversions==0), cost_analysis (full "
            "google_ads.cost_increase.investigate payload), "
            "wasteful_terms (top 5 zero-CV cost terms from "
            "cost_analysis), deviation_pct, status ('healthy' when "
            "current<=target, 'warning' when <=target*1.2 or when "
            "CV==0, 'critical' when >target*1.2), issues:[strings], "
            "summary, suggested_workflow?}. The CPA window is hardcoded "
            "to LAST_7_DAYS. Read-only; does not change bids. For "
            "account-wide rollup use google_ads.health_check.all; for "
            "daily CV-count vs target use google_ads.monitoring.cv_goal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "target_cpa": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Target cost per acquisition in account "
                        "currency (e.g. 3000 = ¥3,000). Required — "
                        "this tool does NOT fall back to bidding-"
                        "strategy or actual CPA. 'warning' threshold is "
                        "target_cpa * 1.2; above that is 'critical'."
                    ),
                },
            },
            "required": ["campaign_id", "target_cpa"],
        },
    ),
    Tool(
        name="google_ads.monitoring.cv_goal",
        description=(
            "Evaluate a Google Ads campaign's daily conversion rate "
            "against a target and identify the dominant bottleneck. "
            "Returns {campaign_id, target_cv_daily, current_cv_daily "
            "(7-day conversions / 7), performance_analysis (full "
            "google_ads.performance.analyze payload), deviation_pct, "
            "status ('healthy' when >= target, 'warning' when >= "
            "target*0.8, 'critical' otherwise), bottleneck "
            "('impression'|'ctr'|'cvr'), issues:[strings], summary, "
            "suggested_workflow?}. Bottleneck routing: 'impression' "
            "when analyze insights mention impression drops or "
            "impressions<clicks*10; 'ctr' when CTR<2%; 'cvr' otherwise. "
            "The evaluation window is hardcoded to LAST_7_DAYS. "
            "Read-only. For CPA-target evaluation use "
            "google_ads.monitoring.cpa_goal; for the underlying "
            "composite use google_ads.performance.analyze."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
                "target_cv_daily": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Target daily conversion count (e.g. 5.0 means "
                        "5 conversions per day). Required. status "
                        "'warning' fires at 80-100% of target; "
                        "'critical' below 80%."
                    ),
                },
            },
            "required": ["campaign_id", "target_cv_daily"],
        },
    ),
    Tool(
        name="google_ads.monitoring.zero_conversions",
        description=(
            "Diagnose a Google Ads campaign that is not acquiring "
            "conversions by composing tracking config, bidding "
            "alignment, last-7-days funnel, delivery diagnostics, and "
            "search-term quality. Returns {campaign_id, "
            "conversion_tracking:{total_actions, enabled_actions, "
            "has_issue, actions}, bidding_cv_alignment:{strategy, "
            "is_smart_bidding, cv_tracking_configured, issue}, "
            "funnel:{period:'LAST_7_DAYS', impressions, clicks, "
            "conversions, cost, ctr, cvr, bottleneck ('no_delivery'|"
            "'no_clicks'|'no_conversions'|None)}, delivery_diagnosis:{"
            "issues, warnings, recommendations}, search_term_quality:{"
            "total_terms, zero_cv_terms, zero_cv_cost, "
            "top_wasteful_terms} (null when clicks==0), status "
            "('critical'|'warning'|'healthy'), issues:[strings], "
            "summary, suggested_workflow?, recommended_actions:[{"
            "priority, action, description}]}. The evaluation window "
            "is hardcoded to LAST_7_DAYS. Read-only; generates an "
            "action plan but does not execute anything. For CPA "
            "monitoring use google_ads.monitoring.cpa_goal; for "
            "CV-count monitoring use google_ads.monitoring.cv_goal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "campaign_id": _CAMPAIGN_ID_PARAM,
            },
            "required": ["campaign_id"],
        },
    ),
    # === Capture ===
    Tool(
        name="google_ads.capture.screenshot",
        description="Capture a URL screenshot in PNG format (for message match evaluation)",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to capture"},
            },
            "required": ["url"],
        },
    ),
]
