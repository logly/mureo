# Strategy Context Guide

mureo supports two optional local files that let agents persist context across sessions without a database:

- **STRATEGY.md** -- strategic context (who your customers are, what your USP is, market conditions)
- **STATE.json** -- campaign state snapshots (current settings, budgets, statuses)

These files are read and written by the `mureo.context` module.

## STRATEGY.md

### Format

STRATEGY.md is a standard Markdown file with `## ` (h2) section headings. Each section maps to a `context_type` that categorizes the strategic information.

```markdown
# Strategy

## Persona
B2B SaaS decision-makers, 30-50 years old, IT managers and CTOs.
Budget authority for marketing tools up to $50k/year.

## USP
Only platform that integrates AI agents with ad operations.
Saves 10+ hours per week of manual campaign management.

## Target Audience
Small-to-mid size marketing teams (2-10 people) running
Google Ads and Meta Ads simultaneously.

## Brand Voice
Professional but approachable. Data-driven recommendations
with clear reasoning.

## Market Context
Competitive CPC rising 15% YoY in the SaaS category.
Meta Ads CPM increased 8% in Q4.

## Operation Mode
EFFICIENCY_STABILIZE

## Custom: Q1 Goals
Reduce CPA by 20% while maintaining conversion volume.
Focus on search term optimization and negative keyword expansion.

## Deep Research: Competitor Analysis
Top 3 competitors are spending 2x on brand terms.
Consider defensive brand campaigns.

## Sales Material: Product Deck Summary
Key selling points extracted from the 2024 product deck.
```

### Section Headings and context_type

| Heading | `context_type` | Description |
|---------|---------------|-------------|
| `## Persona` | `persona` | Target customer persona |
| `## USP` | `usp` | Unique selling proposition |
| `## Target Audience` | `target_audience` | Target audience definition |
| `## Brand Voice` | `brand_voice` | Communication tone and style |
| `## Market Context` | `market_context` | Market conditions and trends |
| `## Operation Mode` | `operation_mode` | Current operational focus |
| `## Custom: <title>` | `custom` | Any custom context with a title |
| `## Deep Research: <title>` | `deep_research` | Research findings with a title |
| `## Sales Material: <title>` | `sales_material` | Extracted sales material with a title |

**Rules:**
- Fixed sections (`Persona`, `USP`, etc.) use exact heading matches.
- Variable sections (`Custom`, `Deep Research`, `Sales Material`) use the `Prefix: Title` format.
- Unknown section headings are logged as warnings and skipped during parsing.
- The `# Strategy` top-level heading is generated automatically by the renderer.

### Python API

```python
from pathlib import Path
from mureo.context import (
    StrategyEntry,
    read_strategy_file,
    write_strategy_file,
    add_strategy_entry,
    remove_strategy_entry,
    parse_strategy,
    render_strategy,
)

path = Path("STRATEGY.md")

# Read all entries
entries = read_strategy_file(path)
for entry in entries:
    print(f"[{entry.context_type}] {entry.title}: {entry.content[:50]}...")

# Add a new entry
new_entry = StrategyEntry(
    context_type="custom",
    title="Q2 Budget Plan",
    content="Increase Meta Ads budget by 30% for summer campaign.",
)
entries = add_strategy_entry(path, new_entry)

# Remove entries by context_type
entries = remove_strategy_entry(path, "custom", title="Q2 Budget Plan")

# Parse from string
text = Path("STRATEGY.md").read_text()
entries = parse_strategy(text)

# Render to string
markdown = render_strategy(entries)
```

## STATE.json

### Format

STATE.json is a JSON file containing campaign state snapshots across platforms, plus an action log for tracking changes and their outcomes.

```json
{
  "version": "2",
  "last_synced_at": "2026-04-01T10:00:00Z",
  "platforms": {
    "google_ads": {
      "account_id": "1234567890",
      "campaigns": [
        {
          "campaign_id": "111222333",
          "campaign_name": "Brand - Search",
          "status": "ENABLED",
          "bidding_strategy_type": "TARGET_CPA",
          "bidding_details": {"target_cpa_micros": 5000000},
          "daily_budget": 5000,
          "campaign_goal": "Maximize conversions at target CPA"
        }
      ]
    }
  },
  "action_log": [
    {
      "timestamp": "2026-04-01T10:30:00+09:00",
      "action": "Added 15 negative keywords",
      "platform": "google_ads",
      "campaign_id": "111222333",
      "command": "/search-term-cleanup",
      "summary": "Excluded informational queries",
      "metrics_at_action": {"cpa": 5200, "conversions": 45, "clicks": 1200},
      "observation_due": "2026-04-15"
    }
  ]
}
```

### Fields

#### Root

| Field | Type | Description |
|-------|------|-------------|
| `version` | `string` | Schema version (`"2"` for multi-platform format) |
| `last_synced_at` | `string \| null` | ISO 8601 timestamp of last sync |
| `platforms` | `object \| null` | Per-platform state (v2) |
| `action_log` | `array` | Log of actions with outcome tracking |
| `customer_id` | `string \| null` | Legacy v1 field (kept for backward compatibility) |
| `campaigns` | `array` | Legacy v1 field (kept for backward compatibility) |

#### Campaign Snapshot

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `campaign_id` | `string` | Yes | Campaign ID |
| `campaign_name` | `string` | Yes | Campaign name |
| `status` | `string` | Yes | Current status (ENABLED, PAUSED, etc.) |
| `bidding_strategy_type` | `string` | No | Bidding strategy type |
| `bidding_details` | `object` | No | Strategy-specific details |
| `daily_budget` | `number` | No | Daily budget amount |
| `device_targeting` | `array` | No | Device bid modifiers |
| `campaign_goal` | `string` | No | Human-readable campaign goal |
| `notes` | `string` | No | Free-form notes |

#### Action Log Entry

Each entry in `action_log` records an action taken by a workflow command, with optional fields for evidence-based outcome tracking.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `timestamp` | `string` | Yes | ISO 8601 timestamp of the action |
| `action` | `string` | Yes | Description of the action taken |
| `platform` | `string` | Yes | Platform the action was taken on |
| `campaign_id` | `string` | No | Campaign affected |
| `command` | `string` | No | Slash command that initiated the action |
| `summary` | `string` | No | Human-readable summary |
| `metrics_at_action` | `object` | No | Key metrics at the time of action (e.g., `{"cpa": 5200, "conversions": 45}`) |
| `observation_due` | `string` | No | ISO 8601 date when the outcome should be evaluated (e.g., `"2026-04-15"`) |

The `metrics_at_action` and `observation_due` fields enable evidence-based outcome evaluation. When an action's observation window has passed, the agent compares current metrics against `metrics_at_action` to assess the action's impact. See `skills/mureo-learning/SKILL.md` for the evidence-based decision framework.

### Python API

```python
from pathlib import Path
from mureo.context import (
    CampaignSnapshot,
    StateDocument,
    read_state_file,
    write_state_file,
    upsert_campaign,
    get_campaign,
    parse_state,
    render_state,
)

path = Path("STATE.json")

# Read state
doc = read_state_file(path)
print(f"Version: {doc.version}, Campaigns: {len(doc.campaigns)}")

# Find a campaign
campaign = get_campaign(doc, "111222333")
if campaign:
    print(f"{campaign.campaign_name}: {campaign.status}")

# Upsert a campaign (add or update by campaign_id)
snapshot = CampaignSnapshot(
    campaign_id="111222333",
    campaign_name="Brand - Search",
    status="PAUSED",
    daily_budget=3000,
)
doc = upsert_campaign(path, snapshot)

# Parse from string / render to string
text = Path("STATE.json").read_text()
doc = parse_state(text)
json_str = render_state(doc)
```

## File Operations

Both `write_strategy_file()` and `write_state_file()` use **atomic writes** (write to temp file, then `os.replace()`). This prevents data corruption if the process is interrupted mid-write.

Parent directories are created automatically if they don't exist.

If a file doesn't exist when reading, the functions return empty/default values (empty list for STRATEGY.md, default `StateDocument` for STATE.json) rather than raising an error.

## Workflow Commands: Strategy in Action

The strategy context files are not just passive documentation -- they are actively consumed by mureo's **workflow commands** (`.claude/commands/`). These 10 slash commands bridge the gap between strategy and action by reading `STRATEGY.md` and `STATE.json`, then orchestrating the appropriate MCP tools.

### How Commands Use Strategy Context

| Strategy Section | Commands That Use It |
|-----------------|---------------------|
| **Operation Mode** | `/daily-check`, `/rescue`, `/budget-rebalance` -- adapts monitoring focus and reallocation logic |
| **Persona** | `/creative-refresh` -- generates ad copy aligned with target customer profile |
| **USP** | `/creative-refresh` -- ensures ad messaging highlights differentiators |
| **Brand Voice** | `/creative-refresh` -- maintains tone consistency across ad variants |
| **Market Context** | `/competitive-scan` -- interprets auction insights against known market conditions |

### Workflow

1. Run `/onboard` to set up credentials, generate `STRATEGY.md`, and initialize `STATE.json`.
2. Use `/daily-check` for routine monitoring -- the command reads `Operation Mode` to decide which metrics to prioritize.
3. When performance degrades, `/rescue` reads the full strategy context to diagnose issues and recommend fixes that align with business goals.
4. Periodic maintenance commands (`/search-term-cleanup`, `/creative-refresh`, `/budget-rebalance`, `/competitive-scan`) each read the relevant strategy sections to make context-aware decisions.
5. Run `/sync-state` to manually refresh `STATE.json` when campaign settings change outside of mureo.

See `skills/mureo-workflows/SKILL.md` for the complete Operation Mode reference and detailed command behavior.

### PDCA Loop: How Strategy Evolves

STRATEGY.md is not a static document -- it evolves through the PDCA operational loop:

- **Plan**: `/onboard` creates the initial STRATEGY.md with Persona, USP, Goals, and Operation Mode.
- **Do**: Daily commands read the current Operation Mode and Goals to drive context-aware actions.
- **Check**: `/goal-review` compares current performance against the Goals defined in STRATEGY.md. `/weekly-report` summarizes what actions were taken and their measured impact.
- **Act**: When `/goal-review` detects that goals are off-track, it recommends an Operation Mode change (e.g., EFFICIENCY_STABILIZE to TURNAROUND_RESCUE). When business context shifts (new product launch, seasonal change), `/onboard` is revisited to update Goals and Market Context sections.

The key fields that change through this loop are **Operation Mode** (updated when campaign conditions trigger a transition) and **Goal "Current" values** (updated as `/goal-review` captures actual performance against targets). STATE.json evolves in parallel, with `/sync-state` and other commands keeping campaign snapshots current.

## Data Model Immutability

All data models are frozen dataclasses:

- `StrategyEntry(frozen=True)` -- context_type, title, content
- `CampaignSnapshot(frozen=True)` -- campaign state fields, with defensive deep-copy of mutable fields
- `ActionLogEntry(frozen=True)` -- action details + metrics_at_action + observation_due, with defensive deep-copy
- `PlatformState(frozen=True)` -- per-platform account_id + campaigns
- `StateDocument(frozen=True)` -- version, metadata, platforms dict, action_log tuple

To "update" a record, create a new instance. The `upsert_campaign()` and `append_action_log()` functions handle this internally.
