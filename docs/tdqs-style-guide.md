# Tool Definition Quality Score (TDQS) Style Guide

Glama's [Tool Definition Quality Score (TDQS)](https://glama.ai/blog/2026-04-03-tool-definition-quality-score-tdqs) evaluates MCP tool definitions along six dimensions. This guide is how mureo writes new tools (and rewrites existing ones) so agents can pick the right tool and call it correctly on the first try.

## Six dimensions

1. **Purpose Clarity** — specific verb + resource, differentiated from siblings.
2. **Usage Guidelines** — when to use this vs. a related tool.
3. **Behavioral Transparency** — side effects, read-only vs. mutating, rate limits, auth.
4. **Parameter Semantics** — format, constraints, defaults beyond what the schema alone conveys.
5. **Conciseness** — no filler; every sentence earns its place.
6. **Contextual Completeness** — return shape, pagination, alternative tools.

## Description template

```
<verb> <resource> in <platform>. Returns <returned fields / structure>.
<Read-only | Mutates X | Destructive — removes Y>. <Defaults, thresholds,
pagination behavior>. Use this when <scenario>; prefer <sibling tool>
when <other scenario>.
```

Target length: **50–100 words**.

### Good (score ~4.4 — `rollback_plan_get`)

> Inspect the reversal plan for a recorded `action_log` entry in `STATE.json`. Returns the planner's status (`supported` / `partial` / `not_supported`), the operation that would be dispatched, its parameters, and any caveats. Does not execute anything.

Covers: verb (Inspect), resource (reversal plan), returns (named fields), side effect ("Does not execute").

### Bad (score ~2.3 — original `google_ads_campaigns_diagnose`)

> Diagnose Google Ads campaign delivery status

Covers: nothing useful. Tautological — just restates the tool name.

## Parameter description checklist

For every parameter, the `description` field should answer:

- **Format / example** — `"Account ID in the format 'act_XXXXXXXXXX' (e.g. 'act_1234567890')"`
- **Required vs. fallback** — `"Required if META_ADS_ACCOUNT_ID is not set in credentials."`
- **Default** — `"Default 25. Maximum 1000."`
- **Constraints** — use `minimum` / `maximum` / `enum` in the schema, then reiterate in the description only when it affects behavior.

## Destructive / mutating tools

For anything that mutates or deletes, the description MUST:

1. Lead with the mutation verb: `"Updates..."`, `"Deletes..."`, `"Pauses..."`
2. Disclose partial-vs-full update semantics: `"Partial update — only the fields provided are changed; omitted fields are preserved."`
3. State reversibility: `"Reversible via rollback.apply."` or `"Irreversible — removed ads cannot be restored."`

## Sibling differentiation

When two tools operate on the same resource (e.g. `campaigns.update` and `campaigns.update_status`), each description must end with a differentiation clause:

- `"For status-only changes use google_ads_campaigns_update_status instead; this tool rewrites the full settings."`

## Anti-patterns

- `"Update an ad"` — no verb specificity, no returns, no differentiation.
- `"Ad group ID"` (as a parameter description) — just restates the name; add format/context.
- Marketing-speak (`"Powerful tool for..."`) — TDQS penalizes filler.

## Review gate

Before adding a new tool or rewriting one, run through this checklist:

- [ ] Description covers verb, resource, returns, side effects.
- [ ] Every parameter `description` adds information beyond the name + type.
- [ ] Sibling tools (same resource, different operation) are referenced.
- [ ] Length 50–100 words for typical tools, up to ~150 for complex mutating ones.
- [ ] No filler phrases ("This tool allows you to...", "Powerful", "Simply").
