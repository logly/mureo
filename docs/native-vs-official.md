# mureo native tools vs. official MCP providers (Google & Meta)

> Status: 2026-06-16. The official ad-platform MCPs are in beta and their tool
> surface changes over time — re-verify before relying on a specific capability.
> See also [architecture.md](./architecture.md) and [byod.md](./byod.md).

## Summary

mureo ships its own **native** tool families (Google Ads, Meta Ads, GA4, Search
Console, Yahoo, LINE, Logly). The ad platforms now also publish **official MCP
servers**, and mureo can install and register those as *drivers*. They are not
mutually exclusive: mureo is the control plane, and an official MCP is a thin
driver onto the platform's own API.

The practical differences for Google and Meta:

| | Google Ads | Meta Ads |
|---|---|---|
| Official MCP | `googleads/google-ads-mcp` (pipx, ADC) | hosted `https://mcp.facebook.com/ads` (OAuth) |
| Official tool count | **3 — read-only** | **29 — read + write** |
| Official can mutate? | No | Yes (direct to live account, no undo/draft/confirm) |
| mureo native tool count | **82** | **88** |
| mureo native can mutate? | Yes | Yes |
| Safety (rollback, action_log, strategy gating) | native only | native only |
| BYOD / `mureo demo` (CSV, no live API) | native only | native only |

---

## Google Ads

### Official MCP — `google-ads-official`

- Package `googleads/google-ads-mcp`, installed via pipx, **ADC** auth
  (`GOOGLE_ADS_DEVELOPER_TOKEN` + `GOOGLE_APPLICATION_CREDENTIALS`; optional
  `GOOGLE_ADS_LOGIN_CUSTOMER_ID` for MCC access).
- Exposes **3 tools, all read-only**:
  - `search` — run a read-only GAQL query
  - `get_resource_metadata` — schema/metadata for a resource type
  - `list_accessible_customers` — list accessible account IDs
- **Cannot create or change anything.** No campaign / ad group / ad / keyword /
  budget creation or edits, no status changes, no applying recommendations, no
  conversion setup.

### mureo native — Google Ads (82 tools)

Full read **and** write, exposed as opinionated, task-level tools:

- Campaigns, ad groups, ads (incl. display + image upload)
- Keywords & negative keywords (add / pause / audit / suggest / dedupe)
- Budgets (get / update / create / reallocate / efficiency)
- Conversions (list / create / update / tag / performance)
- Search terms (report / analyze / review), sitelinks, callouts
- Recommendations (list / apply), auction insights, bid adjustments
- Device / location / schedule targeting, change history
- Performance analysis, cost-increase investigation, health checks, RSA asset audit
- B2B optimizations, landing-page & creative research
- Monitoring goals (delivery / CPA / CV / zero-conversions), screenshot capture
- Cross-cutting control plane: rollback plan/apply, action_log, STRATEGY/STATE
  awareness, learning insights

### Google — what you can do in each

| Capability | Official MCP | mureo native |
|---|:---:|:---:|
| Read performance data | Yes | Yes |
| Arbitrary raw GAQL query | Yes | Partial (via report tools, not free-form GAQL) |
| Create / update campaigns, ad groups, ads | No | Yes |
| Keyword & negative-keyword management | No | Yes |
| Budget create / update / reallocate | No | Yes |
| Conversion setup & tagging | No | Yes |
| Apply recommendations | No | Yes |
| Diagnosis / health checks / monitoring | No | Yes |
| Rollback / audit log / strategy gating | No | Yes |

**Bottom line (Google):** the official MCP is a read-only reporting window (useful
if you want to write your own GAQL). Every *operation* — and all safety — comes
from mureo native.

---

## Meta Ads

### Official MCP — `meta-ads-official`

- Hosted at `https://mcp.facebook.com/ads` (Meta Ads AI Connectors, open beta
  since 2026-04-29). Registered as a **claude.ai connector** via browser OAuth
  (Meta Business Login). It does not support dynamic client registration, so it
  cannot be added as a Claude Code user-scope server.
- **29 tools, read + write**, in five groups:
  - Campaign management (5): create campaign / ad set / ad, update entity, activate entity
  - Product catalog for commerce (10): catalogs, feeds, product sets, products, feed-quality diagnostics
  - Accounts, pages & assets (3): account / entity / page lookups
  - Datasets & tracking (4): Pixel & Conversions API **diagnosis** (event quality, stats, errors) — read-only
  - Insights & performance (7): reporting, benchmarks, anomalies, trends, opportunity scoring
- **Writes apply directly to the live account — no undo, no draft, no
  confirmation.** Meta's own mitigation advice: use read-only permission for the
  first few days, or set an account-level budget cap.
- **Documented gaps (the official Meta MCP cannot):** create audiences / custom /
  lookalikes; **send** Conversions API events (diagnosis only); create or
  retrieve lead forms & leads; set up A/B tests; automated rules; create creative
  assets (copy, images, carousels, collections, dynamic ads); Instagram-specific
  actions.

### mureo native — Meta Ads (88 tools)

Covers the same operational class as the official MCP **plus** every documented
gap above:

- Campaigns, ad sets, ads (CRUD + pause / enable)
- Audiences + **lookalikes**
- Creatives — single / carousel / collection / dynamic / lead — + image/video upload
- Insights + breakdowns; analysis (performance / audience / placements / cost / compare / suggest creative)
- Pixels (list / get / stats / events) and **Conversions API send** (purchase / lead)
- Catalogs / products / feeds
- **Lead forms + lead retrieval + CSV export**
- **Split tests**, **automated rules**, page-post boost, **Instagram** (accounts / media / boost)
- Cross-cutting control plane: rollback, action_log, strategy gating, learning insights, BYOD

### Meta — what you can do in each

| Capability | Official MCP | mureo native |
|---|:---:|:---:|
| Read performance / benchmarks / anomalies | Yes | Yes |
| Create campaigns / ad sets / ads | Yes | Yes |
| Edit budgets / targeting | Yes | Yes |
| Product catalog / feed (shopping) | Yes (10 tools) | Yes |
| Pixel & CAPI signal diagnosis | Yes | Partial (pixel stats/events) |
| Audiences & lookalikes | No | Yes |
| Conversions API event **sending** | No (diagnosis only) | Yes |
| Lead forms / lead retrieval / CSV export | No | Yes |
| Creative asset creation (carousel / collection / dynamic / lead) | No | Yes |
| Split tests / automated rules | No | Yes |
| Instagram-specific actions | No | Yes |
| Rollback / audit log / strategy gating | No | Yes |
| Undo / draft / confirmation guardrails | No (none) | Yes |

**Bottom line (Meta):** the official MCP can run live campaigns and catalogs, but
with no guardrails and several capability gaps (audiences, creatives, CAPI send,
leads, tests, rules). mureo native closes those gaps and adds the safety / audit /
strategy layer.

---

## How they coexist

When you install an official provider for a platform mureo also serves natively,
mureo sets `MUREO_DISABLE_<PLATFORM>=1` on its own MCP server block so the two do
not expose duplicate tools. Per issue #102 / PR #265, **native tools are not
disabled until the official provider is actually credentialed** — you are never
left with zero working tools. Removing the official provider clears the flag and
re-enables native tools.

- Switch native → official: `mureo providers add <provider>` (or the configure dashboard toggle)
- Switch back: `mureo providers remove <provider>`
- Search Console has no official MCP — mureo native remains canonical and is never disabled.

## When to use which

- **Stay on mureo native** when you need: write operations with rollback/audit,
  strategy-driven automation, BYOD/demo on CSV, audiences / creatives / leads /
  tests / rules (Meta), or any Google Ads mutation.
- **Add the official MCP** when you want: the platform's first-party data surface
  (raw GAQL on Google), or to drive Meta live operations through Meta's hosted
  connector — ideally alongside mureo native for the gaps and guardrails.
