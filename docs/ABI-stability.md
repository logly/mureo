# Plugin ABI Stability Promise

> Status: Phase 1 (Issue #89). Audience: plugin authors who need to
> reason about whether a mureo upgrade will break their installed
> plugin.

This document is the source of truth for what mureo treats as a
**stable ABI** versus an **internal implementation detail**, and what
counts as a **breaking change** versus a **non-breaking addition**.

For the plugin authoring walkthrough, see
[plugin-authoring.md](./plugin-authoring.md).

## Table of contents

1. [The stable surface](#1-the-stable-surface)
2. [Stability promise (semver mapping)](#2-stability-promise-semver-mapping)
3. [Capability enum values](#3-capability-enum-values)
4. [Protocol method signatures](#4-protocol-method-signatures)
4b. [ChangeFeedProvider Protocol](#4b-changefeedprovider-protocol-issue-545)
5. [Model dataclass shapes](#5-model-dataclass-shapes)
6. [Entry-point group names](#6-entry-point-group-names)
7. [Provider name and skill name regexes](#7-provider-name-and-skill-name-regexes)
8. [SKILL.md frontmatter contract](#8-skillmd-frontmatter-contract)
9. [Registry behaviour](#9-registry-behaviour)
10. [Versioning policy](#10-versioning-policy)
11. [Deprecation policy](#11-deprecation-policy)
12. [Not part of the ABI](#12-not-part-of-the-abi)

---

## 1. The stable surface

The mureo plugin ABI consists of exactly the following:

| Surface | Module | Stability |
|---|---|---|
| `Capability` enum **values** | `mureo.core.providers.capabilities` | Stable |
| `BaseProvider` Protocol shape (3 attributes) | `mureo.core.providers.base` | Stable |
| Domain Protocol method signatures (`CampaignProvider`, `KeywordProvider`, `AudienceProvider`, `ExtensionProvider`) | `mureo.core.providers.{campaign,keyword,audience,extension}` | Stable (Phase 1) |
| `MCPToolProvider` Protocol shape (`mcp_tools()` + `async handle_mcp_tool()`) — the opt-in MCP-exposure secondary Protocol | `mureo.mcp.tool_provider` | Stable (Phase 1; structural / `runtime_checkable`) |
| Plugin tool-call safety semantics: mureo reads **standard MCP** `Tool.annotations.readOnlyHint` (believed verbatim either way; when the hint is ABSENT the tool NAME decides via mureo's shared read vocabulary, and a name that does not read as a read ⇒ *mutating*, conservative default) and the optional `Tool` `_meta["mureo"]` keys `reversal` / `throttle` / `observation_days` / `identity`. No new required Protocol surface — purely additive & opt-in; undeclared behaviour is unchanged from Phase 1 (audited + throttled). A mutating plugin call additionally receives *structural* strategy parity (confirm + STRATEGY-gate are skill-mediated; action_log promotion + observation window + target identity + rollback-intent are mechanical) — not mureo's platform-specific analytics. | `mureo.mcp.{server,plugin_semantics}` | Stable (Phase 2/4; additive — these meta key names are the only contract) |
| `PlatformModel` dataclass shape (`platform`, `tool_prefix`, `statement`, `evidence`), `register_platform_model` and `PlatformModelWarning` — the always-on per-platform delivery-model contribution point (#648). Rendered into the MCP server's `instructions`, scoped to platforms this server serves tools for **and which the registering provider contributed**. `Evidence` is required; registration is first-wins; `MAX_STATEMENT_CHARS` / `MAX_TOTAL_CHARS` are the documented caps and may only be **raised**, never lowered, within a major version. | `mureo.policy.platform_model` | Stable (additive) |
| `ChangeFeedProvider` Protocol shape (`platform` + `async fetch_change_events()`) — the opt-in change-import secondary Protocol (#545) | `mureo.change_import.protocol` | Stable (structural / `runtime_checkable`) |
| `ExternalChange` / `ChangeFeedResult` / `ChangeImportOutcome` dataclass shapes and the `ChangeImportStatus` / `ImportVerdict` **enum values** | `mureo.change_import.models` | Stable (additive evolution allowed) |
| Model dataclass shapes (`Campaign`, `Ad`, `Keyword`, ...) | `mureo.core.providers.models` | Stable (Phase 1; additive evolution allowed) |
| Status / Kind / MatchType / BidStrategy **enum values** | `mureo.core.providers.models` | Stable (additive evolution allowed) |
| Entry-point group names (`mureo.providers`, `mureo.skills`, `mureo.native_skills`) | `mureo.core.providers.registry` | Stable |
| `ProviderEntry` field set and order | `mureo.core.providers.registry` | Stable |
| `SkillEntry` field set | `mureo.core.skills.models` | Stable |
| SKILL.md frontmatter keys (`name`, `description`, `capabilities.required`, `capabilities.advisory_mode`) | n/a (data format) | Stable |
| Provider name regex (`^[a-z][a-z0-9_]*$`) | `mureo.core.providers.base` | Stable |
| Skill name regex (`^_?[a-z][a-z0-9_-]*$`) | `mureo.core.skills.models` | Stable |
| Module-level functions: `discover_providers`, `get_provider`, `list_providers_by_capability`, `register_provider_class`, `parse_capability`, `parse_capabilities`, `validate_provider`, `match_skills`, `providers_for_skill`, `parse_skill_md`, `discover_skills` | `mureo.core.providers`, `mureo.core.skills` | Stable signatures and semantics |

Anything not listed above is an implementation detail and may change
without notice.

---

## 2. Stability promise (semver mapping)

mureo follows [Semantic Versioning 2.0.0](https://semver.org/) on the
distribution as a whole. Within that envelope:

- **MAJOR** version bump (`1.x.y` -> `2.0.0`): the plugin ABI MAY
  change in breaking ways. The release notes will enumerate breaks.
- **MINOR** version bump (`1.2.x` -> `1.3.0`): the plugin ABI is only
  extended, never broken. New `Capability` members, new Protocols,
  new optional fields on existing dataclasses are all minor-level
  additions.
- **PATCH** version bump (`1.2.3` -> `1.2.4`): no ABI changes. Bug
  fixes and internal refactors only.

### Pre-1.0 caveat

mureo is currently `0.x` (Phase 1 lives in `0.8.x`). Per semver
clause 4, the public API for a `0.y.z` series is allowed to change.
We treat the surface listed in Section 1 as stable across
**minor** version bumps in the `0.x` series, with breaking changes
deferred to either the `0.x` -> `0.(x+1)` boundary or the eventual
`1.0` release. Plugin authors should pin to `mureo>=0.8,<1` for the
duration of the `0.x` series.

---

## 3. Capability enum values

`Capability` is a `StrEnum`. Each member is both a `str` and an
`Enum`. The **string value** is the ABI — plugins serialise these
values into SKILL.md frontmatter and into `entry.capabilities`
introspection.

| Change | Stability |
|---|---|
| Adding a new `Capability` member | **Non-breaking** (minor) |
| Removing a `Capability` member | **Breaking** (major) |
| Renaming a `Capability` value (e.g. `read_campaigns` -> `list_campaigns`) | **Breaking** (major) |
| Reordering members | Non-breaking but discouraged; do not rely on iteration order |
| Changing the underlying class from `StrEnum` to plain `Enum` | **Breaking** (major) |

Adding new members is safe because plugins use existing members as
constants — a new member does not invalidate existing references.
Skills that declare the new capability in `required` would be
classified as `unavailable` on providers that do not list it, which
is the correct downgrade behaviour.

The set of valid tokens is queryable at runtime:

```python
from mureo.core.providers import CAPABILITY_NAMES

print(sorted(CAPABILITY_NAMES))
# ['read_audiences', 'read_campaigns', 'read_extensions',
#  'read_keywords', 'read_performance', 'read_search_terms',
#  'write_audiences', 'write_bid', 'write_budget',
#  'write_campaign_status', 'write_creative', 'write_extensions',
#  'write_keywords']
```

### Style invariant

All `Capability` values are snake_case (lowercase ASCII letters plus
underscores). This is enforced at import time by an assertion in
`mureo/core/providers/capabilities.py`. New members must follow the
same style.

### Delete-via-status invariant

There are no `delete_*` capabilities. Deletion is always folded into
`write_campaign_status` / `write_keywords` / `write_audiences` /
`write_extensions` plus a `*Status.REMOVED` enum value. This rule is
permanent; introducing a `DELETE_*` member would be a breaking ABI
expansion even though additions are nominally non-breaking, because
it would invalidate the documented status-update convention.

---

## 4. Protocol method signatures

Each domain Protocol fixes a set of method names, parameter types,
default values, and return types. The Protocol is the contract; the
underlying ABI is the **structural shape** Python's runtime-checkable
mechanism inspects.

### Non-breaking changes

- **Adding a new Protocol** (e.g. a future `BidStrategyProvider`).
  Existing plugins do not implement it and continue working. New
  skills that need it gate on the relevant capability.
- **Adding an optional Capability** that gates an existing method.
  Plugins that already implement the method declare the new
  capability voluntarily.
- **Loosening parameter types** in a way that accepts strictly more
  inputs (e.g. `tuple[str, ...]` -> `Sequence[str]`). Existing
  plugins that pass tuples continue to satisfy the contract.

### Breaking changes

- **Adding a required method** to an existing Protocol. Existing
  plugins instantly fail the structural check. Compensating move:
  introduce a new Protocol instead.
- **Renaming a method** (e.g. `list_campaigns` -> `enumerate_campaigns`).
  Compensating move: keep the old method and deprecate it through
  one minor release before removal in the next major.
- **Adding a positional argument with no default**. Compensating move:
  add it as a keyword argument with a default.
- **Changing a return type** in a non-compatible way (e.g.
  `tuple[Campaign, ...]` -> `list[Campaign]`). Tuples are used
  deliberately for immutability; the inverse change would also be
  breaking for any plugin that relies on hashability.
- **Removing a method**. Compensating move: deprecate, then remove
  at the next major.

### Optional-keyword-argument additions

Adding a new keyword argument **with a default** is the gray-zone
case. It is non-breaking for:

- Plugins that **call** the method (they pass fewer arguments —
  fine).
- Plugins that **implement** the method via duck typing (their
  signature simply does not see the new kwarg — fine).

It IS breaking for plugins that implement the method via subclassing
of a base class that explicitly forwards `**kwargs`. mureo Protocols
are not subclass-based, so in practice this is a non-issue — but
plugin authors who override an explicit `**kwargs` handler should
keep an eye on Protocol changelogs.

---

## 4a. AnalyticsModule Protocol (Issue #120)

`mureo.analytics.AnalyticsModule` is a separate runtime-checkable
Protocol shipped under its own entry-point group
(`mureo.analytics`). It is opt-in: a plugin that does not implement
it remains fully supported, and skills detect the absence via
`mureo_analytics_modules_list` and report
`analytics_not_available_for_<platform>` honestly. Skills execute an
advertised capability via the `mureo_analytics_run` MCP tool (Issue #440),
which drives the Protocol methods directly — no per-plugin tool ABI.

The contract:

| Member | Stability |
|---|---|
| `platform: str` class attribute | Required; must match STATE.json platform identifier. |
| `capabilities() -> frozenset[AnalyticsCapability]` | Required. |
| `async detect_anomalies(account_id, *, window_days=7)` | Required signature; raise `NotImplementedError` when capability not advertised. |
| `async diagnose_performance(account_id, *, scope)` | Same. |
| `async audit_creative(account_id)` | Same. |
| `async analyze_budget_efficiency(account_id)` | Same. |

**`detect_delivery_collapse` is NOT on this Protocol** (#546). Adding a
fifth member would have been breaking in a way that is easy to miss:
`AnalyticsModule` is `runtime_checkable`, and `isinstance` against a
runtime-checkable Protocol requires *every* member, so every already
published four-method module would have started failing the check. The
optional extension lives in its own Protocol instead:

| Member | Stability |
|---|---|
| `mureo.analytics.DeliveryCollapseModule` | Optional extension Protocol; `runtime_checkable`. Implement it **in addition to** `AnalyticsModule`. |
| `async detect_delivery_collapse(account_id, *, history_days=60, thresholds=None, as_of=None) -> DeliveryCollapseReport` | Required signature when implemented; advertise `AnalyticsCapability.DETECT_DELIVERY_COLLAPSE`. |

The registry's structural validator is unchanged — it still requires
exactly the four `AnalyticsModule` methods — so a module that does not
implement the extension keeps registering and simply never advertises
the capability. This is the pattern to follow for any future optional
method: a sibling Protocol, never a new member on a runtime-checkable
one.

`AnalyticsCapability` is `class AnalyticsCapability(str, Enum)` (not
the 3.11-only `StrEnum`, since mureo supports 3.10). Member values
are stable strings — compare with `cap.value` or `cap == "detect_anomalies"`,
not `str(cap)` (which renders the enum repr, not the value).
`AnomalySeverity` and `PerformanceScope` follow the same convention.
Adding a new member is **non-breaking**: existing modules simply do
not advertise it; skills that need it report unavailability for those
platforms. Renaming or removing a member is breaking, same rule as
`Capability`.

`Anomaly` / `PerformanceDiagnosis` / `CreativeAudit` /
`CreativeFinding` / `BudgetEfficiency` / `DeliveryCollapseReport` live in
`mureo.analytics.models` as `@dataclass(frozen=True)`. The
delivery-collapse models (`CollapseSignal`, `DeliverySeries`,
`DailyDelivery`, `CollapseThresholds`, `CollapseSeverity`,
`BaselineMethod`) are defined once in `mureo.analysis.delivery_collapse`
and re-exported from `mureo.analytics.models` / `mureo.analytics`; import
them from either path. The field-
mutation rules in §5 apply to them identically — adding a field with
a default is non-breaking; adding one without a default is breaking.

Stable additions so far (each was added with a default, so existing
plugin code keeps constructing without changes):

- `CreativeFinding.campaign_id: str = ""` — owning campaign for the
  finding, empty when the platform's `list_ads` response omits the
  join.
- `CreativeAudit.per_campaign_summary: tuple[tuple[str, int], ...] = ()`
  — `(campaign_id, finding_count)` pairs sorted by campaign_id,
  letting workflow skills drill down without re-walking the findings
  tuple.
- `PerformanceDiagnosis.per_campaign_metrics: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = ()`
  — populated when `diagnose_performance` runs at
  `PerformanceScope.DEEP`. One entry per campaign as
  `(campaign_id, ((metric_name, value), ...))`, sorted by spend
  descending. Empty at coarser scopes.

### Row-shape TypedDicts (documentation contract)

Plugin authors can import these `TypedDict`s from
`mureo.analytics` to type their own analytics-module code against
the shapes the built-in adapters consume:

| Type | Shape source |
|---|---|
| `GoogleLivePerformanceRow` | `mureo.google_ads.mappers.map_performance_report` |
| `GoogleByodPerformanceRow` | `mureo.byod.clients.ByodGoogleAdsClient.get_performance_report` |
| `GoogleMetricsDict` | inner `row["metrics"]` of the live shape |
| `GooglePerformanceRow` | union of live + BYOD |
| `MetaLivePerformanceRow` | `MetaAdsApiClient.get_performance_report` |
| `MetaByodPerformanceRow` | `ByodMetaAdsClient.get_performance_report` |
| `MetaActionEntry` | element of live Meta `actions` list |
| `MetaPerformanceRow` | union of live + BYOD |
| `GoogleAdRow` / `MetaAdRow` | `list_ads` row, audit-relevant subset |

All are `total=False` — mureo only promises the field *set* as the
ABI, not that any given field is always present at runtime. Adding
a field to an existing TypedDict is **non-breaking**; removing or
renaming a field is **breaking**.

The four analytics methods follow the same Protocol-evolution rules
as §4: adding a new method is breaking, adding a new method
parameter as a keyword with a default is non-breaking. Adding an
entirely new analytics method is breaking unless gated by a new
`AnalyticsCapability`; the safer move is to add a new sibling
Protocol when the new surface is large.

---

## 4b. ChangeFeedProvider Protocol (Issue #545)

`mureo.change_import.ChangeFeedProvider` is a separate runtime-checkable
Protocol shipped under its own entry-point group
(`mureo.change_feeds`). It lets a bridge or plugin publish its
platform's change history so mureo can import work done outside
mureo into `action_log`. It is opt-in: a plugin that does not
implement it remains fully supported, and the importer reports
`change_import_unavailable_for_<platform>` honestly — the same
degradation contract as `analytics_not_available_for_<platform>`.

The contract:

| Member | Stability |
|---|---|
| `platform: str` class attribute | Required; the module's registry name — the `<provider>` half of `plugin:<dist>:<provider>`. A `plugin:`-prefixed value is refused. |
| `async fetch_change_events(account_id, *, since, until) -> ChangeFeedResult` | Required signature. Raising is a valid "cannot fetch"; the importer reports `error` per platform. A feed that is registered but cannot answer for a given account/mode sets `ChangeFeedResult.unavailable_reason` instead, which the importer maps to `unavailable` — returning an empty result would be reported as a checked-and-quiet window. |

### Why a new Protocol AND a new group

Two separate rules are being obeyed at once, and both matter:

- **§4** — adding a required method to an existing `runtime_checkable`
  Protocol is breaking, because `isinstance` requires *every* member.
  Folding `fetch_change_events` into `AnalyticsModule` would have
  silently de-registered every already-published four-method plugin,
  which is precisely what #546 avoided by splitting
  `DeliveryCollapseModule` out as a sibling.
- **§6** — adding a new entry-point group is non-breaking. Using one
  here (rather than a second Protocol inside `mureo.analytics`) means a
  bridge that only wants to publish a change feed does not have to stub
  four analytics methods it will never implement, and a plugin that has
  never heard of change import is unaffected in every way.

The three registries (`mureo.providers`, `mureo.analytics`,
`mureo.change_feeds`) are independent: a package may register against
any subset, and a failure in one cannot disable another.

`ExternalChange`, `ChangeFeedResult`, `ChangeImportOutcome` live in
`mureo.change_import.models` as `@dataclass(frozen=True)`; the §5
field-mutation rules apply to them identically — adding a field with a
default is non-breaking, adding one without a default is breaking.
`ChangeImportStatus` and `ImportVerdict` follow the `Capability` rule:
adding a member is non-breaking, renaming or removing one is breaking.

### `ActionLogEntry` provenance fields

`ActionLogEntry` gained `origin`, `external_id` and `occurred_at`, each
`str | None = None` and each appended after every pre-#545 field — so
positional construction by a third-party caller is unaffected, and a
STATE.json written before they existed parses unchanged and gains no
new key. `ActionLogEntry.is_external` is a **property**, not a field:
it derives from `origin`, so the dataclass field set (which is the ABI)
is unchanged by its addition.

One invariant is enforced rather than documented: `external_id` without
`origin="external"` raises `ValueError`. An external id on a
mureo-originated entry has no meaning and would poison change-import
dedup — the next import would treat mureo's own action as something it
had already imported.

---

## 5. Model dataclass shapes

Every entity / DTO in `mureo.core.providers.models` is
`@dataclass(frozen=True)`. The field set and field types are the ABI.

### Non-breaking changes

- **Adding a new field with a default value**. Existing constructor
  calls continue to work because the new field has a default.
  Example: adding `Campaign.account_currency: str | None = None`.
- **Tightening an `Optional` field to non-Optional** is breaking —
  do not do this.

### Breaking changes

- **Adding a required field** (no default). Compensating move: add
  with a default first, then deprecate the default, then remove the
  default at the next major.
- **Removing a field**. Compensating move: deprecate with a release
  cycle.
- **Renaming a field**.
- **Changing a field's type** in a non-compatible way (e.g. `str`
  -> `int`, `datetime.date` -> `datetime.datetime`, `int` -> `Decimal`).
- **Removing an enum member** (e.g. dropping
  `CampaignStatus.PAUSED`).
- **Changing the frozen=True invariant** (allowing mutation).
  Plugins may rely on dataclass instances being hashable.

### Enum members

Adding a member to a `mureo.core.providers.models` enum is
**non-breaking** (minor), for the same reason as `Capability`
(section 3): plugins use existing members as constants, and a new
member does not invalidate an existing reference. A plugin that
maps the enum exhaustively should map unknown members to its own
fallback rather than raising. Removing or renaming a member is
breaking (above).

### `BidStrategy.NOT_APPLICABLE` vs `None`

`BidStrategy` carries a `NOT_APPLICABLE` member for a platform that
does not select delivery by a bid. The two ways a
`bidding_strategy: BidStrategy | None` field can be non-committal
mean **different** things, and the distinction is part of the ABI:

| Value | Meaning |
|---|---|
| `BidStrategy.NOT_APPLICABLE` | This platform has no bid strategy. A fetched, final answer. |
| `None` | Unknown / not fetched. Says nothing about the platform. |

A provider that has no bid strategy reports `NOT_APPLICABLE` rather
than picking the closest-looking auction member; it never leaves the
field `None` to mean the same thing. `NOT_APPLICABLE` is a read-side
descriptor: adapters reject it on `CreateCampaignRequest` /
`UpdateCampaignRequest`, since it names the absence of a strategy
rather than one to set.

### Currency convention

Phase 1 money fields are `int` micros (1/1,000,000 of the account
currency). The convention is part of the ABI: if a future Phase 2
introduces a `Money(amount_minor: int, currency: str)` type, it
will land as a **new field** alongside the existing `_micros` field,
not as a type change on the existing field. The `_micros` field will
be deprecated through a documented cycle before any removal in a
later major.

### Date convention

All day-grain fields use `datetime.date`. No `datetime.datetime`,
no `int` epoch seconds, no ISO 8601 strings at the Protocol
boundary. This is permanent.

---

## 6. Entry-point group names

Four group names are part of the ABI:

| Constant | Value | Iterated by |
|---|---|---|
| `PROVIDERS_ENTRY_POINT_GROUP` | `"mureo.providers"` | `Registry.discover` |
| `SKILLS_ENTRY_POINT_GROUP` | `"mureo.skills"` | `discover_skills` |
| `NATIVE_SKILLS_ENTRY_POINT_GROUP` | `"mureo.native_skills"` | `mureo.cli.native_skills.install_native_skills` |
| `ANALYTICS_ENTRY_POINT_GROUP` | `"mureo.analytics"` | `AnalyticsRegistry.discover` |
| `CHANGE_FEED_ENTRY_POINT_GROUP` | `"mureo.change_feeds"` | `ChangeFeedRegistry.discover` |
| (literal) | `"mureo.policy_gates"` | `mureo.mcp.server._load_policy_gates` |

`PROVIDERS_…` / `SKILLS_…` / `NATIVE_SKILLS_…` are exported from
`mureo.core.providers.registry` (the first two re-exported from
`mureo.core.skills`); `ANALYTICS_…` is exported from
`mureo.analytics`; `CHANGE_FEED_…` from `mureo.change_import`. The `mureo.policy_gates` literal is documented
here (no exported constant) because policy gates are loaded by the
MCP server itself rather than by a third-party-facing registry.
Renaming any of these groups is a breaking change — every plugin's
`pyproject.toml` would have to change.

### `mureo.policy_gates` (added in v0.9.23)

Third-party packages register a `PolicyGate` implementation against
this group to participate in mureo's pre-dispatch policy chain. The
contract:

- `mureo.core.policy.PolicyGate` Protocol (`runtime_checkable`,
  single method `evaluate(tool_name, arguments) -> PolicyDecision`).
- `mureo.core.policy.PolicyDecision` frozen dataclass
  (`allowed: bool`, `reason: str = ""`).
- The MCP server consults every registered gate before dispatching
  each tool call. If any gate returns `allowed=False`, the call is
  refused and the reason surfaces verbatim to the agent. A gate
  that raises any `Exception` is treated as **abstain** (allow this
  gate; consult the next) and logged at WARNING — a broken
  third-party gate cannot take mureo offline.
- mureo MAY add fields to `PolicyDecision` over time but MUST NOT
  remove or rename existing ones. Implementations SHOULD construct
  it with keyword arguments only.
- Gate evaluation order is **unspecified**; gates MUST NOT depend
  on each other or on a particular ordering — any single deny
  blocks the call regardless of position in the chain.
- A buggy gate that returns any type other than `PolicyDecision`
  (e.g. `None`, `True`, a tuple) is treated as **abstain** + logged
  WARNING, identical to the per-call exception isolation. This
  keeps a buggy third-party gate from taking mureo offline.
- The dispatcher's refusal payload deliberately echoes the tool
  name and the gate's `reason` but **not** the `arguments` dict —
  arguments routinely contain account IDs, budget figures, or
  credentials, and the agent already has them. Do not put secrets
  in `reason`; that is the only field surfaced.
- The default behaviour with zero gates registered is byte-
  identical to v0.9.22: every call dispatches normally.
- **Lifecycle** (pinned since v0.10.47, #633): the entry point is
  enumerated and `load()`-ed **once per process**, on the first
  dispatch, and the resulting class is memoized. The *instance* is
  still constructed fresh per tool call, so instance attributes do
  not persist across calls — put cross-call state on a class
  attribute or a module-level singleton, as before. Consequence: a
  gate installed or uninstalled while the server runs takes effect
  on restart, the same as its distribution's tools (collected at
  module import) and its runtime-context factory (resolved once).
  A gate whose `load()` *raised* is not memoized — it is retried on
  the next dispatch, so a transient import error cannot silently
  remove a guardrail for the life of the process.

The groups are independent: a package may register against any subset
(provider only, analytics only, change feed only, any combination) —
the discovery paths and fault isolation are separate, so a failure in
one group cannot disable another.

If a new entry-point group is introduced (e.g. for a future
`mureo.workflows` extension), it will be **additive**. Plugins that
do not opt into the new group are unaffected.

---

## 7. Provider name and skill name regexes

Two regexes are part of the ABI:

| Identifier | Regex | Example |
|---|---|---|
| Provider `name` | `^[a-z][a-z0-9_]*$` | `google_ads`, `meta_ads`, `acme_ads` |
| Skill `name` | `^_?[a-z][a-z0-9_-]*$` | `daily-check`, `_mureo-shared` |

Tightening a regex (e.g. forbidding hyphens in skill names) is a
breaking change because existing in-tree skills already use the
permitted characters. Loosening a regex (e.g. allowing uppercase) is
non-breaking but discouraged because it weakens the stylistic
contract.

These regexes are validated:

- Provider names — at registration time (`register_provider_class`,
  entry-points discovery) via `validate_provider_name`.
- Skill names — at construction time (`SkillEntry.__post_init__`).

---

## 8. SKILL.md frontmatter contract

The SKILL.md file format is part of the ABI for any plugin shipping
skills:

| Key | Required | Type | Stability |
|---|---|---|---|
| `name` | Yes | `str` matching skill name regex | Stable |
| `description` | Yes | non-empty `str` | Stable |
| `capabilities.required` | No | `list[str]` of capability tokens | Stable |
| `capabilities.advisory_mode` | No | `list[str]` of capability tokens (must be subset of `required`) | Stable |
| any other top-level key | No | preserved in `SkillEntry.extra` | Stable behaviour: forward-compatible passthrough |

### Non-breaking changes

- Adding a new optional top-level key to the consumed set (e.g. a
  future `capabilities.optional`).
- Allowing a new capability token (driven by `Capability` enum
  evolution).
- Preserving unknown top-level keys in `SkillEntry.extra` (already
  the documented behaviour).

### Breaking changes

- Making `capabilities.required` mandatory.
- Changing the YAML parser from `yaml.safe_load` to something
  stricter (e.g. requiring `---` opening delimiter to be on byte 0
  exactly, rejecting BOM — currently the parser is lenient about a
  leading UTF-8 BOM).
- Removing the `advisory_mode` subset rule.
- Changing the bounded-input limit (currently 64 KiB per SKILL.md)
  to a value smaller than the current cap.

### Discovery limits (also part of the ABI)

| Limit | Value | Module |
|---|---|---|
| Max SKILL.md file size | 64 KiB | `mureo.core.skills.parser.MAX_SKILL_FILE_BYTES` |
| Max recursion depth per entry-point root | 4 | `mureo.core.skills.discovery._MAX_RECURSION_DEPTH` |
| Max SKILL.md files per entry-point root | 64 | `mureo.core.skills.discovery._MAX_SKILLS_PER_ENTRY_POINT` |

These limits may be **raised** in minor releases (non-breaking) but
will not be **lowered** without a deprecation cycle.

---

## 9. Registry behaviour

The following semantics are part of the ABI and will not change
without a deprecation cycle:

- **Deferred instantiation**: discovery registers the class object,
  not an instance. Plugin `__init__` does not run during discovery.
- **First-wins on duplicate names**: the earlier-registered provider
  / skill wins; the later one is dropped with a warning.
- **Per-plugin fault isolation**: a broken plugin emits a
  `RegistryWarning` / `SkillDiscoveryWarning` and is skipped; it
  does not abort discovery of other plugins.
- **Strict-mode opt-in**: setting
  `warnings.filterwarnings("error", category=RegistryWarning)` (or
  `SkillDiscoveryWarning`) converts the first malformed plugin into
  a raise.
- **Path-traversal guard on skill discovery**: symlinks that escape
  the entry-point root are skipped with a warning.
- **`ep.load()` is invoked exactly once per entry point** per
  discovery pass. A second `discover_providers()` call without
  `refresh=True` does not re-iterate `entry_points`.
- **Module-level wrapper functions delegate to a shared
  `default_registry`** singleton. The class `Registry` is exposed
  for tests / advanced use.

- **Platform models default to silence**: mureo core registers no
  `PlatformModel` of its own, and a platform with no registered model
  contributes no text to `instructions`. mureo will not start
  generating a default statement for an unregistered platform — that
  would be the guess the mechanism exists to prevent.
- **A refused `PlatformModel` raises, it is not truncated**: an
  unsourced, over-long or multi-paragraph statement raises
  `ValueError` at `register_platform_model`. Registration will not
  become lossy-but-quiet.
- **First-wins on a duplicate platform key**: the earlier
  `PlatformModel` wins; the later one is dropped with a
  `PlatformModelWarning`. Same rule, same reason, as duplicate
  provider names — this repository has one answer to "can a package
  installed later take over a slot?", and it is no.
- **A model is rendered only for tools its own provider
  contributed**: a `tool_prefix` matching a tool that some *other*
  provider (or mureo core) exposes puts nothing in `instructions`.
  Registering under another platform's key does not help; that key is
  checked against tool ownership, not taken on trust.

The thread-safety **non-property** is also documented and stable:
discovery and registration are not thread-safe. Plugin authors
should not assume otherwise.

---

## 10. Versioning policy

### Plugin author dependency pin

Pin your plugin's `mureo` dependency to the current major (or `0.x`
series before 1.0):

```toml
# In your plugin's pyproject.toml
dependencies = [
    "mureo>=0.8,<1",
]
```

This is the recommended pin for the 0.8.x series. When mureo
reaches 1.0, the pin becomes `mureo>=1,<2`.

### What changes trigger a bump?

| Change in mureo | Bump |
|---|---|
| Add new `Capability` member | minor |
| Add new optional field to existing dataclass | minor |
| Add new domain Protocol | minor |
| Raise discovery limits | minor |
| Bug fix without ABI change | patch |
| Internal refactor without ABI change | patch |
| Remove `Capability` member | major |
| Remove / rename field on existing dataclass | major |
| Rename Protocol method | major |
| Rename entry-point group | major |
| Tighten name regex | major |
| Drop Python version support (e.g. drop 3.10) | major |

### Python version policy

mureo supports Python 3.10+. Dropping a supported Python version is
a breaking change for plugin authors whose CI matrices target it,
and will only happen on a major bump.

---

## 11. Deprecation policy

When an ABI surface must be removed, we go through a documented
cycle rather than removing it in a single release.

### Standard deprecation cycle

1. **Announce** in the release notes for version `N`.
2. **Soft-warn** in code starting at version `N` — use Python's
   `warnings.warn(...)` with `DeprecationWarning`. The deprecated
   surface continues to work.
3. **Hard-warn** at version `N+1` (or later) — escalate to
   `FutureWarning` or `RegistryWarning` for visibility.
4. **Remove** no earlier than the next **major** bump after the
   announcement. The release notes for the major bump enumerate
   every removed item.

The minimum effective deprecation window is one minor release.
Where reasonable, we aim for at least two minor releases of warning
before removal.

### What if you cannot follow the cycle?

A security-critical fix may bypass the standard cycle. In that case
the release notes will explicitly call out the bypassed
deprecation, and a corresponding entry will be added to the
plugin-author migration notes for the affected version.

### Deprecation visibility for plugin authors

Run your plugin's test suite with `-W error::DeprecationWarning` to
catch deprecated mureo APIs early:

```bash
pytest -W error::DeprecationWarning
```

This converts every deprecation warning into a test failure, giving
you the maximum lead time before the eventual removal.

---

## 12. Not part of the ABI

The following are **NOT** stable and may change without notice
between minor releases. Do not depend on them from plugin code:

- **Private modules**: anything whose module path includes a
  leading underscore (e.g. `mureo.core.providers._internal_helper`
  would be private). At the time of writing, no underscored modules
  exist in `mureo.core.providers` / `mureo.core.skills`, but future
  internal helpers will follow this convention.
- **Private helper functions** in otherwise-public modules: names
  starting with `_` (e.g. `_is_provider_class`, `_warn_skip`,
  `_resolve_source`, `_scan_root`).
- **Warning message text**: `RegistryWarning` /
  `SkillDiscoveryWarning` messages embed dynamic data and may be
  reworded for clarity. The warning class identity is stable; the
  exact string is not.
- **Discovery iteration order**: `Registry.__iter__` yields
  registered entries in insertion order today, but plugin authors
  should not depend on that ordering. Use
  `list_providers_by_capability` (returns name-sorted) if you need
  determinism.
- **The 16 in-tree built-in skills**: the set of bundled skills
  ships under `mureo/_data/skills/` and may grow / shrink / be
  renamed across releases. Plugins should not depend on a specific
  built-in skill being present.
- **Adapter implementation classes**: `mureo.adapters.google_ads.adapter.GoogleAdsAdapter`
  and `mureo.adapters.meta_ads.adapter.MetaAdsAdapter` are internal
  to mureo's first-party adapters and not intended for plugin
  inheritance. The Protocol contract is the ABI; the adapter
  classes are reference implementations.
- **Built-in MCP tool surface**: the *built-in* platform tools
  (`google_ads_*`, `meta_ads_*`, ...) — their names, parameters, and
  `inputSchema` — are independent of the provider Protocol layer and
  evolve on their own schedule. (The `MCPToolProvider` *Protocol* a
  plugin implements to expose its own tools **is** part of the stable
  surface — see Section 1. A plugin's own tool names/schemas are
  authored and owned by the plugin, not by mureo.)
- **`ProviderEntry.source_distribution`** values: PEP 503
  normalization rules may evolve in upstream `importlib.metadata`.
  The field exists and is stable; treat its value as untrusted
  display data.
- **`mureo.core.skills.matcher`**'s **internal** algorithms.
  `SkillMatch` / `ProviderMatch` dataclass shapes are stable; the
  matcher's classification rules (Section 6 of plugin-authoring.md)
  are stable; everything else (sort stability, helper internals) is
  not part of the contract.

---

## Quick reference: is my change breaking?

A handy cheat sheet for mureo maintainers and curious plugin authors.

| Change | Breaking? |
|---|---|
| Add new `Capability` member | No |
| Raise `MAX_STATEMENT_CHARS` / `MAX_TOTAL_CHARS` | No |
| Lower `MAX_STATEMENT_CHARS` / `MAX_TOTAL_CHARS` | Yes |
| Add a required field to `PlatformModel` | Yes |
| Make `register_platform_model` last-wins | Yes |
| Rename `Capability` member | Yes |
| Remove `Capability` member | Yes |
| Add new Protocol | No |
| Add new Protocol in a NEW entry-point group | No |
| Add required method to existing Protocol | Yes |
| Add optional keyword arg to Protocol method (with default) | No (in practice) |
| Add positional arg to Protocol method | Yes |
| Rename Protocol method | Yes |
| Add field with default to existing dataclass | No |
| Add field without default to existing dataclass | Yes |
| Remove field from existing dataclass | Yes |
| Change field type on existing dataclass | Yes |
| Rename entry-point group | Yes |
| Add new entry-point group | No |
| Tighten name regex | Yes |
| Loosen name regex | No (but discouraged) |
| Raise discovery limits (size / depth / count) | No |
| Lower discovery limits | Yes |
| Change `yaml.safe_load` to a stricter parser | Yes |
| Drop a supported Python version | Yes |
| Rename a private helper (`_xxx`) | No |
| Reword a warning message | No |

---

## Related documentation

- [plugin-authoring.md](./plugin-authoring.md) — how to write a
  plugin that targets the ABI documented here.
- [change-import.md](./change-import.md) — the `ChangeFeedProvider`
  hook in context, plus per-platform coverage.
- [architecture.md](./architecture.md) — overall mureo architecture
  and how plugins fit into it.
- [CHANGELOG.md](../CHANGELOG.md) — version-by-version log; ABI
  changes are called out explicitly.
