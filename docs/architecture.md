# Architecture

mureo is a **local-first control plane** for AI-driven ad ops. It does not compete with the official ad-platform MCPs (Meta Ads MCP, Google Ads MCP, etc.) — it consumes them as drivers and provides the layer they structurally cannot: strategic intent, outcome correlation, and audit trail. Where the official MCPs answer *how to call the API*, mureo answers *should this change happen, what does it mean for the business, and how do we prove it later*.

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

The workflow commands form a continuous Plan-Do-Check-Act cycle: `/onboard` defines strategy and goals (Plan); `/daily-check` and its downstream commands execute operations (Do); `/goal-review` and `/weekly-report` evaluate progress (Check); and `/goal-review` recommendations feed back into the Do phase by adjusting the Operation Mode, which changes how every command behaves (Act). This loop runs daily (Do) and weekly (Check), with the Act phase closing the loop by updating STRATEGY.md when conditions change. See the operational skills under `skills/` (daily-check, budget-rebalance, etc.) for the full PDCA cycle.

### Tool Connection Layer

The bottom layer connects to advertising platforms and analytics services. mureo currently ships its own MCP tools for Google Ads, Meta Ads, and Google Search Console; third-party MCP servers (e.g., GA4) can be composed alongside them. **This layer is intentionally replaceable.** As platforms release official MCP servers (Meta Ads MCP shipped 2026-04-29; Google Ads MCP available), mureo's built-in connectors are swapped for official ones with no change to the orchestration layer above. Official MCPs are drivers; mureo is the control plane that drives them.

## The Pillars (what an official MCP cannot replace)

mureo's durable value is not platform connectivity — that commoditizes as official MCPs ship. The value is in control-plane responsibilities that platforms structurally will not provide:

### Strategy Enforcer

Every proposed change passes through a runtime gate that reads `STRATEGY.md` and decides: allow / deny / require approval. Persona, USP, brand voice, budget rules, allowed mutation scope, and operation mode all become enforcement signals — not just context. An official MCP has no view of your strategy and cannot enforce one.

### Audit & Provenance

Every decision is recorded in an append-only ledger: who proposed, when, with what reasoning, on what evidence, with what predicted impact, with what rollback plan. Decisions are reversible. An official MCP records API calls, not strategic intent. This is the layer that makes AI ad ops survivable in regulated industries (GDPR, CCPA) and through procurement / SOC2 review.

These pillars are why mureo's value increases — not decreases — as official MCPs ship.

## Package Structure

```
mureo/
├── __init__.py              # Package root (version)
├── auth.py                  # Credential loading & client factory (+ Meta token auto-refresh)
├── auth_setup.py            # Interactive setup wizard (OAuth + MCP config + credential guard)
├── throttle.py              # Rate limiting (token bucket + rolling hourly cap)
├── google_ads/              # Google Ads API client
│   ├── client.py            # GoogleAdsApiClient (Mixins)
│   ├── mappers.py           # Response mapping to structured dicts
│   ├── _ads.py              # _AdsMixin (create/update/list RSAs)
│   ├── _ads_display.py      # _DisplayAdsMixin (create RDAs + RDAUploadError)
│   ├── _keywords.py         # _KeywordsMixin (add/remove/suggest)
│   ├── _extensions.py       # _ExtensionsMixin (sitelinks, callouts, conversions, targeting)
│   ├── _monitoring.py       # _MonitoringMixin (anomaly detection, reports)
│   ├── _diagnostics.py      # _DiagnosticsMixin (campaign diagnosis)
│   ├── _analysis.py         # _AnalysisMixin (auction insights, CPC trends, device analysis)
│   ├── _creative.py         # _CreativeMixin (LP analysis, RSA insights)
│   ├── _media.py            # _MediaMixin (image asset upload)
│   ├── _rsa_validator.py    # RSA ad text validator
│   ├── _rda_validator.py    # RDA input validator (display ads)
│   └── _gaql_validator.py   # GAQL input validators (IDs, dates, date ranges, IN clauses)
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
│   ├── lp_analyzer.py       # Landing page analysis
│   └── anomaly_detector.py  # CPA spike / CTR drop / zero-spend detection with sample-size gates
├── rollback/                # Rollback feature (allow-list gated, append-only)
│   ├── models.py            # RollbackStatus enum + RollbackPlan dataclass
│   ├── planner.py           # plan_rollback(ActionLogEntry) -> RollbackPlan | None
│   └── executor.py          # execute_rollback(...) -> appends ActionLogEntry(rollback_of=index)
├── context/                 # File-based context (STRATEGY.md, STATE.json)
│   ├── models.py            # Immutable dataclasses (ActionLogEntry.rollback_of for audit trail)
│   ├── strategy.py          # STRATEGY.md parser / renderer
│   ├── state.py             # STATE.json parser / renderer
│   └── errors.py            # Context-specific exceptions
├── cli/                     # Typer CLI (setup + auth + rollback inspection; ad operations are via MCP)
│   ├── main.py              # Entry point (mureo command)
│   ├── setup_cmd.py         # mureo setup claude-code / cursor / codex / gemini (Typer handlers)
│   ├── setup_codex.py       # Codex install-kit (MCP config, credential guard, workflow-command skills, shared skills)
│   ├── setup_gemini.py      # Gemini extension manifest (~/.gemini/extensions/mureo/gemini-extension.json)
│   ├── auth_cmd.py          # mureo auth setup (+ --web) / status / check-*
│   ├── rollback_cmd.py      # mureo rollback list / show (inspection only; apply routes through MCP)
│   ├── _tty.py              # TTY-safe helpers (confirm_or_default, is_tty) for non-interactive setup
│   └── web_auth.py          # mureo auth setup --web — browser-based OAuth wizard (Google + Meta)
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
    ├── _handlers_search_console.py        # Search Console handlers
    ├── tools_rollback.py                  # rollback_plan_get / rollback_apply
    ├── _handlers_rollback.py              # Rollback handlers (lazy-resolve dispatcher)
    ├── tools_analysis.py                  # analysis_anomalies_check
    └── _handlers_analysis.py              # Anomaly detector composition handler

.claude/commands/                # Workflow slash commands for Claude Code
├── onboard.md                   # Account setup + STRATEGY.md generation
├── daily-check.md               # Mode-aware daily health monitoring
├── rescue.md                    # Emergency performance rescue
├── search-term-cleanup.md       # Strategy-aligned search term hygiene
├── creative-refresh.md          # Persona/USP-driven ad copy refresh
├── budget-rebalance.md          # Mode-guided budget reallocation
├── competitive-scan.md          # Auction analysis with Market Context
├── sync-state.md                # Manual STATE.json synchronization
└── learn.md           # Save diagnostic insights to knowledge base

│   └── SKILL.md                 # Orchestration paradigm + Operation Mode reference
skills/_mureo-learning/           # Evidence-based decision framework
│   └── SKILL.md                 # Statistical thinking for marketing decisions
skills/_mureo-pro-diagnosis/      # Learnable diagnostic knowledge base
│   └── SKILL.md                 # Diagnostic insights (grows with /learn)
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

### BYOD Mode (Bring Your Own Data)

When `~/.mureo/byod/manifest.json` registers a platform, the MCP server's per-tool `_client_factory.py` dispatches the BYOD CSV-backed client (`mureo/byod/clients.py`) instead of the live API client — **per platform, decided at every call**. Real credentials are never read for that platform; mutations are blocked at the client level (every method whose name starts with `create_`, `update_`, `delete_`, `pause_`, `resume_`, etc. returns `{"status": "skipped_in_byod_readonly"}`). The activation signal is purely the manifest's existence — there is no `--byod` flag, and `mureo setup claude-code` does not need to be re-run when a user starts or stops importing data.

The user-facing input is a single XLSX bundle: either the mureo Google Ads Script's Sheet output (`scripts/sheet-template/google-ads-script.js`) or a Meta Ads Manager Saved Report export. The bundle importer (`mureo/byod/bundle.py`) opens the workbook with openpyxl, dispatches each adapter (`mureo/byod/adapters/<platform>.py`) by header signature, and writes per-platform CSVs to `~/.mureo/byod/<platform>/`. Manifest update is atomic with rollback on partial failure. GA4 and Search Console are **not** part of the BYOD bundle pipeline — they remain on the Live API OAuth path. See `docs/byod.md` for the user-facing walkthrough.

```
Claude Code ─MCP──▶ mureo MCP server
                       │
                       ▼ _client_factory.py per-platform routing
              byod_has(p)?  yes──▶ Byod*Client (CSV) ──▶ ~/.mureo/byod/<platform>/*.csv
                            no ──▶ create_*_client (Live API) ──▶ Google Ads / Meta / SC / GA4 API
```

### Defense-in-Depth for AI Agents

mureo assumes the caller is an AI agent susceptible to prompt injection, not a trusted human. Three layered controls address that threat model:

1. **Credential guard** — `mureo setup claude-code` writes a PreToolUse hook to `~/.claude/settings.json` that blocks reads of `~/.mureo/credentials.json`, `.env`, and similar secret files, so a prompt-injection payload cannot exfiltrate tokens via the file-system tools.
2. **GAQL input validation** — every ID, date, date-range constant, and string literal entering a Google Ads query flows through a single whitelist-based surface in `mureo/google_ads/_gaql_validator.py`. `_period_to_date_clause`'s `BETWEEN` branch pattern-matches and revalidates its dates instead of passing the raw caller string into GAQL.
3. **Anomaly detection** — `mureo/analysis/anomaly_detector.py` compares current campaign metrics against a median-based baseline built from historical `action_log` entries and emits prioritized alerts for zero spend (CRITICAL), CPA spikes (≥1.5×, critical at 2×), and CTR drops (≤0.5×, critical at 0.3×). Sample-size gates (30+ conversions, 1000+ impressions) follow the `_mureo-learning` skill's statistical-thinking rules to suppress single-day noise. Baselines tolerate malformed `metrics_at_action` rows; CPA/CTR are medianed per-entry so baseline values reflect a real historical day.
4. **Rollback with allow-list gating** — `mureo/rollback/` turns agent-authored `reversible_params` hints into concrete `RollbackPlan` records. `reversible_params` is untrusted input for the rollback executor, so the planner enforces an explicit allow-list of operations (budget update + status toggles across Google/Meta Ads), refuses destructive verbs (`.delete` / `.remove` / `.destroy` / `.purge` / `.transfer`), and rejects unexpected parameter keys — a compromised agent cannot smuggle a privileged call through the rollback path. The `mureo rollback list` / `show` CLI commands are inspection-only; execution stays with the MCP dispatcher so it re-enters the same policy gate as forward actions, and control characters from STATE.json are stripped before terminal output to prevent ANSI-escape spoofing.

See [SECURITY.md](../SECURITY.md) for the full threat model.

## Mixin Architecture

Both API clients use multiple inheritance with Mixins to organize functionality by domain. This keeps each file focused on a single concern while providing a unified client interface.

### Google Ads Client -- Mixins

```python
class GoogleAdsApiClient(
    _AdsMixin,           # RSA CRUD (create/update/list/status)
    _DisplayAdsMixin,    # RDA creation with auto image upload
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
| `/learn` | Save diagnostic insights to knowledge base | *(writes SKILL.md)* |

The operational skills (`skills/daily-check/`, `skills/budget-rebalance/`, ...) documents the full set of Operation Modes and their behavioral implications for each command, as well as cross-platform data correlation patterns.
