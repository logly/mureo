"""Search Console MCP tool definitions."""

from __future__ import annotations

from mcp.types import Tool

_SITE_URL_PARAM = {
    "type": "string",
    "description": (
        "Property identifier as registered in Search Console. For "
        "URL-prefix properties use the full URL including trailing "
        "slash (e.g. 'https://example.com/'). For Domain properties "
        "use the 'sc-domain:' prefix (e.g. 'sc-domain:example.com'). "
        "The property must be verified and accessible to the "
        "authenticated Google account."
    ),
}

_DATE_PARAM_START = {
    "type": "string",
    "format": "date",
    "pattern": r"^\d{4}-\d{2}-\d{2}$",
    "description": (
        "Inclusive start date in 'YYYY-MM-DD' format (e.g. "
        "'2026-03-01'). Search Console data typically lags 2-3 days, "
        "so 'today' returns no rows. Maximum lookback is 16 months."
    ),
}

_DATE_PARAM_END = {
    "type": "string",
    "format": "date",
    "pattern": r"^\d{4}-\d{2}-\d{2}$",
    "description": (
        "Inclusive end date in 'YYYY-MM-DD' format (e.g. "
        "'2026-03-31'). Must be >= start_date. Search Console data "
        "lags 2-3 days; requesting the last two days typically "
        "returns no rows."
    ),
}

_ROW_LIMIT_PARAM = {
    "type": "integer",
    "minimum": 1,
    "maximum": 25000,
    "description": (
        "Maximum rows to return. Default 100. Search Console API "
        "caps at 25000 per request; agents that need more should "
        "split the call by date range."
    ),
}

TOOLS: list[Tool] = [
    # === Sites ===
    Tool(
        name="search_console_sites_list",
        description=(
            "List every Search Console property the authenticated "
            "Google account can access, regardless of permission "
            "level. Returns the raw 'siteEntry' array from the "
            "Webmasters API: [{siteUrl (URL-prefix form or "
            "'sc-domain:' form), permissionLevel ('siteOwner'|"
            "'siteFullUser'|'siteRestrictedUser'|"
            "'siteUnverifiedUser')}]. Read-only; takes no input. For "
            "permission and metadata on a single property use "
            "search_console_sites_get."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="search_console_sites_get",
        description=(
            "Fetch metadata and the current user's permission level for "
            "a single Search Console property. Returns the raw "
            "Webmasters API response shape: {siteUrl, permissionLevel "
            "('siteOwner'|'siteFullUser'|'siteRestrictedUser'|"
            "'siteUnverifiedUser')}. Read-only; no mutation. Use this "
            "to verify whether the authenticated account has write "
            "access before calling mutating tools like "
            "search_console_sitemaps_submit. For a full list of "
            "accessible properties use search_console_sites_list; for "
            "per-URL indexing data use "
            "search_console_url_inspection_inspect."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": _SITE_URL_PARAM,
            },
            "required": ["site_url"],
        },
    ),
    # === Search Analytics ===
    Tool(
        name="search_console_analytics_query",
        description=(
            "Query the Search Console Search Analytics API for organic "
            "Google Search performance data. Returns the raw 'rows' "
            "array from the searchAnalytics.query response: [{keys: "
            "[<one value per requested dimension>], clicks (int), "
            "impressions (int), ctr (float 0.0-1.0), position (float, "
            "1-indexed average ranking)}]. Empty array when no data. "
            "Read-only. Use dimensions=['query'] for keywords, ['page'] "
            "for URLs, ['device'] for device split, ['date'] for a "
            "daily trend. For convenience shortcuts use "
            "search_console_analytics_top_queries / top_pages / "
            "device_breakdown; for before/after comparisons use "
            "search_console_analytics_compare_periods."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": _SITE_URL_PARAM,
                "start_date": _DATE_PARAM_START,
                "end_date": _DATE_PARAM_END,
                "dimensions": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "query",
                            "page",
                            "country",
                            "device",
                            "date",
                            "searchAppearance",
                        ],
                    },
                    "minItems": 1,
                    "maxItems": 4,
                    "description": (
                        "Dimensions to group rows by. Allowed: query, "
                        "page, country, device, date, searchAppearance. "
                        "Omit for an ungrouped total (clicks/"
                        "impressions/ctr/position across the window). "
                        "Each additional dimension multiplies row "
                        "cardinality — agents should usually pick 1-2."
                    ),
                },
                "row_limit": _ROW_LIMIT_PARAM,
                "dimension_filter_groups": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Optional Search Console dimensionFilterGroups "
                        "payload (list of {groupType: 'and', filters: "
                        "[{dimension, operator ('equals'|'contains'|"
                        "'notContains'|'notEquals'|'includingRegex'|"
                        "'excludingRegex'), expression}]}). Passed "
                        "through verbatim to the REST API."
                    ),
                },
            },
            "required": ["site_url", "start_date", "end_date"],
        },
    ),
    Tool(
        name="search_console_analytics_top_queries",
        description=(
            "Get top search queries for a site. "
            "Shortcut for analytics.query with dimensions=['query']."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "Site URL",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                },
                "row_limit": {
                    "type": "integer",
                    "description": "Max rows (default: 100)",
                },
            },
            "required": ["site_url", "start_date", "end_date"],
        },
    ),
    Tool(
        name="search_console_analytics_top_pages",
        description=(
            "Get top pages for a site. "
            "Shortcut for analytics.query with dimensions=['page']."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "Site URL",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                },
                "row_limit": {
                    "type": "integer",
                    "description": "Max rows (default: 100)",
                },
            },
            "required": ["site_url", "start_date", "end_date"],
        },
    ),
    Tool(
        name="search_console_analytics_device_breakdown",
        description=(
            "Get device breakdown for a site. "
            "Shortcut for analytics.query with dimensions=['device']."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "Site URL",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                },
                "row_limit": {
                    "type": "integer",
                    "description": "Max rows (default: 100)",
                },
            },
            "required": ["site_url", "start_date", "end_date"],
        },
    ),
    Tool(
        name="search_console_analytics_compare_periods",
        description=(
            "Query Search Console search analytics twice and return "
            "both periods side-by-side. Returns {period_1: [rows], "
            "period_2: [rows]} where each rows list has the same shape "
            "as search_console_analytics_query (keys, clicks, "
            "impressions, ctr, position). The tool does NOT diff or "
            "merge the periods — the agent must align by the first key "
            "in each row. Read-only. Two REST calls are issued per "
            "invocation. Defaults: dimensions=['query'], row_limit=100 "
            "per period. For a single-period query use "
            "search_console_analytics_query."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": _SITE_URL_PARAM,
                "start_date_1": {
                    **_DATE_PARAM_START,
                    "description": (
                        "Period 1 inclusive start date "
                        "('YYYY-MM-DD'). Convention: period 1 is the "
                        "older / baseline window."
                    ),
                },
                "end_date_1": {
                    **_DATE_PARAM_END,
                    "description": (
                        "Period 1 inclusive end date ('YYYY-MM-DD'). "
                        "Must be >= start_date_1."
                    ),
                },
                "start_date_2": {
                    **_DATE_PARAM_START,
                    "description": (
                        "Period 2 inclusive start date "
                        "('YYYY-MM-DD'). Convention: period 2 is the "
                        "newer / comparison window."
                    ),
                },
                "end_date_2": {
                    **_DATE_PARAM_END,
                    "description": (
                        "Period 2 inclusive end date ('YYYY-MM-DD'). "
                        "Must be >= start_date_2."
                    ),
                },
                "dimensions": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "query",
                            "page",
                            "country",
                            "device",
                            "date",
                            "searchAppearance",
                        ],
                    },
                    "minItems": 1,
                    "maxItems": 4,
                    "description": (
                        "Dimensions shared across both periods. "
                        "Default ['query']. Use ['page'] to compare "
                        "URL-level changes, ['device'] for device "
                        "shifts."
                    ),
                },
                "row_limit": {
                    **_ROW_LIMIT_PARAM,
                    "description": (
                        "Maximum rows per period (default 100, cap "
                        "25000). Applied independently to period 1 "
                        "and period 2."
                    ),
                },
            },
            "required": [
                "site_url",
                "start_date_1",
                "end_date_1",
                "start_date_2",
                "end_date_2",
            ],
        },
    ),
    # === Sitemaps ===
    Tool(
        name="search_console_sitemaps_list",
        description=(
            "List every sitemap registered against a Search Console "
            "property, with their most recent crawl status. Returns "
            "the raw Webmasters 'sitemap' array: [{path (absolute "
            "sitemap URL), lastSubmitted (ISO 8601), isPending, "
            "isSitemapsIndex, type ('sitemap'|'sitemapIndex'|"
            "'rssFeed'|'atomFeed'|'urlList'|'patternSitemap'), "
            "lastDownloaded (ISO 8601), warnings (int), errors (int), "
            "contents: [{type, submitted (int), indexed (int)}]}]. "
            "Read-only. For submitting or resubmitting a sitemap use "
            "search_console_sitemaps_submit."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": _SITE_URL_PARAM,
            },
            "required": ["site_url"],
        },
    ),
    Tool(
        name="search_console_sitemaps_submit",
        description=(
            "Submit a sitemap URL to Google Search Console for the given "
            "verified site. Mutates Search Console state — registers or "
            "refreshes the sitemap entry so Google will re-crawl it. Safe "
            "to call repeatedly: re-submitting the same feedpath re-queues "
            "a crawl without creating a duplicate entry (Search Console "
            "PUTs the sitemap URL, not POST). Returns "
            "{status: 'submitted', sitemap: <feedpath>} on success; the "
            "API gives no synchronous processing status. Does not fetch "
            "or validate the sitemap contents — that happens asynchronously "
            "on Google's side and the parsed results surface in "
            "search_console_sitemaps_list afterwards. Requires the "
            "authenticated user to be a verified owner or full user of "
            "site_url. For read-only inspection of already-submitted "
            "sitemaps use search_console_sitemaps_list; for per-URL "
            "indexing diagnostics use search_console_url_inspection_inspect."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": (
                        "Property identifier as registered in Search "
                        "Console. For URL-prefix properties use the full "
                        "URL including trailing slash "
                        "(e.g. 'https://example.com/'). For Domain "
                        "properties use the 'sc-domain:' prefix "
                        "(e.g. 'sc-domain:example.com')."
                    ),
                },
                "feedpath": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "Absolute URL of the sitemap to submit "
                        "(e.g. 'https://example.com/sitemap.xml'). Must be "
                        "on the same host as site_url and reachable to "
                        "Googlebot over HTTPS."
                    ),
                },
            },
            "required": ["site_url", "feedpath"],
        },
    ),
    # === URL Inspection ===
    Tool(
        name="search_console_url_inspection_inspect",
        description=(
            "Inspect a single URL's indexing state via the Search "
            "Console URL Inspection API. Returns the raw "
            "inspectionResult envelope: {inspectionResult:{"
            "inspectionResultLink (live UI URL), indexStatusResult:{"
            "verdict ('PASS'|'PARTIAL'|'FAIL'|'NEUTRAL'), "
            "coverageState (string, e.g. 'Submitted and indexed' / "
            "'Crawled - currently not indexed' / 'Discovered - "
            "currently not indexed'), robotsTxtState, indexingState, "
            "lastCrawlTime (ISO 8601), pageFetchState, "
            "googleCanonical, userCanonical, referringUrls, "
            "sitemap}, mobileUsabilityResult, "
            "richResultsResult?, ampResult?}}. Read-only; no "
            "re-indexing is triggered. Rate limit: Search Console "
            "caps inspection at ~2000 URLs per property per day. Use "
            "this to debug why a specific page isn't ranking. For "
            "site-wide coverage numbers use "
            "search_console_sitemaps_list; for organic-performance "
            "metrics use search_console_analytics_query."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": _SITE_URL_PARAM,
                "inspection_url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "Absolute URL to inspect (e.g. "
                        "'https://example.com/about'). Must be under "
                        "site_url's property; cross-property "
                        "inspection is rejected by the API."
                    ),
                },
            },
            "required": ["site_url", "inspection_url"],
        },
    ),
]
