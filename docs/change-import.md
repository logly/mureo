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
| Google Ads | `google_ads` | `change_event` (GAQL) | **Yes** — built-in feed (live API only) | Capped at 100 rows with no paging; ~30-day retention; user-made changes only. **BYOD mode reports `unavailable`** — the export carries performance rows, not an audit trail |
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

So the discriminator is mureo's own log. **Four conditions, all required:**

| Condition | Why it is not optional |
|---|---|
| Same platform | Ids from two platforms share no namespace |
| Same **kind** of change | Without it, mureo pausing campaign 111 swallows the operator's budget edit on campaign 111 four minutes later. Manual and mureo-driven work overlapping on one campaign is normal for a while after onboarding, so this is the common case |
| The **same** target — see below | "Some shared id" is not the same thing, and treating it as such discards the operator's edit |
| Within 10 minutes | Absorbs the skew between mureo's stamp (when the call returned) and the platform's (when it committed) |

Additionally, a **definite** create-vs-remove disagreement refutes a match —
mureo removing a negative keyword while the operator adds one on the same ad
group in the same minute. It only refutes, never confirms: a `*_update` tool
may well be an upsert, so requiring agreement would block far more true
matches than it protects.

### How "the same target" is decided

Identity is slot-qualified (`campaign_id` / `ad_id` / `entity_id`), so a
campaign id never matches an ad id that happens to be the same string. Two
rules on top of that, and both are the "fail toward over-import" bias applied
at the identity layer rather than only at the kind layer:

1. **No slot populated on both sides may disagree.** Rejecting on any
   disagreement — rather than accepting on any agreement — is what stops
   mureo's bid change on keyword `kw-A` from swallowing the operator's bid
   change on `kw-B` in the same campaign. The shared `campaign_id` is not a
   licence to ignore the `entity_id` that disagrees.
2. **Both sides must name their target at the same specificity**
   (`entity_id` > `ad_id` > `campaign_id`, mureo's existing canonical-target
   precedence). If mureo names an ad and the feed row can only name a
   campaign, those are a target and a container, not a match. Identity is
   **unresolved**, and unresolved means import — otherwise mureo pausing one
   ad swallows the operator pausing the whole campaign.

The consequence for a feed adapter is that a row must name **one** canonical
target, not a target plus its parents: a row reporting both an ad and its ad
group would look strictly more specific than mureo's own record of that same
change, and rule 2 would then reject every true match. The built-in Google
Ads feed follows that convention (ad-level rows name the ad, not the ad
group), the same rule `plugin_semantics.extract_mutation_identity` already
applies to plugin mutations.

### How "kind" is derived

A small shared vocabulary — `status`, `budget`, `bid`, `criterion`, `ad`,
`ad_group`, `campaign` — computed independently from each side:

- **From the feed**: `changed_fields` first, `resource_type` second. The
  field list is the more specific signal, because Google reports a budget
  edit as `CAMPAIGN` + `changed_fields=["campaign_budget"]` at least as often
  as it reports it as `CAMPAIGN_BUDGET`; reading only the resource type would
  file the first one as a generic campaign edit — the same bucket a status
  toggle falls into.
- **From `action_log`**: the tool name, matched verb-before-noun so
  `google_ads_campaigns_update_status` reads as `status` rather than
  `campaign`.

**Both sides must yield a kind, and the two must be equal.** "Unknown matches
anything" would restore identity-only behaviour for every action mureo cannot
classify.

### Known limitation: a same-kind edit within 10 minutes of a mureo change is lost

> **If you edit an entity by hand shortly after mureo changed the same thing
> on it, mureo will record your edit as its own and you will not be told.**
>
> **What to do:** after mureo changes an entity, wait out the 10-minute
> attribution window before editing *that same entity's same setting* by
> hand — or make the edit and then say so, so the run has a record that does
> not depend on the import. Anything else on the account is unaffected: a
> different entity, or a different setting on the same entity, is imported
> normally.

This is the one case where change import fails in the expensive direction,
and it is worth being blunt about it because it is not an exotic shape. It is
exactly the mixed-operation pattern of the incident behind #545: mureo raises
a campaign's budget, the operator looks at the result and raises it again two
minutes later. Both are `budget`, both are campaign 111, both are inside the
window — so the second one is attributed to mureo and silently dropped from
`action_log`.

Nothing in the feed can separate them. `user_email` is the same OAuth
identity either way, `client_type: GOOGLE_ADS_API` covers mureo and every
other API tool on the account, and the two rows are otherwise identical in
every field the feed exposes. Widening what mureo compares cannot fix it;
only the operator's own timing or their own note can.

It is bounded by design, and the bound is what makes the advice usable:

| Situation | Imported? |
|---|---|
| Same entity, same setting, within 10 min of a mureo change | **No — silently attributed to mureo** |
| Same entity, same setting, after 10 min | Yes |
| Same entity, *different* setting (budget vs status), any time | Yes |
| A *sibling* entity in the same campaign (different ad group, ad, keyword) | Yes — provided the sibling was recorded at its own granularity; see below |
| A *broader* entity than mureo touched (campaign-wide vs one ad) | Yes |
| A *narrower* entity than mureo touched (one ad vs campaign-wide) | Yes |
| A different campaign entirely | Yes |
| Anything at all when mureo made no nearby change | Yes |

Only the first row is lost. Every other combination of target is imported —
including the ones an earlier version of this table got wrong, where a shared
`campaign_id` was enough to absorb an edit to a different entity inside it.

**The sibling row depends on both sides naming the sibling.** mureo can only
tell two keywords apart if both its own `action_log` entry and the feed row
name the criterion rather than the ad group they share. The built-in Google
feed does (criterion rows name the criterion, ad rows name the ad), and
plugin mutations passing `criterion_id` do. But mureo does **not** record
native keyword / exclusion / creative mutations automatically at all — only
status toggles are automatic, everything else is recorded when the agent
calls `mureo_state_action_log_append`. If that call names the ad group
instead of the criterion, two keywords in that ad group are one target again
and the sibling row does not hold for them. `_mureo-shared` tells the agent
what to pass; there is no mechanism that enforces it.

`/daily-check` cannot flag what it never saw, so the limitation is stated
here and in the `_mureo-shared` skill rather than left to be discovered.

### Other things this cannot discriminate

Both of these fail toward over-import — visible and correctable — rather than
toward the silent loss above:

- **Free-text and unrecognised action names.** An `action_log` entry an agent
  wrote as prose yields no kind, so nothing is attributed to it — mureo's own
  change re-imports as external.
- **Sub-kind detail.** A targeting change and a negative-keyword change are
  both `criterion`; a bid-modifier change on an ad group and on a campaign
  are both `bid`. Splitting these further would trade one failure direction
  for the other, and the vocabulary is deliberately coarse.

**Which way it fails is a deliberate choice.** Wherever the comparison cannot
be made — identity missing, kind underivable — the change is imported as
external. An over-import shows the operator a change they may have made
through mureo: visible, mildly annoying, correctable. An over-attribution
silently swallows a real UI edit, which is the exact blindness this feature
exists to remove. Never trade a visible wrong answer for an invisible one.

That asymmetry is also why the 10-minute window should not be widened
casually. Widening it can only ever *add* attributions, and the ones it adds
are the least certain — a hand edit further away from mureo's action, hiding
behind it. Narrowing it can only add over-imports, which the operator sees.

The window now multiplies exactly one gap: the same-entity/same-setting case
above. It used to multiply a much larger one — every edit anywhere inside a
campaign mureo had touched — which is worth knowing if you are reading an
older account's history.

### Imports never join a batch

An imported change is never stamped with the open batch id (#549). A batch is
the operator's declared change set — "what I did on Monday" — and a change
mureo merely observed is by definition not something they did through mureo.
Letting it join would drop that batch's rollback coverage to `partial` and
list an unrelated UI edit as a member the operator cannot reverse, for no
reason other than that the batch happened to be open when the poll ran.

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
- **Populate whatever identity the feed exposes**, and a `resource_type` /
  `changed_fields` that mureo can classify. Without identity, mureo cannot
  tell its own change apart from an operator's; without a derivable kind, no
  attribution is attempted at all. Both cost an over-import, never a swallow —
  but both are avoidable.
- **Set `unavailable_reason` when you did not look.** A feed that is
  registered but cannot answer for this account or mode (BYOD, an unsupported
  account type, a plan without change history) must say so rather than return
  an empty `changes` tuple. An empty result is reported as `imported`, which
  keeps the platform out of `blind_spots` and tells the caller it was checked.

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
