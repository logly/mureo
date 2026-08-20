---
name: _mureo-strategy
description: "Strategy Context: Manage business strategy files (STRATEGY.md, STATE.json) for strategy-driven ad operations."
metadata:
  version: 0.10.48
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
- Platform: Google Ads, Meta Ads, Amazon Ads
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
| `Platform` | No | Applicable ad platforms (e.g., `Google Ads, Meta Ads`, `Amazon Ads`, `TikTok Ads`, or a plugin platform) |
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
prose instruction the model could overlook. How strong depends on the platform
— read *Coverage* below before promising an operator a hard cap.

**Coverage:** the gate runs inside mureo's own MCP dispatch, so it **reaches**
every **mureo-dispatched** tool call — but the **strength of the check differs
by platform**: exact argument keys on native `google_ads_*` / `meta_ads_*`
(**hard enforcement**), declaration-first on plugin / bridged platforms — exact
on the money surface mureo declares, best-effort pattern-matched keys on the
rest (**strong but not guaranteed**) — and hosted connectors bypass mureo
entirely (**no gate at all**). In detail:

- **Native `google_ads_*` / `meta_ads_*`** (and `mureo_*`) — the gate reads the
  **exact argument keys** it knows (`daily_budget`, `bid_amount`,
  `cpc_bid_micros`, …). This is the hard, deterministic case.
- **Plugin / bridged platforms** routed through mureo (including **Amazon
  Ads**, `plugin:mureo-amazon-ads-bridge:amazon_ads`) — **declaration first, pattern
  second**. A tool that declares its budget / bid keys in its MCP metadata is
  matched **exactly** and that declaration takes precedence. So is the *known*
  bridged money surface, which mureo declares itself: the **13 money-carrying
  Amazon tools** (campaign / ad-group / portfolio budgets, per-country budget
  caps, target and ad-group bids) are enforced on **exact argument paths**, not
  by pattern — and the best-effort scan **still runs underneath those paths as
  a floor**, the larger amount winning, so a money field that drifted shape or
  that the provider added after mureo's snapshot falls back to that best-effort
  cover rather than to nothing — it is found when the new name still looks like
  money (`budget` / `spend` / `bid`, or a plain `value` / `amount` under one),
  which is the honest limit of a pattern. Everything
  else on such a platform — a tool the provider adds later, a plugin that
  declares nothing — is covered by that scan alone. So: an Amazon cap on the
  declared tools is exact; everywhere else on these platforms treat a cap as
  **strong but not guaranteed**, tell the operator so, and verify the resulting
  values after the first mutations on a new platform.

It does **NOT** cover a **hosted connector** (e.g. TikTok's `tt-ads-*`, or an
official Google/Meta MCP used directly as a connector): those calls go
client→platform and never reach mureo's dispatcher, so the hard gate cannot see
them. For hosted connectors, guardrail adherence remains an instruction the
skill must follow (or, when available, an advisory pre-check the skill calls
before mutating).

The section is machine-readable: one `- key: value` bullet per rule. Recognized
keys (all optional):

```markdown
## Guardrails
- max_daily_budget_per_campaign: 50000
- max_daily_budget_increase_pct: 20
- max_total_daily_budget: 300000
- max_lifetime_budget_per_campaign: 900000
- max_bid_amount_per_ad_set: 5000   # minor units: 5000 = $50.00 (USD) but ¥5,000 (JPY)
- max_cpc_bid_per_ad_group: 100      # currency units: 100 = $100 (USD) or ¥100 (JPY)
- blocked_operations: google_ads_keywords_remove, meta_ads_audiences_delete
- block_learning_resets: false
- block_learning_resets_during_incident: true
- max_delivery_share_removed_pct: 25
- max_cumulative_delivery_share_removed_pct: 60
- exclusion_impact_window_days: 30
- exclusion_impact_metrics: impressions, cost
- block_exclusions_without_impact_data: false
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
- `max_bid_amount_per_ad_set` — an ad-set mutation proposing a bid *cap* above
  this is **refused** (`meta_ads_ad_sets_create` / `meta_ads_ad_sets_update`
  `bid_amount`). A bid is a per-auction ceiling, not a spend budget, so it is
  capped separately from the budget rules above. Compared against Meta's native
  `bid_amount` in Meta's **minor units** (= currency units for JPY-like
  zero-decimal currencies, cents for USD-like). The `bid_constraints`
  `roas_average_floor` is a min-ROAS floor, not a spend amount, so it is **not**
  constrained by this cap.
- `max_cpc_bid_per_ad_group` — an ad-group mutation proposing a CPC bid above
  this is **refused** (`google_ads_ad_groups_create` /
  `google_ads_ad_groups_update` `cpc_bid_micros`). Given in account-currency
  **units**; the tool's `cpc_bid_micros` is converted from micros before
  comparison. A `bid_modifier` (a bid-adjustment multiplier) is not a spend
  amount and is not constrained by this cap.
- `blocked_operations` — comma-separated tool names that are always refused.
  Each name must **exactly match the dispatched MCP tool name**; the gate does a
  literal string match, so a typo or a non-existent name silently never fires.
  Distinct single-purpose destructive tools that DO exist include
  `google_ads_keywords_remove`, `google_ads_conversions_remove`,
  `google_ads_negative_keywords_remove`, `meta_ads_audiences_delete`,
  `meta_ads_catalogs_delete`, and `meta_ads_ad_rules_delete`.

  **Whole-tool granularity only (design limit).** The match is on the tool name,
  never its arguments, so you cannot block a single argument value. In
  particular there is **no** `google_ads_campaigns_remove` or
  `meta_ads_campaigns_delete` tool: a Google Ads campaign is removed via
  `google_ads_campaigns_update_status` with `status=REMOVED` — the SAME tool that
  also pauses and enables campaigns — and Meta has no campaign-delete tool at all
  (pausing is `meta_ads_campaigns_pause`). Blocking
  `google_ads_campaigns_update_status` would therefore also block pausing and
  enabling; refusing *only* the `status=REMOVED` case is not currently possible.
  To target deletion, block a distinct destructive tool (e.g.
  `google_ads_keywords_remove`) instead.

- `block_learning_resets` — every change mureo classifies as restarting an
  automated bid strategy's learning period is **refused**. The blunt rule: use
  it during a freeze, not day to day.
- `block_learning_resets_during_incident` — the same refusal, but narrower by
  name and in fact: *"during incident"* names **a specific campaign that is
  known to be unstable**. It refuses only when the call (1) identifies a
  campaign at all and (2) that campaign is **not positively known to be out
  of** a learning period. Stacking a second reset on a campaign that is already
  re-learning is almost never intended, and is the exact shape of the incident
  this rule comes from (a collapsed campaign "fixed" by moving its bid ceiling,
  which restarted learning and delayed recovery).

  Condition (2) is **fail-closed**: an `unknown` or `unreportable` state on an
  identified campaign is refused, not assumed steady. Condition (1) is what
  keeps that from degenerating into a permanent block. Several
  reset-triggering tools are **not campaign-scoped** —
  `google_ads_conversions_*` is account-level and `google_ads_budget_update` is
  keyed on a `budget_id` — so their campaign can never be resolved and their
  state is always `unknown`. Without (1) this rule would refuse every one of
  those calls forever, with no relation to any incident: an operator who
  followed mureo's own advice to declare it would find conversion actions
  permanently un-editable. A rule with no subject has nothing to refuse. Use
  `block_learning_resets` when you want the account-wide freeze — that one is
  honestly blunt and needs no subject.

  Coverage is honest rather than uniform. mureo classifies reset triggers from
  **first-party sources only**: Google Ads is complete (Google publishes the
  causes as the `LEARNING_*` members of `BiddingStrategySystemStatus`), and no
  other platform ships a trigger list in mureo core — Meta documents that
  "significant edits" restart the phase without enumerating them, so every Meta
  mutation is reported `unknown`, never `no_reset`. Only a `resets` verdict is
  ever refused, so these two rules are effectively Google-Ads rules today; a
  plugin can register its own platform's rules via
  `mureo.policy.learning_rules.register_platform_learning_rules`.

  The **learning state** is read locally, from
  `bidding_details.bidding_strategy_system_status` on the campaign's STATE.json
  snapshot (a policy gate runs on every tool call and must not make network
  calls). Keep it fresh or the answer is `unknown` — which these rules treat as
  "refuse", not as "fine".

### Exclusion delivery-impact rules (#547)

The five keys below govern **bulk exclusions / blocks / negative keywords** —
the operation that removes inventory rather than money. Before such a call is
dispatched, mureo computes how much of the account's OWN recent delivery the
batch removes and refuses it when it is over the cap. All five are optional and
all default to off; with none of them written mureo issues no extra report
request and behaves exactly as before.

- `max_delivery_share_removed_pct` — refuse an exclusion batch whose entities
  accounted for more than this share of the recent window. This is the rule
  that stops "I tightened placements and delivery went to zero".
- `max_cumulative_delivery_share_removed_pct` — refuse when the account's
  **whole** standing exclusion set, including this batch, is over the cap. The
  incident behind #547 was two weeks of individually-small passes, none of
  which would have tripped the incremental cap.

  **Do not write this one alone.** It needs the standing exclusion set, and
  mureo cannot read that for an **ad group-scoped** write: campaign-level
  exclusions also cover the ad group and are not reachable from the call's
  arguments, and Google Ads exposes no ad group-level negative keyword
  listing at all. On those calls the cumulative figure is withheld (`null`
  with a reason) and this rule therefore enforces **nothing** — which is
  exactly the scope the motivating incident happened at. Always pair it with
  `max_delivery_share_removed_pct`, which is evaluated per batch, needs no
  standing list, and so still fires there. When a rule you wrote could not be
  evaluated, mureo says so on the call itself (`NOT ENFORCED on this call:`
  in the appended notice, `unevaluated_rules` in
  `analysis_exclusion_impact_preview`) — treat that line as a gap to close,
  not as a pass.
- `exclusion_impact_window_days` — the recent window (default 30, max 365).
- `exclusion_impact_metrics` — which of `impressions` / `clicks` / `cost` /
  `conversions` the caps apply to. Default `impressions`; any listed metric
  over the cap refuses.
- `block_exclusions_without_impact_data` — refuse an exclusion mureo cannot
  size (coverage `unknown` or `partial`) instead of applying it blind. Default
  `false`, because several real exclusion surfaces are structurally
  unattributable (Meta publisher categories / block lists / brand-safety
  content types have no insights breakdown). Even with it off, the measured —
  or unmeasurable — verdict is appended to the call's own result, so an
  exclusion is never applied *silently*.

Call `analysis_exclusion_impact_preview` **before** any bulk exclusion to see
the same numbers without applying anything. It also works for platforms mureo
does not model: pass `excluded_entities` + `delivery_records` you fetched from
that platform's own report and it reaches no API at all. Its `would_block`
field is computed by the same rule the dispatcher enforces.

Absent section (or an unparseable value) ⇒ no enforcement for that rule
(fail-open); mureo never blocks on a rule the operator did not write. A boolean
rule accepts `true` / `yes` / `on` / `1`; anything else (including a typo) reads
as off. When a mutation is refused, the agent receives the guardrail's reason
verbatim and should surface it to the operator rather than retrying.

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
          "bidding_details": {"target_cpa": 5000,
                              "bidding_strategy_system_status": "LEARNING_BUDGET_CHANGE"},
          "daily_budget": 8000.0,
          "campaign_goal": "Lead generation for SaaS trial signups",
          "notes": "Learning period ends ~April 5. Do not change bids."
        }
      ]
    },
    "plugin:mureo-amazon-ads-bridge:amazon_ads": {
      "account_id": "ENTITY1A2B3C4D5E",
      "campaigns": [
        {
          "campaign_id": "444555666",
          "campaign_name": "SP - Brand Defense",
          "status": "ENABLED",
          "daily_budget": 12000.0,
          "campaign_goal": "Defend brand terms on the product detail page"
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
    },
    {
      "timestamp": "2026-04-01T11:05:00+09:00",
      "action": "Raised daily budget 10000 -> 12000",
      "platform": "plugin:mureo-amazon-ads-bridge:amazon_ads",
      "campaign_id": "444555666",
      "command": "/budget-rebalance",
      "summary": "Shifted spend toward the brand-defense campaign",
      "observation_due": "2026-04-15"
    }
  ]
}
```

> The second platform key shows the canonical `plugin:<dist>:<provider>` shape
> used for every mureo-dispatched plugin / bridged platform — Amazon Ads is
> `plugin:mureo-amazon-ads-bridge:amazon_ads`. The older `plugin:<dist>` form
> stays valid on read, so an entry already stored under it keeps working and
> must not be rewritten. Use the identical string in the
> `platforms` map and in each `action_log` entry's `platform`; see
> `../_mureo-shared/SKILL.md` → *Canonical platform key*.

### Campaign Snapshot Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `campaign_id` | string | Yes | Campaign identifier |
| `campaign_name` | string | Yes | Human-readable name |
| `status` | string | Yes | `ENABLED`, `PAUSED`, or `REMOVED` |
| `bidding_strategy_type` | string | No | The platform's OWN name for the strategy, verbatim (Google Ads e.g. `MAXIMIZE_CONVERSIONS`, `TARGET_CPA`). Omit for a platform that does not select delivery by a bid — see `../_mureo-shared/SKILL.md` → *Status vocabulary contract* |
| `bidding_details` | object | No | Strategy-specific details (target_cpa, target_roas, etc.); omitted alongside `bidding_strategy_type` |
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

**`fetched_at` is what the dashboard's staleness marker reads — set it on
every rollup you write**, including each `periods[<window>]` bucket. The
reporting view judges a figure against the window it covers: stale once it is
older than that window's own length plus one day of grace, i.e. the point at
which the stored numbers no longer overlap the window their label claims
(`YESTERDAY` after 2 days, `LAST_7_DAYS` after 8, `LAST_30_DAYS` after 31).
A **stale** rollup is no longer rendered as the selected window's answer: the
headline figures read `—` and the stored numbers are restated below with
their age ("last collected 11d ago: …"). Nothing is hidden, but the card
stops claiming an old figure is this window's result. Do not lean on the
document-level `last_synced_at` for this: it is re-stamped on **any** platform
write, so one platform syncing would otherwise make every other platform's
months-old numbers read as just-synced.

On the **`mureo_state_platform_metrics_set`** path you may leave `fetched_at`
out: the server stamps the write time onto every rollup that call supplies
without one (`totals` and each `periods` bucket), and never re-stamps a
window it merely preserves. Pass your own value only when the figures were
pulled at some other time — a historical window — and it is relayed verbatim.
On the **`Write`** path nothing stamps for you, so write it yourself. A rollup
that still has no `fetched_at` renders as *"update time unknown"* — never as
fresh, because that would be a claim mureo cannot back.

**When a platform could not be collected, say so — do not write zeros.**
`platforms[<p>].not_collected` records WHY that platform's figures were not
refreshed:

```json
"not_collected": {
  "attempted_at": "2026-08-18T09:00:00+09:00",
  "reason": "Meta returned OAuthException 190: the access token expired"
}
```

Write it with `mureo_state_platform_not_collected_set` (pass `platform`,
`account_id`, `reason`; `attempted_at` is stamped by the server), or the same
object on the Code `Write` path. Without it, "not collected" and "collected,
and the answer was zero" are the same document, and the card cannot tell an ad
account that stopped delivering from a collector that stopped running.

Two rules, both load-bearing:

- **Leave the stored figures alone.** They are still the last numbers truly
  collected — not wrong, just older than they should be. Never write `0` or a
  guess for a window you could not pull; the card restates the old numbers
  with their age and now also says why they did not move.
- **Clear it on the next successful collection** — call the tool again with
  `reason` omitted (or the Python helper with `reason=None`). No other write
  retires the note: omitting a field means *leave it alone* everywhere in
  STATE.json, so a note left behind would outlive its failure and become
  permanently stale information stated with confidence. (The dashboard also
  stops showing a note once a rollup carries a `fetched_at` later than the
  note's `attempted_at`, so a card never shows fresh figures beside a stale
  reason — but that is a backstop, not a substitute: the document itself is
  yours to keep honest.)

A `reason` with no text is dropped on read, and long text is truncated for
display — write one sentence an operator can act on, not a stack trace.
Recording a failure does not re-stamp `last_synced_at`: a collection that
failed is not a sync.

**Per-period rollups:** `platforms[<p>].periods` is an optional map keyed by a
canonical period token, each value a totals-shaped object using the SAME
vocabulary above — so the reporting dashboard can offer a period toggle. Use
these exact tokens (they are Google Ads date-range tokens):

| Token | Window | Written by |
|-------|--------|------------|
| `YESTERDAY` | The prior day | `daily-check` (runs daily) |
| `LAST_7_DAYS` | Trailing 7 days | — (accepted; no built-in skill writes it) |
| `LAST_30_DAYS` | Trailing 30 days | `sync-state` |

**These three tokens are the whole vocabulary, and it is closed.**
`mureo_state_platform_metrics_set` **refuses** any other window — as
`metrics_period` or as a `periods` key — rather than storing it, and it never
re-files your figures under a neighbouring window: `LAST_8_DAYS` is rejected,
not rounded to `LAST_7_DAYS`, because eight days of spend is not a seven-day
answer. If your analysis covers some other span (since launch, month-to-date),
report it in your reply and in `reports.*`, but do **not** invent a window
token: nothing reads it, so the write would report success while the dashboard
truthfully kept showing the canonical numbers as stale — the operator sees a
run that "worked" and a card that did not move. Windows already stored under a
non-canonical label stay readable and are listed to the operator, so nothing
collected is lost.

Write a platform's rollup with the `mureo_state_platform_metrics_set` tool on
hosts without filesystem access (Desktop / Cowork), or a direct file write in
Code mode: pass `totals` + `metrics_period` for the single most-recent window
and/or `periods` for the per-window map. `periods` is merged per window key, so
writing `YESTERDAY` never clobbers a prior `LAST_30_DAYS` bucket (and vice
versa); omitted fields preserve their existing value.

**One ad account, one platform key.** The rollup is written under the
`platforms` key you pass, and the reporting view aggregates across platforms —
so an account stored under two keys double-counts spend, conversions and CPA.
Pass the key the account is already stored under; a write that would create a
*second* key for an `account_id` another key already holds is rejected, naming
both keys. Existing entries are never merged or deleted (they usually hold
different partial figures), so writes to a key that already exists always
succeed and reconciling a duplicated document stays the operator's call. See
`../_mureo-shared/SKILL.md` → *STATE.json Schema*.

On the read side the dashboard no longer adds such entries up silently: when
it finds two keys resolving to one account it **withholds the client total**
and names both keys, and when it finds a key it cannot resolve to any platform
at all it reports that separately (that entry's identity cannot be
established, so it *may* be a duplicate). Both are reports, not repairs — the
per-platform figures still render untouched.

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

Step 3: Apply it with the tool that covers the surface -- never draft first
        and look for a tool afterwards (see "Apply or draft" in
        skills/creative-refresh/SKILL.md)

  Search RSA -> google_ads_ads_create {
       headlines addressing persona pain points,
       descriptions highlighting USP
     }

  Performance Max -> not an ad: its copy lives on the asset group.
     google_ads_asset_group_assets_list {campaign_id}   # get old_asset_id
     google_ads_asset_group_assets_replace {asset_group_id, field_type,
       old_asset_id, new_text}                          # one asset per call

  No write tool for this surface (any image / video / logo asset today)
     -> present the draft as copy for the operator to paste in, said up
        front, and offer no apply step
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
  Performance Max returns NO rows here (it has no ad_group_ad) -- auditing
  brand voice from this tool alone silently skips every P-MAX campaign
  -> google_ads_asset_group_assets_list {customer_id, campaign_id}

Step 3: Review each ad against brand voice rules
  Flag: "Best Ad Platform Ever!" -> violates "no hype" rule
  OK: "Reduce CPA by 30% with AI-Powered Optimization" -> data-backed, professional

Step 4: Update non-compliant ads (CONFIRM WITH USER)
  Search RSA -> google_ads_ads_update {headlines: [improved versions]}
  Performance Max -> google_ads_asset_group_assets_replace {asset_group_id,
       field_type, old_asset_id, new_text}
  No write tool for the surface -> draft only, said up front; see
       "Apply or draft" in skills/creative-refresh/SKILL.md
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
