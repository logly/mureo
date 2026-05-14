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
| Model dataclass shapes (`Campaign`, `Ad`, `Keyword`, ...) | `mureo.core.providers.models` | Stable (Phase 1; additive evolution allowed) |
| Status / Kind / MatchType / BidStrategy **enum values** | `mureo.core.providers.models` | Stable |
| Entry-point group names (`mureo.providers`, `mureo.skills`) | `mureo.core.providers.registry` | Stable |
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

Two group names are part of the ABI:

| Constant | Value | Iterated by |
|---|---|---|
| `PROVIDERS_ENTRY_POINT_GROUP` | `"mureo.providers"` | `Registry.discover` |
| `SKILLS_ENTRY_POINT_GROUP` | `"mureo.skills"` | `discover_skills` |

Both names are exported from `mureo.core.providers.registry` (and
re-exported from `mureo.core.skills`). Renaming either group is a
breaking change — every plugin's `pyproject.toml` would have to
change.

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
- **MCP tool surface**: the MCP server's tool list and parameters
  are independent of the provider Protocol layer. They evolve on
  their own schedule.
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
| Rename `Capability` member | Yes |
| Remove `Capability` member | Yes |
| Add new Protocol | No |
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
- [architecture.md](./architecture.md) — overall mureo architecture
  and how plugins fit into it.
- [CHANGELOG.md](../CHANGELOG.md) — version-by-version log; ABI
  changes are called out explicitly.
