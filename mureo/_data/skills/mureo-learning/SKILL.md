---
name: mureo-learning
description: "Evidence-based marketing decision framework: statistical thinking for AI agents operating ad accounts."
metadata:
  version: 0.1.0
  openclaw:
    category: "marketing"
    requires:
      bins:
        - mureo
---

# Evidence-Based Marketing Decisions

A decision framework for AI agents managing marketing accounts through mureo. This skill teaches agents to distinguish signal from noise, avoid premature optimization, and only commit to strategy changes backed by sufficient evidence.

## Why This Matters

Marketing data is noisy. A campaign's CPA can swing 30% day-to-day from random variation alone. Without statistical rigor, agents will:

- Chase noise: "CPA dropped yesterday, the keyword change worked!" (It might just be Tuesday.)
- Oscillate: Undo Monday's changes on Wednesday because metrics dipped, then redo them Friday.
- Overfit: Draw conclusions from 12 conversions when 50+ are needed for reliability.
- Contaminate: Attribute an improvement to one change when three changes happened simultaneously.

**The antidote: observe, wait, verify, then act.**

## The Evidence Lifecycle

Every action that modifies a campaign enters this lifecycle. The agent tracks it via `action_log` entries in STATE.json.

```
Action taken (e.g., add negative keywords)
    │
    ├── Record metrics_at_action + observation_due in action_log
    │
    ▼
[OBSERVING]  ── Do NOT draw conclusions yet
    │             Wait for the observation window to pass
    │
    ├── Observation window elapsed, collect current metrics
    │
    ▼
[CANDIDATE]  ── "This looks like it worked" or "This didn't help"
    │             But one observation is NOT enough
    │
    ├── Wait for a second observation period to confirm
    │
    ▼
[VALIDATED]  ── Consistent improvement across 2+ observation periods
    │             NOW you can recommend a strategy change
    │
    ▼
[APPLIED]    ── User approved, STRATEGY.md updated

At any stage:
[REJECTED]   ── Not significant, contradicted, or confounded by concurrent actions
```

**Critical rule: OBSERVING and CANDIDATE findings are NOT actionable. Only VALIDATED insights should influence strategy.**

## Observation Windows

Different actions need different wait times before evaluation:

| Action Type | Observation Window | Why |
|------------|-------------------|-----|
| Budget change (>10%) | 7 days | Smart bidding needs ~7 days to re-learn |
| Keyword addition/removal | 14 days | Need enough impressions/clicks to evaluate |
| Negative keyword addition | 14 days | Impact on CPA unfolds gradually |
| Creative/ad copy change | 14 days | Ad rotation needs time to gather data |
| Bid strategy change | 21 days | Full learning period for smart bidding |
| Audience/targeting change | 14 days | Need sufficient reach data |
| Operation Mode change | 21 days | Compound effects across multiple campaigns |

**Do NOT evaluate an action before its observation window has passed.**

## Minimum Sample Sizes

Before drawing any conclusion about a metric change, verify sufficient data:

| Metric | Minimum Sample | What Counts as "Sample" |
|--------|---------------|------------------------|
| CPA | 30 conversions (before) + 30 (after) | Each conversion is a sample point |
| CTR | 1,000 impressions (before) + 1,000 (after) | Each impression is a sample point |
| CVR | 200 clicks (before) + 200 (after) | Each click is a sample point |
| ROAS | 30 conversions with revenue | Each conversion is a sample point |
| Impression share | 7 days of daily data | Each day is a sample point |

**If the sample size is insufficient, the finding stays in OBSERVING. Do NOT promote it.**

## How to Evaluate an Outcome

When the observation window for an action has passed:

### Step 1: Collect Before/After Metrics

```
metrics_at_action (recorded when action was taken):
  CPA: 5,200  |  Conversions: 45  |  Clicks: 1,200  |  CTR: 3.2%

metrics_now (collected after observation window):
  CPA: 4,100  |  Conversions: 58  |  Clicks: 1,400  |  CTR: 3.5%
```

### Step 2: Check Sample Size

- Conversions before: 45, after: 58 → both > 30 → sufficient for CPA evaluation
- Clicks before: 1,200, after: 1,400 → both > 200 → sufficient for CVR evaluation

### Step 3: Assess Magnitude and Consistency

Ask these questions:

1. **Is the change large enough to matter?**
   - CPA change < 5%: probably noise, even if "statistically significant"
   - CPA change 5-15%: meaningful if consistent
   - CPA change > 15%: strong signal, but verify it persists

2. **Is the change consistent across the observation period?**
   - Did CPA improve every day, or did one great day skew the average?
   - Look at daily/weekly trends, not just period totals

3. **Were there confounding factors?**
   - Did another change happen to the same campaign during the window?
   - Did seasonality, a holiday, or external event affect the data?
   - Did a competitor enter or exit the auction?

4. **Does the direction match the hypothesis?**
   - If you added negative keywords expecting CPA to drop, did CPA actually drop?
   - An improvement in an unexpected metric may be coincidence

### Step 4: Classify the Finding

| Condition | Classification |
|-----------|---------------|
| Sample size insufficient | Stay in OBSERVING |
| Observation window not yet passed | Stay in OBSERVING |
| Change < 5% | REJECTED (noise) |
| Change 5-15%, consistent, no confounders | CANDIDATE → wait for 2nd period |
| Change > 15%, consistent, no confounders | CANDIDATE → wait for 2nd period |
| CANDIDATE confirmed in 2nd observation period | VALIDATED |
| CANDIDATE contradicted in 2nd observation period | REJECTED |
| Multiple concurrent actions on same campaign | Flag as confounded, extend window 2x |

### Step 5: Report with Confidence Level

When reporting findings, always state the evidence level:

```
GOOD (high confidence):
  "CPA improved 18% (5,200 → 4,100) after negative keyword cleanup.
   Observed over 14 days with 58 conversions. Consistent daily trend.
   Confirmed across 2 observation periods. [VALIDATED]"

BAD (jumping to conclusions):
  "CPA improved! The keyword changes are working great!"
   (No sample size, no observation window, no consistency check.)
```

## Noise Guards for Each Command

### /daily-check
- **DO**: Report current metrics and flag anomalies
- **DO**: Check if any action's observation_due date has passed and evaluate outcomes
- **DO NOT**: Recommend strategy changes based on day-to-day fluctuations
- **SAY**: "CPA is 12% above target today, but this is within normal daily variance. Monitoring."

### /rescue
- **DO**: Take emergency action when metrics are clearly critical (>30% off target for 7+ days)
- **DO**: Record metrics_at_action for every change made
- **DO NOT**: Trigger rescue based on a single bad day
- **THRESHOLD**: At least 3 consecutive days of critical metrics before rescue actions

### /search-term-cleanup, /creative-refresh, /budget-rebalance
- **DO**: Record metrics_at_action and set observation_due when making changes
- **DO**: Consult past VALIDATED learnings before proposing new changes
- **DO NOT**: Reverse a previous action that is still in OBSERVING
- **SAY**: "The budget increase from 4/1 is still in its observation window (due 4/8). I recommend waiting before making further budget changes to this campaign."

### /goal-review
- **DO**: Distinguish between metric movements backed by evidence vs noise
- **DO**: Highlight VALIDATED learnings that explain goal progress
- **DO NOT**: Attribute goal progress to specific actions without checking the evidence lifecycle
- **SAY**: "CPA improved 15% toward goal. This aligns with the VALIDATED finding from negative keyword cleanup on 3/20."

### /weekly-report
- **DO**: Include an "Evidence Pipeline" section showing pending observations and validated insights
- **DO**: Rate confidence in reported improvements (low/medium/high based on lifecycle status)
- **DO NOT**: Present OBSERVING findings as confirmed wins

### /competitive-scan
- **DO**: Look at trends over 4+ weeks, not week-to-week changes
- **DO NOT**: React to a single week's impression share dip

## Recording Outcomes in action_log

When executing any write operation, record the context needed for future evaluation:

```json
{
  "timestamp": "2026-04-01T10:30:00+09:00",
  "action": "Added 15 negative keywords",
  "platform": "google_ads",
  "campaign_id": "12345",
  "command": "/search-term-cleanup",
  "summary": "Excluded informational queries misaligned with Persona",
  "metrics_at_action": {
    "cpa": 5200,
    "conversions": 45,
    "clicks": 1200,
    "impressions": 37500,
    "ctr": 0.032,
    "cost": 234000
  },
  "observation_due": "2026-04-15"
}
```

**Which metrics to record** depends on the action type:

| Action Type | Key Metrics to Record |
|------------|----------------------|
| Budget change | cost, impressions, clicks, conversions, cpa |
| Keyword change | impressions, clicks, conversions, cpa, ctr |
| Creative change | impressions, clicks, ctr, conversions, cpa |
| Targeting change | impressions, clicks, conversions, cpa, reach |
| Bid strategy change | conversions, cpa, cost, impression_share |

## Consulting Past Evidence

Before proposing any action, check the action_log for:

1. **Pending observations**: Actions whose observation_due has not passed. Do not stack changes on the same campaign.
2. **Past outcomes**: Actions whose observation_due has passed. Evaluate and report the result.
3. **Patterns**: If a type of action has been VALIDATED before (e.g., "negative keyword cleanup consistently improves CPA by 10-20%"), reference it when proposing the same action again.
4. **Failures**: If a type of action was previously REJECTED (e.g., "device bid adjustments had no significant impact"), note this when the same action is proposed.

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | What to Do Instead |
|-------------|-------------|-------------------|
| "CPA dropped today, the change worked!" | One day is noise | Wait for the full observation window |
| Reverting a change after 2 days | Not enough data | Respect the observation window |
| Making 5 changes at once | Cannot attribute outcomes | Make one change, observe, then make the next |
| "Conversions went up 50%!" (from 2 to 3) | Tiny sample size | Check minimum sample requirements |
| Ignoring seasonality | External factors confound | Note day-of-week and seasonal patterns |
| Strategy update after one good week | One period insufficient | Require 2 consistent observation periods |
| Never updating strategy | Analysis paralysis | Once VALIDATED, commit to the learning |

## Summary

```
1. Every write action → record metrics_at_action + observation_due
2. Before the window passes → DO NOT evaluate, DO NOT reverse
3. After the window passes → collect current metrics, check sample size
4. Sufficient data + meaningful change → CANDIDATE
5. Confirmed in 2nd period → VALIDATED → recommend strategy update
6. Not confirmed → REJECTED → document and move on
```

**Be patient. Be rigorous. Let the data speak — but only when it has enough to say.**
