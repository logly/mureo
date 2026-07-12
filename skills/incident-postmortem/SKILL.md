---
name: incident-postmortem
description: "Close the learning loop after a rescue or incident — reconstruct the timeline from action_log, run root-cause analysis (platform / site / measurement / external), produce a structured postmortem document, distill reusable insights via /learn, and propose preventive guardrails. Use after a /rescue, a CPA spike, a conversion drop, or a runaway-spend event has been handled, or when the user asks for a postmortem, retrospective, root-cause writeup, or requests インシデント振り返り / ポストモーテム / 事後分析 / なぜ起きたのか / 再発防止策. Read-and-document only — makes no ad-platform writes."
metadata:
  version: 0.10.22
---

# Incident Postmortem

> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, output format, and **Tool Selection** (Read/Write on Code, `mureo_strategy_*` / `mureo_state_*` MCP on Desktop / Cowork).

After the fire is out, learn from it. A rescue that is never reflected on repeats: the same root cause resurfaces, the same scramble happens, and nothing in the account got more resilient. This skill reconstructs what happened, finds the controllable cause, and converts the episode into durable know-how and guardrails.

**This skill makes NO ad-platform writes** — it changes no campaigns, ads, budgets, bids, or targeting. It only *reads* platform and state data, *writes a postmortem document*, appends the postmortem to `action_log`, saves insights via `/learn`, and — with explicit approval — edits STRATEGY.md `## Guardrails`. Say this up front to the operator so they know nothing in the ad accounts moves during this review.

## Prerequisites
- STRATEGY.md and STATE.json must exist (run the `onboard` skill first)

## Steps

**Before you start**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions.

1. **Identify the incident**: Take the operator's description if given. Otherwise scan the `action_log` (via `mureo_state_get`) over the chosen window for the fingerprints of a handled incident: entries with `command="/rescue"`, actions taken while Operation Mode was `TURNAROUND_RESCUE`, or a cluster of stabilization actions (budget cuts, bulk pauses, bid drops) around a CPA-spike / CV-drop / runaway-spend date. Confirm the incident's scope (which platform(s), campaign(s), and date range) with the operator before reconstructing.

2. **Reconstruct the timeline** from `action_log` (`mureo_state_get`) plus STRATEGY.md/STATE.json notes (`mureo_strategy_get`). Lay out, in order:
   - **Detection** — when and how the problem surfaced (a daily-check flag, an operator report, an anomaly). Note the detection *lag* — how long the account was off before anyone noticed; a long lag is itself a finding.
   - **Actions taken** — each rescue action with its `metrics_at_action` baseline and timestamp.
   - **Outcomes** — for each action whose `observation_due` window has now closed, call `mureo_outcome_evaluate` (`before` = that entry's `metrics_at_action`, `after` = current numbers) for a deterministic improved / regressed / inconclusive verdict per action. For actions still inside their window, mark them **still observing** — do not score them (respect `../_mureo-learning/SKILL.md`).

3. **Root-cause analysis**: Classify the cause into one (or a ranked combination) of four buckets, with the **evidence** for each:
   - **Platform-side** — a bid-strategy misfire, a budget/CBO change, an auction/CPM shift, a disapproval. Evidence: change history, CPM/CPC trend, delivery diagnostics.
   - **Site-side** — a landing-page break, a checkout/lead-form failure, a speed regression. Evidence: CVR collapse with stable CTR, a deploy that lines up with the drop.
   - **Measurement-side** — a pixel/tag break, a conversion-action misconfig, an attribution change. Evidence: conversions flatlining while sessions/clicks hold (cross-check `/tracking-health`).
   - **External** — seasonality, a holiday, a competitor entering the auction, a demand shift. Evidence: same-period-last-year, category-wide movement, impression-share change.
   Run a **5-whys** chain until you reach a **controllable cause** (something the operator can change) or an **honest unknown** (say "root cause not determinable from available data" rather than forcing a story). Do not stop at the first symptom.

4. **What-worked / what-didn't table** — grade the response, not just the incident:

   | Response action | Intent | Verdict | Evidence |
   |-----------------|--------|---------|----------|
   | Cut prospecting budget 40% | Stop the bleed | Worked | Spend/day −38%, CPA back under target in 5d |
   | Paused top ad set | Reduce waste | Backfired | Removed the only converting audience; CV fell |
   | Added negatives | Cut junk queries | Inconclusive | Still observing (due in 6d) |

5. **Output a structured postmortem document** with these sections: **Summary** (one paragraph), **Impact** (spend wasted / conversions lost / days affected), **Timeline** (step 2), **Root cause** (step 3, with the 5-whys), **What worked / what didn't** (step 4), **Insights** (step 6), **Preventive guardrails** (step 7). On **Code**, offer to `Write` it to `./postmortems/YYYY-MM-DD-<slug>.md` (create the `postmortems/` directory if absent). On **Desktop / Cowork**, present it inline (no local filesystem). Keep it blameless and factual.

6. **Distill 1–3 generalized insights and run `/learn` for each**: Convert the root cause and the response grading into reusable, account-agnostic lessons (e.g. *"A CVR collapse with stable CTR points site-side — check the LP/tracking before touching bids"*). Present each for **explicit approval**, then save it through the **`/learn`** flow — `mureo learn add` per that skill's conventions (do not duplicate its steps here). One approval per insight; never record account IDs, credentials, or personal data.

7. **Propose preventive guardrails** where the root cause suggests one: if the incident was a runaway budget, propose a `## Guardrails` `max_total_daily_budget` / `max_daily_budget_increase_pct`; if it was a measurement break, propose a recurring `/tracking-health` cadence; if detection lag was the problem, propose a tighter `/daily-check` rhythm. Editing STRATEGY.md `## Guardrails` is a write — apply the **approval gate**: show the exact before/after of the `## Guardrails` section and get explicit confirmation before saving (Write / Edit on Code, `mureo_strategy_set` on Desktop / Cowork). If the operator declines, leave STRATEGY.md untouched.

8. **Log the postmortem itself to `action_log`** via `mureo_state_action_log_append`: `command="/incident-postmortem"`, a `summary` naming the incident and its root-cause classification, and a `metrics_at_action` snapshot of the post-incident state. This is a context-layer record (STATE.json), **not** an ad-platform mutation — it has no `observation_due` because the postmortem itself is not an experiment to observe. It leaves a durable marker that this incident was reviewed, so it is not re-litigated later.

No `mureo_state_report_set` call: a postmortem is a one-off narrative document, not a recurring dashboard report — it is delivered as the document in step 5 and the `action_log` marker in step 8, not persisted to the reports section.
