# Change import — recording work done outside mureo

> Issue #545. Audience: operators who run accounts partly by hand, and
> plugin/bridge authors who want their platform to participate.

## The gap this closes

Every guarantee mureo offers hangs off mureo having *made* the change. A
budget edit dispatched through mureo is evaluated by `StrategyPolicyGate`
before it runs, lands in `action_log` after it, gets an `observation_due`
window, and comes back for review in `/daily-check`'s evidence step.

An operator working in a platform's own UI is doing normal professional
work, not misusing mureo — and none of that machinery runs for any of it.
The consequence is not just a thin log. It is that **mureo cannot tell the
difference between "nothing happened" and "something happened that I cannot
see"**, which is how a delivery collapse turns into six days of guesswork:
there is no record connecting "delivery died" to "exclusions were added", so
recovery proceeds by elimination against an unknown change set.

Change import polls each platform's own change history, drops what mureo has
already recorded and what mureo itself did, and writes the rest into
`action_log` marked as **observed** rather than performed.

## Per-platform coverage

This table is the honest answer, not the roadmap. "Not read by mureo" means
the feed exists on the platform side and mureo does not fetch it — which is
a different statement from "the platform has no change history", and both
are different from "nothing happened there".

| Platform | Key | Change feed | Read by mureo today | What is missing |
|---|---|---|---|---|
| Google Ads | `google_ads` | `change_event` (GAQL) | **Yes** — built-in feed | Capped at 100 rows with no paging; ~30-day retention; user-made changes only |
| Meta Ads | `meta_ads` | Ad Account Activity (`/activities` edge on the Marketing API) | **No** | mureo ships no client for that edge. The data exists on Meta's side; mureo does not fetch it yet |
| Amazon Ads (official-MCP bridge) | `plugin:mureo-amazon-ads-bridge:amazon_ads` | Vendor API | **No** | The bridge can opt in through the ABI hook below; it does not today |
| Yahoo Ads (Search / Display) | `plugin:<dist>:yahoo_ads` / `…:yahoo_ads_display` | Vendor change history | **No** | Same — plugin-side, via the ABI hook |
| LINE Ads | `plugin:<dist>:line_ads` | Vendor API | **No** | Same |
| SmartNews Ads | `plugin:<dist>:…` | Vendor API | **No** | Same |
| TikTok Ads (hosted connector) | `tiktok_ads` | The connector's own tools | **No — and mureo cannot** | TikTok is outside mureo's data path entirely: mureo holds no credentials and dispatches nothing. A skill that can call the connector's change tools records what it finds through `mureo_state_action_log_append` with `origin: "external"` (see *Hosted connectors* below) |
| Search Console / GA4 | — | n/a | n/a | Not ad-serving platforms; no change surface to import |

**Every configured platform appears in the tool's response**, including the
ones with no feed. They come back `status: "unavailable"` with
`reason: "change_import_unavailable_for_<platform>"` — the same
honest-degradation contract as `analytics_not_available_for_<platform>`.

> **The absence of a change feed is not proof of innocence.** A platform
> mureo cannot poll is a platform mureo is blind on. Read `unavailable` as
> "unreviewed", never as "quiet". The same applies to `error`: a feed that
> could not be read did not report that the window was calm.

### What Google Ads' feed does not contain

Even where mureo *can* read, the read is partial, and the partiality is
reported on every result rather than buried here:

- **~30-day retention.** Older changes are gone from the API. They cannot be
  backfilled, by mureo or by anyone.
- **100 rows, no pagination.** A single bulk edit can consume the entire
  window and make everything before it permanently unreachable. This is not
  hypothetical — it is exactly what the post-mortem behind #545 hit. When a
  response is capped, the outcome carries `truncated: true`; treat it as
  "there were more changes than this and they are unrecoverable", and poll
  more often.
- **User-made changes only.** Automated bidding moving a bid, a policy
  disapproval, an automated rule firing — none of these appear. An empty
  feed is not evidence of a static account.

## How an imported change is recorded

An imported change is an `action_log` entry like any other, with three extra
fields on `ActionLogEntry`:

| Field | Meaning |
|---|---|
| `origin` | `"external"` — mureo observed this, it did not perform it. Absent (`None`) on every mureo-originated entry, which is what every entry written before #545 is |
| `external_id` | The feed's identity for the change, namespaced by platform. What makes a repeated poll a no-op |
| `occurred_at` | When the **platform** says the change happened |

`timestamp` keeps its existing meaning — when mureo wrote the entry, stamped
server-side (#460). `occurred_at` is history reported by the platform and is
never a source of "today".

All three are emitted only when set, so a STATE.json written by a
mureo-driven run round-trips unchanged and gains no new key.

### The observation window anchors on the change, not the import

An imported entry gets a 14-day `observation_due` measured from
`occurred_at`. A change that has been live for three weeks therefore lands
**already past due** and is reviewed on the next `/daily-check`, rather than
a fortnight from the day mureo happened to notice it.

`metrics_at_action` is deliberately left unset. mureo was not there when the
change was made and has no baseline for it; synthesising one from today's
numbers would invent a "before" that never existed and
`mureo_outcome_evaluate` would then score a fabricated delta. External
entries are reviewed qualitatively, the same way a plugin mutation is.

### mureo will not roll back an imported change

`rollback_plan_get` returns `not_supported` for every entry with
`origin: "external"`, before any other check — including one that carries a
well-formed `reversible_params` hint. mureo never dispatched the change, so
it never captured the prior value, which is the one thing a reversal needs.
A hint on such an entry describes a state mureo never read; applying it
would push whatever the hint happens to say, which is a fresh change dressed
as a restoration.

This keeps the batch plan honest too. A bulk pass that mixes mureo's own
changes with imported ones reports `partial` coverage and names the imported
members as gaps, instead of promising a full revert it could only half
deliver. Undo an external change in the platform, where the previous state
is known.

## Deduplication

Two ways a change can already be accounted for.

**Already imported.** Matched exactly on `external_id`. Feeds are polled with
overlapping windows on purpose, so re-seeing a change is the normal case.

**Made by mureo.** Every change mureo dispatches also shows up in the
platform's change feed. Recording that back as external would double-count
mureo's own work and — worse — would file a change mureo *can* reverse under
a provenance that says it cannot.

This second one cannot be matched exactly, and it is worth being precise
about why. The feed's own attribution fields do not separate the two:

- `user_email` is the same OAuth identity whether the operator worked in the
  UI or through mureo.
- `client_type: GOOGLE_ADS_API` covers mureo and every other API tool the
  account uses.

So the discriminator is mureo's own log: **same platform, same target
identity, within 10 minutes**. The window absorbs the skew between mureo's
stamp (when the call returned) and the platform's (when it committed).

**Which way it fails is a deliberate choice.** When identity is missing on
either side, no match can be made and the change is imported as external. An
over-import shows the operator a change they may have made through mureo —
visible, mildly annoying, correctable. An over-attribution silently swallows
a real UI edit, which is the exact blindness this feature exists to remove.
Never trade a visible wrong answer for an invisible one.

## When import runs

**In `/daily-check`, step 2b** — before any diffing, so a UI edit is a
recorded fact by the time the report explains the numbers.

**On demand**, via the `mureo_external_changes_import` MCP tool. Safe to call
repeatedly; importing the same change twice is a no-op.

Where the next poll starts is **derived**, not stored: it is the newest
`occurred_at` mureo has already imported for that platform, read straight out
of `action_log`. The first pass falls back to a deliberately short 7-day
lookback — a wider first window does not recover more history, it just makes
a row-capped feed likelier to truncate and lose the newest changes too.

> **Continuous polling is the only thing that captures history.** A one-off
> deep backfill is not available and cannot be made available: what has aged
> out of a platform's feed is gone. Running `/daily-check` daily is what keeps
> the record complete; a gap in the schedule is a gap in the record.

### Hosted connectors (TikTok)

TikTok is reached through a hosted MCP connector: mureo holds no credentials
and dispatches nothing, so there is nothing for a change feed to hook into.
A skill that *can* call the connector's own change-history tools records what
it finds through `mureo_state_action_log_append`:

```json
{
  "entry": {
    "action": "external_change:CAMPAIGN",
    "platform": "tiktok_ads",
    "campaign_id": "17...",
    "origin": "external",
    "external_id": "tiktok_ads|<the connector's change id>",
    "occurred_at": "2026-08-05T09:14:00+09:00",
    "summary": "observed outside mureo — budget raised"
  }
}
```

`origin: "external"` gets the entry the same treatment an imported one gets:
marked as observed, reviewed by daily-check, refused by rollback. Omitting
`external_id` is allowed but means a later pass cannot recognise the entry
and will record it again.

## The ABI hook — adding a change feed

A plugin or bridge participates by shipping an entry point in the
**`mureo.change_feeds`** group whose class implements
`mureo.change_import.ChangeFeedProvider`:

```python
from datetime import datetime
from mureo.change_import import ChangeFeedResult, ExternalChange


class AcmeChangeFeed:
    platform = "acme_ads"  # your registry name, NOT a "plugin:" key

    async def fetch_change_events(
        self, account_id: str, *, since: datetime, until: datetime
    ) -> ChangeFeedResult:
        rows = await my_client.change_history(account_id, since, until)
        return ChangeFeedResult(
            changes=tuple(
                ExternalChange(
                    platform="acme_ads",
                    occurred_at=row["changed_at"],
                    resource_type=row["entity_kind"],
                    operation=row["op"],
                    change_id=row["id"],          # stable id → exact dedup
                    changed_fields=tuple(row["fields"]),
                    actor=row.get("user", ""),
                    campaign_id=row.get("campaign_id"),
                )
                for row in rows
            ),
            truncated=len(rows) >= MY_ROW_CAP,
            notes=("acme retains 60 days of change history",),
        )
```

```toml
[project.entry-points."mureo.change_feeds"]
acme_ads = "my_plugin.change_feed:AcmeChangeFeed"
```

Two obligations worth stating plainly:

- **Set `truncated` when your response was capped.** Reporting a capped page
  as a complete answer turns a known blind spot into an invisible one.
- **Populate whatever identity the feed exposes.** Without `campaign_id` /
  `ad_id` / `entity_id`, mureo cannot tell its own change apart from an
  operator's and will record mureo's own work a second time as external.

Raising is a valid answer for "cannot fetch" (missing credentials, expired
token, unsupported account). The importer catches it per platform and reports
`error` — never silence.

### Why this is a new Protocol in a new group

`docs/ABI-stability.md` §4: adding a required method to an existing
`runtime_checkable` Protocol is **breaking**, because `isinstance` against
such a Protocol requires *every* member — a new method would have silently
de-registered every already-published plugin. #546 hit the same wall on
`AnalyticsModule` and split its extension into a sibling Protocol.

A new entry-point group (§6: non-breaking) goes one step further: a bridge
that only wants to publish a change feed does not have to stub four analytics
methods it will never implement, and a plugin that has never heard of change
import is unaffected in every way. It registers nothing here, so it is simply
absent, and its platform is reported as unavailable.

## Related documentation

- [ABI-stability.md](./ABI-stability.md) — the stability rules the hook follows
- [plugin-authoring.md](./plugin-authoring.md) — writing a plugin
- [strategy-context.md](./strategy-context.md) — the `action_log` schema
- [mcp-server.md](./mcp-server.md) — the MCP tool surface
