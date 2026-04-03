"""Search Console MCP tool definitions."""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Sites ===
    Tool(
        name="search_console.sites.list",
        description="List all verified Google Search Console sites",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="search_console.sites.get",
        description="Get details for a specific Search Console site",
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": (
                        "Site URL (e.g., 'https://example.com/' or "
                        "'sc-domain:example.com')"
                    ),
                },
            },
            "required": ["site_url"],
        },
    ),
    # === Search Analytics ===
    Tool(
        name="search_console.analytics.query",
        description=(
            "Query Google Search Console search analytics data. "
            "Returns clicks, impressions, CTR, and position."
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
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("Dimensions: query, page, country, device, date"),
                },
                "row_limit": {
                    "type": "integer",
                    "description": "Max rows (default: 100)",
                },
                "dimension_filter_groups": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional dimension filter groups",
                },
            },
            "required": ["site_url", "start_date", "end_date"],
        },
    ),
    Tool(
        name="search_console.analytics.top_queries",
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
        name="search_console.analytics.top_pages",
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
        name="search_console.analytics.device_breakdown",
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
        name="search_console.analytics.compare_periods",
        description=(
            "Compare search analytics between two date periods. "
            "Returns data for both periods side by side."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "Site URL",
                },
                "start_date_1": {
                    "type": "string",
                    "description": "Period 1 start date (YYYY-MM-DD)",
                },
                "end_date_1": {
                    "type": "string",
                    "description": "Period 1 end date (YYYY-MM-DD)",
                },
                "start_date_2": {
                    "type": "string",
                    "description": "Period 2 start date (YYYY-MM-DD)",
                },
                "end_date_2": {
                    "type": "string",
                    "description": "Period 2 end date (YYYY-MM-DD)",
                },
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Dimensions (default: ['query'])",
                },
                "row_limit": {
                    "type": "integer",
                    "description": "Max rows per period (default: 100)",
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
        name="search_console.sitemaps.list",
        description="List all sitemaps for a Search Console site",
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "Site URL",
                },
            },
            "required": ["site_url"],
        },
    ),
    Tool(
        name="search_console.sitemaps.submit",
        description="Submit a sitemap to Google Search Console",
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "Site URL",
                },
                "feedpath": {
                    "type": "string",
                    "description": "Sitemap URL to submit",
                },
            },
            "required": ["site_url", "feedpath"],
        },
    ),
    # === URL Inspection ===
    Tool(
        name="search_console.url_inspection.inspect",
        description=(
            "Inspect a URL's indexing status in Google Search Console. "
            "Returns coverage state, verdict, and crawl details."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "site_url": {
                    "type": "string",
                    "description": "Site URL",
                },
                "inspection_url": {
                    "type": "string",
                    "description": "URL to inspect",
                },
            },
            "required": ["site_url", "inspection_url"],
        },
    ),
]
