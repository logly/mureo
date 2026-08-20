# Strategy Context Guide

mureo supports two optional local files that let agents persist context across sessions without a database:

- **STRATEGY.md** -- strategic context (who your customers are, what your USP is, market conditions)
- **STATE.json** -- campaign state snapshots (current settings, budgets, statuses)

These files are read and written by the `mureo.context` module.

## STRATEGY.md

### Format

STRATEGY.md is a standard Markdown file with `## ` (h2) section headings. Each section maps to a `context_type` that categorizes the strategic information.

```markdown
# Strategy

## Persona
B2B SaaS decision-makers, 30-50 years old, IT managers and CTOs.
Budget authority for marketing tools up to $50k/year.

## USP
Only platform that integrates AI agents with ad operations.
Saves 10+ hours per week of manual campaign management.

## Target Audience
Small-to-mid size marketing teams (2-10 people) running
Google Ads and Meta Ads simultaneously.

## Brand Voice
Professional but approachable. Data-driven recommendations
with clear reasoning.

## Market Context
Competitive CPC rising 15% YoY in the SaaS category.
Meta Ads CPM increased 8% in Q4.

## Operation Mode
EFFICIENCY_STABILIZE

## Custom: Q1 Goals
Reduce CPA by 20% while maintaining conversion volume.
Focus on search term optimization and negative keyword expansion.

## Deep Research: Competitor Analysis
Top 3 competitors are spending 2x on brand terms.
Consider defensive brand campaigns.

## Sales Material: Product Deck Summary
Key selling points extracted from the 2024 product deck.
```

### Section Headings and context_type

| Heading | `context_type` | Description |
|---------|---------------|-------------|
| `## Persona` | `persona` | Target customer persona |
| `## USP` | `usp` | Unique selling proposition |
| `## Target Audience` | `target_audience` | Target audience definition |
| `## Brand Voice` | `brand_voice` | Communication tone and style |
| `## Market Context` | `market_context` | Market conditions and trends |
| `## Operation Mode` | `operation_mode` | Current operational focus |
| `## Custom: <title>` | `custom` | Any custom context with a title |
| `## Deep Research: <title>` | `deep_research` | Research findings with a title |
| `## Sales Material: <title>` | `sales_material` | Extracted sales material with a title |

**Rules:**
- Fixed sections (`Persona`, `USP`, etc.) use exact heading matches.
- Variable sections (`Custom`, `Deep Research`, `Sales Material`) use the `Prefix: Title` format.
- Unknown section headings are logged as warnings and skipped during parsing.
- The `# Strategy` top-level heading is generated automatically by the renderer.

### `## Tracking Convention` (opt-in)

A section the STRATEGY.md parser preserves verbatim (it has no `context_type` of its own) and the tracking-parameter consistency check reads:

```markdown
## Tracking Convention

- recognize: utm_*, argument
- require: utm_source, utm_medium, utm_campaign
- pattern utm_source: google, yahoo
- pattern utm_campaign: seg[ab]??
```

`recognize:` **adds** parameter-name globs to the default `utm_*`; `require:` names parameters every tagged final URL must carry; `pattern <name>:` lists the allowed value patterns for one parameter (a value matching any one of them conforms). Patterns are `fnmatch` globs (`*`, `?`, `[seq]`), not regular expressions.

mureo parses this section itself — the agent passes the text through unchanged. Declaring nothing is fine: the zero-configuration checks still run. See [tracking-consistency.md](tracking-consistency.md).

### `## Custom: Monthly Budget` (opt-in)

The operator's **intended monthly spend** — what `/budget-pacing` reads, offers to persist, and paces against:

```markdown
## Custom: Monthly Budget
- total: 300000
- google_ads: 180000
- meta_ads: 120000
```

`total:` is the whole-month figure and is required; every other numeric bullet is a per-platform sub-target, keyed by platform key (a plugin's own key works too). Code can read it too (#652), so monthly pacing can reach a surface the skill is not running on:

```python
from mureo.context import resolve_monthly_budget

# days_in_month belongs to the caller: pacing's "today" comes from
# server_now, never from this machine's clock.
budget = resolve_monthly_budget(
    strategy_text, days_in_month=31, platforms=state.platforms
)
if not budget.is_set:
    ...  # no target — ask the operator; do NOT render 0, 100%, or "on pace"
elif budget.is_platform_configured:
    ...  # what the platforms are SET to spend; never call it the agreed target
elif budget.is_derived:
    ...  # a ceiling stretched over a month; label it as an implied cap
```

The precedence is the skill's, matched rather than replaced:

1. **`## Custom: Monthly Budget`** wins — `source == "strategy_section"`. A `total: 0` is a real target ("spend nothing"), not an absence.
2. Otherwise the **sum of the per-campaign monthly budgets** held for platforms that declared they have that concept (#656), returned with `is_platform_configured` set and `source == "platform_configured_sum"`. It is what the platforms are **configured** to spend — a real figure, but not an agreement. Each platform's subtotal is in `configured_per_platform`, a **different field** from the operator's `per_platform` sub-targets: reading the wrong one gives an empty mapping rather than the other rung's figures under the other rung's label, and `MonthlyBudget` refuses to be constructed with a split that does not match its `source`.
3. Otherwise **`## Guardrails` → `max_total_daily_budget` × days in month**, returned with `is_derived` set and `source == "implied_daily_ceiling"`. It is a **cap, not a plan**: show it as derived wherever it appears.
4. Otherwise **not set** — `total is None`, `is_set` false. Ask the operator.

Omitting `platforms` skips rung 2 entirely and answers exactly what the two-argument call answered before it existed.

A missing, empty or malformed section degrades to "not set" rather than raising; an unreadable sub-target bullet drops only itself.

### Where the platform figure comes from (#656)

Rung 2 has two halves, because one route cannot carry both:

- **The figure is data.** `CampaignSnapshot.monthly_budget` — optional, `None` by default, emitted only when set, so a STATE.json written before it existed parses unchanged and gains no key. A collector writes it through `mureo_state_upsert_campaign` beside `daily_budget`. **No total is stored anywhere**: the sum is computed on read, because a cached total is stale the moment one campaign's budget changes.
- **The concept is declared.** A provider, bridge or plugin registers it, and mureo core declares no platform of its own:

```python
from mureo.context.platform_monthly_budget import (
    MonthlyBudgetSupport,
    register_monthly_budget_support,
)
from mureo.policy.learning_rules import Evidence

register_monthly_budget_support(
    MonthlyBudgetSupport(
        platform="acme_ads",  # the STATE.json platforms key this provider writes
        evidence=Evidence(
            source="https://developers.acme.example/reference/campaigns",
            retrieved="2026-08-19",
            quote="A campaign body accepts monthly_budget alongside daily_budget.",
        ),
    )
)
```

The declaration answers a question no campaign row can: whether an absent figure is a **gap** or a field that platform simply does not have. Google Ads and Meta campaigns are configured per day, so they contribute nothing here rather than a multiplied-out daily figure.

**An incomplete set is not a smaller budget.** A platform is not summed when a campaign it holds has no readable monthly budget, when it holds no campaigns at all, or when its last collection failed (`not_collected`, #638). One such platform withholds the *whole* total.

The platforms come back in `incomplete_platforms` as `IncompletePlatform(platform, reason)` records, which ride along whatever answer is used instead — so a caller states the gap rather than rendering a confident figure computed from part of the account, **and says which gap it is**:

| `reason` | What it means | Fix |
|---|---|---|
| `no_monthly_budgets` | It holds campaigns and not one carries a monthly budget — what a mistaken declaration looks like, and it disables this rung for every account on that platform. | The platform plugin must write the figures, or withdraw its declaration. |
| `missing_monthly_budgets` | Some campaigns have one, some do not — a sync that has not covered the account. | Re-run the platform sync. |
| `no_campaigns` | mureo holds no campaigns for it. | Re-run the platform sync. |
| `not_collected` | Its last collection failed (#638). | See that platform's `not_collected` note. |

`IncompletePlatform.detail` renders the one operator-readable line for each — held in one place so a dashboard, a CLI and a skill cannot give three accounts of one fact. That is also why nothing here logs: the record *is* the notification, and it reaches whoever asked.

**This is not a guardrail.** `Guardrails` carries ceilings that refuse an operation; a monthly target is the intended spend, where underspending is a problem too and nothing should be blocked for approaching it. Hence a separate type (`MonthlyBudget`) and separate functions (`parse_monthly_budget`, `monthly_budget_from_strategy_text`, `resolve_monthly_budget`). The agreed figure lives in STRATEGY.md only — it is deliberately not copied into STATE.json — and the platform-configured sum lives nowhere at all, being computed from the campaign snapshots on every read.

### Python API

```python
from pathlib import Path
from mureo.context import (
    StrategyEntry,
    read_strategy_file,
    write_strategy_file,
    add_strategy_entry,
    remove_strategy_entry,
    parse_strategy,
    render_strategy,
)

path = Path("STRATEGY.md")

# Read all entries
entries = read_strategy_file(path)
for entry in entries:
    print(f"[{entry.context_type}] {entry.title}: {entry.content[:50]}...")

# Add a new entry
new_entry = StrategyEntry(
    context_type="custom",
    title="Q2 Budget Plan",
    content="Increase Meta Ads budget by 30% for summer campaign.",
)
entries = add_strategy_entry(path, new_entry)

# Remove entries by context_type
entries = remove_strategy_entry(path, "custom", title="Q2 Budget Plan")

# Parse from string
text = Path("STRATEGY.md").read_text()
entries = parse_strategy(text)

# Render to string
markdown = render_strategy(entries)
```

## STATE.json

### Format

STATE.json is a JSON file containing campaign state snapshots across platforms, plus an action log for tracking changes and their outcomes.

```json
{
  "version": "2",
  "last_synced_at": "2026-04-01T10:00:00Z",
  "platforms": {
    "google_ads": {
      "account_id": "1234567890",
      "campaigns": [
        {
          "campaign_id": "111222333",
          "campaign_name": "Brand - Search",
          "status": "ENABLED",
          "bidding_strategy_type": "TARGET_CPA",
          "bidding_details": {"target_cpa_micros": 5000000},
          "daily_budget": 5000,
          "campaign_goal": "Maximize conversions at target CPA"
        }
      ]
    },
    "plugin:mureo-amazon-ads-bridge:amazon_ads": {
      "account_id": "ENTITY1A2B3C4D5E",
      "campaigns": [
        {
          "campaign_id": "444555666",
          "campaign_name": "SP - Brand Defense",
          "status": "ENABLED",
          "daily_budget": 12000
        }
      ]
    }
  },
  "action_log": [
    {
      "timestamp": "2026-04-01T10:30:00+09:00",
      "action": "Added 15 negative keywords",
      "platform": "google_ads",
      "campaign_id": "111222333",
      "command": "/search-term-cleanup",
      "summary": "Excluded informational queries",
      "metrics_at_action": {"cpa": 5200, "conversions": 45, "clicks": 1200},
      "observation_due": "2026-04-15"
    },
    {
      "timestamp": "2026-04-01T11:05:00+09:00",
      "action": "Raised daily budget 10000 -> 12000",
      "platform": "plugin:mureo-amazon-ads-bridge:amazon_ads",
      "campaign_id": "444555666",
      "command": "/budget-rebalance",
      "summary": "Shifted spend toward the brand-defense campaign",
      "observation_due": "2026-04-15"
    }
  ]
}
```

### Platform keys

A platform key is one of:

- a **first-class ad-platform key** — `google_ads`, `meta_ads`, `tiktok_ads`,
  `search_console`;
- a **`plugin:<dist>:<provider>` key** for any platform mureo dispatches
  through the plugin / bridge path, where `<dist>` is the provider's pip
  **distribution** name and `<provider>` the **entry-point name** that
  platform is registered under. One distribution may ship several platforms
  (`mureo-lineyahoo-bridge` ships `line_ads`, `yahoo_ads` and
  `yahoo_ads_display`), so the distribution alone cannot name one of them —
  see #537. The shape does not depend on how many a distribution happens to
  ship: Amazon Ads is `plugin:mureo-amazon-ads-bridge:amazon_ads`.

  The older **`plugin:<dist>`** form (#481) stays valid on read everywhere,
  and for a distribution providing a single platform it denotes the same
  platform, so entries already written under it keep joining. mureo migrates
  nothing: it never merges, drops or rewrites an operator's `platforms`
  entries.

The same key is used everywhere — the `platforms` map, each `action_log`
entry's `platform`, `mureo_state_upsert_campaign` / `mureo_state_platform_metrics_set`,
the reporting dashboard's label lookup, and `mureo_analytics_modules_list` /
`mureo_analytics_run`. Writing state under one spelling and reading it back
under another is a silent join failure; see
`skills/_mureo-shared/SKILL.md` → *Canonical platform key*.

**A key mureo cannot resolve is rejected on create.** Creating a `platforms`
entry through `upsert_campaign` / `set_platform_metrics` /
`set_conversion_action_types` / `set_platform_not_collected` (and so through
the `mureo_state_*` tools)
requires the key to be one of: a first-class ad-platform key; a platform an
**installed** plugin registered (its provider / analytics entry-point name,
e.g. `logly_ads_context`); or a `plugin:<dist>:<provider>` key, which is
accepted whether or not that distribution is installed here — use it for a
snapshot whose bridge lives on another machine. Anything else is refused with
an error naming the key and listing what would have been accepted, because an
invented key (`logly_ads` for a bridge whose provider is `logly_ads_context`)
files an account under a key nothing joins with and double-counts it against
the entry it really belongs to.

The check is create-only and applies to the targeted writers only: a
**whole-document** write (a restore, an import, a digest sync) still lands
whatever keys it carries, and an entry that already exists keeps taking writes
under its own key — an operator holding a bad key has to be able to sync and
repair it.

**One ad account has exactly one platform key.** The `platforms` map is keyed
by a free-form string, so two spellings of the same platform would otherwise
produce two entries for one real ad account — and the reporting view sums
every entry, inflating spend, conversions and CPA together. The STATE.json
write path therefore rejects a write that would **create** a second key for an
`account_id` another key already holds, with an error naming both keys and the
account. It applies to every writer that goes through `upsert_campaign`,
`set_platform_metrics`, `set_conversion_action_types` or
`set_platform_not_collected`, MCP or not.

"Would create a duplicate" is **not** "the key does not exist yet" — reusing a
key while changing which account it points at manufactures a new duplicate just
as surely. What happens depends on what the entry already says:

| Existing entry | Incoming `account_id` | Result |
|----------------|------------------------|--------|
| absent | held by another key | **rejected** (create) |
| absent | free | created |
| same account (`act_`-tolerant) | — | plain update |
| no `account_id` (`""`) | free | id stamped on |
| no `account_id` (`""`) | held by another key | **allowed** — see below |
| different known account | held by another key | **rejected** (re-point) |
| different known account | free | re-pointed |

The `""` row is deliberate and is not a loophole. An entry with no
`account_id` does not yet claim any account, so stamping one onto it cannot
create a real-world duplicate: if the two keys really are one account, that was
already true and merely invisible. Allowing the write is what makes the
duplicate *detectable* — and therefore fixable. Rejecting it would block the
very write that reveals the problem.

**A write to a key that already exists is never refused on the key's shape** —
including a whitespace-padded key or an unusable one. An operator holding bad
state must be able to keep syncing, or the guard becomes a trap they cannot
escape.

Three things it deliberately does **not** do:

- It never rewrites the key you passed. A key that claims the plugin namespace
  but carries no distribution (a bare `plugin:`) is rejected rather than
  repaired, because nothing can tell a bare distribution name from a built-in
  key — silently canonicalizing would fabricate one. A key with surrounding
  whitespace (`" google_ads"`, a different key from `google_ads` and another
  route to a duplicate) is likewise rejected on create rather than stripped.
- It never merges or deletes an existing entry. The two halves of a duplicate
  typically hold different *partial* figures, so dropping either under-counts
  as much as summing over-counts; reconciling them is the operator's call.
- It cannot reject on a **whole-document** write. A writer that assembles a
  complete `StateDocument` and writes it wholesale (`StateStore.write_state`)
  carries no notion of which entry is new, so there is nothing to refuse —
  and refusing would lock an operator out of repairing their own file. Such a
  write instead logs a **warning** naming both keys and the account, once per
  process per pair. Detection, not enforcement.

An `account_id` of `""` means **unknown**: it is never a join key, so it
neither triggers this rejection nor matches another empty id.

#### If your two platforms genuinely share an account id

The join is on `account_id` alone, across all keys — it has to be, because the
whole point is to catch one account stored under two *different* platform keys.
So if you really do operate two different platforms whose account identifiers
happen to be the same string, mureo will refuse to create the second entry and
report them as a duplicate.

This is a deliberate trade: a clear, recoverable failure at setup time is
cheaper than silently double-counting real money on a client card at every
sync. There is no override flag. To proceed, add the second `platforms` entry
by hand in STATE.json — once both keys exist, every subsequent write to either
succeeds, because the guard only ever refuses a *create*. The duplicate warning
described above will keep appearing once per process; that is the honest signal
that mureo cannot tell your case apart from the bug.

#### The shared join

The one-account-one-key rule is defined once, in
`mureo.context.platform_accounts`, and consumed by the write guards, the
read-only Reports view and out-of-tree writers alike:

| Function | Use |
|----------|-----|
| `normalize_account_id(account_id)` | Fold an id to its join form (strips surrounding space and an optional `act_` prefix, case-insensitive on the prefix only). `None` / empty folds to `""`; a non-string is folded textually rather than raising |
| `account_ids_match(a, b)` | Same **known** account? `False` whenever either side is unknown — including `("", "")` |
| `platform_keys_for_account(platforms, account_id)` | Every key that already describes this account, in document order |
| `duplicate_account_entries(platforms)` | One `DuplicateAccountEntry(account_id, platform_keys)` per account held under two or more keys |

If you write STATE.json from outside mureo, call `duplicate_account_entries`
on the `platforms` map you assembled **before** writing it. Do not reimplement
the comparison — the empty-id and `act_` rules are easy to get subtly wrong,
and a private copy that drifts re-creates the bug.

#### What the reporting view does with a duplicate it finds

None of the write guards repair anything, so an operator whose STATE.json is
*already* doubled keeps seeing a doubled card until they fix the file. The
read-only Reports view therefore detects the problem itself and reports it on
the summary as `platform_conflicts` — a list of
`{kind, platform_keys, account_known}`, in document order, carrying **no
`account_id`** (the platform rows deliberately omit it, and the grouping is
done server-side precisely so the browser is never handed one).
`account_known` is a presence bit, not an id: it says only whether the
entries behind the row named an ad account mureo could resolve.

Two `kind`s, deliberately never merged into one warning, because an
operator's next move differs:

| `kind` | What it establishes | Signal |
|--------|---------------------|--------|
| `duplicate_account` | Two or more keys resolve to **one** ad account, so any total over these rows is double-counted *right now* | `duplicate_account_entries` (the shared join above) |
| `unrecognized_key` | A key **no mureo surface can resolve**, so mureo cannot say which platform that entry describes — and, when the entry names no ad account either (`account_known: false`), it *may* duplicate a canonical one | `platform_display_name(key) == key` — the key resolves to no label |

The label lookup resolves exactly the vocabulary the write guard accepts: a
built-in key, a `plugin:<dist>:<provider>` key (or the legacy `plugin:<dist>`),
**and a bare provider name an installed plugin registered** —
`logly_ads_context` renders `Logly Ads Context (plugin)`. Both sides read one
enumeration of the installed plugins and both fail open when the environment
cannot be enumerated, so a key mureo itself accepts on write is never reported
here, and `mureo repair platform-key` and the Reports view cannot give an
operator opposite answers about one entry. (Until they could: the bare form
was accepted on write, reported `Clean` by the repair command, and flagged
here, all at once.)

The `unrecognized_key` condition tests the **key** alone, so it also fires on
an entry whose `account_id` resolves perfectly well — including one the
`duplicate_account` row has just named with certainty. `account_known` is what
keeps the two notes on one key from asserting opposite facts: on a known
account the dashboard says only that the *platform* cannot be resolved, and
the "may be a duplicate — review it by hand" wording is reserved for the
account-less shape, which is the one the join genuinely cannot see.

The second signal is not redundant. The join treats an empty `account_id` as
unknown, and unknown never matches unknown — so a document holding one
canonical key with a real id and one non-canonical key with `account_id: ""`
(the shape actually observed in the field) produces **no**
`duplicate_account` finding at all. Account joining alone does not detect it;
the unrecognisable key does.

**Two rows with different labels can still be one platform.** A plugin
platform held under both the legacy `plugin:<dist>` key and the canonical
`plugin:<dist>:<provider>` one renders as two rows carrying two *different*
labels — `Logly (plugin)` and `Logly Ads Context (plugin)` — because the
legacy key can only be labelled from the distribution while the canonical one
names the provider. Both keys resolve, so neither is flagged
`unrecognized_key`; when the two entries carry the same `account_id` the
`duplicate_account` conflict names both keys. A document should not reach this
state on its own: the write path refuses to **create** the second entry, so
both forms coexist only after a hand edit or a write that predates the guard.
mureo merges and rewrites nothing — check which entry holds the right figures,
keep the key that platform is already stored under, and remove the other by
naming it: `mureo repair platform-key --key <the key to remove>
--drop-duplicate` (dry run first; `--apply` makes the change).

The bare provider name is the third spelling of that same platform, and it
renders *identically* to the canonical key (`Logly Ads Context (plugin)`) —
it is the same platform from the same plugin, so a second label would be a
fiction. Two rows sharing one label therefore mean two entries for one
platform, which is what the `duplicate_account` conflict names whenever they
also carry the same `account_id`.

What the dashboard does about it:

- a client card with a `duplicate_account` conflict **withholds its KPI
  totals** rather than showing a figure it knows is wrong. A doubled spend
  reads as a real outlier in an at-a-glance grid and gets acted on, so no
  number is safer than a wrong one under a warning; the un-summed
  per-platform figures are one click away in the client's detail view;
- an `unrecognized_key` conflict is a *labelling* problem, not a proof that
  any figure is wrong (the key may well be a genuine platform mureo does not
  know), so the totals still render — the card is flagged, not blanked;
- either way the card carries a visible marker, so a flagged card cannot be
  skimmed as a healthy one, and the per-platform cards in the detail view
  carry the same finding (a single-client OSS install has no index grid, so
  that is the only surface it can appear on there);
- nothing is merged, dropped or reordered. Detection, not repair;
- and on a multi-client install the finding is also raised in the triage
  layer above the grid, ranked first of all of them — see *Triaging many
  clients at once* below.

#### Repairing an entry filed under a key mureo cannot resolve

Detection is right for the general case and still leaves one gap: a key that
names **no platform at all** (`logly_ads` for a bridge whose provider is
`logly_ads_context`). There is no question about which of two platforms the
data belongs to, because only one of the two keys names a platform — so that
case has a supported repair mureo performs on its own judgement. When both
keys are real the judgement is yours, and `--drop-duplicate` is where you
record it:

```bash
# Show what mureo would do. Changes nothing.
mureo repair platform-key

# Make the change (asks first; --yes skips the prompt).
mureo repair platform-key --apply

# Narrow it to one key, or point at another workspace's file.
mureo repair platform-key --key logly_ads --state-file ./client-a/STATE.json

# Both keys real? Name the one YOU decided is wrong. Dry run first.
mureo repair platform-key --key plugin:mureo-logly-bridge --drop-duplicate

# Or sweep every client this machine knows about, summary first.
mureo repair platform-key --all
```

What it does, and deliberately does not:

- **A dry run is the default**, not a flag. The command prints the key, the ad
  account, how many campaigns the entry carries, whether it holds a `totals`
  rollup, which windows it covers with each window's `fetched_at` and any
  `not_collected` note — for the unresolvable entry *and* for the entry the
  same ad account is stored under — then states exactly what would change. `--apply` is a second, deliberate
  step and still asks; with no TTY (an AI agent's shell, a CI runner) it
  declines rather than proceeding.
- **It drops the unresolvable entry; it never merges one.** The alternative —
  moving its figures under the canonical key — is only defensible once you have
  decided the canonical entry is empty or older, which is a judgement about
  which of two sets of partial figures is true, and that is precisely what the
  reporting view refuses to make. Dropping needs no such judgement, and the
  figures are not lost: the next sync refills the canonical key from the
  platform itself.
- **It backs the document up first**, timestamped
  (`STATE.json.bak.<unix_ns>`, so a second run cannot overwrite the first
  backup), and prints the `cp` that puts it back. That backup is the undo. The
  repair is **not** written to `action_log`: that log records changes made to
  an *ad platform*, every entry names a `platform` and is fed to the rollback
  planner's MCP-operation allow-list, and a local-file edit has no platform
  operation to name or reverse — the entry would also have to carry the very
  key just removed, putting it back on the dashboard's activity feed.
- **"Resolvable" is not decided twice.** The command asks the same
  `reject_unknown_platform_key` the write guard asks, including its fail-open
  behaviour: on an environment whose installed plugins cannot be enumerated,
  every key counts as resolvable and nothing is proposed for removal.
- **An entry holding only a `not_collected` note is not an empty stub.** A
  platform that failed on its very first collection has no campaigns, no
  `totals` and no `periods`, so the note (#638) is the whole entry — and it is
  the only thing in the document saying why that platform has no figures.
  Nothing re-derives it: a later run that succeeds retires it, one that fails
  again writes a new note about a new attempt. So it is reported and handed
  back rather than removed as empty, and the dry run states it among what the
  entry holds. It is not a veto, though: an entry that duplicates a key mureo
  can resolve is still a duplicate, and the block then says which part of it
  a sync brings back and which part it does not.
- **A duplicate whose two keys both name real platforms is reported, not
  repaired** — the command says so in as many words and hands the decision
  back, describing **what each entry holds** so the decision and its evidence
  are on one screen. It is not a general duplicate merger. What it now also
  does is print the command that ends it: `--key <the key to remove>
  --drop-duplicate` removes the entry **you** named even though mureo can
  resolve its key. That is the operator recording a decision, not mureo making
  one — it is honoured only where the document shows another entry holding the
  same ad account, it still refuses an entry carrying
  `conversion_action_types`, and it is not accepted with `--all` (one client's
  decision must not sweep the machine).
  Until it existed the dashboard withheld such a client's totals "until this
  is resolved" while nothing could resolve it.
- Only the `platforms` map changes. `last_synced_at` is not re-stamped (a
  repair is not a sync, and re-stamping it would make every other platform's
  stale figures read as just-synced), and the legacy flat `campaigns` list is
  left alone because it is platform-blind — nothing in it says which entries
  came from the removed key.

- **`--all` repairs every client, not every directory you remembered.** The
  bad key was written by an agent, and an agent that ran against every client
  wrote it everywhere. `--all` surveys each client the active `StateStore`
  advertises (the same `list_clients()` / `state_store_for_client(slug)` seam
  the Reports tab reads — no OSS dependency on a multi-account backend), leads
  with "N of M need repair", confirms **once** with the whole list in view,
  and carries on past a client it cannot read with a non-zero exit. On an
  install whose store declares neither capability it surveys exactly one
  client, the active workspace. Archived clients are swept and labelled. See
  [`docs/cli.md`](cli.md#every-client-at-once---all).

The write goes through `write_state_file`, the whole-document funnel the
create guard deliberately does not police, so a document that is *already*
duplicated stays repairable.

#### The metrics-window vocabulary

mureo reports on exactly three windows — `YESTERDAY`, `LAST_7_DAYS`,
`LAST_30_DAYS` — and the rule points in opposite directions on the two sides
of the file, deliberately (#659).

**Writing is strict.** `set_platform_metrics` (and the
`mureo_state_platform_metrics_set` tool over it) refuses a `metrics_period`
or a `periods` key outside that set, before the document is touched, and the
tool schema states the set as an `enum` rather than an example. A write that
lands where no default view looks is not a successful write, it is a silent
one: the reported failure had a daily check report *All persistence complete*
truthfully while the card read stale for three days, because the figures had
gone into `SINCE_LAUNCH_17D`. Both statements were true and nothing named the
contradiction — refusing puts it in front of the caller at the one moment the
figures are still in hand.

**Nothing is normalised.** `LAST_8_DAYS` is refused, not mapped onto
`LAST_7_DAYS`: that would present eight days of figures as a seven-day
answer, the same mislabelling the staleness rule below exists to prevent.

**Reading is tolerant.** Labels already on disk were written before the guard
existed. They are real figures, correctly collected, under a name no view
expects, so `_available_periods` still surfaces them and their totals still
resolve — refusing to read them would delete data mureo did collect in order
to tidy a vocabulary. They are not quietly kept either: the report summary
lists them in `non_canonical_periods` and the dashboard marks their toggle
button as a window mureo does not define, so an operator can see what
accumulated and decide what to do about it.

The window's length is part of the definition, not decoration — the staleness
threshold below is derived from it. That is why a fourth window is a
deliberate decision with a defined length rather than something a caller can
create by naming it.

#### Per-platform freshness

`fetched_at` (the metric-vocabulary key, see *Performance Metrics* in
`skills/_mureo-strategy/SKILL.md`) is what the dashboard reads to say how old
each platform's numbers are. It is judged against the window the figure
covers: a rollup is **stale** once it is older than that window's own length
plus one day of grace — `YESTERDAY` after 2 days, `LAST_7_DAYS` after 8,
`LAST_30_DAYS` after 31. The window's length is the threshold because past it
the stored figure no longer overlaps the window its label claims (a
`LAST_30_DAYS` rollup pulled 31 days ago describes days -31 to -61, which
shares not one day with today's last 30); the grace day absorbs a missed
daily sync and the platforms' own reporting lag. An unrecognised window gets
the most forgiving threshold rather than a guess.

`set_platform_metrics` (and the `mureo_state_platform_metrics_set` tool)
**stamps the write time** onto every rollup a call supplies without a
`fetched_at` — `totals` and each `periods` bucket alike — and never re-stamps
a window the call merely preserves. A value the caller did supply is relayed
verbatim, so a historical window keeps the time its figures were really
pulled. The field used to be one the writer had to remember, and the writer
that reaches it most often is an agent following a skill, so "optional" turned
into "usually missing" and most cards read *"update time unknown"*.

That state has not gone away and must stay renderable: a document written
before the stamp, or by something outside mureo, still has no `fetched_at` and
renders as *"update time unknown"* — never as fresh. A value that is not a
timestamp at all is treated the same way, and is still relayed **verbatim**:
the staleness verdict is the authoritative "could this be interpreted?"
answer, so blanking the string would only throw away the clue an operator
needs to find the writer that produced it. Treat `fetched_at` as an opaque
string unless the verdict is not "unknown".

A **stale** figure is not rendered as the selected window's result. Mureo
cannot vouch for it — the same position it takes on a double-counted account —
so the headline metrics read `—` and the stored numbers are restated below
with their age (*"last collected 11d ago: …"*). Nothing is hidden and no
number is lost; what stops is the claim that an old figure answers the window
on screen. A card once reported 25,862 in cost for a window whose real cost
was 0, with the age demoted to a badge beside it; the operator read the bold
number, as anyone would. A figure whose staleness is *unknown* keeps its
ordinary rendering — withholding on "we were not told" would blank almost
every historical card.

A client card shows one aggregate rather than per-platform rows, so it reports
the **oldest** freshness among the platforms that actually contribute totals —
an aggregate is only as current as its stalest input — and marks itself stale
if any of them is. When some contributor has no usable `fetched_at` the card
cannot honestly quote an age, so it says *"update time unknown"*; if it also
knows one contributor is genuinely stale it says *"stale — some update times
unknown"* instead, because a fresh sibling must never hide a stale one and the
label has to match the marker.

This is per platform and **cannot** come from the document-level
`last_synced_at`, which is re-stamped on any platform write: refreshing one
platform would otherwise make every other platform's stale numbers read as
just-synced. `last_synced_at` still means exactly what it always did — the
detail view shows it, labelled as the document sync it is.

#### Why a platform's figures did not move

Freshness says a figure is out of date. `platforms[<p>].not_collected` says
**why** — the half an operator can act on. Without it, "not collected" and
"collected, and the answer was zero" are the same document: a stopped ad
account and a stopped collector produce an identical card, and the card that
reported eleven-day-old figures sat untouched for eleven days because nobody
could tell which it was.

```json
"not_collected": {
  "attempted_at": "2026-08-18T09:00:00+09:00",
  "reason": "Meta returned OAuthException 190: the access token expired"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reason` | `string` | Yes | What happened, in words an operator can act on. A note with no reason is dropped on read: it would say something happened and refuse to say what. Truncated for display (500 characters), so write a sentence, not a stack trace |
| `attempted_at` | `string` | No — server-stamped | ISO 8601 time of the failed collection, written by `set_platform_not_collected` / `mureo_state_platform_not_collected_set`. Absent means the age is stated as unknown rather than guessed |

**It does not mean the figures are wrong.** `totals` / `periods` are left
exactly as they were, because they are still the last numbers that were
truly collected — writing `0` for a request that timed out would be the lie
the merge semantics already avoid. The card says so in as many words: *"…
could not be collected 2d ago: … The figures shown are the last ones
collected — they are not wrong, they are older."* It renders directly under
the stale note it explains, and above the repair hint.

**Whoever collects clears it.** Set it with
`set_platform_not_collected(path, platform, account_id, reason=...)` (or the
`mureo_state_platform_not_collected_set` tool) when a collection fails, and
call the same writer with `reason=None` — omit `reason` on the tool — on the
next successful collection. No other write retires it: every targeted mutator
treats an omitted field as *leave it alone*, and one window's rollup landing
does not prove the platform-level collection recovered. A note that outlives
its failure is permanently stale information stated with confidence, which is
precisely the defect it exists to remove.

**And the dashboard does not depend on that being honoured.** A note is not
shown once any of the platform's rollups carries a `fetched_at` *later* than
its `attempted_at` — a collection that succeeded after the failure has
already answered it. The rule is applied server-side, once, exactly where the
staleness verdict is, so the browser is handed a resolved answer rather than
a second copy of the rule. Three deliberate limits:

- **Any window counts.** The note is platform-level, so `YESTERDAY` landing
  proves as much as `LAST_30_DAYS`; the comparison uses the newest
  `fetched_at` in the entry, not the window on screen. Switching the period
  toggle can never resurrect a retired note.
- **No collection time, no retirement.** A platform with no `fetched_at`
  anywhere has never been collected as far as the document knows, and that is
  the case where the note is the only thing the card can say.
- **Retirement is a proof, not a guess.** An unparseable `fetched_at`, or a
  note with no `attempted_at`, leaves the question open — and open is not
  retired, the same position the staleness verdict takes on a value it cannot
  interpret.

Re-pointing a platform key at a *different* ad account also drops the note,
because it describes a failure for the account the entry used to name.

Between the two, a card can never show a fresh figure and a stale reason at
the same time: the contract stops the contradiction being written, the read
rule stops it being shown when the contract was not honoured.

Recording a failure is **not** a sync, so unlike every other platform write
this one does not re-stamp `last_synced_at`: reporting the document as
just-synced on the strength of nothing having been collected is the same
false statement one field over.

#### Triaging many clients at once

Everything above is rendered inside one client's card — which is exactly the
problem when you run twenty-seven of them. A double-counted ad account and an
eleven-day-old figure were both on screen, on the right card, in red, for
days: they carried the same visual weight as everything on that card that was
fine, and nothing said *which client to open first*. Neither was a missing
signal. Both were unsurfaced ones.

So the multi-client Reports view puts a **triage layer** above the client
grid: the findings mureo has already made, aggregated across clients and
ranked. It adds no new fact about an ad account.

**It appears only where a client registry is wired in.** A single workspace
has no second client to rank against, so the layer is *omitted* rather than
shrunk to one row, and `/api/reports/summary` is byte-for-byte what it was
before the layer existed — same keys, same order. The test is whether the
active `StateStore` **declares** `list_clients`, not what calling it returns:
`build_report_summary` runs once per client card and the dashboard fetches
every visible client in parallel, so a predicate that called the registry
would cost one registry read per client on the very screen this feature is
for.

The ranking is by what mureo can act on, and it is stated in code
(`REPORTS_TRIAGE_KINDS` in `mureo/_data/web/reports_triage.js`), never left
to render order:

| Rank | Finding | What it means | What to run |
|------|---------|---------------|-------------|
| 1 | Totals double-counted | One ad account under two platform keys — the client's totals are withheld right now | `mureo repair platform-key --key <the key to remove> --drop-duplicate` |
| 2 | Totals stale | The newest figures pre-date the window on screen, so they are not its answer | `/sync-state` for that client |
| 3 | Not collected | A collection failed and said why. The figures have not aged out yet, and this is the cheapest moment to fix it | clear the stated cause, then `/sync-state` |
| 4 | Unrecognised key | mureo cannot resolve an entry to a platform, so the client cannot be fully checked for a duplicate | `mureo repair platform-key` |
| 5 | Observation due | A change mureo made is past its review date | `/daily-check` for that client |

Three properties are load-bearing, and each is pinned by a test:

- **Every row names something runnable.** #636 was reported precisely because
  the dashboard said "resolve this" and no command existed that could. A row
  with no next step is a bug in the row, not a display detail.
- **"mureo cannot state this" is a row, not a blank.** The two withholding
  findings say so in words. A client whose totals are withheld renders `—` on
  its card, and an empty cell in an at-a-glance grid reads as zero, or as
  fine — which is the one thing this view must never let happen.
- **The count matches the grid.** If the layer says three clients need
  attention, exactly three cards below it are marked; both read one list.
  And when there is nothing, the layer renders nothing — no "0 alerts"
  banner competing for attention with the cards.

Four of the five findings are already on the wire per client (`freshness`,
`not_collected`, `platform_conflicts`). The fifth is not, and cannot be
derived in the browser: `recent_actions` is capped at the 20 most recent
entries, and it carries neither `rollback_of` nor `evaluation_of`, so a
count taken from it would both under-report a long log and keep asking for
reviews that were already done. The summary therefore carries

```json
"observations_due": { "count": 2, "oldest_due": "2026-08-01" }
```

— present **only** under the client-registry seam. "Due" means the window has
closed (`observation_due` on or before the server's local date) and nothing
has closed the entry, which is the same rule
`mureo_state_get(action_log="pending")` applies; it lives in
`mureo.context.observations` so the two surfaces cannot drift. An
`observation_due` mureo cannot parse as a date is not counted — it cannot be
judged against today, and unknown is not a verdict — and `oldest_due` is
re-rendered from the date mureo itself parsed rather than echoed.

### Fields

#### Root

| Field | Type | Description |
|-------|------|-------------|
| `version` | `string` | Schema version (`"2"` for multi-platform format) |
| `last_synced_at` | `string \| null` | ISO 8601 timestamp of last sync |
| `platforms` | `object \| null` | Per-platform state (v2) |
| `action_log` | `array` | Log of actions with outcome tracking |
| `batches` | `array` | Declared bulk change sets (see below). Absent until the first `mureo_batch_begin` |
| `customer_id` | `string \| null` | Legacy v1 field (kept for backward compatibility) |
| `campaigns` | `array` | Legacy v1 field (kept for backward compatibility) |

#### Campaign Snapshot

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `campaign_id` | `string` | Yes | Campaign ID |
| `campaign_name` | `string` | Yes | Campaign name |
| `status` | `string` | Yes | Current status (ENABLED, PAUSED, etc.) |
| `bidding_strategy_type` | `string` | No | Bidding strategy type |
| `bidding_details` | `object` | No | Strategy-specific details |
| `daily_budget` | `number` | No | Daily budget amount |
| `device_targeting` | `array` | No | Device bid modifiers |
| `campaign_goal` | `string` | No | Human-readable campaign goal |
| `notes` | `string` | No | Free-form notes |
| `metrics` | `object` | No | Performance numbers for the reporting dashboard (`spend`, `impressions`, `clicks`, `conversions`, `cpa`, `ctr`, `result_indicator`, `period`, `fetched_at`) |
| `ads` | `array` | No | Ad-level delivery state (see below). Absent means ad-level status was never fetched — distinct from `[]`, which means "fetched, this campaign has no ads" |

#### Ad State

Each entry in a campaign's `ads` array records one ad's delivery state, so a change made **outside** mureo (an ad paused by hand in the platform UI, stopped by its ad set/campaign, or rejected by policy) is stored as fact and can be diffed on the next `/sync-state` or `/daily-check`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ad_id` | `string` | Yes | Platform ad ID |
| `name` | `string` | No | Ad name |
| `status` | `string` | No | What the ad is **configured** as (e.g. ACTIVE, PAUSED) |
| `effective_status` | `string` | No | Whether the ad is **actually delivering**, where the platform reports it (Meta: ACTIVE / ADSET_PAUSED / CAMPAIGN_PAUSED / DISAPPROVED / ...). `status` and `effective_status` disagreeing is the signal that the ad was stopped somewhere other than on the ad itself |
| `as_of` | `string` | No — server-stamped | ISO 8601 timestamp with UTC offset at which the status was observed. Written by `mureo_state_upsert_campaign` from the **server's** clock; a caller-supplied value is ignored |

#### Action Log Entry

Each entry in `action_log` records an action taken by a workflow command, with optional fields for evidence-based outcome tracking.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `timestamp` | `string` | No — server-stamped | ISO 8601 timestamp of the action, with UTC offset. Written by `mureo_state_action_log_append` from the **server's** clock — a value supplied by the caller is ignored, so a drifted agent date is never persisted. Always present in a stored entry |
| `action` | `string` | Yes | Description of the action taken |
| `platform` | `string` | Yes | Platform the action was taken on |
| `campaign_id` | `string` | No | Campaign affected |
| `ad_id` | `string` | No | Ad affected, for ad-level actions — lets a later run tell an ad mureo stopped from one an operator stopped by hand |
| `command` | `string` | No | Slash command that initiated the action |
| `summary` | `string` | No | Human-readable summary |
| `metrics_at_action` | `object` | No | Key metrics at the time of action (e.g., `{"cpa": 5200, "conversions": 45}`) |
| `observation_due` | `string` | No | ISO 8601 date when the outcome should be evaluated (e.g., `"2026-04-15"`) |
| `batch_id` | `string` | No — server-stamped | The bulk change set this action belongs to. Stamped automatically while a batch is open (see below). You may supply it as an explicit assertion, but it is **validated**: it must name a declared batch that is still open, so membership can neither be invented nor added to a batch already closed. Absent means the action was standalone |
| `origin` | `string` | No | `"external"` when mureo only **observed** this change (imported from a platform's change feed, #545). **Absent means mureo made it** — which is every entry written before this field existed. mureo refuses to plan a rollback for an external entry: it never dispatched the change, so it never captured the prior value |
| `external_id` | `string` | No | The change feed's identity for an external change, namespaced by platform (`"google_ads\|customers/…/changeEvents/…"`). What makes re-importing the same change a no-op. Requires `origin: "external"` — setting it without one raises, because an external id on a mureo-originated entry would make the next import skip mureo's own action |
| `occurred_at` | `string` | No | When the **platform** says an external change happened, which is routinely well before mureo saw it. The one date the server does not stamp — it cannot know it — but history, never a claim about "now". `observation_due` is measured from it, so a change that has been live for three weeks is already past due rather than due in a fortnight |

An imported (`origin: "external"`) entry deliberately carries **no** `metrics_at_action`: mureo was not present when the change was made, so there is no baseline, and synthesising one from today's numbers would invent a "before" that never existed. Those entries are reviewed qualitatively. Which platforms mureo can import from — and what each feed omits — is in [`docs/change-import.md`](change-import.md).

The `metrics_at_action` and `observation_due` fields enable evidence-based outcome evaluation. When an action's observation window has passed, the agent compares current metrics against `metrics_at_action` to assess the action's impact. See `skills/_mureo-learning/SKILL.md` for the evidence-based decision framework.

#### Batch Record

Each entry in `batches` is one **declared** bulk change set (#549). A bulk pass is many tool calls and nothing in a single call says which others belong with it, so the boundary is declared with `mureo_batch_begin` / `mureo_batch_end` rather than inferred; every `action_log` entry written in between carries the batch's `batch_id`. `rollback_plan_get` then takes that id and reports the reversibility of **every** member — including the ones it cannot reverse — before anything is applied.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `batch_id` | `string` | Yes | The id stamped onto member `action_log` entries |
| `label` | `string` | Yes | What the change set is, in the operator's words |
| `started_at` | `string` | No — server-stamped | ISO 8601 timestamp with UTC offset |
| `ended_at` | `string` | No — server-stamped | When the batch was closed. **Absent means the batch is open** and still collecting; at most one may be open. Once set, membership is final — no later entry can join |

The record is kept after the batch closes rather than deleted, so a `batch_id` found in `action_log` still resolves to its label later. What can join a batch differs by platform — native non-status mutations must be recorded by the agent, and Search Console mutations are not recorded at all — see [`docs/mcp-server.md`](mcp-server.md#batch).

### Python API

```python
from pathlib import Path
from mureo.context import (
    CampaignSnapshot,
    StateDocument,
    read_state_file,
    write_state_file,
    upsert_campaign,
    get_campaign,
    parse_state,
    render_state,
)

path = Path("STATE.json")

# Read state
doc = read_state_file(path)
print(f"Version: {doc.version}, Campaigns: {len(doc.campaigns)}")

# Find a campaign
campaign = get_campaign(doc, "111222333")
if campaign:
    print(f"{campaign.campaign_name}: {campaign.status}")

# Upsert a campaign (add or update by campaign_id)
snapshot = CampaignSnapshot(
    campaign_id="111222333",
    campaign_name="Brand - Search",
    status="PAUSED",
    daily_budget=3000,
)
doc = upsert_campaign(path, snapshot)

# Parse from string / render to string
text = Path("STATE.json").read_text()
doc = parse_state(text)
json_str = render_state(doc)
```

## File Operations

Both `write_strategy_file()` and `write_state_file()` use **atomic writes** (write to temp file, then `os.replace()`). This prevents data corruption if the process is interrupted mid-write.

Parent directories are created automatically if they don't exist.

If a file doesn't exist when reading, the functions return empty/default values (empty list for STRATEGY.md, default `StateDocument` for STATE.json) rather than raising an error.

## Workflow Commands: Strategy in Action

The strategy context files are not just passive documentation -- they are actively consumed by mureo's **workflow commands** (`~/.claude/skills/`). These slash commands bridge the gap between strategy and action by reading `STRATEGY.md` and `STATE.json`, then orchestrating the appropriate MCP tools.

### How Commands Use Strategy Context

| Strategy Section | Commands That Use It |
|-----------------|---------------------|
| **Operation Mode** | `/daily-check`, `/rescue`, `/budget-rebalance` -- adapts monitoring focus and reallocation logic |
| **Persona** | `/creative-refresh` -- generates ad copy aligned with target customer profile |
| **USP** | `/creative-refresh` -- ensures ad messaging highlights differentiators |
| **Brand Voice** | `/creative-refresh` -- maintains tone consistency across ad variants |
| **Market Context** | `/competitive-scan` -- interprets auction insights against known market conditions |

### Workflow

1. Run `/onboard` to set up credentials, generate `STRATEGY.md`, and initialize `STATE.json`.
2. Use `/daily-check` for routine monitoring -- the command reads `Operation Mode` to decide which metrics to prioritize.
3. When performance degrades, `/rescue` reads the full strategy context to diagnose issues and recommend fixes that align with business goals.
4. Periodic maintenance commands (`/search-term-cleanup`, `/creative-refresh`, `/budget-rebalance`, `/competitive-scan`) each read the relevant strategy sections to make context-aware decisions.
5. Run `/sync-state` to manually refresh `STATE.json` when campaign settings change outside of mureo.

See the operational skills (`skills/daily-check/`, `skills/budget-rebalance/`, etc.) for Operation Mode behavior.

### PDCA Loop: How Strategy Evolves

STRATEGY.md is not a static document -- it evolves through the PDCA operational loop:

- **Plan**: `/onboard` creates the initial STRATEGY.md with Persona, USP, Goals, and Operation Mode.
- **Do**: Daily commands read the current Operation Mode and Goals to drive context-aware actions.
- **Check**: `/goal-review` compares current performance against the Goals defined in STRATEGY.md. `/weekly-report` summarizes what actions were taken and their measured impact.
- **Act**: When `/goal-review` detects that goals are off-track, it recommends an Operation Mode change (e.g., EFFICIENCY_STABILIZE to TURNAROUND_RESCUE). When business context shifts (new product launch, seasonal change), `/onboard` is revisited to update Goals and Market Context sections.

The key fields that change through this loop are **Operation Mode** (updated when campaign conditions trigger a transition) and **Goal "Current" values** (updated as `/goal-review` captures actual performance against targets). STATE.json evolves in parallel, with `/sync-state` and other commands keeping campaign snapshots current.

## Data Model Immutability

All data models are frozen dataclasses:

- `StrategyEntry(frozen=True)` -- context_type, title, content
- `CampaignSnapshot(frozen=True)` -- campaign state fields, with defensive deep-copy of mutable fields
- `ActionLogEntry(frozen=True)` -- action details + metrics_at_action + observation_due, with defensive deep-copy
- `PlatformState(frozen=True)` -- per-platform account_id + campaigns
- `StateDocument(frozen=True)` -- version, metadata, platforms dict, action_log tuple

To "update" a record, create a new instance. The `upsert_campaign()` and `append_action_log()` functions handle this internally.
