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

**Where the rule is stated matters more than the refusal.** The MCP
dispatcher schema-validates before any handler runs, so an agent's refusal is
the JSON-Schema one (`'SINCE_LAUNCH_17D' is not one of [...]`) and mureo's own
message is never reached on that path. The allowed values survive it; the
reason only does if it was already in the schema the model read. So the rule
text lives in the `metrics_period` / `periods` descriptions and the raised
`ValueError` appends the same constant — one explanation, shown on whichever
path a caller takes.

**What is not guarded.** The refusal is on the targeted writer
(`set_platform_metrics`, and the MCP tool over it). A Code-mode agent writing
STATE.json directly, and every whole-document path (`write_state_file`,
imports, restores, a digest sync), are untouched — the same split the
platform-key guard draws, and for the same reason: a document that arrived
from elsewhere has no notion of which entry is new, and refusing it would
strand an operator holding state they cannot repair. For those paths the
vocabulary is documentation, not enforcement.

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

#### Day-grain history (#690)

`periods` holds exactly ONE rollup per window and every collection overwrites
it, so the value it replaces is gone. That is correct for a window — a
`YESTERDAY` rollup collected today is what "yesterday" means today — but it
leaves the document unable to answer *"was yesterday better than the day
before?"*: no day-over-day delta, no trend line.

`platforms[<platform>].daily` is the half that accumulates. Same shape and
same merge rules as `periods`, with `YYYY-MM-DD` keys instead of window
tokens:

```json
"daily": {
  "2026-08-19": {"spend": 12400.0, "impressions": 88000, "clicks": 910,
                 "conversions": 21, "fetched_at": "2026-08-20T09:05:00+09:00"},
  "2026-08-20": {"spend": 13100.0, "impressions": 91500, "clicks": 940,
                 "conversions": 19, "fetched_at": "2026-08-21T09:04:00+09:00"}
}
```

It costs no extra platform call. Every family already ships a daily delivery
report, and `daily-check`'s delivery-collapse step already pulls those rows —
step 14 of that skill folds the rows it is holding into
`mureo_state_platform_daily_set` instead of discarding them.

Optional with a `None` default, like every field added to this document since
v2: an entry that has never accumulated a day emits no key, so old files
round-trip byte-for-byte.

**Only complete past days are written.** `set_platform_daily` (and the tool
over it) refuses a key that is not `YYYY-MM-DD`, one that is not a date that
exists (`2026-02-30` matches the shape perfectly), and any date at or after
today — for the reason the collapse detector drops the current day
before comparing anything: budget pacing spreads a day's delivery unevenly,
so a part-spent day filed as a whole one is a false low, and nothing revisits
a day already in the map. The refusal happens before the file is opened, so a
rejected call leaves the document exactly as it was and the caller still
holds every figure.

**Whose today, though, is the caller's to state.** An ad account closes its
day in the ACCOUNT's timezone, and the host running the collector need not
share it: on a UTC host at 02:00 Asia/Tokyo — exactly when a nightly cron
runs — yesterday-in-Tokyo is still today in UTC, and a genuinely complete day
was being refused. Pass `as_of_date` (today, resolved in the account's
timezone) to the tool or to `set_platform_daily` and the check is measured
against that instead. Omit it and it is measured against the server's own
today, which is what every caller had before the parameter existed. The rule
itself does not move: a day at or after the anchor is still refused.

**The merge is available without the file.** A writer that must land `daily`
together with other fields in ONE atomic document write cannot go through a
path-based mutator. `mureo.context.daily.with_platform_daily(doc, platform,
account_id, days, as_of_date=None)` is the whole write minus the filesystem —
the same guards, the same per-date-key merge, the same `fetched_at` stamping
and the same retention trim — returning a new `StateDocument`;
`capped_platform_daily(daily)` is the retention rule on its own, for a writer
that has already merged its own map. `set_platform_daily` is a thin wrapper
around the first, so neither route can drift from the other.

**A missing day stays missing.** Nothing zero-fills a day that was not
collected — "not collected" and "collected, and the answer was zero" are
different facts, the same distinction the `not_collected` note exists for,
and a manufactured zero both reads as an account that stopped spending and
poisons the median the collapse detector baselines against. Readers render a
gap as a gap.

**The history is capped at 35 days on write.** 28 (`DEFAULT_BASELINE_DAYS`,
the collapse detector's trailing baseline) plus margin for an operator who
raises `delivery_collapse_baseline_days` and for the days a collector missed
— a gap is not backfilled, so 35 stored keys are not 35 calendar days. A key
mureo cannot date is kept and does not count towards the cap: the write guard
refuses one today, but one already on disk is figures somebody collected, and
a retention sweep is not the place to delete them (the same asymmetry the
non-canonical windows above get).

On the wire, each platform row carries `daily` — the most recent 7 days,
ascending, gaps intact, each bucket whitelisted through the same canonical
key list as `totals` — and `daily_delta`, the difference between the last two
days. The delta is resolved server-side because it is one rule, and it is
`null` whenever the comparison cannot honestly be made: fewer than two stored
days, or two days that are not calendar neighbours. A difference computed
across a collection gap is not a day-over-day change, and unknown is not
zero.

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

#### Why the whole workspace was not collected

`platforms[<p>].not_collected` answers *"why did THIS platform's figures not
move"*. It cannot answer *"why is there nothing here at all"* — because
`set_platform_not_collected` requires a platform key and an `account_id`, and
those are precisely what a collection that died before reaching any platform
failed to resolve. Requiring them to record that resolving them failed is
circular; writing the note onto every existing entry says something else
("Meta failed, and Google failed, and…"); and a workspace that has **never**
been collected — the case where the record matters most — has no entry to
write it onto.

So the document has its own note, at the root, with the same two fields
(#661):

```json
{
  "version": "2",
  "workspace_not_collected": {
    "attempted_at": "2026-08-18T09:00:00+09:00",
    "reason": "the workspace credentials file could not be read"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reason` | `string` | Yes | What happened, in words an operator can act on. A note with no reason is dropped on read, exactly as the per-platform one is. Truncated for display (500 characters) |
| `attempted_at` | `string` | No — server-stamped | ISO 8601 time of the failed collection, written by `set_workspace_not_collected` / `mureo_state_workspace_not_collected_set` |

**It is not the per-platform note repeated, and must never be rendered as
one.** "This workspace could not be collected" and "this workspace's Meta
failed" are different facts calling for different actions, so they are
separate fields, written by separate calls, and put on the wire under
separate keys (`workspace_not_collected` beside the document's
`last_synced_at`; `not_collected` inside each platform row). Setting or
clearing one never touches the other.

**Writable with nothing collected.** The absence of figures is the thing
being reported, so `set_workspace_not_collected(path, reason=...)` takes no
platform key and no account id, creates no platform entry, and works on a
STATE.json that does not exist yet.

**Retired by evidence, not by discipline** — #638's rule, one level up. The
note is not shown once **any** rollup **anywhere in the document** carries a
`fetched_at` later than its `attempted_at`: the note is about the workspace,
so any platform being reached is proof the collection ran. The same three
limits apply — any window counts, no collection time means no retirement, and
an unparseable `fetched_at` (or a note with no `attempted_at`) leaves the
question open, and open is not retired. Clearing it is still the collector's
job (call the same writer with `reason=None` on the next success), but
nothing an operator sees depends on that being remembered.

Recording it is **not** a sync, so `last_synced_at` is not re-stamped —
same reason as one field over.

It rides on `/api/reports/summary` as `workspace_not_collected` (whitelisted
to the two keys, truncated, `null` when there is none). Drawing it is the
triage layer's job (#651) and is not wired into the page yet; the reader had
to exist first.

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

#### How the layer is shown

Everything below is display only. None of it changes which clients the layer
counts: the heading, the "clients needing attention" cell and the marked
cards all read one list, and that list is over every finding.

- **One row per kind, not per client.** A 27-client install rendered sixteen
  rows, six of them the same sentence about the same unresolvable platform
  key under six different names. Rows now group by finding and name the
  clients they cover; the per-client sentences are in the row's disclosure,
  with what to run underneath them.
- **The list opens short.** Four rows, then *Show all (N more)*. Showing
  "the top four" is only defensible because the ranking is stated in code —
  they are the four mureo can do most about, not the four that rendered
  first. It opens short again every time you arrive.
- **A row is one line.** The sentence is clipped to it (the full text is on
  the row's `title`, and every item's full text is one click away).
- **A message can be closed, and closing it resolves nothing.** Expand a row
  and every message on it carries its own ✕; the row's ✕ is the same thing
  applied to all of them. Closing one shrinks the row — its count and the
  clients it names — and the row goes when its last message does. While
  anything is hidden the panel says how many MESSAGES (counting rows would
  report "1" for six findings nobody can see), says in words that the
  conditions are still true and still counted, and offers *Show them again*.
  A dismissal is keyed to a fingerprint of what that message SAID — the age
  of a stale figure in days, the reason a collection gave, the keys in a
  conflict, the client it belongs to — so a message whose content has changed
  is a different message and comes back on its own. It is stored in
  `localStorage`, capped, and a browser that cannot read it hides nothing.

The client cards below carry the same findings as short **badges** — "Figures
29 days old", "Double-counted" — and no longer repeat the sentences or the
repair command. A card that withholds a client's totals still prints `—`, and
the badge next to it is what stops that dash reading as zero; the explanation
is in the alert row directly above the grid, and the remedy is on the
client's own detail view, where the per-platform conflict note has always
named it.

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

#### Reading the roster at a glance

Above the alerts the index states the roster's own figures — total spend,
total conversions, the cost per conversion, and how many clients need
attention — and beside the grid, where that spend went by platform.

Every one of those is a sum over other clients' numbers, which is the
easiest place in the product to hide one mureo cannot vouch for: a client
whose totals are withheld would contribute a silent zero and nothing on
screen would say so. So a cross-client figure is never just a number.

- It is summed **only** over the clients whose totals mureo is willing to
  state at all, using the same decision the cards use
  (`aggregateClientKpis` in `reports_logic.js`) — not a second opinion about
  the same payload.
- It carries **how many clients that was**, whenever that is not all of
  them: *"stated over 24 of 27 clients"*.
- When no client stated it, the cell reads `—` with the reason under it,
  never `0`.
- The cost per conversion is taken from the clients that stated **both**
  figures. Spend from one set of clients over conversions from another is
  not a cost per anything.

The spend-by-platform bars follow the same rule, on a card and across the
roster: a client whose totals are withheld contributes no slice, because
drawing the shares of figures the card refuses to print is the same claim in
a shape that looks like a picture. A platform's colour is chosen from its
key, so one platform is one colour on every card — the bars are ranked by
spend, and a colour that followed the ranking would change from card to
card.

The grid can also be filtered to *needs attention* / *watch* / *nothing
raised*. That verdict is the triage layer's own findings and not a fourth
judgement: the two withholding findings (ranks 1–2 above) make a client
*needs attention*, the rest make it *watch*, and a client that raised
nothing is *nothing raised* — which says only that mureo has nothing to
raise about the state of its data, never that the account is performing
well. Cards are hidden by the filter, never removed, so your own card order
survives it.

#### The per-client report

A report summary is `{totals, flags, narrative}`, and the detail view now
renders each as what it is: the headline figures as figures, the flags as
chips, the narrative as prose. Only the canonical metric vocabulary and only
real numbers are rendered as figures — everything a report states outside
that (a formatted string, a per-platform breakdown, a metric mureo has no
label for) is *not* re-presented as a headline number it may not be.

It is still shown. Directly below the figure row, and shaped nothing like
it, is what this particular report stated: `cvr 0.21%`, `goal target CPA
30000`, `google ads · spend ¥773,957` — the key humanized, the value printed
**exactly as written**. mureo does not know that metric's unit, whether it
is a ratio or what currency it is in, so it adds no separator, no symbol and
no percentage heuristic: a figure re-derived by a view that does not know
what it holds is a different number from the one the report wrote. A field
with no flat rendering — a deeper tree, a list — is counted (`+2 more fields
in the report`; the count is of fields, so a fifty-element list counts once)
rather than dropped, because content that is accepted on write and then
silently invisible is the failure this row exists to end.

Both spellings are read here. `totals` wins the headline row where a report
carries `totals` *and* `kpis`, and a key that lives only on the losing block
would otherwise be stored, refused by nothing and rendered nowhere — the
same failure one level down. A key both blocks carry is shown once, with the
winning block's value: printing two numbers under one name would state a
disagreement the report never wrote.

A report that stated no structure at all renders exactly as it did before:
reports already on disk are real content, and they stay readable as the
prose they are rather than being reformatted by guesswork.

Rendering the structure only helps if there is one, and for a long time
there was not: `mureo_state_report_set` documented the three fields and
checked none of them, so a report that folded everything into the paragraph
looked, to the writer, exactly like one that did not. `narrative` is
therefore bounded — 400 characters, which is what a verdict and a proposal
need once the figures are in `totals` and each finding is its own flag — and
over the bound the write is **refused, not truncated**: a sentence cut in
half reads like a bug in mureo, and nobody can tell what was removed. A
canonical metric carrying a string (`"¥773,957"`) is refused for the same
reason it was worth catching at all: it sits where the view reads a figure
and renders as nothing.

What is *not* refused is a key outside the vocabulary. A totals block also
carries a CVR, a per-goal target, a per-platform split — refusing those
would send exactly that content back into the paragraph the bound exists to
empty, so they are stored, shown in the row above as the report's own words,
and never stated as one of mureo's headline figures. The
rule is stated once (`mureo/core/report_summary.py`), pasted into the tool
description an agent reads before it composes the report, and repeated in
the refusal — the same shape #659 settled on for the metrics windows, minus
the `enum` that prose cannot have.

**What is not guarded.** The refusal is on the targeted writer
(`set_report`, and the MCP tool over it). A Code-mode agent writing STATE.json
directly with `Write`, and every whole-document path (`write_state_file`, an
import, a restore), never reach `validate_report_summary` — the same split the
metrics-window vocabulary draws above, and for the same reason: a document
that arrived from elsewhere has no notion of which report is new, and refusing
it would strand an operator holding state they cannot repair. So the skills
route this write through `mureo_state_report_set` on every host, including
Code — no hand-written alternative is offered for `reports`, and the Code
`Write` path documented for the bulk snapshot does not describe the section.
For anything that does hand-write it, the structure is documentation rather
than enforcement.

The bound applies to new writes only. A paragraph already in STATE.json is
read, rendered and preserved exactly as it is, including when a later run
writes a sibling report kind.

**Which kinds exist.** One per skill that writes a report: `daily`
(daily-check), `weekly` (weekly-report), `monthly` (monthly-report), `goal`
(goal-review), `audience` (audience-review), `experiment`, `fatigue`
(ad-fatigue-check), `pacing` (budget-pacing) and `tracking`
(tracking-health). `mureo_state_report_set` refuses anything else, at the
schema layer, before a handler runs — so the list is not advice. It was
three for a while and nine skills instructed nine kinds (#671), which meant
six shipped skills told an agent to do something the tool refused; the
vocabulary now lives in one place (`mureo/core/report_kinds.py`) and the
enum, the tool description and the dashboard's pick are all generated from
or pinned to it.

The "Latest report" block shows the **most recently generated** of them, not
a fixed favourite. A daily check runs every day, so a `daily`-first
preference would have hidden every other kind the moment more than one could
be written — a kind that can be written and never seen is the same failure
as one the schema refuses, from the other side. A report already on disk
that carries no `generated_at` still ranks (below the dated ones), and a key
outside the vocabulary is preserved and read back verbatim; it simply does
not compete for that block.

#### The display contract (#706)

The report summary above is written for whoever reads *that report*. The
`display` section is written for the **screen**, and it is a different
thing on purpose.

STATE.json is the agent's working memory — prose-heavy by design, because
the next AI decision needs the reasoning. The dashboard had been rendering
that memory directly, and what an operator got (measured on two live
clients, 2026-08-26) was walls of jargon, thirty-row value dumps with whole
sentences sitting in numeric columns, and work-journal action logs showing
raw `**` markdown on screen. A dashboard is numbers and charts first; any
text on it has to be short, partial and instantly readable.

So the two audiences are separated. The agent's prose keeps every home it
already has, and **the dashboard reads only this contract** — one small,
strictly structured, write-guarded surface per client.

| Field | Shape | Bound |
|-------|-------|-------|
| `nav_message` | One operator-facing line (運用ナビ) | ≤80 characters |
| `highlights` | `[{tone, text}]`, tone `good` / `watch` / `bad` | ≤3 items, text ≤60 |
| `proposals` | `[{title, body, status, date}]`, status `proposed` / `done` | title ≤30, body ≤80, date ≤12 |
| `breakdown.campaigns` / `.adgroups` | `[{name, spend, mcpa, target_cpa, state, note}]`, `state` from a closed set (`target_met` / `improving` / `watch` / `worsening` / `no_data`) | note ≤40 |
| `stated_values` | `[{label, value}]` | label ≤24, **value a raw number or a string ≤12** |
| `source` | the skill that wrote this screen | ≤24, **required** alongside any section |
| `generated_at` | when it was written | server-stamped (#460) |

Every bound **refuses** the write; nothing is truncated. That is #662's
rule applied to a second surface, and for the same reason: a sentence cut
in half reads like a bug in mureo, and the operator cannot tell what was
removed. The writer is holding the content at the moment of refusal and can
shorten it — nobody downstream ever can. The three closed vocabularies are
refused for #659's reason: each is rendered as a chip or a colour, so a
value no view knows is a value no view draws.

`stated_values` is where the reported defect lives in miniature. It is a
chip row — a caption and a figure — and whole sentences were arriving in
it. A value is therefore a real number, or a string short enough to still
*be* a value (`"3 of 7"`, `"¥12,400"`, `"未設定"`). A short string is
allowed rather than refused because a report legitimately states things a
number cannot carry, and refusing those would push exactly that content
back into the prose this contract exists to empty. A sentence is refused.

**What is deliberately NOT in the contract.** The KPI funnel (spend →
impressions → clicks → conversions, with CPM / CPC / CPA) and the daily
chart. Both are computed from the canonical totals and `PlatformState.daily`
(#690), per selected platform — so no agent writes them, and no agent can
state them wrongly.

**One write, one moment.** `mureo_state_display_set` replaces the whole
section with exactly what the call states; an omitted section is written as
absent, never inherited. Unlike `reports`, whose unit is a report *kind*
written by one skill about one question, these five sections describe one
client at one moment off one set of figures. Merging them per section would
put last week's highlights beside today's nav line with nothing on screen
able to say they came from different runs. A call that states nothing
clears the contract, and the key leaves the document entirely rather than
lingering as an empty one a reader could render.

**One writer per run, and it owns the whole screen.** The contract is
written by exactly one skill per run — the one producing that run's report —
and that skill states every section it wants shown. Two skills writing
different sections in the same run is outside the design: the second call
replaces the first rather than merging into it, so what survives is whatever
ran last. There is no partial-update entry point on purpose, because any
merge policy re-creates the mixed-moment screen the whole-section
replacement exists to prevent. Two writers compose their sections *before*
calling, never by calling twice.

**Across runs, though, there is always a second writer.** A day has a
morning weekly-report and an evening daily-check, and the evening one
overwrites the morning's screen. Keeping that (rather than merging) is the
same decision for the same reason — but it is not free, so the second writer
carries one duty, stated in `DISPLAY_OVERWRITE_RULE` and pasted into every
skill that writes a contract: **read the current `display` first, and carry
over the other skill's `proposals` that are still live** — not yet done, and
not contradicted by what this run just found. Nothing else travels. A
`nav_message`, a `highlights` chip, a `breakdown` row or a `stated_values`
chip is a reading of the figures in front of whoever wrote it, and copying
one forward would put that judgement on screen under an author who never
made it — the same reason #545 refuses to plan a rollback for a change mureo
only observed. `proposals` is the exception because a recommendation is a
standing commitment rather than a reading of one moment: it stays true until
it is done or withdrawn.

**The screen says who drew it.** `source` (the skill's own name, ≤24 chars)
is **required** alongside any section, and `generated_at` is stamped
server-side — the #460 rule every other timestamp in this document follows,
because the age of a screen is exactly what tells an operator whether to
believe it. Together they are what last-writer-wins costs, paid back: a card
whose weekly proposals were replaced by the evening's run still says who
last spoke and when. A call that states no section clears the screen and
needs neither — there is no document left to attribute, and an attributed
blank would be worse than none.

**Chip tone comes from the severity the finding already has**, so one
finding is not amber on one client's card and red on another's: `action →
bad`, `watch → watch`, `positive → good`. `info` deliberately does **not**
become a highlight — there are at most three chips, a neutral note would
spend one an action or a win needed, and the note is still in the report for
whoever wants it.

**Strict on write, tolerant on read.** Every bound and vocabulary here is a
*write* rule. A value already on disk — hand-edited, or written by an
outside tool — is read back exactly as it is, because refusing it would
only delete content an operator has. The same asymmetry the metrics-window
vocabulary draws above. Only an entry with no shape at all is dropped on
read: a highlight with no text, a breakdown row with no name, a stated
value with no label.

**The action log gets a line of its own.** An `action_log` entry may carry
`display_title` (≤40) and `display_summary` (≤120) — the one line the
dashboard shows for it, bounded by `mureo_state_action_log_append` under the
same refuse-never-truncate rule. They *add* a rendering and replace nothing:
`summary` is still written as fully as the next agent needs, and is still
what the drill-down shows. An entry without them is every entry written
before they existed.

The bounds are stated once (`mureo/core/display_contract.py`), pasted into
the tool descriptions an agent reads before it composes anything, and
repeated in every refusal — the shape #659 settled on, now with the `enum`s
and `maxLength`s that this surface, unlike prose, can actually have.

**Who writes it.** The same nine skills that write a report: `daily-check`,
`weekly-report`, `monthly-report`, `goal-review`, `audience-review`,
`experiment`, `ad-fatigue-check`, `budget-pacing` and `tracking-health`.
Each has a *Persist the display contract* step immediately after its report
step, so the screen is rendered from the same figures in the same pass —
and each states, in as many words, that it **reaches no new verdict there**.
A skill that re-decided a campaign's state while writing the screen would
put two answers in one document, and the dashboard would show whichever one
was written second.

The same paragraph is what the skills carry: `DISPLAY_CONTRACT_RULE` is
pasted into each of them verbatim rather than paraphrased, so the sentence
an agent reads while composing and the sentence it gets back on a refusal
cannot drift apart. And because a refusal is what an agent meets, the
skills name the recovery too: **shorten and rewrite** — lead with the point,
drop the connectives — rather than re-sending the same sentence trimmed by a
character, which spends a run's context on a bound one rewrite would have
met. `skills/_mureo-strategy/SKILL.md` → *Display contract section* carries
the schema itself, once, for all nine.

#### What mureo did today

Beside the grid, the index lists the actions mureo logged **today** across
the whole roster — newest first, the client, the time, one sentence. It is
built from the `recent_actions` every client's summary already carries, so
it costs no extra request, and it is capped (6 rows) with the rest counted:
a rail is a glance at the day, not the log.

**The day is the server's.** An action-log `timestamp` is stamped
server-side from `server_now` — the host's local wall clock, offset and all
— so a browser deciding "today" from its own clock would draw the boundary
in its own timezone, and an operator in London reading a Tokyo host would
see nine hours of yesterday's work listed as today's. The summary therefore
states

```json
"server_today": "2026-08-20"
```

— present **only** under the client-registry seam, like `observations_due`,
so a single-workspace summary keeps the exact keys it had before. The
browser compares the first ten characters of a timestamp against it: two
strings out of one clock, and no timezone arithmetic anywhere. If the date
is absent or malformed the feed is empty rather than dated by the browser —
a feed headed "today" that lists yesterday is worse than no feed.

**Each row is the entry's own display line** (#706 step 3-b). A row with a
`display_title` shows that and stops — it was written for a row exactly like
this one, under bounds that make it fit — and a row that predates the
contract shows its work-journal `summary` with the markdown emphasis removed
and cut at 120 characters, which is the same helper the detail view uses
rather than a second copy of the rule. The whole line is on the row's
`title`, and nothing stored is altered by either.

On a **roster** (two clients or more) a day with nothing logged keeps the
panel and says so in one line; below that there is no panel at all, the same
default silence the alert layer keeps. The asymmetry is deliberate: on a
roster the rail is where an operator looks to see mureo working, and an
absent panel and a quiet day are indistinguishable from each other.

A row is **clamped to two lines**, with the whole sentence on its `title`. A
real action-log `summary` runs to several hundred characters, and one of them
is enough to turn the rail back into the wall of prose this redesign exists
to end. Nothing is altered by the clamp — the string is unchanged, it is
complete on the attribute, and the action log is rendered in full on the
client's own detail view. mureo's rule about never truncating silently is
about a stored VALUE it would be changing; how many lines of an unchanged
string a 340px rail shows is a display decision, and the alert rows above
make the same one at one line.

#### The detail screen a contract draws (#706)

A client that has a display contract gets a different detail view, and the
order down the page is the argument — a dashboard is numbers and charts
first, and any text on it has to be short, partial and instantly readable:

1. the **運用ナビ band** — `display.nav_message`, the one line to act on
   today, with the skill that wrote the screen and how long ago beside it.
   The contract is replaced whole by whoever writes it last, so that
   attribution is the one question the content cannot answer about itself;
2. the **KPI funnel** — spend → impressions → clicks → conversions, each
   carrying the rate it implies (CPM, CPC, CPA);
3. the **daily chart**, with a metric switch and a 日/週/月 granularity
   switch, beside the **proposals** panel (`display.proposals`: the open ones
   as cards, plus how many have been carried out this month and in total);
4. the **campaign** and **ad group** breakdown tables from
   `display.breakdown`, each row carrying the four-state badge;
5. `display.stated_values` as a **chip row**, and `display.highlights` as
   tone-coloured chips;
6. the **action log**, one short line per entry;
7. the agent's narrative, behind an *Open the report text* disclosure.

**The funnel and the chart are derived, not written.** That is exactly why
they are not in the contract: they come from the canonical totals and
`platforms[<p>].daily` (#690), so no agent writes them and no agent can state
them wrongly. A step the totals do not carry renders as an em dash — never as
a zero, which would be a measurement nobody made. Both follow the platform
selector, and it selects ONE platform rather than summing: two platforms'
impressions do not add up to anything an operator asked for, and their CPAs
cannot be added at all.

**A week or a month is a sum of stored days, and says when it is partial.**
#690 refused to zero-fill a day nobody collected; summing days into a week
would smuggle that zero back one level up, so every bucket carries how many
of its days it actually holds, an incomplete one is drawn hollow, and a note
under the chart says how many. A gap between collected days is a break in the
line, never a segment across it.

**Every section hides itself when it has nothing** — frame and all. On this
screen that is the common case rather than the edge one: a client whose last
run wrote only a nav line shows exactly that band and nothing else.

**A client with no contract is unchanged.** It still gets the three-tier
screen described above, and that is a supported path rather than a fallback:
it is every client on every install until a skill writes a contract.

**The colours are tokens, and the semantic vocabulary is unchanged.** The
screen is built on a `--report-blue` family added *beside* `--accent` rather
than over it (that indigo is what every control on every other screen uses),
defined for both themes. The blue is ACCENT and INFORMATION and does not join
the status vocabulary: red still means "act now" and nothing else, which is
why a `worsening` breakdown row is amber rather than red, and why a spend
movement is blue — a rise in spend is neither good nor bad without a target
nobody has put on the wire.

The **action log** is shortened on both screens, because the shape is a
property of the ENTRY rather than of the client. A row with a `display_title`
/ `display_summary` shows those and stops — the stored `summary` is the work
journal and stays in the drill-down. A row without one shows its `summary`
with the markdown emphasis removed (`**bold**` reaching a person as asterisks
was the reported defect) and cut at 120 characters, with *Read more* offering
the rest. Nothing stored is altered by either.

#### The list screen a roster gets (#706 step 3-b)

Above the portfolio strip, a roster of **two clients or more** now opens with
a dark band that answers one question before anything is clicked: how many of
these are fine, and how many are not. Everything on it is a **count of
clients** — the day, the fraction of the roster that raised nothing, and four
blocks — because the money is already on the strip below it, where every
figure states how many clients it was summed over.

**The band grades nothing.** The health of a client has exactly one answer in
this product, `reports_triage.js`'s, and the band is handed that layer's own
counts (`triageHealthCounts`) and its own per-client verdict
(`triageClientHealth`) — the same two the cards, the roster rows and the
filter chips are painted from. A band that counted for itself would be a
fourth opinion: green on the band, red on the card, and an operator with no
way to tell which is true.

**The fourth block is not a health verdict.** The triage vocabulary has three
states — needs attention, watch, nothing raised — and the fourth block is the
client mureo is **not running yet**: no figure at all in its summary
(`aggregateClientKpis(...).hasFigures`, the same answer the cards use to
decide whether to print a number). It is carved out of the "nothing raised"
bucket and out of nothing else, so a client the triage layer marked keeps its
mark whatever its figures look like, and the four blocks always add up to the
roster. It is grey, because "no verdict" is exactly what mureo has for it. A
client whose totals are *withheld* — stale, double-counted — is not idle: it
has figures and mureo is refusing to state them, which is already an alert.

**A single client keeps the index it had.** With one card, "which of these do
I open first?" is not a question, so no band is drawn — the same rule the
filter chips and the roster table already follow.

The band is painted from `--report-blue` and `--report-on-blue` — the same
two tokens the detail screen's 運用ナビ banner is painted from, referenced
rather than restated. A mureo band is one colour in this product, so a
recolour moves both screens or neither, in both themes. Nothing on the band
is dimmed — white on this blue is 4.9:1, which clears AA with nothing above
it, so an opacity-softened caption would fail — and the hierarchy is carried
by the type scale instead.

Each block is a **white card**, not a coloured one. Filling a block with its
meaning colour put it within 1.2:1 of the blue, which is how a green and a
red end up equally invisible; the card surface is the thing that stands out
on this band. The meaning is the COUNT and a bar down the leading edge, in
the same vocabulary the cards use (`--report-band-*`), at 5.9–8.1:1 as text
— and `idle` is neutral grey because "no verdict" is not one of the three.
Every block carries its word as well as its colour, and none of them is
faded at zero: a partition an operator cannot see all of is not one.

The report screens themselves sit on a **ground** — `--report-surface`, with
`--report-line` / `--report-line-strong` for the panel edges — applied to the
container that holds the list AND the detail, so the two screens cannot drift
apart. White panels stand off it with one step of edge and the shallowest
shadow in the system; table header rows take the ground colour.

#### The shape of the page

The dashboard's frame is one width for every left-nav item, and it is the
width the widest screen needs: at the old 1180px the Reports card column
fitted two cards abreast, so a 27-client roster was fourteen rows of
scrolling. It is `min(1680px, 96vw)` now — three cards abreast at 1440px and
four at 1920px — and the content follows it: lists, rows and tables take the
width they are given. The exceptions are the two things that stretching
actually breaks. A single-line field is not better at 1600px, so the fields
flow side by side instead, as many across as fit — the freed space is used
rather than left empty beside a narrow column. And a table whose two columns
exist to ASSOCIATE a name with a value (About's package/version list) keeps
the width its content needs: stretched, "mureo" and "0.12.0" end up half a
metre apart and the table stops doing the only thing it is for. The test is
whether stretching breaks the association, not whether the table is small —
BYOD's platform / mode / detail table keeps the full width.

The index itself is two columns above 960px: the alerts and the client grid
they triage in the main column, and — in a 340px rail beside it — what mureo
did today, then where the roster's money went. Below 960px it stacks. Stacking every section full width at every
width was two screens of scrolling before the operator had read anything,
which is what the rail, the grouped alert rows, the collapsed list and the
slimmer cards are all for.

`tests/js/reports_index_height.test.js` keeps that from creeping back: it is
arithmetic over the box metrics `app.css` declares — not a browser
measurement, and it says so — and it fails if the modelled index at ten
clients grows past its budget.

#### Getting back to the list

**Reports** in the left menu always opens the client list, whatever you had
open before. Everything else that redraws the section — switching the
period, a status refresh, archiving a client — leaves you where you are,
because a redraw that ejected you from the report you were reading would be
the same bug pointing the other way. A single-workspace install has no list,
so it opens its one client's report either way.

### Fields

#### Root

| Field | Type | Description |
|-------|------|-------------|
| `version` | `string` | Schema version (`"2"` for multi-platform format) |
| `last_synced_at` | `string \| null` | ISO 8601 timestamp of last sync |
| `platforms` | `object \| null` | Per-platform state (v2) |
| `action_log` | `array` | Log of actions with outcome tracking |
| `workspace_not_collected` | `object \| null` | Why the whole workspace could not be collected (see above). Absent until such a failure is recorded |
| `batches` | `array` | Declared bulk change sets (see below). Absent until the first `mureo_batch_begin` |
| `display` | `object \| null` | The write-guarded surface the dashboard renders (see [The display contract](#the-display-contract-706)). Absent until one is written, and absent again once it is cleared |
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
| `display_title` | `string` | No | What this action was, in a few words an operator reads on a dashboard row (≤40 characters). Over the bound the append is **refused**, never truncated |
| `display_summary` | `string` | No | One plain-text sentence under the title (≤120 characters) — no markdown, since `**bold**` is shown to a person as asterisks. It *adds* a rendering: `summary` is still written as fully as the next agent needs, and is what the drill-down shows |
| `occurred_at` | `string` | No | When the **platform** says an external change happened, which is routinely well before mureo saw it. The one date the server does not stamp — it cannot know it — but history, never a claim about "now". `observation_due` is measured from it, so a change that has been live for three weeks is already past due rather than due in a fortnight |

An imported (`origin: "external"`) entry deliberately carries **no** `metrics_at_action`: mureo was not present when the change was made, so there is no baseline, and synthesising one from today's numbers would invent a "before" that never existed. Those entries are reviewed qualitatively. Which platforms mureo can import from — and what each feed omits — is in [`docs/change-import.md`](change-import.md).

The `metrics_at_action` and `observation_due` fields enable evidence-based outcome evaluation. When an action's observation window has passed, the agent compares current metrics against `metrics_at_action` to assess the action's impact. See `skills/_mureo-learning/SKILL.md` for the evidence-based decision framework.

#### Display Contract

The `display` object is what the dashboard renders for this client (#706) —
see [The display contract](#the-display-contract-706) for why it is separate
from `reports` and what is deliberately kept out of it. Every field is
optional, every section is emitted only when it states something, and every
bound below **refuses** an over-long write rather than truncating it.

| Field | Type | Description |
|-------|------|-------------|
| `nav_message` | `string` | The one operator-facing line at the top of the report (運用ナビ), ≤80 characters |
| `highlights` | `array` | ≤3 chips of `{tone, text}` — `tone` is `good` / `watch` / `bad`, `text` ≤60 characters |
| `proposals` | `array` | `{title ≤30, body ≤80, status, date ≤12}`; `status` is `proposed` or `done`, and only `title` is required. `date` should **prefer** `YYYY-MM-DD` — free text like `"last week"` is allowed, but keep one spelling within a client, since two in one list read as two different kinds of fact. mureo enforces the length and no format: it displays the value and never parses it |
| `breakdown` | `object` | Two tables, `campaigns` and `adgroups`, each an array of `{name, spend, mcpa, target_cpa, state, note ≤40}`. The three figures are raw numbers and a figure a row does not have is **omitted**, never written as `0` — a row with no conversions has no `mcpa`, and `0` would state a perfect CPA rather than the absence of one. `state` is one of `target_met` / `improving` / `watch` / `worsening` / `no_data` |
| `stated_values` | `array` | `{label ≤24, value}` chips. The value is a raw number or a string of ≤12 characters; prose is refused, because it lands in a numeric column |
| `source` | `string` | Which skill wrote this screen (≤24 characters). **Required** alongside any section: the contract is replaced whole by whoever writes it last, so without it a card cannot say whose answer it is showing |
| `generated_at` | `string` | When it was written, stamped **server-side** (#460) — never taken from the caller, because the age of a screen is what tells an operator whether to believe it |

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
