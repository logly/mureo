---
name: mureo-strategy
description: "Strategy Context: Manage business strategy files (STRATEGY.md, STATE.json) for strategy-driven ad operations."
metadata:
  version: 0.1.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
---

# Strategy Context
> PREREQUISITE: Read `../mureo-shared/SKILL.md` for auth, global flags, and security rules.

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

### Operation Modes

The `Operation Mode` section contains one of 7 predefined modes that control agent behavior:

| Mode | When to Use |
|------|-------------|
| `ONBOARDING_LEARNING` | New campaigns in learning period |
| `TURNAROUND_RESCUE` | Campaigns with poor performance needing rescue |
| `SCALE_EXPANSION` | Campaigns ready to scale up |
| `EFFICIENCY_STABILIZE` | Mature campaigns optimizing for efficiency |
| `COMPETITOR_DEFENSE` | Increased competitive pressure detected |
| `CREATIVE_TESTING` | Focus on ad creative testing and iteration |
| `LTV_QUALITY_FOCUS` | Prioritize lead/conversion quality over volume |

## STATE.json

### File Structure

```json
{
  "version": "1",
  "last_synced_at": "2026-03-29T10:30:00+09:00",
  "customer_id": "1234567890",
  "campaigns": [
    {
      "campaign_id": "111222333",
      "campaign_name": "Brand Search - Tokyo",
      "status": "ENABLED",
      "bidding_strategy_type": "MAXIMIZE_CONVERSIONS",
      "bidding_details": {
        "target_cpa": 5000
      },
      "daily_budget": 8000.0,
      "device_targeting": [
        {"type": "DESKTOP", "bid_modifier": 1.0},
        {"type": "MOBILE", "bid_modifier": 1.2}
      ],
      "campaign_goal": "Lead generation for SaaS trial signups",
      "notes": "Learning period ends ~April 5. Do not change bids."
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

### State Lifecycle

1. **Initial sync**: Agent calls campaign list/get tools, populates STATE.json
2. **Upsert on read**: After any read tool call, the campaign snapshot is upserted
3. **Notes on write**: After write operations, action logs and notes are updated
4. **Agent reads STATE.json** before making decisions, ensuring context continuity

## Strategy-Driven Workflows

### 1. Persona-Based Ad Copy Creation

Using the persona to write better ad copy:

```
Step 1: Read STRATEGY.md to understand the target persona

Step 2: Based on persona pain points, craft headlines that address them directly
  Example persona pain point: "Limited budget, too many low-quality leads"
  -> Headlines: "Reduce Wasted Ad Spend by 40%", "Get Better Leads, Not More Leads"

Step 3: Create the RSA ad (with Google Ads tools)
  -> google_ads.ads.create {
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
  -> google_ads.keywords.suggest {seed_keywords: ["slack ad management", "ai ad optimization", "ad budget automation"]}

Step 3: Review suggestions against target audience
  Filter by relevance to the target audience segment

Step 4: Add selected keywords
  -> google_ads.keywords.add {keywords: [...]}
```

### 3. Brand Voice Compliance Check

Ensuring ad copy matches the brand voice:

```
Step 1: Read STRATEGY.md Brand Voice section
  Rules: "Professional but approachable", "data-backed claims", "no hype"

Step 2: List current ads
  -> google_ads.ads.list {customer_id, ad_group_id}

Step 3: Review each ad against brand voice rules
  Flag: "Best Ad Platform Ever!" -> violates "no hype" rule
  OK: "Reduce CPA by 30% with AI-Powered Optimization" -> data-backed, professional

Step 4: Update non-compliant ads (CONFIRM WITH USER)
  -> google_ads.ads.update {headlines: [improved versions]}
```

### 4. Operation Mode-Guided Actions

Different modes guide different agent behaviors:

**TURNAROUND_RESCUE mode:**
```
Priority: Stop the bleeding
1. Check search terms for wasted spend
   -> google_ads.search_terms.review {campaign_id, target_cpa}
2. Add negative keywords aggressively
3. Pause underperforming ad groups
4. Review budget allocation
```

**SCALE_EXPANSION mode:**
```
Priority: Grow while maintaining efficiency
1. Find new keyword opportunities
   -> google_ads.keywords.suggest {seed_keywords}
2. Test new ad copy variations
3. Increase budgets on high-performing campaigns (confirm with user)
4. Expand targeting (new geographies, demographics)
```

**ONBOARDING_LEARNING mode:**
```
Priority: Let the algorithm learn, minimal changes
1. Monitor performance but avoid making changes
2. Warn before any budget or bid changes
3. Check campaign diagnose for learning status
   -> google_ads.campaigns.diagnose {customer_id, campaign_id}
4. Wait until learning period completes before optimizing
```

### 5. Market Context for Competitive Response

Using market context to respond to competitor moves:

```
Step 1: Read STRATEGY.md Market Context section
  Known: Competitor A is Google-only, Competitor B has no Slack

Step 2: Check auction insights for competitor activity
  -> google_ads.auction_insights.analyze {customer_id, campaign_id}

Step 3: If a new competitor appears or impression share drops:
  - Check CPC trends for bidding pressure
    -> google_ads.cpc.detect_trend {customer_id, campaign_id}
  - Review device performance for competitor dominance patterns
    -> google_ads.device.analyze {customer_id, campaign_id}

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
