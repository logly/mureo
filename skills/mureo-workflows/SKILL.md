---
name: mureo-workflows
description: "Operational workflow reference: strategy-driven marketing orchestration with mureo commands."
metadata:
  version: 0.3.0
  openclaw:
    category: "marketing"
    requires:
      bins:
        - mureo
---

# mureo Workflows

Operational workflow reference for strategy-driven marketing orchestration using mureo commands.

## Overview

mureo provides a set of workflow commands that orchestrate marketing operations across all configured platforms (Google Ads, Meta Ads, Search Console, GA4, and future platforms). Every command reads strategy context before taking action, discovers available platforms at runtime, and adapts its behavior to what is configured — no hardcoded platform assumptions.

> **Invocation syntax by host:** this document uses the `/command` form throughout for readability, which matches the Claude Code slash-command surface. On **OpenAI Codex CLI** the same commands are installed as Codex skills at `~/.codex/skills/<command>/SKILL.md` and are invoked with `$command` (or via the `/skills` picker) — e.g. read `$daily-check` wherever you see `/daily-check`. Codex CLI 0.117.0+ stopped rendering `~/.codex/prompts/`, so skills are the only supported surface.

### Core Principles

1. **Strategy-first operations**: Every optimization, budget change, and creative decision is validated against the business strategy defined in STRATEGY.md and the current state in STATE.json.

2. **Platform discovery**: Commands iterate over `STATE.json.platforms` and probe for external data sources (GA4, CRM) at runtime. Operations scale automatically as platforms are added.

3. **Cross-platform correlation**: Commands leverage multiple data sources to provide insights that no single platform can offer (paid vs organic overlap, ad platform vs on-site conversion data, cross-platform budget efficiency).

## Command Quick Reference

| Command | Purpose | Frequency | Data Sources |
|---------|---------|-----------|--------------|
| `/onboard` | Initial account setup | Once | All discovered platforms |
| `/daily-check` | Daily health monitoring | Daily | Ad platforms + Search Console + GA4 |
| `/rescue` | Emergency performance fix | As needed | Ad platforms + GA4 (site-side diagnosis) |
| `/search-term-cleanup` | Search term hygiene | Weekly/Bi-weekly | Ad platforms + Search Console + GA4 |
| `/creative-refresh` | Ad copy refresh | Monthly | Ad platforms + Search Console + GA4 |
| `/budget-rebalance` | Budget optimization | Monthly | Ad platforms + Search Console + GA4 |
| `/competitive-scan` | Competitive analysis | Bi-weekly/Monthly | Ad platforms + Search Console + GA4 |
| `/goal-review` | Goal progress evaluation | Weekly | All platforms + all data sources |
| `/weekly-report` | Weekly operations summary | Weekly | All platforms + all data sources |
| `/sync-state` | State synchronization | As needed | All platforms |
| `/learn` | Save diagnostic insights | As needed | All platforms |

## PDCA Operational Loop

The commands form a continuous **Plan-Do-Check-Act** cycle that drives all mureo operations:

```
Plan:  /onboard → Discover platforms, define strategy, set goals
  ↓
Do:    /daily-check → /rescue, /search-term-cleanup, /creative-refresh,
                      /budget-rebalance, /competitive-scan
  ↓
Check: /goal-review → Evaluate goal progress across all platforms & data sources
       /weekly-report → Summarize actions + impact with cross-platform insights
  ↓
Act:   /goal-review recommendations → Adjust Operation Mode → Back to Do
       /onboard (revisit) → Update Goals if business context changed
```

**How the loop runs:**

- **Daily**: The Do phase executes via `/daily-check`, which discovers all platforms, runs diagnostics, checks organic search pulse (Search Console), correlates on-site behavior (GA4), and triages into specialized commands based on detected issues.
- **Weekly**: The Check phase runs `/goal-review` and `/weekly-report` to measure progress against goals using data from all configured sources.
- **Act phase trigger**: `/goal-review` closes the loop by recommending which Do commands to prioritize next and whether the Operation Mode should change.
- **Evidence gate**: Strategy changes (Operation Mode, Goals) should only be made when backed by sufficient evidence. See `skills/mureo-learning/SKILL.md` for observation windows, sample sizes, and the OBSERVING → CANDIDATE → VALIDATED lifecycle.
- **Strategy refresh**: When business context changes, revisit `/onboard` to update STRATEGY.md, restarting the Plan phase.

## Dependency Graph

```
/onboard (run first — Plan phase)
  |
  +-- Discovers platforms, creates STRATEGY.md + STATE.json
  |
  +---> /daily-check (routine monitoring — Do phase)
  |       |
  |       +--- Discovers platforms + data sources at runtime
  |       |
  |       +---> /rescue (if performance problems detected)
  |       +---> /search-term-cleanup (if wasted spend detected)
  |       +---> /creative-refresh (if underperforming creatives)
  |       +---> /budget-rebalance (if budget inefficiency detected)
  |       +---> /competitive-scan (if impression share drops)
  |
  +---> /goal-review (evaluate goal progress — Check phase)
  |       |
  |       +--- Gathers metrics from all platforms + GA4 + Search Console
  |       +--- Synthesizes unified goal progress view
  |
  +---> /weekly-report (summarize actions + impact — Check phase)
  |       |
  |       +--- Cross-platform performance comparison
  |       +--- Recommendations feed back into Do commands (Act phase)
  |       +--- Operation Mode change → alters Do command behavior
  |
  +---> /sync-state (manual refresh of STATE.json — runs throughout)
```

**Critical path**: `/onboard` must run first. All other commands depend on STRATEGY.md and STATE.json existing.

## Cross-Platform Data Correlation

Commands leverage multiple data sources together for deeper insights:

| Correlation | Sources | Value |
|------------|---------|-------|
| Paid vs organic keyword overlap | Ad platforms + Search Console | Reduce paid spend on terms with strong organic ranking; identify SEO opportunities from high-performing paid terms |
| Ad platform vs on-site conversions | Ad platforms + GA4 | Detect conversion tracking discrepancies; identify landing page issues vs ad issues |
| Landing page quality by source | Ad platforms + GA4 | Evaluate bounce rate, time on page, scroll depth by traffic source to inform budget allocation |
| Full-funnel visibility | Ad platforms + GA4 + CRM | Impression → click → session → conversion → lead quality pipeline |
| Competitive landscape (paid + organic) | Ad platforms + Search Console | Unified view of competitive position across paid auction and organic rankings |

## Operation Mode Behavior Matrix

The Operation Mode in STRATEGY.md controls how each command behaves. The matrix below defines what each mode prioritizes and what it avoids.

### ONBOARDING_LEARNING

| Aspect | Behavior |
|--------|----------|
| **Priority** | Let smart bidding algorithms learn; collect data |
| **Daily check focus** | Monitor learning status on each platform |
| **Allowed actions** | Read-only analysis, minor negative keyword additions |
| **Avoid** | Budget changes, bid strategy changes, pausing campaigns |
| **Transition trigger** | Learning period complete (typically 2-4 weeks) |
| **Next mode** | EFFICIENCY_STABILIZE or TURNAROUND_RESCUE |

### EFFICIENCY_STABILIZE

| Aspect | Behavior |
|--------|----------|
| **Priority** | Maintain or improve CPA/ROAS within stable performance |
| **Daily check focus** | CPA trend analysis across all platforms, performance anomaly detection |
| **Allowed actions** | Search term cleanup, incremental budget shifts (<10%), creative testing |
| **Avoid** | Large budget swings (>20%), drastic structural changes |
| **Transition trigger** | CPA exceeds target by >30% for 7+ days |
| **Next mode** | TURNAROUND_RESCUE or SCALE_EXPANSION |

### TURNAROUND_RESCUE

| Aspect | Behavior |
|--------|----------|
| **Priority** | Stop wasted spend, restore conversions |
| **Daily check focus** | Zero-conversion campaigns, cost spikes across all platforms |
| **Allowed actions** | Aggressive negative keywords, budget cuts on waste, device bid adjustments |
| **Avoid** | Scaling, new campaigns, experimental features |
| **Transition trigger** | CPA returns to within 10% of target for 7+ days |
| **Next mode** | EFFICIENCY_STABILIZE |

### SCALE_EXPANSION

| Aspect | Behavior |
|--------|----------|
| **Priority** | Grow volume while maintaining acceptable efficiency |
| **Daily check focus** | Budget utilization across all platforms, impression share headroom |
| **Allowed actions** | Budget increases, new keyword expansion, new campaign tests |
| **Avoid** | Cutting budgets on learning campaigns, over-optimizing for CPA at expense of volume |
| **Transition trigger** | CPA rises above acceptable threshold |
| **Next mode** | EFFICIENCY_STABILIZE or TURNAROUND_RESCUE |

### COMPETITOR_DEFENSE

| Aspect | Behavior |
|--------|----------|
| **Priority** | Protect impression share on core brand/product terms |
| **Daily check focus** | Auction insights, impression share trends, organic ranking trends |
| **Allowed actions** | Budget increases on core terms, bid adjustments, cross-platform shifts |
| **Avoid** | Broad expansion into new areas, reducing spend on core terms |
| **Transition trigger** | Impression share stabilizes at acceptable levels |
| **Next mode** | EFFICIENCY_STABILIZE or SCALE_EXPANSION |

### CREATIVE_TESTING

| Aspect | Behavior |
|--------|----------|
| **Priority** | Test and iterate on ad creatives to find winning messages |
| **Daily check focus** | Ad asset ratings across all platforms, creative performance comparison |
| **Allowed actions** | New creative creation, A/B tests, LP analysis |
| **Avoid** | Budget changes, keyword changes, structural campaign edits |
| **Transition trigger** | Winning creative identified (statistically significant) |
| **Next mode** | EFFICIENCY_STABILIZE or SCALE_EXPANSION |

### LTV_QUALITY_FOCUS

| Aspect | Behavior |
|--------|----------|
| **Priority** | Improve lead/conversion quality over volume |
| **Daily check focus** | Search term quality, audience alignment across all platforms |
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

mureo commands leverage data from all available sources. Built-in platforms (Google Ads, Meta Ads, Search Console) are accessed directly. External data sources (GA4, CRM) are accessed via companion MCP servers configured alongside mureo.

### Platform Types

| Type | Platform | Access | Required? |
|------|----------|--------|-----------|
| Built-in | Google Ads | mureo MCP | At least one ad platform |
| Built-in | Meta Ads | mureo MCP | At least one ad platform |
| Built-in | Search Console | mureo MCP | No — additive |
| Companion | GA4 | Google's official MCP | No — additive |
| Companion | CRM | Third-party MCP | No — additive |

**No hard dependency on any single platform**: Commands adapt to whatever is configured. At minimum, one ad platform is needed.

### Which Commands Benefit from Each Data Source

| Command | Search Console Value | GA4 Value |
|---------|---------------------|-----------|
| `/daily-check` | Organic ranking drops needing paid coverage | LP conversion rates, on-site behavior correlation |
| `/search-term-cleanup` | Paid/organic keyword overlap matrix | LP bounce rates for keyword quality signals |
| `/creative-refresh` | Top organic queries for ad copy inspiration | LP engagement metrics for creative direction |
| `/budget-rebalance` | Organic coverage to reduce paid spend | Conversion quality by traffic source |
| `/competitive-scan` | Organic competitive landscape | Brand/direct traffic trend signals |
| `/rescue` | Organic alternatives for wasted paid terms | Site-side vs platform-side diagnosis |
| `/goal-review` | Organic metrics for SEO-related goals | Website conversion data for holistic tracking |
| `/weekly-report` | Organic trend summary (WoW) | Website-level metrics for holistic view |
| `/onboard` | Organic baseline establishment | Site conversion metric baseline |
| `/sync-state` | Site access verification | Connectivity verification |

See [docs/integrations.md](../../docs/integrations.md) for configuration instructions.

## Workflow Best Practices

### Recommended Weekly Cadence

| Day | Activity |
|-----|----------|
| Monday | `/daily-check` + `/competitive-scan` (include organic competitive pulse) |
| Tuesday-Thursday | `/daily-check` |
| Friday | `/daily-check` + `/search-term-cleanup` (include paid/organic overlap review) |
| Weekly | `/goal-review` + `/weekly-report` |
| Monthly (1st week) | `/budget-rebalance` + `/creative-refresh` |

### Safety Rules

1. **Never auto-execute write operations** — all commands ask for approval before changes
2. **Budget changes >20% trigger a warning** — smart bidding may reset its learning period
3. **Always show current vs proposed values** — for budgets, bids, and status changes
4. **Batch keyword operations** — add/remove in groups of 20 or fewer
5. **Respect learning periods** — ONBOARDING_LEARNING mode blocks most changes
6. **Evidence before strategy changes** — do not change STRATEGY.md based on unvalidated data. See `mureo-learning` skill for the evidence lifecycle

### Strategy File Maintenance

- **STRATEGY.md**: Review quarterly; update immediately when business strategy changes. Keep `Data Sources` section current when platforms are added/removed.
- **STATE.json**: Auto-updated by commands; use `/sync-state` for manual refresh
- **Operation Mode**: Update when campaign conditions change (see transition triggers above)
