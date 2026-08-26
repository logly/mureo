---
name: _mureo-pro-diagnosis
description: "Professional marketing diagnostic frameworks: expert-level campaign analysis that grows with your experience."
metadata:
  version: 0.15.0
  openclaw:
    category: "marketing"
    requires:
      bins:
        - mureo
---

# Professional Campaign Diagnosis

A growing knowledge base of marketing diagnostic expertise. This skill starts with foundational frameworks and **learns from your corrections** — every time you point out a missed insight or wrong recommendation, the knowledge is captured here for future use.

**How this skill grows:** When you correct the agent's analysis during `/daily-check`, `/rescue`, or other commands, the agent will ask if the insight should be saved. Approved insights are appended to this file as new entries under the appropriate section.

## How to Use This Skill

- **For the agent:** Read this skill before making diagnostic recommendations. Apply any learned insights that match the current situation.
- **For the user:** When the agent misses something or makes a wrong call, say so. The agent will offer to save that knowledge here.

---

## Diagnostic Principles

### Always Diagnose Before Prescribing

A professional marketer asks "Why?" before recommending changes:

- **Surface analysis** (avoid): React to symptoms (high CPA → cut keywords)
- **Root cause analysis** (do this): Identify structural causes first (high CPA ← budget dispersed across too many ad groups ← need to consolidate)

### The Diagnostic Order

When analyzing a campaign, work through issues in this priority:

```
1. Structure    → Is the account structure appropriate for the budget?
2. Data         → Is there enough conversion data for the bidding strategy, where the platform has one?
3. Targeting    → Are keywords/audiences reaching the right people?
4. Creative     → Are ads relevant, compelling, and aligned with the LP?
5. Bids/Budget  → Are bid targets and budgets realistic?
```

**Fix higher-level issues before lower-level ones.** Optimizing bids on a structurally broken account is like tuning the engine of a car with flat tires.

---

## Allocation & Learning-State Discipline

Modern ad platforms decide *where the next impression goes* on the advertiser's behalf. That single fact invalidates a whole family of intuitive-looking moves: ranking rows in a breakdown table and cutting the worst ones. The three principles below are cross-platform — they hold on Meta and on Google Ads for the same underlying reason — and they apply **before** any exclusion, pause, or reallocation is proposed.

### Judge by Marginal Efficiency, Not Averages

**Principle:** A segment, placement, keyword, or campaign with a poor **average** CPA is not automatically a cut candidate. The decision-relevant quantity is the **marginal** one: what the *next* unit of spend would return, and what the *removed* unit of spend would have returned. Averages summarize history under an allocation you did not choose; margins describe the change you are about to make.

**Why it holds:** Automated delivery spends the cheapest, highest-probability inventory first. An entity's average therefore blends its cheap early conversions with its progressively more expensive later ones. Two failure modes follow, and average-ranking misfires in **both** directions:

- **Saturated winners scale badly.** A campaign with an excellent average has already been served its best inventory. Pushing more budget into it buys the expensive tail — the marginal CPA can be far worse than the average that justified the increase.
- **Suppressed losers look worse than they are.** A small entity with a bad average may simply be spend-suppressed: too little delivery to have found its efficient inventory, or an average dominated by one or two costly outcomes. Cutting it removes volume that was never given a fair chance, and the "saving" reappears as higher CPA elsewhere.

**How it shows up:**

- **Meta** — Ad-set budgets (and campaign-level budget allocation across ad sets) are spent toward the configured optimization goal. Moving budget between ad sets changes *which* auctions get bid on, so the post-move CPA is a new outcome, not the old average carried over.
- **Google Ads** — Smart Bidding sets bids per auction against the target. Raising a budget on a target-constrained campaign buys additional auctions that were previously below the bar; those incremental conversions cost more than the campaign's historical average. A keyword with a high average CPA but few conversions is a sample-size question first and an efficiency question second.

**Already in mureo:** the evidence gates in `_mureo-learning` (minimum sample sizes, observation windows, the OBSERVING → CANDIDATE → VALIDATED lifecycle) exist precisely so a thin average is not mistaken for a verdict. Honor them before proposing any cut.

**What to say instead:**

- Not: *"Campaign B has a CPA of ¥8,200 vs the account's ¥5,000 — cut its budget by 40%."*
- Say: *"Campaign B's average CPA is ¥8,200 on 11 conversions — below the 30-conversion floor, so this is not yet evidence of inefficiency. If we move ¥40k/month out of it, we should expect to lose roughly the conversions it produced at the margin, not at its average. I recommend either holding, or testing the reallocation via `/experiment` so the marginal effect is measured rather than assumed."*
- Not: *"Campaign A has the best CPA — give it the extra budget."*
- Say: *"Campaign A has the best average CPA and is not budget-limited, which usually means it is already getting the inventory it wants. A +20% increase will buy incremental auctions at a worse-than-average cost; I'd step it up in one increment and re-measure after the observation window rather than doubling it."*

### Respect Learning States

**Principle:** Automated bidding needs a stable window of data after an entity is created or significantly edited. Entities inside that window are **Watch-only**: report them, do not judge them, and do not schedule edits that restart the clock without a reason worth the reset.

**Why it holds:** The bidding system is estimating conversion probability for a new configuration. Until it has enough recent outcomes, delivery is deliberately exploratory — cost per result is unstable and typically worse than the same entity's eventual steady state. Reading that instability as "performance" produces exactly the wrong action: cutting a unit that has not yet finished learning, or crediting a change with an improvement that is just the learning period ending.

**How it shows up:**

- **Meta** — A new or significantly edited ad set enters a **learning phase** and exits once it has accumulated enough recent optimization events (Meta's published guidance is on the order of ~50 conversions in a week for the optimized event). Significant edits — the optimization goal, the audience, the creative, or a large budget or bid change — **reset** it. An ad set that keeps getting edited can sit in a permanently unstable state and never reach steady delivery.
- **Google Ads** — A bid strategy shows a **"Learning"** status after the strategy is switched or its target (Target CPA / Target ROAS) is changed, typically for a period of days up to about two weeks. Large target jumps make the adjustment harder and the recovery longer; prefer **small steps — roughly 20% or less at a time** — and let each settle before the next.

**Already in mureo:** the Operation Mode `ONBOARDING_LEARNING`, the `observation_due` / `metrics_at_action` fields on `action_log`, and the "pending observation — do not stack changes" checks across the operational skills are the machinery for this. A learning-state entity is a `Watch` in the health report, never an `Action needed` on efficiency grounds alone.

**What to say instead:**

- Not: *"This ad set's CPA is 2.4× target — pause it."*
- Say: *"This ad set was edited 4 days ago and is still in its learning phase, so its CPA is not steady-state. Marking it **Watch**; I'll re-evaluate once it has exited learning (or after the 14-day window), and I'd avoid further edits until then so the phase isn't reset again."*
- Not: *"CPA is high — drop the Target CPA from ¥6,000 to ¥3,500."*
- Say: *"A 42% target cut would put the strategy back into Learning and likely suppress volume sharply. I recommend stepping to ¥4,800 (−20%), letting the strategy re-stabilize, and reassessing before the next step."*

### Don't Hand-Optimize Inside an Auto-Allocated Unit

**Principle:** When the platform distributes delivery *within* a unit automatically, the per-breakdown numbers you can see are **outcomes of that allocation, not levers you control**. Breakdown tables generate hypotheses; they do not license exclusions.

**Why it holds:** The system chose those breakdowns to hit the goal you set. A breakdown that looks expensive is often carrying cheap reach or assisted volume that made the *unit's* overall result possible; removing it does not relocate its budget into the good rows at the good rows' historical efficiency — it shrinks the auction pool the optimizer had to work with, and the unit's blended result can get **worse**. This is the same marginal-vs-average error as the first principle, applied inside a unit rather than across units.

**How it shows up:**

- **Meta** — Delivery within an ad set is distributed across audiences, placements, and devices automatically. A placement breakdown showing an expensive placement is a report of where the optimizer found results, not a per-placement bid you set. Placement and audience decisions belong at the level the platform optimizes — the ad set — so if a split genuinely matters, build it as a separate ad set rather than excluding a row inside a working one.
- **Google Ads** — Under fully-automated Smart Bidding strategies (Target CPA / Target ROAS / Maximize Conversions / Maximize Conversion Value), **manual bid adjustments are ignored**, with the single exception of a **−100% device adjustment** (a full device opt-out). Reporting still shows per-device and per-segment rows, which makes them look adjustable; they are not. Performance Max reports across channels and asset groups, but channel mix is not an advertiser lever — a channel row is diagnostic, not a dial.

**Already in mureo:** the `audience-review` skill deliberately routes segment findings into a recommendations table behind an approval gate rather than auto-excluding, and honestly reports where **no mutation tool exists**. Keep that discipline: the table is the hypothesis, `/experiment` is the test.

**What to say instead:**

- Not: *"Audience Network shows ¥18k spend and 0 conversions — exclude it."*
- Say: *"The placement breakdown shows ¥18k on Audience Network with 0 conversions. Meta allocated that spend within the ad set, so excluding the row removes inventory the optimizer was using rather than redirecting that budget to Feed at Feed's current CPA. This is a hypothesis worth testing: I'd run a two-ad-set `/experiment` (one with the placement, one without), and act on the result."*
- Not: *"Mobile CPA is 1.8× desktop — set a −30% mobile bid adjustment."*
- Say: *"This campaign uses Smart Bidding, so a −30% mobile adjustment would be ignored — the only device adjustment that still applies is −100%, which opts the device out entirely. The mobile/desktop gap is a signal about the mobile landing-page experience or mobile intent; I'd investigate there rather than reach for a bid modifier that has no effect."*

---

## Learned Insights

This section grows as you use mureo. Each insight is learned from real campaign experience.

<!-- 
When the agent learns a new insight from user correction, append it here using this format:

### [Short title]

**Situation:** [When this applies]
**Wrong assumption:** [What the agent initially thought]
**Correct approach:** [What the user taught]
**Why:** [The reasoning behind the correct approach]

Date learned: YYYY-MM-DD
-->

*No insights learned yet. As you use mureo and correct the agent's recommendations, knowledge will accumulate here.*
