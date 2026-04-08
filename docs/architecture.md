# Architecture

mureo is a **marketing orchestration framework** that bridges the gap between marketing strategy and advertising platform execution. Rather than a simple API wrapper, mureo provides a layered system where human-defined goals flow through strategy context, get orchestrated by AI-powered workflows, and execute via pluggable platform connections.

## System Architecture

The system is organized into four layers. Each layer has a clear responsibility and communicates downward through well-defined interfaces.

```
┌─────────────────────────────────────────────────────┐
│  Marketing Goals                                     │
│  (awareness, lead generation, sales, retention)      │
├─────────────────────────────────────────────────────┤
│  Strategy Context                                    │
│  STRATEGY.md: Persona, USP, Brand Voice, Goals,     │
│               Operation Mode, Market Context         │
│  STATE.json: Campaign snapshots, action log          │
├─────────────────────────────────────────────────────┤
│  Orchestration Layer                                 │
│  Workflow Commands: /daily-check, /rescue, etc.      │
│  Domain Knowledge: Skills (analysis, diagnostics)    │
│  AI Agent (LLM): Strategic judgment, creative gen    │
├─────────────────────────────────────────────────────┤
│  Tool Connection Layer                               │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌─────┐      │
│  │Google Ads│ │Meta Ads  │ │Search  │ │ GA4 │      │
│  │(mureo)   │ │(mureo)   │ │Console │ │(MCP)│      │
│  │          │ │          │ │(mureo) │ │     │      │
│  └──────────┘ └──────────┘ └────────┘ └─────┘      │
└─────────────────────────────────────────────────────┘
```

### Marketing Goals (Top Layer)

The user defines high-level marketing objectives -- awareness, lead generation, sales, retention. These goals drive every decision downstream. mureo does not prescribe goals; it receives them from the marketer and ensures all operations align with them.

### Strategy Context

mureo persists marketing strategy in two files that travel with the project:

- **STRATEGY.md** captures the durable strategic context: target persona, unique selling proposition (USP), brand voice guidelines, marketing goals, the current operation mode (e.g., EFFICIENCY_STABILIZE, GROWTH_SCALE), and market context including competitors.
- **STATE.json** holds ephemeral operational state: campaign snapshots, recent action logs, and metric baselines used for anomaly detection.

Together these files give the AI agent enough context to make strategy-aware decisions without requiring a database.

### Orchestration Layer

This is where mureo's workflow commands, domain knowledge (skills), and the AI agent converge. Workflow commands like `/daily-check` and `/rescue` define multi-step operational procedures. Skills provide domain-specific reference material (operation mode definitions, diagnostic patterns). The AI agent (LLM) supplies strategic judgment, creative generation, and adaptive decision-making. The orchestration layer reads the strategy context, selects the appropriate tools, and synthesizes results into actionable recommendations.

#### PDCA Operational Loop

The workflow commands form a continuous Plan-Do-Check-Act cycle: `/onboard` defines strategy and goals (Plan); `/daily-check` and its downstream commands execute operations (Do); `/goal-review` and `/weekly-report` evaluate progress (Check); and `/goal-review` recommendations feed back into the Do phase by adjusting the Operation Mode, which changes how every command behaves (Act). This loop runs daily (Do) and weekly (Check), with the Act phase closing the loop by updating STRATEGY.md when conditions change. See `skills/mureo-workflows/SKILL.md` for the full PDCA diagram and Operation Mode transition rules.

### Tool Connection Layer

The bottom layer provides concrete connections to advertising platforms and analytics services. mureo ships its own MCP tools for Google Ads, Meta Ads, and Google Search Console. Third-party MCP servers (e.g., GA4) can be composed alongside mureo's tools. This layer is intentionally replaceable -- as platforms release official MCP servers, mureo's built-in connectors can be swapped out without affecting the orchestration layer above.

## Package Structure

```
mureo/
├── __init__.py              # Package root (version)
├── auth.py                  # Credential loading & client factory (+ Meta token auto-refresh)
├── auth_setup.py            # Interactive setup wizard (OAuth + MCP config + credential guard)
├── throttle.py              # Rate limiting (token bucket + rolling hourly cap)
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
├── search_console/          # Google Search Console API client (reuses Google OAuth2 credentials)
│   └── client.py            # SearchConsoleApiClient
├── analysis/                # Cross-platform analysis utilities
│   └── lp_analyzer.py       # Landing page analysis
├── context/                 # File-based context (STRATEGY.md, STATE.json)
│   ├── models.py            # Immutable dataclasses
│   ├── strategy.py          # STRATEGY.md parser / renderer
│   ├── state.py             # STATE.json parser / renderer
│   └── errors.py            # Context-specific exceptions
├── cli/                     # Typer CLI (setup + auth only; ad operations are via MCP)
│   ├── main.py              # Entry point (mureo command)
│   ├── setup_cmd.py         # mureo setup claude-code / cursor
│   └── auth_cmd.py          # mureo auth setup / status / check-*
└── mcp/                     # MCP server
    ├── __main__.py                        # python -m mureo.mcp entry point
    ├── server.py                          # MCP server setup (stdio transport)
    ├── _helpers.py                        # Shared handler utilities
    ├── tools_google_ads.py                # Google Ads tool definitions (aggregator)
    ├── _tools_google_ads_*.py             # Tool definition sub-modules
    ├── _handlers_google_ads.py            # Google Ads base handlers
    ├── _handlers_google_ads_extensions.py # Extensions handlers
    ├── _handlers_google_ads_analysis.py   # Analysis handlers
    ├── tools_meta_ads.py                  # Meta Ads tool definitions (aggregator)
    ├── _tools_meta_ads_*.py               # Tool definition sub-modules
    ├── _handlers_meta_ads.py              # Meta Ads base handlers
    ├── _handlers_meta_ads_extended.py     # Extended handlers
    ├── _handlers_meta_ads_other.py        # Other handlers
    ├── tools_search_console.py            # Search Console tool definitions
    └── _handlers_search_console.py        # Search Console handlers

.claude/commands/                # Workflow slash commands for Claude Code
├── onboard.md                   # Account setup + STRATEGY.md generation
├── daily-check.md               # Mode-aware daily health monitoring
├── rescue.md                    # Emergency performance rescue
├── search-term-cleanup.md       # Strategy-aligned search term hygiene
├── creative-refresh.md          # Persona/USP-driven ad copy refresh
├── budget-rebalance.md          # Mode-guided budget reallocation
├── competitive-scan.md          # Auction analysis with Market Context
├── sync-state.md                # Manual STATE.json synchronization
└── learn-diagnosis.md           # Save diagnostic insights to knowledge base

skills/mureo-workflows/          # Workflow skill reference
│   └── SKILL.md                 # Orchestration paradigm + Operation Mode reference
skills/mureo-learning/           # Evidence-based decision framework
│   └── SKILL.md                 # Statistical thinking for marketing decisions
skills/mureo-pro-diagnosis/      # Learnable diagnostic knowledge base
│   └── SKILL.md                 # Diagnostic insights (grows with /learn-diagnosis)
```

## Design Principles

### No Database

mureo has zero database dependencies. All state lives either in the advertising platform APIs or in optional local files (`STRATEGY.md`, `STATE.json`). This makes it trivially deployable -- `pip install mureo` is all you need.

### No Embedded LLM

mureo does not bundle or call an LLM itself. The tool connection layer wraps advertising APIs and returns structured JSON dictionaries. The orchestration layer relies on an external AI agent (e.g., Claude via Claude Code) for reasoning, planning, and creative generation. This separation keeps mureo lightweight and model-agnostic.

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

### Meta Ads Client -- 15 Mixins

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
  ├── list_tools()  → returns _ALL_TOOLS (GOOGLE_ADS_TOOLS + META_ADS_TOOLS + SEARCH_CONSOLE_TOOLS)
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
        ├── name in _SEARCH_CONSOLE_NAMES? → handle_search_console_tool(name, args)
        │     │
        │     └── _HANDLERS[name](args)
        │           │
        │           ├── load_google_ads_credentials()  (reuses Google OAuth2)
        │           ├── create_search_console_client(creds)
        │           └── client.method() → list[TextContent]
        │
        └── else → ValueError("Unknown tool")
```

Key implementation details:

1. **Tool definitions** are `mcp.types.Tool` objects with `inputSchema` (JSON Schema).
2. **Handler dispatch** uses a `dict[str, Callable]` mapping tool names to async handler functions.
3. **Error handling**: the `@api_error_handler` decorator catches exceptions and converts them to `TextContent` error messages, so the agent always gets a text response.
4. **Credential loading** happens per-request. Each handler call loads credentials from file/env, creates a fresh client, and executes the operation.

## Rate Limiting

mureo includes a built-in rate limiter (`mureo/throttle.py`) to prevent API bans caused by high-speed requests from AI agents.

### Algorithm

Each platform throttler combines two mechanisms:

1. **Token bucket** -- controls instantaneous QPS (queries per second) with configurable burst allowance.
2. **Rolling hourly cap** -- enforces a hard ceiling on total requests per hour.

### Default Limits

| Platform | QPS | Burst | Hourly Limit | Notes |
|----------|-----|-------|-------------|-------|
| Google Ads | 10 | 5 | *(none)* | Conservative defaults; Google uses dynamic server-side limits |
| Meta Ads | 20 | 10 | 50,000 | Tuned to stay within the Business Use Case (BUC) quota |
| Search Console | 5 | 5 | *(none)* | Reuses Google OAuth2 credentials |

### Integration

- **Module-level singletons** -- one `Throttler` instance per platform, shared across all MCP tool calls in the same process.
- **Transparent** -- tool handlers call `await throttler.acquire()` before making API requests. No configuration is needed from the user.
- **Graceful** -- when the token bucket is empty, `acquire()` awaits until a token becomes available rather than raising an error.

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

### Meta Ads Token Auto-Refresh

When loading Meta Ads credentials, `mureo/auth.py` checks the `token_obtained_at` timestamp in `credentials.json`. If the Long-Lived Token is 53+ days old (7-day safety margin before the 60-day expiry), mureo automatically exchanges it for a fresh token via the Meta Graph API. This requires `app_id` and `app_secret` to be present in the credentials. The refresh is protected by an `asyncio.Lock` to prevent concurrent refresh races, and the updated token is written atomically to `credentials.json` with `0600` file permissions. If the refresh fails (network error, invalid app credentials, etc.), mureo falls back to the existing token and logs a warning.

## Command-Based Workflow System

In addition to the 169 individual MCP tools, mureo provides **workflow commands** as Claude Code slash commands (`.claude/commands/`). These commands are **platform-agnostic orchestration instructions** that guide the AI agent to discover platforms, select tools, and synthesize cross-platform insights — all driven by the strategy context in `STRATEGY.md`.

### How It Works

```
User runs /daily-check in Claude Code
  │
  ├── Read STRATEGY.md → extract Operation Mode, Persona, Data Sources
  ├── Read STATE.json → discover configured platforms (platforms dict)
  │
  ├── For each configured platform, select appropriate MCP tools based on Operation Mode
  │   (no hardcoded platform assumptions — adapts to whatever is configured)
  │
  ├── Check availability of enrichment data sources:
  │     ├── Search Console (built-in) → organic search pulse
  │     └── GA4 (external MCP) → on-site behavior correlation
  │
  ├── Execute selected tools across all discovered platforms
  │
  └── Synthesize results into a unified, strategy-aware cross-platform report
```

### Commands

All commands follow the same orchestration pattern: **discover platforms → select tools → correlate data sources → present unified results**. Commands do not hardcode tool names; the AI agent chooses appropriate tools per platform at runtime.

| Command | Purpose | Strategy Sections Used |
|---------|---------|-----------------------|
| `/onboard` | Platform discovery + strategy generation | *(generates all sections)* |
| `/daily-check` | Cross-platform health monitoring | Operation Mode, Data Sources |
| `/rescue` | Emergency performance fix with site-side diagnosis | All sections |
| `/search-term-cleanup` | Keyword hygiene with paid/organic overlap | Persona, USP, Data Sources |
| `/creative-refresh` | Multi-platform creative refresh | Persona, USP, Brand Voice, Data Sources |
| `/budget-rebalance` | Cross-platform budget optimization | Operation Mode, Goals, Data Sources |
| `/competitive-scan` | Paid + organic competitive analysis | Market Context, Data Sources |
| `/goal-review` | Multi-source goal evaluation | Operation Mode, Goals, Data Sources |
| `/weekly-report` | Cross-platform weekly report | All sections |
| `/sync-state` | Multi-platform state synchronization | *(writes STATE.json)* |
| `/learn-diagnosis` | Save diagnostic insights to knowledge base | *(writes SKILL.md)* |

The workflow skill reference (`skills/mureo-workflows/SKILL.md`) documents the full set of Operation Modes and their behavioral implications for each command, as well as cross-platform data correlation patterns.
