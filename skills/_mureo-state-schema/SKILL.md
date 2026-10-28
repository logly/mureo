---
name: _mureo-state-schema
description: "mureo: STATE.json schema and status vocabulary for writing state on Code."
metadata:
  version: 0.35.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
      python: ">=3.10"
    cliHelp: "mureo --help"
---

# mureo STATE.json Schema
> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, global flags, and security rules.

This file is the STATE.json schema and the status vocabulary contract every skill follows when it writes STATE.json with `Write` on Code (the bulk-snapshot flows `sync-state` / `daily-check`); on Desktop / Cowork the `mureo_state_*` MCP tools apply it for you. The *Success Response* it refers to as "above" is `../_mureo-shared/SKILL.md` → *Output Format*.

## STATE.json Schema (when writing on Code via `Write`)

> **Tool output ≠ STATE.json.** The *Success Response* above is what a vendor
> MCP tool *returns* — a campaign there is `{"campaign_id", "name", "status", …}`.
> STATE.json's `CampaignSnapshot` is a **different** shape: it requires
> **`campaign_name`**, not `name`. When you hand-write STATE.json with `Write`
> on Code, **map** the tool-output `name` → `campaign_name` (and `id` →
> `campaign_id`), and always set the platform's **`account_id`**. On Desktop /
> Cowork the `mureo_state_*` MCP tools serialize this canonical shape for you,
> so the mapping only matters on the Code `Write` path.

A campaign or platform missing a required field below, or a `decisions` record
mureo cannot read, is **not rejected**: it is kept as written and re-emitted
unchanged on every later write (a decision record mureo can read keeps its
extra keys too). But it reads with the missing values empty (a
campaign without `campaign_name` shows unnamed), and an unreadable decision
record is kept opaque — ignored by every reader — so get these exact names
right:

- **Campaign snapshot** (root `campaigns[]` and `platforms[<p>].campaigns[]`) —
  required: `campaign_id` (str), `campaign_name` (str), `status` (str).
  Optional: `bidding_strategy_type`, `daily_budget`, `campaign_goal`, `notes`,
  `device_targeting`, and `metrics` (the per-campaign performance object:
  `spend` / `impressions` / `clicks` / `conversions` / `cpa` / `ctr` / …).
- **Platform entry** (`platforms[<platform>]`) — required: `account_id` (str;
  use `""` only if genuinely unknown — an empty id is treated as *unknown*
  everywhere, so it never joins with another entry and never matches a
  per-account override). A placeholder — `unknown`, `none`, `null`, `n/a`,
  `undefined`, `tbd`, in any case — is read as unknown too, but only so a
  document that already carries one does not join two entries; `""` is still
  the one spelling to write. The MCP write tools read `""` the same way, but
  only `mureo_state_platform_not_collected_set` accepts it: a platform whose
  figures you DID collect knows which account they came from, so every other
  one still requires a real id. Plus `campaigns[]` and the rollups the dashboard
  actually renders: `totals`, `metrics_period`, `periods[<window>]`.
  A rollup carries the canonical metrics (`spend`, `impressions`, `clicks`,
  `conversions`, `cpa`, `ctr`, the Meta `result_indicator`) plus two
  statements ABOUT them, which are different facts and never stand in for
  each other: `fetched_at` (when the rollup was WRITTEN — ISO-8601, stamped
  for you by the `mureo_state_*` write tools when you omit it) and
  `period_end` (the last calendar date the figures COVER — `YYYY-MM-DD`, in
  the ad account's own timezone). `period_end` is optional and **yours to
  supply**: the server cannot derive it without the account's timezone, and a
  coverage date off by one day is worse than none. A window written without
  it is judged stale on its write time alone, which is how a card goes on
  showing two-day-old numbers under a fresh-looking update time. Each window
  states its own — never copy one window's date onto another.
  **`metrics_period` and every `periods` key must be one of mureo's three
  windows** — `YESTERDAY` / `LAST_7_DAYS` / `LAST_30_DAYS`. The set is closed:
  any other token is refused rather than stored (and never rounded onto a
  neighbouring window), because a window nothing reads makes a write that
  reports success over a dashboard that never moves.
  **One ad account has exactly one platform key.** Before writing an entry,
  check whether that `account_id` is already stored under a *different* key
  and write to that key instead — the reporting view aggregates across
  platforms, so two keys for one account inflate spend / conversions / CPA
  together. (The read side detects that case and **withholds the client
  total** rather than showing the inflated one, and separately reports a key
  it cannot resolve to any platform — but detection is not repair, so do not
  treat it as a licence to write the duplicate.) The
  `mureo_state_*` write tools now **reject** a write that would create the
  second key (naming both keys and the account); on the Code `Write` path the
  same rule is yours to honour, and a wholesale `Write` that lands a duplicate
  is logged as a warning rather than blocked. Pass the key exactly — a key with
  surrounding whitespace (`" google_ads"`) is a *different* key, and is
  rejected on create rather than silently stripped. **Never invent or
  abbreviate a platform key**: creating an entry under a key that is neither a
  first-class ad-platform key, nor a platform an installed plugin registered
  (its entry-point name — `logly_ads_context`, not `logly_ads`), nor a
  `plugin:<dist>:<provider>` key is rejected, with the accepted keys listed in
  the error. Use the canonical `plugin:<dist>:<provider>` form when the bridge
  that owns a snapshot is not installed on this machine. If a document already
  carries the duplicate pair, writes to the *existing* keys still succeed —
  mureo never merges or deletes an entry, because the two typically hold
  different partial figures; reconciling them is the operator's call. Changing
  an existing key's `account_id` to one another key already holds is rejected
  for the same reason (it creates the duplicate just as surely); pointing a
  key at an account nobody else holds is fine.
- **Top-level** — required: `last_synced_at` (ISO-8601 string, **stamped to
  _now_** by every campaign/metrics/report write). It drives the dashboard's
  "Synced N ago" freshness; a missing or stale value makes the data read as
  not-recently-synced. `mureo_state_upsert_campaign` / `_platform_metrics_set`
  / `_report_set` set it for you (`_action_log_append` does not); on the Code
  `Write` path you must set it yourself.
- **`history/` beside STATE.json** (#758) — the `daily` days trimmed past the
  35-day retention cap and every version of every report kind are archived
  there by the `mureo_state_*` write tools
  (`history/daily/<YYYY-MM>.json`, `history/reports/<kind>.jsonl`) while
  STATE.json keeps only the current window and the latest report, so never
  hand-write, prune or carry over those files on the Code `Write` path. Read
  them with `mureo_history_query` (`sources: ["daily"]` / `["reports"]`),
  never by opening the files yourself.
- **Top-level `batches`** (declared bulk change sets, #549) — **carry it over
  verbatim** on the Code `Write` path, together with each `action_log` entry's
  `batch_id`. Dropping either detaches a change set from its members, which is
  precisely the "reconstruct what I did from memory" state batches exist to
  remove. A record with no `ended_at` is an OPEN batch; do not invent, close or
  renumber one by hand — use `mureo_batch_begin` / `mureo_batch_end`.
- **`action_log` provenance** (`origin` / `external_id` / `occurred_at`, #545)
  — **carry these over verbatim** on the Code `Write` path. `origin` absent
  means mureo made the change; `origin: "external"` means mureo only observed
  it. Dropping `origin` silently promotes an observed change into one mureo
  claims it made (and could offer to roll back); dropping `external_id` makes
  the next import record the same change again. Never add `origin` to an entry
  that did not have it, and never write these three by hand for a platform
  `mureo_external_changes_import` covers.

Canonical STATE.json shape (note `campaign_name`, `account_id`, `last_synced_at`):

```json
{
  "version": "2",
  "last_synced_at": "2026-06-26T10:00:00+09:00",
  "platforms": {
    "google_ads": {
      "account_id": "123-456-7890",
      "campaigns": [
        {
          "campaign_id": "12345",
          "campaign_name": "Brand Search",
          "status": "ENABLED",
          "daily_budget": 5000.0,
          "metrics": {"spend": 4200.0, "clicks": 310, "conversions": 12}
        }
      ],
      "totals": {"spend": 4200.0, "clicks": 310, "conversions": 12},
      "metrics_period": "LAST_30_DAYS",
      "periods": {"LAST_30_DAYS": {"spend": 4200.0, "clicks": 310, "conversions": 12, "fetched_at": "2026-06-26T10:00:00+09:00", "period_end": "2026-06-25"}}
    }
  }
}
```

### Status vocabulary contract

STATE.json stores delivery-status strings **verbatim** — mureo never
normalizes them. Whatever a platform's own tools emit is what lands in the
campaign snapshot's `status` and in each `ads[]` entry's `status` /
`effective_status`:

- **Built-in platforms** persist the vendor's vocabulary as returned — Meta
  `ACTIVE` / `PAUSED` / `ADSET_PAUSED` / `DISAPPROVED`, Google Ads `ENABLED` /
  `PAUSED` / `REMOVED`.
- **Plugin platforms** persist the status strings **their own tools emit,
  verbatim**. A Protocol-based plugin emits the provider ABI's **lowercase**
  vocabulary — `enabled` / `paused` / `removed` (`AdStatus` in
  `mureo/core/providers/models.py`, whose values are the public ABI) — so
  those lowercase values are what its STATE.json carries. Do not translate
  them into another platform's spelling.
- **A platform that does not have the concept omits the field** rather than
  having one invented for it: only `ad_id` is required on an `ads[]` entry.
  This limb is not about statuses alone — it governs every platform-conditional
  field in the snapshot, `bidding_strategy_type` and `bidding_details`
  included. Pricing and delivery selection differ per platform: a platform that
  does not select delivery by a bid stores no bid strategy, and no skill may
  require one of it or narrate an auction, a win rate, a bid floor or a
  smart-bidding learning phase for it. Those are facts about the platforms that
  work that way, not facts about advertising. Metrics follow the same limb
  (`../_mureo-strategy/SKILL.md` → *Performance Metrics*): **a platform whose
  own primary figure has no canonical key omits it rather than borrowing a key
  that means something else** — writing an eCPM-priced network's selection
  price into `cpa` or `ctr` makes every consumer of that number wrong. Name
  such a figure in prose instead, in the platform's own words.

The `/daily-check` and `/sync-state` diffs compare the **stored previous**
value against the **stored current** value **case-insensitively**, so any
consistent vocabulary works — `ACTIVE`, `ENABLED` and `enabled` all read as
delivering. What matters is writing the **same field the same way every
run**: switching vocabulary between runs, or writing `status` one day and
`effective_status` the next, manufactures a status change that never happened.
