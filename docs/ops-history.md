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
| `expected` | Every mutating tool, `mureo_decision_record`, and `entry.expected` on `mureo_state_action_log_append` | The effects the change should have: an array of `{metric, direction, target?, horizon_days?, primary?}` |
| `decision_id` | Every mutating tool, and `entry.decision_id` on `mureo_state_action_log_append` | Links the change to a `proposed` or `adopted` decision already on record |
| Decision record | `STATE.json` `decisions` | Created as `adopted` from the call's `reason` and `expected` when no `decision_id` is given |
| `action_log[].decision_id` | `STATE.json` | Stamped on the change. It always names the **first** record of the decision's `supersedes` chain, so it stays stable when the decision is later updated |
| `applied_params` | `STATE.json`, on `action_log` entries and on decisions mureo writes for a call | The parameters the call sent, masked like the journal's `args`. Omitted when there were none, or when they exceed 4,000 characters of JSON |
| `journal_call_id` | `STATE.json`, on decisions mureo writes for a call | The `call_id` of that call's `JOURNAL.jsonl` record. The record carries `call_id` and `decision_id` in turn |
| `journal_tool` | `STATE.json`, on decisions mureo writes for a call that wrote no entry | The call's tool name, which rule 4 matches against an entry's `action` |
| `action_log[].evaluation` | `STATE.json`, on every `evaluation_of` entry: the automatic closure's `outcome_evaluated` entries and the manual evaluation records | The evaluation table: every metric before and after, with a verdict and a note |
| `approval` | Every mutating tool, and `entry.approval` on `mureo_state_action_log_append`; stored on `action_log` entries and on decisions | An external approval the change carries out: `{reference, approved_by, approved_at}`. Optional, never required |
| `settings.ops_history.enabled` | `STATE.json` | Off by default. When on, `reason` and `expected` are required |

### `expected`

```json
"expected": [
  {"metric": "cpa", "direction": "down", "target": 4500, "horizon_days": 14,
   "primary": true},
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
- `primary` is an optional `true` / `false`: the effect the verdict is read
  off (see [The evaluation table](#the-evaluation-table)). A single effect
  is primary by itself; with several, exactly one must be `true`, or the
  declaration is refused with `expected_primary_required`.
- One entry per metric at most (`cost` and `spend` are one metric). Anything else is refused with
  `invalid_args`, before anything is written.

### External approval

Some changes are approved by a person outside mureo before they are made:
a ticket, a change request or an approval queue. `approval` records which
one, on the change itself:

```json
"approval": {
  "reference": "REQ-2026-1017-04",
  "approved_by": "Jane Operator",
  "approved_at": "2026-10-17T09:30:00+09:00"
}
```

- `reference` is 1 to 128 characters of `A-Z`, `a-z`, `0-9`, `.`, `_`
  and `-`.
- `approved_by` is 1 to 80 characters after surrounding whitespace is
  removed, with no control, format or separator characters (Unicode
  categories Cc, Cf, Zl, Zp, Cs and Co, which covers bidi overrides,
  zero-width spaces and line separators).
- `approved_at` is a date, `YYYY-MM-DD`, optionally followed by `T` or
  a space and a time `HH:MM`, `HH:MM:SS` or `HH:MM:SS.ffffff` (one to
  six fraction digits), optionally followed by `Z` or an offset
  `+HH:MM` / `-HH:MM`. It must be a real calendar date and time, is at
  most 64 characters, and is stored exactly as given. Other ISO 8601
  forms (basic `20261017`, week dates `2026-W42-1`, an offset without
  a colon) are refused on every supported Python version.
- All three keys are required and no other key is accepted. Anything
  else is refused with `invalid_args` naming the field, before the
  platform is called.

The value is **recorded and shown, never verified**. mureo does not look
the reference up, does not check that the person exists and does not
compare the time with anything. It is never required, whether or not the
setting is on.

Where it lands:

- A call that writes an `action_log` entry stores it on the entry, the
  same way the entry carries the call's `reason`.
  `mureo_state_action_log_append` has no call-level `approval`; it takes
  the value as `entry.approval` instead.
- Every decision record the change writes stores it too, next to
  `applied_params`: the new `adopted` decision, the record that adopts a
  proposal named by `decision_id`, and the decision a call that wrote no
  entry gets right after it succeeded (see below). A batch opened by a
  `mureo_batch_begin` call that carries one stores it on the batch's
  decision.
- A call that writes no entry needs no `reason` for this: an `approval`
  alone records the call's decision, so the value is never kept only in
  the journal. With no reason stated, the decision's `rationale` reads
  `Carried out under external approval <reference>.` A call that wrote
  an entry without a `reason` gets no decision; the entry keeps the
  value.
- Two paths store a supplied approval on no decision record:
  - A call that joins a decision without writing a record (a member of
    a batch with a decision, or a second call naming an already adopted
    decision) leaves it only in its own entry, if it writes one, and in
    its `JOURNAL.jsonl` record's masked `args`.
  - An entry appended with `mureo_state_action_log_append` that joins
    the decision of a call that wrote no entry (rule 4 below) keeps its
    approval on the entry only. That decision was written by the call
    and is not changed; it carries the call's own approval, if any.
- Imported external changes and rollback entries never carry one.
- A malformed value already in `STATE.json` (hand-edited, say) is
  refused when a write reads the file, like any other malformed field.
  The read-only dashboard and history reads drop only the `approval`
  and keep the entry or decision it was on.

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
never linked. An evaluation record (`evaluation_of`), automatic or
appended by hand, inherits the `decision_id` of the entry it evaluates;
a value passed on it is replaced.

Nothing else is joined. A change is never attached to an earlier decision
because it looks related — same session, same campaign or same platform is
not enough. A wrong link is worse than a duplicate the operator can see:
recording a decision with `mureo_decision_record` and then making the
change with only a `reason` leaves two decisions. To link a change to a
decision you recorded, pass its `decision_id` on the change-making call.

### Calls that write no `action_log` entry

Most changes on a native platform — a budget, bid, keyword or ad change —
write no `action_log` entry. When such a call succeeds and carries a
`reason` (or an `approval`, see [External approval](#external-approval)),
mureo records its decision right after the call, by the same
rules: an explicit `decision_id` adopts that decision, a call inside a batch
with a decision joins the batch's, and otherwise a new `adopted` decision
is created. That makes exactly one decision per call, or per batch. A call
with no `reason`, no `approval`, no `decision_id` and no open batch is not
looked at at all. One
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
example to give it an `observation_due` so it is evaluated; its
`metrics_at_action` is filled from the campaign's snapshot when
omitted, see below), give the entry `action: "google_ads_budget_update"` and the
target (`entity_type: "budget"`, `entity_id: "b1"`): it then joins the
call's decision by rule 4. Passing the decision's id as
`entry.decision_id` links it whatever else the entry says.

On the mutating tools, `expected` is advertised as an array whose shape
and vocabulary are given in its description rather than as a nested JSON
Schema, which keeps the tool list small. mureo validates every item on the
server and refuses a malformed one with `invalid_args`. The recording
tools (`mureo_decision_record`, `mureo_state_action_log_append`) keep the
full schema.

## The baseline

The baseline is the entry's `metrics_at_action`. When a campaign-level
entry is appended with `mureo_state_action_log_append` without one,
mureo fills it from STATE.json (#890): the campaign's `metrics`, copied
whole (`period`, `fetched_at` and `result_indicator` included), plus
`days` read from `period`, so counts compare per day. It is filled
only for a change mureo made (no `origin`), never for an evaluation
record, and only when the snapshot has metrics and its `fetched_at` is
at most 2 days old (and at most a day ahead); otherwise nothing is
written, and the append's
`baseline` answer says why (`baseline_stale` for an old snapshot). A
baseline the caller passes is stored as given, never merged.

## The evaluation table

When an observation window closes and the change has a baseline, the
automatic closure writes an `outcome_evaluated` entry carrying:

```json
"evaluation": {
  "rules": 2,
  "overall": "improved",
  "basis": "expected",
  "primary": "cpa",
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

`rules: 2` marks the verdict rules below (#888). A table written before
them has no `rules`, no `primary` and no `reason`; it is read as it is and
never rewritten.

- **One primary metric decides `overall`.** It is chosen in this order,
  and `basis` names which rule chose it:
  1. `expected`: the declared effect marked `"primary": true`. A single
     declared effect is primary by itself; a declaration of several needs
     exactly one marked and is refused otherwise
     (`expected_primary_required`). A stored legacy declaration with
     several effects and none marked uses the first.
  2. `bidding_target`: the campaign snapshot's `bidding_details` —
     `target_roas` makes `roas` primary, `target_cpa` makes `cpa` primary.
  3. `default`: `cpa`, when both sides have conversions.
  4. Otherwise `overall` is `inconclusive` with
     `reason: "no_primary_metric"` and `primary` is `null`.

  A declared primary stays the primary even when its metric has no
  figures: the result is then `inconclusive` with `no_primary_metric`,
  `primary` names the declared metric, and it is listed in
  `expected_missing` — never a verdict on a metric the decision did not
  name. The bidding target and the default apply only when nothing is
  declared, and only when their metric has figures on both sides.
  Every other metric is a `reference` row: judged by its own direction,
  never deciding. A volume metric such as `spend` has no direction of its
  own and is `inconclusive` as a reference row.
- **Volume floor.** Both sides must reach the floor for the primary, on
  the raw counts: conversions (30) for `cpa` / `cpl` / `roas` /
  `conversions`, impressions (1,000) for `ctr` / `cpm`, clicks (200)
  for `cpc` / `cvr`. Below it the result is `inconclusive` with
  `insufficient_volume`, or `volume_unknown` when the count is missing.
- **Periods.** Count metrics (`conversions`, `clicks`, `impressions`,
  `spend`) are compared per day when both sides state their length — a
  `days` number, or a `period` of `YESTERDAY` / `LAST_7_DAYS` /
  `LAST_30_DAYS` — and the row's note says so. A count primary without
  both is `inconclusive` with `period_unknown`; a count reference row
  without both is compared as it is, and its note says
  `raw totals, periods unknown`. Ratios (`cpa`, `ctr`, `cvr`, `roas`,
  `cpc`, `cpm`) compare across periods of any length.
- **Direction and target** of a declared primary:
  - `up` / `down`: `improved` when it moved that way by at least the
    noise band, `regressed` when it moved the other way, `inconclusive`
    with `no_change` inside the band.
  - `hold`: `held` inside the band, `regressed` outside it. With a
    `target`, `held` within the band around the target.
  - With a `target`, reaching it is `improved`, even inside the band. A
    move the right way beyond the band that misses it is `inconclusive`
    with `target_not_reached`.
  - A target on a count metric is the total over the evaluation
    window: it is compared with the raw `after` figure, not the
    per-day row, and the note says `(window total N)`.
- **Zero baseline.** A primary whose baseline is zero has no
  percentage change: `inconclusive` with `zero_baseline`, unless a
  declared target decides on its own.
- `reason` is present only when set, and is one of `no_primary_metric`,
  `insufficient_volume`, `volume_unknown`, `period_unknown`,
  `zero_baseline`, `target_not_reached`, `no_change`.
- **A held-back result is recorded, not left open.** When
  `insufficient_volume`, `volume_unknown`, `period_unknown`,
  `zero_baseline` or `no_primary_metric` holds the verdict back, the
  primary's row is `inconclusive` too and its note leads with that code.
  The automatic closure stores the result as `inconclusive` and closes
  the observation like any other verdict. To judge the change anyway,
  evaluate it manually with `mureo_outcome_evaluate` over a longer window
  once both sides reach the floor.
- The noise band and the three floors can be set per workspace in
  STRATEGY.md `## Guardrails` (`outcome_noise_pct`,
  `outcome_min_conversions`, `outcome_min_impressions`,
  `outcome_min_clicks`).
- Metric names are matched after normalising long forms to the
  vocabulary above: `cost_per_conversion` and `cost_per_acquisition` match
  `cpa`, `conversion_rate` matches `cvr`, `cost_per_click` matches `cpc`,
  `cost` matches `spend`, and so on. When a snapshot carries both a long
  form and the short name, one row is kept: the short name's.
- Two snapshots that state different `period` windows are skipped
  (`period_mismatch`) only when the primary is a count metric.
- Declared metrics with no figures on both sides are listed in
  `expected_missing`.
- The schema reserves `control` (a comparison group) and `skipped_reason`.
  Neither is written in this phase.

### Manual evaluations store the same table

An observation the automatic closure skips is evaluated by the agent, and
that record carries the same table, in the same field (#889):

1. `mureo_outcome_evaluate` with `evaluation_of: <index>` and `after` —
   the campaign's `metrics` from `mureo_state_get`, unchanged, `period`
   and `fetched_at` included (`fetched_at` ends the window). The
   entry's `metrics_at_action`, its decision's `expected` effects and its
   campaign's `bidding_details` are read from STATE.json and scored by the
   automatic closure's own path, so for the same `after` the table is
   identical to the one the closure would store. `before` is required
   only when the entry recorded no baseline, and refused beside one
   (`evaluation_of_conflicts_with_before`). `expected` beside
   `evaluation_of` is refused (`evaluation_of_conflicts_with_expected`);
   a count primary over two different stated periods is refused
   (`period_mismatch`), and so is a result with no metric on both
   sides (`no_comparable_metric`), so an empty table is never stored.
2. `mureo_state_action_log_append` with `evaluation_of` and `evaluation`
   — the `evaluation` object the tool returned, unchanged. An
   `evaluation_of` without it is refused (`evaluation_required`), and
   `evaluation` without `evaluation_of` is refused
   (`evaluation_without_target`). Its shape is checked: `rules` 2, a known
   `overall` / `basis` / `reason`, `primary` a name or null, `noise_pct`
   in (0, 100], at least one row, rows with the row keys above, no
   unknown key. A table with no rows is refused (`no_comparable_metric`),
   as the automatic closure never stores one.
3. `action` is a short neutral label (`"Outcome evaluated"`); the verdict
   lives in the table. As on an automatic record, `summary` is built
   from the table (`outcome_summary`) and `decision_id` is the
   evaluated entry's; values passed for either are replaced.

The view, its counts and the dashboard feed read a manual record exactly
as an automatic one. Reading stays lenient: a stored table that is
malformed or missing never blocks a load or a write, and reads as no
verdict.

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
- Each change carries `approval`, its entry's external approval, and each
  decision carries `approval`, the newest one stated on its chain. Both
  are `null` when none was stated.
- Each item has a derived `state`: `proposed`, `adopted`, `executed`,
  `observing`, `evaluated` (with `verdict`: `regressed` if any of its
  changes regressed, else `improved`, else `held`, else `inconclusive`),
  `skipped`, `rejected` or `deferred`. It also has a `rolled_back` flag. Nothing about the state is
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
and inclusive. They default to the last 30 calendar days ending today,
today included, by the server's clock (`since` is today minus 29 days,
`until` is today). A date that is not exactly `YYYY-MM-DD`, or an `until`
before `since`, is a 400. The response always carries `enabled`, so the
browser can leave the section out while the setting is off. If the feed
cannot be read, the section is left out too.

- **One row per item**: its date, the decision's title, the platform, the
  state, the primary metric before and after with its change
  (`CPA 1,840 → 1,520 ▼17%`), and the verdict. The primary metric is the
  `expected` metric marked `primary` (the first one for a legacy
  declaration without a mark), or else the evaluation table's primary
  row, or else its first row; a change not yet evaluated shows `—`.
- **Order**: regressed first, then observing, then everything else, then
  improved. Newest first within each group.
- **A change with no decision** is titled "(no decision recorded)".
- **Weak rationale**: a decision whose rationale is shorter than
  `WEAK_RATIONALE_MIN_CHARS` (20) characters, after markdown emphasis is
  stripped and whitespace trimmed, carries a "weak rationale" chip. The
  constant is in `dashboard_ops_history_section.js`.
- **Expanding a row** shows the rationale, the expected effects, the
  operations sent (tool, target, before → after, reason; a nested value is
  shown as JSON, cut at 80 characters), the observation
  deadline, the evaluation table (metric, before, after, change, verdict,
  note), the reason a change was not evaluated, and whether it was rolled
  back.
- **An external approval** is shown under the operation it was stated on,
  "Approved by Jane Operator on 2026-10-17 (ref REQ-2026-1017-04)". For a
  call that wrote no entry it is shown under the parameters sent, from
  the decision. The date is the first ten characters of `approved_at`.
- **Filters**: the period (the last 7, 30 or 90 days, today included, 30 by
  default) fetches again;
  platform, state and verdict filter the rows already fetched. The
  platform list is the platforms the items name.
- A permanent note says the before/after comparison is indicative and
  includes market and seasonal effects.

All writer text is set as text, never as HTML.

### The client list

Where a client registry supplies the clients, the per-client summary
(`/api/reports/summary`) carries an `ops_history` object:
`{enabled, window_days, changes, improved, regressed, regressed_open,
held, inconclusive, observing}`, counted over the last 30 days, today included
(the detail section's default window). `changes` counts items in state
`executed`, `observing`, `evaluated` or `skipped`. `held` counts the
evaluated items whose verdict is `held`; an evaluated item with any
other verdict that is not improved or regressed counts as inconclusive.
`regressed_open` counts the regressed changes that were not rolled back. A
single-workspace summary does not carry the key.

- Each client card shows one line when the setting is on and the window
  holds at least one change: "Last 30 days: N changes · a improved ·
  b regressed · h held · c inconclusive · d observing".
- A client with at least one regressed change that was not rolled back
  (`regressed_open`) raises an attention finding in the triage list
  ("1 regressed change", "N regressed changes"). It ranks after analysis
  findings and before collection failures.

## Compatibility

Every new field is optional, and a document written before ops history
existed reads and writes unchanged. Entries recorded before this feature
have no `decision_id`, and show up as changes without a decision.

Record changes with `mureo_state_action_log_append`, which stamps
`timestamp` and requires `platform`. An `action_log` entry written into
STATE.json by hand should carry `timestamp` (ISO 8601), `action` and
`platform`. One that is missing any of them is kept in place, so it
never blocks a write: its required and unknown keys are written back as
found, and the keys mureo knows are normalized exactly as before. It
shows with an empty timestamp / platform, sorts as undated, and automatic
evaluation and rollback skip it when the platform or the metrics they
need are missing. An entry holding a value mureo refuses (a malformed
`approval`, say) is kept in place as an opaque record, written back
verbatim in full, with only its `timestamp` / `action` / `platform` and
its link to another entry (`rollback_of`, `evaluation_of`, `origin` /
`external_id`) read. Only an entry that is not an object is refused.
