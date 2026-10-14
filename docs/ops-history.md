# Ops history

Ops history links every change mureo makes to the decision behind it and
to how that decision turned out. Each change records why it was made and
which metrics it was expected to move. A decision record is created for it
automatically, and when the observation window closes the evaluation is
scored against that expectation. A later session can then ask "what did we
decide, what did we change, and did it work" in one query.

Everything below works with the setting off. The setting only decides
whether the reason and the expected effect are **required**.

## The pieces

| Piece | Where | What it is |
|---|---|---|
| `expected` | Every mutating tool, `mureo_decision_record`, and `entry.expected` on `mureo_state_action_log_append` | The effects the change should have: an array of `{metric, direction, target?, horizon_days?}` |
| `decision_id` | Every mutating tool, and `entry.decision_id` on `mureo_state_action_log_append` | Links the change to a `proposed` or `adopted` decision already on record |
| Decision record | `STATE.json` `decisions` | Created as `adopted` from the call's `reason` and `expected` when no `decision_id` is given |
| `action_log[].decision_id` | `STATE.json` | Stamped on the change. It always names the **first** record of the decision's `supersedes` chain, so it stays stable when the decision is later updated |
| `action_log[].evaluation` | `STATE.json`, on `outcome_evaluated` entries | The evaluation table: every metric before and after, with a verdict and a note |
| `settings.ops_history.enabled` | `STATE.json` | Off by default. When on, `reason` and `expected` are required |

### `expected`

```json
"expected": [
  {"metric": "cpa", "direction": "down", "target": 4500, "horizon_days": 14},
  {"metric": "conversions", "direction": "hold"}
]
```

- `metric` uses the outcome evaluator's vocabulary: `cpa`, `cpc`, `cpl`,
  `cpm`, `conversions`, `cvr`, `ctr`, `roas`, `cost`, `spend`, `clicks`,
  `impressions`.
- `direction` is `up`, `down` or `hold` (should not move beyond the noise
  band).
- `target` is an optional number, and `horizon_days` an optional whole
  number of days, from 1 to 365.
- One entry per metric at most. Anything else is refused with
  `invalid_args`, before anything is written.

## How a change is linked

When a mutating call produces an `action_log` entry, these rules apply in
order:

1. **An explicit `decision_id`.** The change joins that decision. A
   `proposed` decision is adopted first, with a new `adopted` record that
   names it in `supersedes`. A `rejected` or `deferred` decision, or an id
   that names nothing, is refused.
2. **An earlier entry of the same call.** One call that writes several
   entries shares one decision.
3. **An open batch with a decision.** Every member of a batch shares the
   batch's decision. `mureo_batch_begin` creates it from its own `reason`
   and `expected` (titled `Batch: <label>`), or adopts the `decision_id` it
   is given.
4. **A `reason`.** A new `adopted` decision is created. Its `rationale` is
   the reason, its `expected` the call's `expected`, and its `metrics` the
   entry's `metrics_at_action`. The title is derived from the change:
   `google_ads_campaigns_update_status campaign 123: status ENABLED → PAUSED`
   when the entry records the prior value, otherwise the operation and
   target followed by the entry's `display_title` or `summary`.
5. **Otherwise** the change is recorded without a decision, as before.

Imported external changes (`origin: "external"`) and rollback entries are
never linked. An `outcome_evaluated` entry inherits the `decision_id` of
the entry it evaluates.

Some calls write no `action_log` entry, such as a budget update on a
native platform, which the agent records itself with
`mureo_state_action_log_append`. Those calls create no decision. The
agent's entry creates or links it instead, from its own `reason`,
`expected` and `decision_id`, so one change never produces two decisions.

## The evaluation table

When an observation window closes and the change has a baseline, the
automatic closure writes an `outcome_evaluated` entry carrying:

```json
"evaluation": {
  "overall": "improved",
  "basis": "expected",
  "noise_pct": 10.0,
  "window": {"from": "2026-09-01", "to": "2026-09-18"},
  "metrics": [
    {"metric": "clicks", "before": 900.0, "after": 950.0, "delta_pct": 5.6,
     "verdict": "inconclusive", "note": "within ±10% noise band",
     "role": "reference"},
    {"metric": "cpa", "before": 5200.0, "after": 4400.0, "delta_pct": -15.4,
     "verdict": "improved",
     "note": "expected down; -15.4% (noise band ±10%); target 4500 reached",
     "role": "primary"}
  ]
}
```

- The **declared** metrics are `primary` and decide `overall`. A metric
  expected `up` or `down` counts as improved when it moved that way by at
  least the noise band, and as regressed when it moved the other way. A
  metric expected to `hold` counts as improved while it stays inside the
  band.
- Every other metric is kept as `reference`, judged by the evaluator's
  own rules. A volume metric such as `spend` has no direction of its own
  and is always `inconclusive` there.
- With nothing declared, or no declared metric present on both sides,
  `basis` is `default` and the evaluator's own direction rules decide, as
  before. Declared metrics that were missing are listed in
  `expected_missing`.
- The schema reserves `control` (a comparison group) and `skipped_reason`.
  Neither is written in this phase.

## The setting

`settings.ops_history.enabled` is off for every workspace, existing or
new. Turn it on with:

- `mureo_state_settings_set` with `{"ops_history_enabled": true}`, or
- `mureo configure` → **Advanced** → **Ops history**.

While it is on:

- A mutating call without `reason`, or without `expected`, is refused with
  `invalid_args`, and the message names the missing parameter. A call that
  names a `decision_id`, or that runs inside a batch whose decision already
  has them, satisfies the requirement.
- `mureo_state_action_log_append` requires `entry.reason` and
  `entry.expected` the same way, for an entry that would open a new
  decision. An entry with `entry.decision_id`, one recorded inside a batch
  that has a decision, an imported external change, an evaluation and a
  rollback entry open none and are exempt.
- `mureo_decision_record` requires `expected` on a `proposed` or `adopted`
  record.
- `rollback_apply` and the `mureo_*` tools that write STATE.json or
  STRATEGY.md (other than `mureo_batch_begin`) are not affected.

Turning it off stops the requirement. It removes nothing that was
recorded.

## Reading it back

- `mureo_history_query` with `sources: ["decisions"]` returns one item per
  decision: its chain, the changes that carried it out (with before-values,
  reason and `metrics_at_action`) and their evaluations.
  `sources: ["ops_history"]` returns the same items, plus one item per
  change that no decision covers.
- Each item has a derived `state`: `proposed`, `adopted`, `executed`,
  `observing`, `evaluated` (with `verdict`), `skipped`, `rejected` or
  `deferred`. It also has a `rolled_back` flag. Nothing about the state is
  stored, so it can never disagree with the records.
- `since` / `until` on these two sources compare the item's recorded local
  date (a decision's first record, or the uncovered change's timestamp).
- For a custom view, `mureo.web.reports.build_ops_history(client, since,
  until)` returns the same items.

## Compatibility

Every new field is optional, and a document written before ops history
existed reads and writes unchanged. Entries recorded before this feature
have no `decision_id`, and show up as changes without a decision.
