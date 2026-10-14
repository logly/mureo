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
| `applied_params` | `STATE.json`, on `action_log` entries and on decisions mureo writes for a call | The parameters the call sent, masked like the journal's `args`. Omitted when there were none, or when they exceed 4,000 characters of JSON |
| `journal_call_id` | `STATE.json`, on decisions mureo writes for a call | The `call_id` of that call's `JOURNAL.jsonl` record. The record carries `call_id` and `decision_id` in turn |
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
4. **A `reason`, and a decision this session already adopted for the same
   target.** A decision is a candidate when all four hold:
   1. its latest record was written in the same MCP session as the change;
   2. that record is `adopted` and belongs to no batch;
   3. nothing has carried it out yet: no change is stamped with it and no
      record of it names `related_actions`. A decision recorded for a call
      that wrote no `action_log` entry stays open only to an
      `action_log` entry appended for that change, never to another call;
   4. that record names the change's platform and/or campaign — at least
      one of the two — and every one it names equals the change's.

   If exactly one decision is a candidate, the change joins it. With two or
   more, the change gets a decision of its own (rule 5). This is what keeps
   "record the decision, then make the change" from leaving two decisions
   for one change.
5. **A `reason`.** A new `adopted` decision is created. Its `rationale` is
   the reason, its `expected` the call's `expected`, and its `metrics` the
   entry's `metrics_at_action`. The title is derived from the change:
   `google_ads_campaigns_update_status campaign 123: status ENABLED → PAUSED`
   when the entry records the prior value, otherwise the operation and
   target followed by the entry's `display_title` or `summary`.
6. **Otherwise** the change is recorded without a decision, as before.

Imported external changes (`origin: "external"`) and rollback entries are
never linked. An `outcome_evaluated` entry inherits the `decision_id` of
the entry it evaluates.

### Calls that write no `action_log` entry

Most changes on a native platform — a budget, bid, keyword or ad change —
write no `action_log` entry. When such a call succeeds and carries a
`reason`, mureo records its decision right after the call, by the same
rules: an explicit `decision_id` adopts that decision, a call inside a batch
with a decision joins the batch's, and otherwise it joins the session's
decision as in rule 4 or a new `adopted` decision is created. That makes
exactly one decision per call, or per batch. One
`google_ads_budget_update` call with `budget_id: "b1"`, `amount: 12000`, a
`reason` and `expected` records:

```json
{"status": "adopted",
 "title": "google_ads_budget_update budget b1: amount 12,000",
 "rationale": "<the reason>",
 "platform": "google_ads",
 "expected": [{"metric": "spend", "direction": "up"}],
 "applied_params": {"budget_id": "b1", "amount": 12000},
 "journal_call_id": "call-…"}
```

The value before the change is not shown in this title: a budget update
does not read the budget before changing it. Nothing is recorded for a call
that failed, and nothing is created in a workspace that has no
`STATE.json`.

If you also record the change with `mureo_state_action_log_append` (for
example to give it `metrics_at_action` and an `observation_due` so it is
evaluated), that entry joins the call's decision by rule 4. Pass the
decision's id as `entry.decision_id` to make the link explicit.

On the mutating tools, `expected` is advertised as an array whose shape
and vocabulary are given in its description rather than as a nested JSON
Schema, which keeps the tool list small. mureo validates every item on the
server and refuses a malformed one with `invalid_args`. The recording
tools (`mureo_decision_record`, `mureo_state_action_log_append`) keep the
full schema.

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
- Metric names are matched after normalising long forms to the
  vocabulary above: `cost_per_conversion` and `cost_per_acquisition` match
  `cpa`, `conversion_rate` matches `cvr`, `cost_per_click` matches `cpc`,
  and so on.
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

Only `mureo configure` can turn it off. The MCP tool refuses `false` with
`invalid_args`: the requirement is the operator's to lift, not the
agent's. Setting the value already in force writes nothing.

While it is on:

- A mutating call without `reason`, or without `expected`, is refused with
  `invalid_args`, and the message names the missing parameter. A call that
  runs inside a batch whose decision already has them satisfies the
  requirement. So does a call that names a `decision_id`, provided that
  decision declares `expected` or the call passes it.
- `mureo_state_action_log_append` requires `entry.reason` and
  `entry.expected` the same way, for an entry that would open a new
  decision. An entry with `entry.decision_id`, one recorded inside a batch
  that has a decision, an imported external change, an evaluation and a
  rollback entry open none and are exempt.
- `mureo_decision_record` requires `expected` on a `proposed` or `adopted`
  record.
- `rollback_apply` and the `mureo_*` tools that write STATE.json or
  STRATEGY.md (other than `mureo_batch_begin`) are not affected.
- A `STATE.json` that cannot be read counts as off: the call goes through
  and the fault is logged. A call naming a `decision_id` is refused,
  because the decision cannot be checked.

Turning it off stops the requirement. It removes nothing that was
recorded.

## Reading it back

- `mureo_history_query` with `sources: ["decisions"]` returns one item per
  decision: its chain, the changes that carried it out (with `before` from
  `reversible_params`, `after` from `applied_params`, reason and
  `metrics_at_action`) and their evaluations. Each change appears under
  one decision only, the one it is stamped with; a decision's
  `related_actions` add only changes that name no decision, and never an
  evaluation or a rollback entry. A decision carried out by a call that
  wrote no entry is `executed` with no actions, and shows the call's
  `applied_params`.
  `sources: ["ops_history"]` returns the same items, plus one item per
  change that no decision covers.
- Each item has a derived `state`: `proposed`, `adopted`, `executed`,
  `observing`, `evaluated` (with `verdict`), `skipped`, `rejected` or
  `deferred`. It also has a `rolled_back` flag. Nothing about the state is
  stored, so it can never disagree with the records.
- `since` / `until` on these two sources compare the date of the item's
  timestamp (a decision's first record, or the uncovered change's own),
  by the same rule the `action_log` source uses. Items are sorted newest
  first by the full timestamp.
- For a custom view, `mureo.web.reports.build_ops_history(client, since,
  until)` returns the same items.

## Compatibility

Every new field is optional, and a document written before ops history
existed reads and writes unchanged. Entries recorded before this feature
have no `decision_id`, and show up as changes without a decision.
