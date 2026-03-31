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

STATE.json is a JSON file containing a snapshot of campaign state.

```json
{
  "version": "1",
  "last_synced_at": "2025-01-15T10:30:00Z",
  "customer_id": "1234567890",
  "campaigns": [
    {
      "campaign_id": "111222333",
      "campaign_name": "Brand - Search",
      "status": "ENABLED",
      "bidding_strategy_type": "TARGET_CPA",
      "bidding_details": {
        "target_cpa_micros": 5000000
      },
      "daily_budget": 5000,
      "device_targeting": [
        {"device": "MOBILE", "bid_modifier": 1.2}
      ],
      "campaign_goal": "Maximize conversions at target CPA",
      "notes": "Learning period ends 2025-01-20"
    }
  ]
}
```

### Fields

#### Root

| Field | Type | Description |
|-------|------|-------------|
| `version` | `string` | Schema version (currently `"1"`) |
| `last_synced_at` | `string \| null` | ISO 8601 timestamp of last sync |
| `customer_id` | `string \| null` | Google Ads customer ID or Meta Ads account ID |
| `campaigns` | `array` | List of campaign snapshots |

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

## Data Model Immutability

All data models are frozen dataclasses:

- `StrategyEntry(frozen=True)` -- context_type, title, content
- `CampaignSnapshot(frozen=True)` -- campaign state fields, with defensive deep-copy of mutable fields
- `StateDocument(frozen=True)` -- version, metadata, tuple of campaigns

To "update" a record, create a new instance. The `upsert_campaign()` function handles this internally.
