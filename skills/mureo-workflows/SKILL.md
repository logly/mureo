---
name: mureo-workflows
description: "Operational workflow reference: strategy-driven ad operations with mureo commands."
metadata:
  version: 0.2.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
---

# mureo Workflows

Operational workflow reference for strategy-driven ad campaign management using mureo slash commands.

## Overview

mureo provides 8 slash commands that combine MCP tool calls with business strategy context (STRATEGY.md + STATE.json) to manage advertising campaigns across Google Ads and Meta Ads. Every command reads strategy context before taking action, ensuring all operations are aligned with business goals.

### Core Principle

**Strategy-first operations**: Every optimization, budget change, and creative decision is validated against the business strategy defined in STRATEGY.md and the current campaign state in STATE.json.

## Command Quick Reference

| Command | Purpose | Frequency | Prerequisites |
|---------|---------|-----------|---------------|
| `/onboard` | Initial account setup | Once | mureo installed |
| `/daily-check` | Daily health monitoring | Daily | STRATEGY.md, STATE.json |
| `/rescue` | Emergency performance fix | As needed | STRATEGY.md, STATE.json |
| `/search-term-cleanup` | Search term hygiene | Weekly/Bi-weekly | STRATEGY.md, STATE.json |
| `/creative-refresh` | Ad copy refresh | Monthly | STRATEGY.md, STATE.json |
| `/budget-rebalance` | Budget optimization | Monthly | STRATEGY.md, STATE.json |
| `/competitive-scan` | Competitive analysis | Bi-weekly/Monthly | STRATEGY.md, STATE.json |
| `/sync-state` | State synchronization | As needed | STATE.json (or run /onboard) |

## Dependency Graph

```
/onboard (run first)
  |
  +-- Creates STRATEGY.md + STATE.json
  |
  +---> /daily-check (routine monitoring)
  |       |
  |       +---> /rescue (if performance problems detected)
  |       +---> /search-term-cleanup (if wasted spend detected)
  |       +---> /creative-refresh (if LOW/POOR assets detected)
  |       +---> /budget-rebalance (if budget inefficiency detected)
  |       +---> /competitive-scan (if impression share drops)
  |
  +---> /sync-state (manual refresh of STATE.json)
```

**Critical path**: `/onboard` must run first. All other commands depend on STRATEGY.md and STATE.json existing.

## Operation Mode Behavior Matrix

The Operation Mode in STRATEGY.md controls how each command behaves. The matrix below defines what each mode prioritizes and what it avoids.

### ONBOARDING_LEARNING

| Aspect | Behavior |
|--------|----------|
| **Priority** | Let smart bidding algorithms learn; collect data |
| **Daily check focus** | Monitor learning status via campaign diagnostics |
| **Allowed actions** | Read-only analysis, minor negative keyword additions |
| **Avoid** | Budget changes, bid strategy changes, pausing campaigns |
| **Transition trigger** | Learning period complete (typically 2-4 weeks) |
| **Next mode** | EFFICIENCY_STABILIZE or TURNAROUND_RESCUE |

### EFFICIENCY_STABILIZE

| Aspect | Behavior |
|--------|----------|
| **Priority** | Maintain or improve CPA/ROAS within stable performance |
| **Daily check focus** | CPA trend analysis, performance anomaly detection |
| **Allowed actions** | Search term cleanup, incremental budget shifts (<10%), creative testing |
| **Avoid** | Large budget swings (>20%), drastic structural changes |
| **Transition trigger** | CPA exceeds target by >30% for 7+ days |
| **Next mode** | TURNAROUND_RESCUE or SCALE_EXPANSION |

### TURNAROUND_RESCUE

| Aspect | Behavior |
|--------|----------|
| **Priority** | Stop wasted spend, restore conversions |
| **Daily check focus** | Zero-conversion campaigns, cost spikes, search term waste |
| **Allowed actions** | Aggressive negative keywords, budget cuts on waste, device bid adjustments |
| **Avoid** | Scaling, new campaigns, experimental features |
| **Transition trigger** | CPA returns to within 10% of target for 7+ days |
| **Next mode** | EFFICIENCY_STABILIZE |

### SCALE_EXPANSION

| Aspect | Behavior |
|--------|----------|
| **Priority** | Grow volume while maintaining acceptable efficiency |
| **Daily check focus** | Budget utilization, impression share headroom, new keyword opportunities |
| **Allowed actions** | Budget increases, new keyword expansion, new campaign tests |
| **Avoid** | Cutting budgets on learning campaigns, over-optimizing for CPA at expense of volume |
| **Transition trigger** | CPA rises above acceptable threshold |
| **Next mode** | EFFICIENCY_STABILIZE or TURNAROUND_RESCUE |

### COMPETITOR_DEFENSE

| Aspect | Behavior |
|--------|----------|
| **Priority** | Protect impression share on core brand/product terms |
| **Daily check focus** | Auction insights, impression share trends, CPC trends |
| **Allowed actions** | Budget increases on core terms, bid adjustments, cross-platform shifts |
| **Avoid** | Broad expansion into new areas, reducing spend on core terms |
| **Transition trigger** | Impression share stabilizes at acceptable levels |
| **Next mode** | EFFICIENCY_STABILIZE or SCALE_EXPANSION |

### CREATIVE_TESTING

| Aspect | Behavior |
|--------|----------|
| **Priority** | Test and iterate on ad creatives to find winning messages |
| **Daily check focus** | RSA asset ratings, ad variant performance, landing page relevance |
| **Allowed actions** | New headline/description creation, ad copy A/B tests, LP analysis |
| **Avoid** | Budget changes, keyword changes, structural campaign edits |
| **Transition trigger** | Winning creative identified (statistically significant) |
| **Next mode** | EFFICIENCY_STABILIZE or SCALE_EXPANSION |

### LTV_QUALITY_FOCUS

| Aspect | Behavior |
|--------|----------|
| **Priority** | Improve lead/conversion quality over volume |
| **Daily check focus** | Search term quality, audience alignment, conversion quality signals |
| **Allowed actions** | Search term refinement, audience exclusions, quality-focused bid adjustments |
| **Avoid** | Broad targeting, volume-maximizing bid strategies |
| **Transition trigger** | Lead quality meets target thresholds |
| **Next mode** | EFFICIENCY_STABILIZE or SCALE_EXPANSION |

## KPI Thresholds Reference

Use these thresholds to classify campaign health in daily checks and reports.

### CPA (Cost Per Acquisition)

| Status | Condition |
|--------|-----------|
| **Healthy** | Within 10% of target CPA |
| **Warning** | 10-30% above target CPA |
| **Critical** | >30% above target CPA or zero conversions with spend |

### CVR (Conversion Rate)

| Status | Condition |
|--------|-----------|
| **Healthy** | Within 20% of account average CVR |
| **Warning** | 20-50% below account average |
| **Critical** | >50% below average or 0% with 100+ clicks |

### Impression Share

| Status | Condition |
|--------|-----------|
| **Healthy** | >70% for brand terms, >30% for generic terms |
| **Warning** | Brand terms 50-70%, generic terms 15-30% |
| **Critical** | Brand terms <50%, generic terms <15% |

### CTR (Click-Through Rate)

| Status | Condition |
|--------|-----------|
| **Healthy** | >3% for search campaigns |
| **Warning** | 1-3% for search campaigns |
| **Critical** | <1% for search campaigns |

### Budget Utilization

| Status | Condition |
|--------|-----------|
| **Healthy** | 80-100% of daily budget utilized |
| **Warning** | <60% utilized (underspend) or >100% consistently (limited by budget) |
| **Critical** | <30% utilized or campaign limited by budget with strong performance |

### RSA Asset Ratings

| Status | Condition |
|--------|-----------|
| **Healthy** | All assets rated GOOD or BEST |
| **Warning** | Any assets rated LOW |
| **Critical** | Multiple assets rated POOR or no performance data after 30+ days |

### CPC Trend

| Status | Condition |
|--------|-----------|
| **Healthy** | Stable or declining CPC with maintained volume |
| **Warning** | CPC rising 10-20% week-over-week |
| **Critical** | CPC rising >20% week-over-week or sudden spike >50% |

## External Tool Integration

mureo workflow commands can leverage data from external MCP servers (e.g., GA4, Search Console, CRM) when configured alongside mureo in the same client.

### Opportunistic Data Access

Commands check for external tool availability at runtime. If a GA4 MCP is configured and responds, the agent incorporates analytics data (conversion rates, user behavior, traffic sources) into its analysis. If the external MCP is not available, the command proceeds normally using only mureo's Google Ads and Meta Ads data.

**No hard dependency**: No mureo command requires any external MCP server to function. External data is always additive, never blocking.

### Which Commands Benefit

| Command | External Data Value |
|---------|-------------------|
| `/daily-check` | GA4 LP conversion rates enrich health assessment |
| `/creative-refresh` | GA4 engagement metrics inform copy decisions |
| `/budget-rebalance` | GA4 e-commerce data and CRM LTV data improve budget allocation |
| `/competitive-scan` | Search Console organic data reveals full competitive picture |
| `/search-term-cleanup` | Search Console keyword overlap identifies SEO/SEM coordination opportunities |

See [docs/integrations.md](../../docs/integrations.md) for configuration instructions and supported platforms.

## Workflow Best Practices

### Recommended Weekly Cadence

| Day | Activity |
|-----|----------|
| Monday | `/daily-check` + `/competitive-scan` |
| Tuesday-Thursday | `/daily-check` |
| Friday | `/daily-check` + `/search-term-cleanup` |
| Monthly (1st week) | `/budget-rebalance` + `/creative-refresh` |

### Safety Rules

1. **Never auto-execute write operations** -- all commands ask for approval before changes
2. **Budget changes >20% trigger a warning** -- smart bidding may reset its learning period
3. **Always show current vs proposed values** -- for budgets, bids, and status changes
4. **Batch keyword operations** -- add/remove in groups of 20 or fewer
5. **Respect learning periods** -- ONBOARDING_LEARNING mode blocks most changes

### Strategy File Maintenance

- **STRATEGY.md**: Review quarterly; update immediately when business strategy changes
- **STATE.json**: Auto-updated by commands; use `/sync-state` for manual refresh
- **Operation Mode**: Update when campaign conditions change (see transition triggers above)
