---
name: goal-review
description: "Review Goal progress against STRATEGY.md targets. Use when the user asks to evaluate goal achievement, review KPI progress, assess strategy performance, or check if targets are being met."
metadata:
  version: 0.7.1
---

# Goal Review

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

Review progress toward all marketing goals across all platforms.

## Prerequisites
- STRATEGY.md with at least one Goal section (run the `onboard` skill first)
- STATE.json (run `/sync-state` first)

## Steps

1. **Load context**: Read STRATEGY.md (all Goal sections, Data Sources) and STATE.json.

2. **Discover platforms**: Identify all configured platforms and available data sources.

3. **For each Goal**, gather current metrics from all relevant platforms and data sources:
   - Ad platforms: Use performance reporting tools for each platform
   - GA4 (if available): Website conversion data, user behavior metrics
   - Search Console (if available): Organic search metrics for SEO-related goals
   - CRM (if available): Lead quality, pipeline data for LTV-related goals

   For goals that span multiple data sources, synthesize a unified view. Example: "Total leads = Platform A 62 + Platform B 28 + Organic 15 = 105 total"

4. **Evaluate progress** for each Goal:
   - Compare current value against target
   - Calculate % of target achieved
   - Calculate days remaining until deadline
   - Assess trajectory: on-track / at-risk / off-track

5. **Present Goal dashboard**:
   | Goal | Target | Current | Progress | Deadline | Status |
   |------|--------|---------|----------|----------|--------|

   Status indicators:
   - On track — current value meets or exceeds the pace needed to hit target by deadline
   - At risk — current value is within 20% of target but trajectory is concerning
   - Off track — current value is more than 20% away from target pace

6. **Consult evidence**: Before recommending actions, check `action_log` for past actions with evaluated outcomes:
   - Reference validated findings when proposing similar actions ("Negative keyword cleanup has consistently improved CPA by 10-20% on this account")
   - Flag previously rejected actions ("Device bid adjustments had no significant impact in the last 2 attempts")
   - Do NOT attribute goal progress to specific actions without checking observation windows and sample sizes

7. **Recommend actions** for off-track Goals:
   - Tie recommendations to the specific platform(s) where the Goal is off-track
   - If cross-platform rebalancing could help, suggest it
   - Suggest specific commands to run (`/rescue`, `/budget-rebalance`, `/creative-refresh`)
   - Prioritize recommendations by Goal priority (P0 > P1 > P2)
   - Prefer actions backed by past validated evidence over unproven strategies

8. **Update STATE.json**:
   - Log the review to `action_log` with a summary of Goal statuses
   - Update Current values in STRATEGY.md Goal sections if approved

IMPORTANT: When updating Goal "Current" values in STRATEGY.md, ask for approval first.
