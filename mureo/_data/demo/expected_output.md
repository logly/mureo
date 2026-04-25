# Expected Output (`/daily-check` on demo dataset)

This is the reference report the agent should produce against the demo
dataset. Used as a check during dev/testing.

## Summary

> **Operation Mode: Conservative**
> **Period: Last 7 days**

## Findings

### 🔴 CRITICAL: Brand Search CPA up 45%

- Campaign: `[DEMO] Brand Search` (id 12345001)
- CPA: ¥3,200 → ¥4,640 (+45%)
- **Root cause is NOT Google Ads**: Search Console shows brand
  keyword position dropped from #1 → #5 starting day -7
- Recommended: Investigate organic SEO regression first.
  Do **not** lower bids — that would compound the loss.
- Approval required: N/A — no action proposed (Conservative mode)

### 🟡 WATCH: Meta Ads Awareness impressions plateauing

- Campaign: `[DEMO] Awareness - Lookalike`
- CTR is stable (1.2% throughout) → **not creative fatigue**
- Recommended: continue monitoring, no creative refresh yet

### 🟢 OK: Conversion-side healthy

- Generic Search CVR stable
- Meta Conversion campaign on plan
- Demo-request conversion rate via brand-query path unchanged in GA4

## Cross-platform Insight

The Google Ads CPA spike on `[DEMO] Brand Search` matches **exactly**
with the Search Console position drop on `[DEMO] mureo` query family.
Same start date (day -7). Causal direction: organic loss → forced
paid clicks → CPC inflation.

## Strategy Alignment

- ✅ Operation Mode: Conservative — recommendations are observations,
  not actions
- ✅ KPI: qualified demo requests (not raw conversions)
- ✅ Brand campaign protected per goal-priority #1

## Brand footer (demo mode only)

```
─ mureo v0.7.0 — Local-first, safety-gated AI ad-ops framework
─ https://mureo.io
─ Apache 2.0 · Built for Claude Code, Codex, Cursor, Gemini
```
