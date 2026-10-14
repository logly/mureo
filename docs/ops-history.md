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
| `journal_tool` | `STATE.json`, on decisions mureo writes for a call that wrote no entry | The call's tool name, which rule 4 matches against an entry's `action` |
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

When an `action_log` entry is recorded — by a mutating call, or by
`mureo_state_action_log_append` — these rules apply in order:

1. **An explicit `decision_id`** (on the call, or as `entry.decision_id`).
   The change joins that decision. A
   `proposed` decision is adopted first, with a new `adopted` record that
   names it in `supersedes`. A `rejected` or `deferred` decision, or an id
   that names nothing, is refused.
2. **An earlier entry of the same call.** One call that writes several
   entries shares one decision.
3. **An open batch with a decision.** Every member of a batch shares the
   batch's decision. `mureo_batch_begin` creates it from its own `reason`
   and `expected` (titled `Batch: <label>`), or adopts the `decision_id` it
   is given.
4. **An entry you append for a call that wrote none.** An entry written
   with `mureo_state_action_log_append`, outside any change-making call,
   joins the decision mureo recorded for such a call (see below) only when
   all of these hold:
   1. the decision was recorded in the same MCP session as the entry;
   2. the decision stores the call's tool name, and the entry's `action`
      equals it;
   3. every target id the call sent — `budget_id`, `campaign_id`,
      `ad_group_id`, `ad_id`, `keyword_ids` and any other `*_id` /
      `*_ids` parameter except `id`, `customer_id` and `account_id` —
      appears with the same value in the entry, in its `campaign_id`,
      `ad_id`, `entity_type` + `entity_id` (`budget` + `b1` is
      `budget_id: b1`) or `reversible_params.params`. The entry's own target
      must in turn be one the call sent: its `entity_type` + `entity_id`
      when it declares them, otherwise every target id it records — an
      entry about ad group 9 never joins a call that sent only
      `campaign_id`. A call that sent no target id never matches;
   4. no `action_log` entry has carried the decision out yet;
   5. exactly one decision meets 1–4.

   Otherwise the entry is linked by the rules below, and may get a decision
   of its own.
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

Nothing else is joined. A change is never attached to an earlier decision
because it looks related — same session, same campaign or same platform is
not enough. A wrong link is worse than a duplicate the operator can see:
recording a decision with `mureo_decision_record` and then making the
change with only a `reason` leaves two decisions. To link a change to a
decision you recorded, pass its `decision_id` on the change-making call.

### Calls that write no `action_log` entry

Most changes on a native platform — a budget, bid, keyword or ad change —
write no `action_log` entry. When such a call succeeds and carries a
`reason`, mureo records its decision right after the call, by the same
rules: an explicit `decision_id` adopts that decision, a call inside a batch
with a decision joins the batch's, and otherwise a new `adopted` decision
is created. That makes exactly one decision per call, or per batch. A call
with no `reason`, no `decision_id` and no open batch is not looked at at
all. One
`google_ads_budget_update` call with `budget_id: "b1"`, `amount: 12000`, a
`reason` and `expected` records:

```json
{"status": "adopted",
 "title": "google_ads_budget_update budget b1: amount 12,000",
 "rationale": "<the reason>",
 "platform": "google_ads",
 "expected": [{"metric": "spend", "direction": "up"}],
 "applied_params": {"budget_id": "b1", "amount": 12000},
 "journal_call_id": "call-…",
 "journal_tool": "google_ads_budget_update"}
```

The value before the change is not shown in this title: a budget update
does not read the budget before changing it. Nothing is recorded for a call
that failed, and nothing is created in a workspace that has no
`STATE.json`.

If you also record the change with `mureo_state_action_log_append` (for
example to give it `metrics_at_action` and an `observation_due` so it is
evaluated), give the entry `action: "google_ads_budget_update"` and the
target (`entity_type: "budget"`, `entity_id: "b1"`): it then joins the
call's decision by rule 4. Passing the decision's id as
`entry.decision_id` links it whatever else the entry says.

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

## Dashboard

While the setting is on, the dashboard shows ops history in two places.
While it is off, neither appears.

### The detail section

A client's detail view has an **Ops history** section directly below the
recent actions. It reads
`GET /api/reports/ops-history?client=&since=&until=`, which returns the
same items as `build_ops_history`. `since` and `until` are `YYYY-MM-DD`
and inclusive. They default to the last 30 days by the server's clock
(`since` is today minus 30 days, `until` is today). A date that is not
`YYYY-MM-DD`, or an `until` before `since`, is a 400. The response always
carries `enabled`, so the browser can leave the section out while the
setting is off.

- **One row per item**: its date, the decision's title, the platform, the
  state, the primary metric before and after with its change
  (`CPA 1,840 → 1,520 ▼17%`), and the verdict. The primary metric is the
  first `expected` metric, or else the evaluation table's primary row; a
  change not yet evaluated shows `—`.
- **Order**: regressed first, then observing, then everything else, then
  improved. Newest first within each group.
- **A change with no decision** is titled "(no decision recorded)".
- **Weak rationale**: a decision whose rationale is shorter than
  `WEAK_RATIONALE_MIN_CHARS` (20) characters, after markdown emphasis is
  stripped and whitespace trimmed, carries a "weak rationale" chip. The
  constant is in `dashboard_ops_history_section.js`.
- **Expanding a row** shows the rationale, the expected effects, the
  operations sent (tool, target, before → after, reason), the observation
  deadline, the evaluation table (metric, before, after, change, verdict,
  note), the reason a change was not evaluated, and whether it was rolled
  back.
- **Filters**: the period (7, 30 or 90 days, 30 by default) fetches again;
  platform, state and verdict filter the rows already fetched. The
  platform list is the platforms the items name.
- A permanent note says the before/after comparison is indicative and
  includes market and seasonal effects.

All writer text is set as text, never as HTML.

### The client list

Where a client registry supplies the clients, the per-client summary
(`/api/reports/summary`) carries an `ops_history` object:
`{enabled, window_days, changes, improved, regressed, inconclusive,
observing}`, counted over the last 30 days (the detail section's default
window). `changes` counts items in state `executed`, `observing`,
`evaluated` or `skipped`. An evaluated item whose verdict is neither
improved nor regressed counts as inconclusive. A single-workspace summary
does not carry the key.

- Each client card shows one line when the setting is on and the window
  holds at least one change: "Last 30 days: N changes · a improved ·
  b regressed · c inconclusive · d observing".
- A client with at least one regressed change raises an attention finding
  in the triage list ("N regressed changes"). It ranks after analysis
  findings and before collection failures.

## Compatibility

Every new field is optional, and a document written before ops history
existed reads and writes unchanged. Entries recorded before this feature
have no `decision_id`, and show up as changes without a decision.
