# Architecture

## Package Structure

```
mureo/
├── __init__.py              # Package root (version)
├── auth.py                  # Credential loading & client factory
├── auth_setup.py            # Interactive setup wizard (OAuth + MCP config)
├── google_ads/              # Google Ads API client
│   ├── client.py            # GoogleAdsApiClient (8 Mixins)
│   ├── mappers.py           # Response mapping to structured dicts
│   ├── _ads.py              # _AdsMixin (create/update/list RSAs)
│   ├── _keywords.py         # _KeywordsMixin (add/remove/suggest)
│   ├── _extensions.py       # _ExtensionsMixin (sitelinks, callouts, conversions, targeting)
│   ├── _monitoring.py       # _MonitoringMixin (anomaly detection, reports)
│   ├── _diagnostics.py      # _DiagnosticsMixin (campaign diagnosis)
│   ├── _analysis.py         # _AnalysisMixin (auction insights, CPC trends, device analysis)
│   ├── _creative.py         # _CreativeMixin (LP analysis, RSA insights)
│   └── _media.py            # _MediaMixin (image asset upload)
├── meta_ads/                # Meta Ads API client
│   ├── client.py            # MetaAdsApiClient (15 Mixins)
│   ├── mappers.py           # Response mapping
│   ├── _campaigns.py        # CampaignsMixin
│   ├── _ad_sets.py          # AdSetsMixin
│   ├── _ads.py              # AdsMixin
│   ├── _creatives.py        # CreativesMixin (carousel, collection, image upload)
│   ├── _audiences.py        # AudiencesMixin
│   ├── _pixels.py           # PixelsMixin
│   ├── _insights.py         # InsightsMixin
│   ├── _analysis.py         # AnalysisMixin
│   ├── _conversions.py      # ConversionsMixin (Conversions API / CAPI)
│   ├── _leads.py            # LeadsMixin (lead forms, lead data)
│   ├── _catalog.py          # CatalogMixin (product catalogs, feeds, products)
│   ├── _split_test.py       # SplitTestMixin (A/B tests)
│   ├── _ad_rules.py         # AdRulesMixin (automated rules)
│   ├── _page_posts.py       # PagePostsMixin (page posts, boost)
│   ├── _instagram.py        # InstagramMixin (accounts, media, boost)
│   └── _hash_utils.py       # SHA-256 hashing utilities for CAPI user data
├── analysis/                # Cross-platform analysis utilities
│   └── lp_analyzer.py       # Landing page analysis
├── context/                 # File-based context (STRATEGY.md, STATE.json)
│   ├── models.py            # Immutable dataclasses
│   ├── strategy.py          # STRATEGY.md parser / renderer
│   ├── state.py             # STATE.json parser / renderer
│   └── errors.py            # Context-specific exceptions
├── cli/                     # Typer CLI commands
│   ├── main.py              # Entry point (mureo command)
│   ├── auth_cmd.py          # mureo auth *
│   ├── google_ads.py        # mureo google-ads *
│   └── meta_ads.py          # mureo meta-ads *
└── mcp/                     # MCP server
    ├── __main__.py           # python -m mureo.mcp entry point
    ├── server.py             # MCP server setup (stdio transport)
    ├── _helpers.py           # Shared handler utilities
    ├── _handlers_google_ads.py  # Google Ads handler implementations
    ├── _handlers_meta_ads.py    # Meta Ads handler implementations
    ├── tools_google_ads.py   # 29 Google Ads tool definitions + dispatch
    └── tools_meta_ads.py     # 52 Meta Ads tool definitions + dispatch
```

## Design Principles

### No Database

mureo has zero database dependencies. All state lives either in the advertising platform APIs or in optional local files (`STRATEGY.md`, `STATE.json`). This makes it trivially deployable -- `pip install mureo` is all you need.

### No LLM Dependency

mureo is the "hands" of your AI agent, not the "brain." It wraps advertising APIs and returns structured JSON dictionaries. All reasoning, planning, and decision-making are the responsibility of the calling agent.

### Immutable Data Models

All dataclasses use `frozen=True` to prevent accidental mutation. Mutable fields like `dict` and `list` are defensively copied in `__post_init__`.

```python
@dataclass(frozen=True)
class CampaignSnapshot:
    campaign_id: str
    campaign_name: str
    status: str
    bidding_strategy_type: str | None = None
    # ...
```

### Structured JSON Output

Every tool and CLI command returns plain Python dicts (serializable to JSON). No custom objects, no ORM models -- just data that any agent or script can consume.

### Credentials Stay Local

Credentials are loaded from `~/.mureo/credentials.json` or environment variables. They are never sent anywhere except the official advertising platform APIs.

## Mixin Architecture

Both API clients use multiple inheritance with Mixins to organize functionality by domain. This keeps each file focused on a single concern while providing a unified client interface.

### Google Ads Client -- 8 Mixins

```python
class GoogleAdsApiClient(
    _AdsMixin,           # Ad CRUD (RSA create/update/list/status)
    _KeywordsMixin,      # Keyword add/remove/suggest/diagnose
    _MonitoringMixin,    # Anomaly detection, reports, goals
    _ExtensionsMixin,    # Sitelinks, callouts, conversions, targeting
    _DiagnosticsMixin,   # Campaign delivery diagnosis
    _AnalysisMixin,      # Auction insights, CPC trends, device analysis, budget efficiency
    _CreativeMixin,      # LP analysis, RSA insights
    _MediaMixin,         # Image asset upload
):
```

The base class (`GoogleAdsApiClient`) provides:
- Constructor: accepts `Credentials`, `customer_id`, `developer_token`, `login_customer_id`
- `_search(query)`: async GAQL query execution via `run_in_executor`
- `_get_service(name)`: access to Google Ads service objects
- Input validation: `_validate_id()`, `_validate_status()`, `_validate_match_type()`, `_validate_date()`
- Error handling: `_wrap_mutate_error()` decorator that catches `GoogleAdsException` and returns user-friendly messages

### Meta Ads Client -- 16 Mixins

```python
class MetaAdsApiClient(
    CampaignsMixin,    # Campaign CRUD
    AdSetsMixin,       # Ad set CRUD
    AdsMixin,          # Ad CRUD
    CreativesMixin,    # Creative management, image/carousel/collection
    AudiencesMixin,    # Custom/lookalike audiences
    PixelsMixin,       # Pixel stats and events
    InsightsMixin,     # Performance reports, breakdowns
    AnalysisMixin,     # Performance analysis, cost investigation
    CatalogMixin,      # Product catalogs, feeds, products (DPA)
    ConversionsMixin,  # Conversions API (CAPI) event sending
    LeadsMixin,        # Lead forms, lead data retrieval
    PagePostsMixin,    # Page post listing and boosting
    InstagramMixin,    # Instagram accounts, media, boosting
    SplitTestMixin,    # A/B test creation and management
    AdRulesMixin,      # Automated rules (alerts, auto-pause, etc.)
):
```

The base class provides:
- Constructor: accepts `access_token`, `ad_account_id` (must start with `act_`)
- HTTP methods: `_get()`, `_post()`, `_delete()` with rate limit monitoring
- Automatic retry with exponential backoff (3 attempts)
- Rate limit header parsing (`x-business-use-case-usage`)
- Async context manager support (`async with`)

## MCP Server Tool Dispatch Flow

The MCP server uses stdio transport and dispatches tool calls to platform-specific handlers.

```
Agent (Claude Code / Cursor / etc.)
  │
  │  stdio (JSON-RPC)
  ▼
server.py :: _create_server()
  │
  ├── list_tools()  → returns _ALL_TOOLS (GOOGLE_ADS_TOOLS + META_ADS_TOOLS)
  │
  └── call_tool(name, arguments)
        │
        ├── name in _GOOGLE_ADS_NAMES? → handle_google_ads_tool(name, args)
        │     │
        │     └── _HANDLERS[name](args)
        │           │
        │           ├── load_google_ads_credentials()
        │           ├── create_google_ads_client(creds, customer_id)
        │           └── client.method() → list[TextContent]
        │
        ├── name in _META_ADS_NAMES? → handle_meta_ads_tool(name, args)
        │     │
        │     └── _HANDLERS[name](args)
        │           │
        │           ├── load_meta_ads_credentials()
        │           ├── create_meta_ads_client(creds, account_id)
        │           └── client.method() → list[TextContent]
        │
        └── else → ValueError("Unknown tool")
```

Key implementation details:

1. **Tool definitions** are `mcp.types.Tool` objects with `inputSchema` (JSON Schema).
2. **Handler dispatch** uses a `dict[str, Callable]` mapping tool names to async handler functions.
3. **Error handling**: the `@api_error_handler` decorator catches exceptions and converts them to `TextContent` error messages, so the agent always gets a text response.
4. **Credential loading** happens per-request. Each handler call loads credentials from file/env, creates a fresh client, and executes the operation.

## Authentication Flow

```
1. Handler receives tool call arguments
     │
2. load_google_ads_credentials() / load_meta_ads_credentials()
     │
     ├── Try ~/.mureo/credentials.json
     │     └── Parse JSON → extract platform section
     │
     └── Fallback to environment variables
           └── GOOGLE_ADS_* / META_ADS_*
     │
3. If credentials found:
     │
     ├── Google Ads: build OAuth2 Credentials → GoogleAdsClient → GoogleAdsApiClient
     └── Meta Ads: MetaAdsApiClient(access_token, ad_account_id)
     │
4. If no credentials: return error TextContent (no exception)
```

The credential resolution logic is centralized in `mureo/auth.py`. Both the CLI and MCP server use the same `load_*_credentials()` and `create_*_client()` functions.
