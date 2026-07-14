---
name: _mureo-strategy
description: "Strategy Context: Manage business strategy files (STRATEGY.md, STATE.json) for strategy-driven ad operations."
metadata:
  version: 0.10.24
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
---

# Strategy Context
> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, global flags, and security rules.

## Overview

mureo uses two local context files to maintain business strategy and campaign state:

| File | Format | Purpose |
|------|--------|---------|
| `STRATEGY.md` | Markdown | Business strategy, personas, USP, brand voice |
| `STATE.json` | JSON | Campaign configuration snapshots |

These files live in the project working directory and are read by AI agents to make strategy-aligned advertising decisions.

## STRATEGY.md

### File Structure

`STRATEGY.md` is a Markdown file with `## Section` headings. Each section maps to a `context_type`:

| Section Heading | context_type | Purpose |
|----------------|--------------|---------|
| `## Persona` | `persona` | Target customer persona |
| `## USP` | `usp` | Unique selling proposition |
| `## Target Audience` | `target_audience` | Audience demographics and behavior |
| `## Brand Voice` | `brand_voice` | Tone, style, and language guidelines |
| `## Market Context` | `market_context` | Competitive landscape and market trends |
| `## Operation Mode` | `operation_mode` | Current operation mode (see below) |
| `## Custom: <title>` | `custom` | Freeform custom strategy entry |
| `## Deep Research: <title>` | `deep_research` | Results from website/competitor research |
| `## Sales Material: <title>` | `sales_material` | Extracted info from sales documents |
| `## Goal: <title>` | `goal` | Quantitative marketing goal with target, deadline, and priority |

### Example STRATEGY.md

```markdown
# Strategy

## Persona

**Name:** Tanaka-san (Marketing Manager)
**Age:** 35-45
**Role:** In-house marketing at mid-size SaaS company
**Goals:** Improve lead quality, reduce CPA below 8,000 yen
**Pain Points:** Limited budget, too many low-quality leads from broad targeting
**Decision Process:** Data-driven, needs ROI justification for budget increases

## USP

- Only platform that automates both Google Ads and Meta Ads from Slack
- AI agent handles routine optimization, freeing up 10+ hours/week
- Built-in budget safety guards prevent overspend

## Target Audience

**Primary:** SaaS marketing managers at companies with 50-500 employees
**Secondary:** Digital agency account managers handling 5+ client accounts
**Geo:** Japan (primary), US/EU (secondary)
**Budget Range:** 500,000 - 5,000,000 JPY/month ad spend

## Brand Voice

- Professional but approachable
- Data-backed claims, no hype
- Use concrete numbers over vague superlatives
- Japanese: polite form (desu/masu), avoid overly casual language

## Market Context

- Competitor A focuses on Google Ads only (no Meta Ads integration)
- Competitor B has Meta Ads but no Slack integration
- Market trend: increasing demand for AI-powered ad optimization
- Budget pressure: clients seeking efficiency gains, not just scale

## Operation Mode

EFFICIENCY_STABILIZE

## Custom: Seasonal Strategy

- Q1 (Jan-Mar): Budget conservative, focus on efficiency
- Q2 (Apr-Jun): Ramp up for spring campaigns
- Q3 (Jul-Sep): Peak season, maximize budget utilization
- Q4 (Oct-Dec): Holiday campaigns, shift to Meta Ads for brand awareness

## Goal: Reduce CPA below 5000 JPY

- Target: CPA < 5,000 JPY
- Deadline: 2026-06-30
- Current: CPA 6,200 JPY
- Platform: Google Ads, Meta Ads
- Priority: HIGH

## Goal: Increase monthly leads to 100

- Target: Leads >= 100/month
- Deadline: 2026-05-31
- Current: 72 leads/month
- Platform: Google Ads
- Priority: MEDIUM

## Deep Research: example.com

**Service Overview:** Cloud-based project management tool for remote teams
**Key Features:** Real-time collaboration, Gantt charts, resource allocation
**Pricing:** Freemium model, Pro plan at $15/user/month
**Competitors:** Asana, Monday.com, Notion
```

### Section Rules

- Each section starts with `## Heading` (h2 level)
- Standard sections use exact heading names (`Persona`, `USP`, etc.)
- Custom/research sections use the `Prefix: Title` format
- Unknown section headings are logged as warnings and skipped during parsing
- The file always starts with `# Strategy` (h1 level)

### Goal Format

Goal sections define quantitative marketing objectives. Each goal uses the `## Goal: <title>` heading and contains bullet-point fields:

| Field | Required | Description |
|-------|----------|-------------|
| `Target` | Yes | Measurable success criterion (e.g., `CPA < 5,000 JPY`) |
| `Deadline` | Yes | Target date in `YYYY-MM-DD` format |
| `Current` | No | Current baseline value for tracking progress |
| `Platform` | No | Applicable ad platforms (e.g., `Google Ads, Meta Ads`) |
| `Priority` | No | `HIGH`, `MEDIUM`, or `LOW` |

Multiple goals can coexist in a single STRATEGY.md. Agents should reference goals when making optimization decisions to ensure actions are aligned with measurable business objectives.

### Operation Modes

The `Operation Mode` section contains one of 7 predefined modes that control agent behavior:

| Mode | When to Use |
|------|-------------|
| `ONBOARDING_LEARNING` | Genuinely new campaigns still in their learning period — set this from campaign maturity (age + accumulated conversions), NOT just because mureo was newly set up on an existing long-running account |
| `TURNAROUND_RESCUE` | Campaigns with poor performance needing rescue |
| `SCALE_EXPANSION` | Campaigns ready to scale up |
| `EFFICIENCY_STABILIZE` | Mature campaigns optimizing for efficiency |
| `COMPETITOR_DEFENSE` | Increased competitive pressure detected |
| `CREATIVE_TESTING` | Focus on ad creative testing and iteration |
| `LTV_QUALITY_FOCUS` | Prioritize lead/conversion quality over volume |

### Guardrails (machine-enforced hard rules)

An **optional** `## Guardrails` section lets the operator declare hard limits
that mureo enforces **deterministically, before dispatch, regardless of what
the LLM decides** — via the built-in `StrategyPolicyGate` (a
`mureo.core.policy.PolicyGate` that ships in OSS). This is stronger than a
prose instruction the model could overlook.

**Coverage:** the gate runs inside mureo's own MCP dispatch, so it hard-enforces
every **mureo-dispatched** tool call — native `google_ads_*` / `meta_ads_*`,
`mureo_*`, and plugin tools routed through mureo. It does **NOT** cover a
**hosted connector** (e.g. TikTok's `tt-ads-*`, or an official Google/Meta MCP
used directly as a connector): those calls go client→platform and never reach
mureo's dispatcher, so the hard gate cannot see them. For hosted connectors,
guardrail adherence remains an instruction the skill must follow (or, when
available, an advisory pre-check the skill calls before mutating).

The section is machine-readable: one `- key: value` bullet per rule. Recognized
keys (all optional):

```markdown
## Guardrails
- max_daily_budget_per_campaign: 50000
- max_daily_budget_increase_pct: 20
- max_total_daily_budget: 300000
- max_lifetime_budget_per_campaign: 900000
- blocked_operations: google_ads_campaigns_remove, meta_ads_campaigns_delete
```

- `max_daily_budget_per_campaign` — a budget mutation proposing more than this
  (per campaign) is **refused**. Compared against the platform's native
  budget value: Google Ads amounts in account-currency units (micros are
  converted), Meta amounts in Meta's minor units — identical to currency
  units for JPY and other zero-decimal currencies, but cents for USD-like
  currencies.
- `max_daily_budget_increase_pct` — a budget raise larger than this percent is
  refused **when the current budget is supplied** (skills pass
  `current_daily_budget`).
- `max_total_daily_budget` — refused when a caller supplies
  `projected_total_daily_budget` above this.
- `max_lifetime_budget_per_campaign` — a mutation proposing a lifetime /
  period-total budget above this is refused. Compared against the
  platform's native value: Meta `lifetime_budget` in Meta's minor units
  (= currency units for JPY-like zero-decimal currencies, cents for
  USD-like), Google Ads CUSTOM_PERIOD `total_amount` in currency units or
  `total_amount_micros` converted from micros. Lifetime and daily budgets
  have distinct semantics, so declare this cap separately — a daily cap
  alone does not constrain lifetime-budget mutations.
- `blocked_operations` — comma-separated tool names that are always refused.

Absent section (or an unparseable value) ⇒ no enforcement for that rule
(fail-open); mureo never blocks on a rule the operator did not write. When a
mutation is refused, the agent receives the guardrail's reason verbatim and
should surface it to the operator rather than retrying.

## STATE.json

### File Structure

```json
{
  "version": "2",
  "last_synced_at": "2026-04-01T10:00:00+09:00",
  "platforms": {
    "google_ads": {
      "account_id": "1234567890",
      "campaigns": [
        {
          "campaign_id": "111222333",
          "campaign_name": "Brand Search - Tokyo",
          "status": "ENABLED",
          "bidding_strategy_type": "MAXIMIZE_CONVERSIONS",
          "bidding_details": {"target_cpa": 5000},
          "daily_budget": 8000.0,
          "campaign_goal": "Lead generation for SaaS trial signups",
          "notes": "Learning period ends ~April 5. Do not change bids."
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
      "summary": "Excluded informational queries misaligned with Persona",
      "metrics_at_action": {"cpa": 5200, "conversions": 45, "clicks": 1200},
      "observation_due": "2026-04-15"
    }
  ]
}
```

### Campaign Snapshot Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `campaign_id` | string | Yes | Campaign identifier |
| `campaign_name` | string | Yes | Human-readable name |
| `status` | string | Yes | `ENABLED`, `PAUSED`, or `REMOVED` |
| `bidding_strategy_type` | string | No | e.g., `MAXIMIZE_CONVERSIONS`, `TARGET_CPA` |
| `bidding_details` | object | No | Strategy-specific details (target_cpa, target_roas, etc.) |
| `daily_budget` | number | No | Daily budget in currency units |
| `device_targeting` | array | No | Device bid modifiers |
| `campaign_goal` | string | No | Business objective for this campaign |
| `notes` | string | No | Important notes (learning period, restrictions, etc.) |
| `metrics` | object | No | Latest performance snapshot — canonical vocabulary below |

### Performance Metrics — canonical vocabulary

`campaigns[].metrics` (per campaign) and `platforms[<p>].totals` (per-platform
rollup) use ONE shared field vocabulary so every skill, the reporting
dashboard, and any other STATE.json consumer agree on names and units. Write
these exact keys (lowercase); omit a key when the platform does not provide it.

| Key | Type | Unit / meaning |
|-----|------|----------------|
| `spend` | number | Cost in the account's **currency units** (NOT micros) |
| `impressions` | integer | Impressions |
| `clicks` | integer | Clicks |
| `conversions` | number | Conversions (see `result_indicator` for what counts) |
| `cpa` | number | Cost per conversion, currency units (`spend / conversions`) |
| `ctr` | number | Click-through rate as a ratio (e.g. `0.024`), not a percent string |
| `result_indicator` | string | **Meta only** — what a "result/conversion" counts (e.g. `link_click` vs `offsite_conversion.fb_pixel_lead`) |
| `period` | string | Window the numbers cover, e.g. `LAST_30_DAYS` |
| `fetched_at` | string | ISO 8601 time the numbers were pulled (freshness) |

**CV-definition rule (Meta):** never aggregate conversions/CPA across campaigns
with **different** `result_indicator` values — `link_click`-optimized totals and
`pixel_lead`-optimized totals are different things. Group by `result_indicator`.
Google Ads has a single conversion definition, so `result_indicator` is omitted.

Platform-level: `platforms[<p>].totals` holds the same keys summed for that
platform (respecting the `result_indicator` grouping for Meta), and
`platforms[<p>].metrics_period` records the window the totals cover.

**Per-period rollups:** `platforms[<p>].periods` is an optional map keyed by a
canonical period token, each value a totals-shaped object using the SAME
vocabulary above — so the reporting dashboard can offer a period toggle. Use
these exact tokens (they are Google Ads date-range tokens):

| Token | Window | Written by |
|-------|--------|------------|
| `YESTERDAY` | The prior day | `daily-check` (runs daily) |
| `LAST_30_DAYS` | Trailing 30 days | `sync-state` |

Write a platform's rollup with the `mureo_state_platform_metrics_set` tool on
hosts without filesystem access (Desktop / Cowork), or a direct file write in
Code mode: pass `totals` + `metrics_period` for the single most-recent window
and/or `periods` for the per-window map. `periods` is merged per window key, so
writing `YESTERDAY` never clobbers a prior `LAST_30_DAYS` bucket (and vice
versa); omitted fields preserve their existing value.

### Reports section

`reports` (top-level, optional) holds the latest agent-written summary per
report kind so the dashboard can show it without re-running the agent:
`reports = {"daily": {...}, "weekly": {...}, "goal": {...}}`. Each value is
`{generated_at (ISO 8601), period, kpis (headline numbers using the vocabulary
above), flags (list of notable items), narrative (short text)}`. Written via
the `mureo_state_report_set` tool by `daily-check` / `weekly-report` /
`goal-review`.

**A report summary must reflect the FINAL state of the run that wrote it.**
Persist it AFTER every STATE change and `action_log` entry the run made, and
let the `narrative` / `flags` describe the post-change state — never a
pre-change snapshot (e.g. "switched to `EFFICIENCY_STABILIZE`", not "recommend
switching", once you have switched it). Otherwise the dashboard's "Latest
report" reads as older than, and contradicts, the very `action_log` entry the
same run appended.

### Action Log Entry Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `timestamp` | string | Yes | ISO 8601 timestamp of the action |
| `action` | string | Yes | Description of the action taken |
| `platform` | string | Yes | Platform the action was taken on |
| `campaign_id` | string | No | Campaign affected |
| `command` | string | No | Slash command that initiated the action |
| `summary` | string | No | Human-readable summary |
| `metrics_at_action` | object | No | Key metrics at the time of action, for outcome evaluation — use the same canonical vocabulary as `metrics` above (e.g. `cpa`, `conversions`, `clicks`) |
| `observation_due` | string | No | ISO 8601 date when the outcome should be evaluated |

The `metrics_at_action` and `observation_due` fields enable evidence-based outcome evaluation. See `skills/_mureo-learning/SKILL.md` for the decision framework.

### State Lifecycle

1. **Initial sync**: Agent calls campaign list/get tools, populates STATE.json
2. **Upsert on read**: After any read tool call, the campaign snapshot is upserted
3. **Notes on write**: After write operations, action logs and notes are updated
4. **Outcome tracking**: Write operations record `metrics_at_action` and `observation_due` for later evaluation
5. **Agent reads STATE.json** before making decisions, ensuring context continuity

## Strategy-Driven Workflows

### 1. Persona-Based Ad Copy Creation

Using the persona to write better ad copy:

```
Step 1: Read STRATEGY.md to understand the target persona

Step 2: Based on persona pain points, craft headlines that address them directly
  Example persona pain point: "Limited budget, too many low-quality leads"
  -> Headlines: "Reduce Wasted Ad Spend by 40%", "Get Better Leads, Not More Leads"

Step 3: Create the RSA ad (with Google Ads tools)
  -> google_ads_ads_create {
       headlines addressing persona pain points,
       descriptions highlighting USP
     }
```

### 2. USP-Driven Keyword Selection

Using USP to find high-intent keywords:

```
Step 1: Read STRATEGY.md USP section
  Key differentiators: "Slack integration", "AI automation", "budget safety"

Step 2: Generate seed keywords from USP
  -> google_ads_keywords_suggest {seed_keywords: ["slack ad management", "ai ad optimization", "ad budget automation"]}

Step 3: Review suggestions against target audience
  Filter by relevance to the target audience segment

Step 4: Add selected keywords
  -> google_ads_keywords_add {keywords: [...]}
```

### 3. Brand Voice Compliance Check

Ensuring ad copy matches the brand voice:

```
Step 1: Read STRATEGY.md Brand Voice section
  Rules: "Professional but approachable", "data-backed claims", "no hype"

Step 2: List current ads
  -> google_ads_ads_list {customer_id, ad_group_id}

Step 3: Review each ad against brand voice rules
  Flag: "Best Ad Platform Ever!" -> violates "no hype" rule
  OK: "Reduce CPA by 30% with AI-Powered Optimization" -> data-backed, professional

Step 4: Update non-compliant ads (CONFIRM WITH USER)
  -> google_ads_ads_update {headlines: [improved versions]}
```

### 4. Operation Mode-Guided Actions

Different modes guide different agent behaviors:

**TURNAROUND_RESCUE mode:**
```
Priority: Stop the bleeding
1. Check search terms for wasted spend
   -> google_ads_search_terms_review {campaign_id, target_cpa}
2. Add negative keywords aggressively
3. Pause underperforming ad groups
4. Review budget allocation
```

**SCALE_EXPANSION mode:**
```
Priority: Grow while maintaining efficiency
1. Find new keyword opportunities
   -> google_ads_keywords_suggest {seed_keywords}
2. Test new ad copy variations
3. Increase budgets on high-performing campaigns (confirm with user)
4. Expand targeting (new geographies, demographics)
```

**ONBOARDING_LEARNING mode:**
```
Priority: Let the algorithm learn, minimal changes
Applies to a campaign genuinely IN its learning period — not to a mature
campaign that mureo was simply set up on recently. If the campaign already
has accumulated conversions / history, it is NOT learning: switch the mode
(e.g. EFFICIENCY_STABILIZE) and analyze normally instead of withholding.
1. Confirm the campaign is actually learning (recent start, sparse conversions)
   -> google_ads_campaigns_diagnose {customer_id, campaign_id}
2. If still learning: monitor performance, warn before budget/bid changes,
   wait until the learning period completes before optimizing
3. If already mature: recommend updating Operation Mode and proceed
```

### 5. Market Context for Competitive Response

Using market context to respond to competitor moves:

```
Step 1: Read STRATEGY.md Market Context section
  Known: Competitor A is Google-only, Competitor B has no Slack

Step 2: Check auction insights for competitor activity
  -> google_ads_auction_insights_analyze {customer_id, campaign_id}

Step 3: If a new competitor appears or impression share drops:
  - Check CPC trends for bidding pressure
    -> google_ads_cpc_detect_trend {customer_id, campaign_id}
  - Review device performance for competitor dominance patterns
    -> google_ads_device_analyze {customer_id, campaign_id}

Step 4: Recommend strategic response based on market context
  e.g., "Competitor A gained 5% impression share. Since they don't support
         Meta Ads, recommend shifting 20% of budget to Meta to leverage
         our cross-platform advantage."
```

## File Management Best Practices

### STRATEGY.md

- Keep sections concise (3-10 bullet points each)
- Update when business strategy changes (quarterly review recommended)
- The persona section should reflect actual customer interviews/data
- Operation mode should be updated when campaign conditions change significantly

### STATE.json

- Treat as a cache, not a source of truth (the ad platform API is authoritative)
- The `notes` field is valuable for tracking learning periods and restrictions
- `last_synced_at` indicates data freshness; re-sync if stale
- Campaign snapshots are upserted (existing entries updated, new ones added)

### Version Control

Both files can be committed to version control:
- `STRATEGY.md`: Yes, contains business knowledge
- `STATE.json`: Optional, contains point-in-time snapshots (may change frequently)

Do **not** commit `~/.mureo/credentials.json` -- it contains secrets.
