# Plugin Authoring Guide

> Status: Phase 1 (Issue #89). Audience: third-party developers shipping
> a pip-installable plugin that adds a new ad-platform provider (and
> optionally skills) to mureo.

mureo's provider abstraction lets any pip-installable package extend
mureo with new ad platforms (e.g. Microsoft/Bing Ads, Apple Search Ads,
TikTok Ads, LinkedIn Ads, X Ads, in-house platforms) without touching
mureo's source tree. This guide walks through the plugin contract,
shows a minimal working example, and documents the distribution
patterns we support.

For the ABI stability contract that governs which changes are breaking
and which are not, see [ABI-stability.md](./ABI-stability.md).

## Table of contents

1. [Introduction](#1-introduction)
2. [Quick start: a minimal plugin](#2-quick-start-a-minimal-plugin)
3. [Provider Protocols](#3-provider-protocols)
4. [Capabilities](#4-capabilities)
5. [Models: frozen dataclasses and enums](#5-models-frozen-dataclasses-and-enums)
6. [Skill matching](#6-skill-matching)
7. [Distribution patterns](#7-distribution-patterns)
8. [Entry-points registration](#8-entry-points-registration)
9. [Shipping skills with your plugin](#9-shipping-skills-with-your-plugin)
10. [Security considerations](#10-security-considerations)
11. [End-to-end example](#11-end-to-end-example)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Introduction

### Architecture in one paragraph

mureo's provider layer is split into three concentric ABIs:

1. **Capabilities** — a `StrEnum` of 13 stable identifiers
   (`read_campaigns`, `write_budget`, ...). Capabilities are the
   currency that skills declare they need and that providers declare
   they offer.
2. **Protocols** — `BaseProvider` plus four domain Protocols
   (`CampaignProvider`, `KeywordProvider`, `AudienceProvider`,
   `ExtensionProvider`). Each domain Protocol fixes a small set of
   synchronous method signatures using a shared vocabulary of frozen
   dataclasses.
3. **Registry** — entry-points-based discovery
   (`mureo.providers` group). Plugins register a class object; mureo
   defers instantiation, isolates per-plugin faults, and applies a
   first-wins policy on duplicate names.

A plugin is, in the smallest case, a Python package that:

- declares one provider class with three class attributes (`name`,
  `display_name`, `capabilities`),
- implements at least one domain Protocol,
- registers the class under the `mureo.providers` entry-point group in
  its `pyproject.toml`.

That is enough to be discovered by `mureo discover_providers()` and
matched against the 16 built-in skills.

### What a plugin can do (and cannot do, in Phase 1)

Phase 1 in scope:

- Add a new ad-platform provider implementing any subset of the four
  domain Protocols.
- Ship a directory of `SKILL.md` files via the `mureo.skills`
  entry-points group; skills are discovered, validated, and matched
  against provider capabilities.
- Plug into the deterministic skill ↔ provider matcher (three-bucket
  classification: `executable` / `advisory_only` / `unavailable`).

Phase 1 explicitly **out of scope** (will land in later phases — your
plugin should not depend on them):

- A standard authentication contract. Phase 1 keeps `BaseProvider`
  authentication-free; each adapter decides its own credential
  loading. A future `AuthenticatedProvider` Protocol will layer on top
  without breaking existing plugins.
- Runtime authorization checks (`permit()`). Today the matcher gates
  purely against the declared `capabilities` frozenset.
- MCP tool **auto-generation** from the Protocol. A provider is not
  published as MCP tools merely by implementing a domain Protocol.
  Exposure is **opt-in**: implement the secondary `MCPToolProvider`
  Protocol (see Section 3, "Exposing operations as MCP tools") and the
  MCP server discovers and publishes your tools. A provider that does
  not implement it is still discovered and skill-matched — just not
  exposed as MCP tools.
- Thread safety. Discovery and registration run single-threaded at
  CLI / MCP-server startup.

---

## 2. Quick start: a minimal plugin

The smallest functioning plugin is a single-file provider that
implements `BaseProvider` plus one domain Protocol, plus a
`pyproject.toml` entry. Below is a complete working example for a
fictional platform `acme_ads`.

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mureo-acme-ads"
version = "0.1.0"
description = "ACME Ads provider for mureo"
requires-python = ">=3.10"
dependencies = [
    "mureo>=0.8,<1",
]

[project.entry-points."mureo.providers"]
acme_ads = "mureo_acme_ads.adapter:AcmeAdsAdapter"

[tool.hatch.build.targets.wheel]
packages = ["mureo_acme_ads"]
```

The entry-point key (`acme_ads`) must match the provider class's
`name` attribute. mureo enforces snake_case on provider names
(`^[a-z][a-z0-9_]*$`).

### `mureo_acme_ads/__init__.py`

```python
"""ACME Ads provider for mureo."""

from mureo_acme_ads.adapter import AcmeAdsAdapter

__all__ = ["AcmeAdsAdapter"]
```

### `mureo_acme_ads/adapter.py`

```python
"""ACME Ads adapter — minimal CampaignProvider implementation."""

from __future__ import annotations

from datetime import date

from mureo.core.providers import (
    Ad,
    AdStatus,
    Campaign,
    CampaignFilters,
    Capability,
    CreateAdRequest,
    CreateCampaignRequest,
    DailyReportRow,
    UpdateAdRequest,
    UpdateCampaignRequest,
)


class AcmeAdsAdapter:
    """ACME Ads provider implementing CampaignProvider (read-only)."""

    # BaseProvider class attributes — see Section 3.
    name: str = "acme_ads"
    display_name: str = "ACME Ads"
    capabilities: frozenset[Capability] = frozenset(
        {
            Capability.READ_CAMPAIGNS,
            Capability.READ_PERFORMANCE,
        }
    )

    def __init__(self, api_key: str) -> None:
        # Real plugins load credentials from env / a credentials file.
        # See Section 10 for the secret-management contract.
        self._api_key = api_key

    # CampaignProvider methods (signatures must match exactly).
    def list_campaigns(
        self, filters: CampaignFilters | None = None
    ) -> tuple[Campaign, ...]:
        # Talk to your platform here; return a tuple of Campaign.
        return ()

    def get_campaign(self, campaign_id: str) -> Campaign:
        raise NotImplementedError

    def create_campaign(self, request: CreateCampaignRequest) -> Campaign:
        raise NotImplementedError

    def update_campaign(
        self, campaign_id: str, request: UpdateCampaignRequest
    ) -> Campaign:
        raise NotImplementedError

    def list_ads(self, campaign_id: str) -> tuple[Ad, ...]:
        return ()

    def get_ad(self, campaign_id: str, ad_id: str) -> Ad:
        raise NotImplementedError

    def create_ad(self, campaign_id: str, request: CreateAdRequest) -> Ad:
        raise NotImplementedError

    def update_ad(
        self, campaign_id: str, ad_id: str, request: UpdateAdRequest
    ) -> Ad:
        raise NotImplementedError

    def set_ad_status(
        self, campaign_id: str, ad_id: str, status: AdStatus
    ) -> Ad:
        raise NotImplementedError

    def daily_report(
        self, campaign_id: str, start_date: date, end_date: date
    ) -> tuple[DailyReportRow, ...]:
        return ()
```

### Verify discovery

After `pip install -e .`:

```python
from mureo.core.providers import discover_providers, get_provider

discover_providers()
entry = get_provider("acme_ads")
print(entry.name, entry.display_name, sorted(str(c) for c in entry.capabilities))
print(entry.source_distribution)  # "mureo-acme-ads"
```

If the class fails validation (bad regex on `name`, wrong type on
`capabilities`, etc.), discovery emits a `RegistryWarning` and skips
the plugin — it does NOT raise. Use `warnings.filterwarnings("error",
category=RegistryWarning)` during development to fail fast.

---

## 3. Provider Protocols

mureo uses [PEP 544](https://peps.python.org/pep-0544/) structural
typing: your class does not need to inherit from any base class. It
just needs the right attributes and method signatures. All Protocols
are `@runtime_checkable`, so `isinstance(obj, CampaignProvider)`
returns `True` for any object exposing the required attributes.

### `BaseProvider` (required by every plugin)

Defined in `mureo.core.providers.base`. Three class attributes:

| Attribute | Type | Contract |
|---|---|---|
| `name` | `str` | Snake_case identifier matching `^[a-z][a-z0-9_]*$`. Used as registry key and skill-frontmatter token. |
| `display_name` | `str` | Non-empty human-readable label (CLI output, error messages). |
| `capabilities` | `frozenset[Capability]` | The capabilities the provider declares it can serve. Must be a `frozenset` (not `set`) so it is hashable and cannot be mutated. |

These should be **class attributes** (not instance attributes) so the
registry and skill matcher can introspect them without instantiating
the provider. `validate_provider()` and `register_provider_class()`
both look them up on the class via `getattr`.

`BaseProvider` declares no methods. Phase 1 keeps it minimal so
adding required methods later cannot break installed plugins — new
behaviour goes into secondary Protocols.

### Domain Protocols (implement at least one)

| Protocol | Purpose | Methods |
|---|---|---|
| `CampaignProvider` | Campaigns, ads, daily-grain reporting | `list_campaigns`, `get_campaign`, `create_campaign`, `update_campaign`, `list_ads`, `get_ad`, `create_ad`, `update_ad`, `set_ad_status`, `daily_report` |
| `KeywordProvider` | Keywords + search-term reports (search platforms only) | `list_keywords`, `add_keywords`, `set_keyword_status`, `search_terms` |
| `AudienceProvider` | Audience / segment management | `list_audiences`, `get_audience`, `create_audience`, `set_audience_status` |
| `ExtensionProvider` | Ad extensions (sitelinks, callouts, conversions) | `list_extensions`, `add_extension`, `set_extension_status` |

Each Protocol is independent. Implementing a Protocol does **not**
auto-grant capabilities — the matcher only looks at your declared
`capabilities` frozenset (see Section 4).

### Delete-via-status convention

There are no `delete_*` methods. Deletion is folded into status
updates with the `REMOVED` enum member:

```python
adapter.set_ad_status(campaign_id, ad_id, AdStatus.REMOVED)
adapter.set_keyword_status(campaign_id, keyword_id, KeywordStatus.REMOVED)
adapter.set_audience_status(audience_id, AudienceStatus.REMOVED)
adapter.set_extension_status(campaign_id, extension_id, ExtensionStatus.REMOVED)
```

Your adapter is responsible for translating `REMOVED` into the
platform-native delete call (e.g. the Meta Custom Audiences delete
endpoint, or the Google Ads `remove` operation). This convention
keeps the Capability surface minimal — no `DELETE_*` capabilities
exist.

### Sync vs async

All Phase 1 Protocols are **synchronous**. If your underlying client
is async, run it on a fresh event loop inside each method — this is
the same pattern used by the built-in `GoogleAdsAdapter` and
`MetaAdsAdapter`:

```python
import asyncio
from collections.abc import Awaitable
from typing import TypeVar

_T = TypeVar("_T")

class MyAdapter:
    @staticmethod
    def _run(coro: Awaitable[_T]) -> _T:
        # Raises RuntimeError if called from inside a running loop —
        # that is the documented Phase 1 contract.
        return asyncio.run(coro)

    def list_campaigns(self, filters=None):
        return self._run(self._client.async_list_campaigns(filters))
```

If a caller is already inside an event loop, `asyncio.run` raises
`RuntimeError`. That is the documented Phase 1 behaviour and is
allowed to propagate.

### Exposing operations as MCP tools (`MCPToolProvider`)

Implementing a domain Protocol makes your provider discoverable and
skill-matchable. It does **not**, on its own, publish your operations
as `mcp__mureo__*` tools. MCP exposure is a separate, **opt-in
secondary Protocol** — `mureo.mcp.tool_provider.MCPToolProvider` — that
you implement *in addition to* `BaseProvider` / a domain Protocol:

```python
from mcp.types import TextContent, Tool

class MyAdapter:               # already a CampaignProvider, etc.
    # ... name / display_name / capabilities / Protocol methods ...

    def mcp_tools(self) -> tuple[Tool, ...]:
        # MUST be pure and credential-free: it is called at MCP-server
        # start, before any API key is necessarily present. Return
        # static Tool definitions only — no network, no secret access.
        return MY_TOOLS

    async def handle_mcp_tool(
        self, name: str, arguments: dict
    ) -> list[TextContent]:
        # Called only for tool names you returned from mcp_tools().
        ...
```

`isinstance` (structural, `runtime_checkable`) is how the server
detects the surface, so you do **not** need to import `MCPToolProvider`
— matching the two method shapes is sufficient. This keeps your plugin
working against any mureo release whose server performs the wiring,
without a hard import dependency on it.

Rules the server enforces (a non-conforming provider is skipped with a
`PluginToolWarning`, never fatal):

- **No-arg constructible.** The server does `YourClass()` at startup.
  Resolve credentials lazily on first tool *call*, not in `__init__`.
- **`mcp_tools()` is static / credential-free.** It runs before any
  secret is guaranteed present.
- **`handle_mcp_tool` must be `async`.** A sync handler is rejected at
  collection time (the dispatch path is not fault-isolated).
- **Namespace your tool names.** Prefix every tool with your provider
  name (e.g. `acme_ads_list_campaigns`). Built-in tool names are
  reserved — a colliding plugin tool is dropped (built-ins win), and a
  name already taken by an earlier plugin is dropped (first wins).
- **Validate inbound arguments yourself.** `inputSchema` validation is
  advisory on the client side and the dispatch path is not
  fault-isolated; translate malformed arguments into your own error
  type rather than letting a bare `KeyError`/`ValueError` escape.

Sync clients: run blocking work off the event loop with
`asyncio.to_thread(...)` inside `handle_mcp_tool` so you do not block
the MCP server.

This is an **opt-in, hand-written** surface (the plugin author writes
the `Tool` schemas). Auto-generating tools from the domain Protocol is
intentionally *not* done — it cannot express platform-specific
operations that fall outside the shared Protocol, which hand-written
`mcp_tools()` can. See `docs/mcp-server.md` for the server-side view.

---

## 4. Capabilities

Defined in `mureo.core.providers.capabilities.Capability`. The enum
values are snake_case strings forming a stable ABI — they appear
verbatim in skill frontmatter and in `entry.capabilities` introspection.

### The 13 Phase 1 capabilities

| Value | Meaning |
|---|---|
| `read_campaigns` | List / read campaign metadata. |
| `read_performance` | Day-grain performance reporting. |
| `read_keywords` | List keywords on a campaign. |
| `read_search_terms` | Read search-term reports (actual user queries). |
| `read_audiences` | List / read audience metadata. |
| `read_extensions` | List ad extensions. |
| `write_budget` | Set daily / lifetime budget on a campaign. |
| `write_bid` | Set bidding parameters. |
| `write_creative` | Create / update ads and creatives. |
| `write_keywords` | Add / pause keywords. |
| `write_audiences` | Create / remove audiences. |
| `write_extensions` | Add / remove ad extensions. |
| `write_campaign_status` | Pause / resume / remove campaigns and ads (covers deletion). |

Add the enum members to your `capabilities` frozenset for the
operations your adapter actually supports:

```python
from mureo.core.providers import Capability

capabilities: frozenset[Capability] = frozenset(
    {
        Capability.READ_CAMPAIGNS,
        Capability.READ_PERFORMANCE,
        Capability.WRITE_BUDGET,
        Capability.WRITE_CAMPAIGN_STATUS,
    }
)
```

### Implementing a Protocol vs declaring a Capability

These are independent decisions:

| Combination | Effect |
|---|---|
| Implement `CampaignProvider` AND declare `WRITE_BUDGET` | Skills needing `write_budget` can run; `create_campaign` is callable. |
| Implement `CampaignProvider` but DON'T declare `WRITE_BUDGET` | Skills needing `write_budget` see your provider as `unavailable`. |
| Don't implement `CampaignProvider` but declare `WRITE_BUDGET` | The matcher will say "executable" but calls fail at runtime — **do not do this**. |

Rule: only declare a capability if your adapter actually implements
the corresponding methods. The matcher trusts your declared set; it
does not introspect method bodies.

### Capability ↔ method mapping

| Capability | Methods it gates |
|---|---|
| `READ_CAMPAIGNS` | `list_campaigns`, `get_campaign`, `list_ads`, `get_ad` |
| `READ_PERFORMANCE` | `daily_report` |
| `READ_KEYWORDS` | `list_keywords` |
| `READ_SEARCH_TERMS` | `search_terms` |
| `READ_AUDIENCES` | `list_audiences`, `get_audience` |
| `READ_EXTENSIONS` | `list_extensions` |
| `WRITE_BUDGET` | `create_campaign`, `update_campaign` (budget field) |
| `WRITE_CREATIVE` | `create_ad`, `update_ad` |
| `WRITE_KEYWORDS` | `add_keywords`, `set_keyword_status` |
| `WRITE_AUDIENCES` | `create_audience`, `set_audience_status` |
| `WRITE_EXTENSIONS` | `add_extension`, `set_extension_status` |
| `WRITE_CAMPAIGN_STATUS` | `set_ad_status`, plus campaign-level status writes; covers `REMOVED` (delete-via-status) |
| `WRITE_BID` | Reserved for bid-strategy mutations; surfaces in Phase 2. |

### Parsing capability tokens (for skill frontmatter or config files)

```python
from mureo.core.providers import parse_capability, parse_capabilities

parse_capability("read_campaigns")
# -> Capability.READ_CAMPAIGNS

parse_capabilities(["read_campaigns", "write_budget"])
# -> frozenset({Capability.READ_CAMPAIGNS, Capability.WRITE_BUDGET})

parse_capability("READ_CAMPAIGNS")
# -> ValueError: unknown capability: 'READ_CAMPAIGNS'. Did you mean: read_campaigns? ...
```

Both helpers raise `ValueError` with close-match suggestions on
unknown tokens, so config-file errors surface with actionable
messages.

---

## 5. Models: frozen dataclasses and enums

Defined in `mureo.core.providers.models`. Every entity is
`@dataclass(frozen=True)`; every enum is a `StrEnum` (with a 3.10
backport shim). Collection fields use `tuple[T, ...]`, never
`list[T]`, so adapters cannot accidentally hand a mutable container
across the Protocol boundary.

### Read-side entities

These are what providers **return**:

| Dataclass | Used by |
|---|---|
| `Campaign` | `list_campaigns`, `get_campaign`, `create_campaign`, `update_campaign` |
| `Ad` | `list_ads`, `get_ad`, `create_ad`, `update_ad`, `set_ad_status` |
| `Keyword` | `list_keywords`, `add_keywords`, `set_keyword_status` |
| `SearchTerm` | `search_terms` |
| `Audience` | `list_audiences`, `get_audience`, `create_audience`, `set_audience_status` |
| `Extension` | `list_extensions`, `add_extension`, `set_extension_status` |
| `DailyReportRow` | `daily_report` |

### Write-side DTOs

These are what providers **accept**:

| Dataclass | Used by |
|---|---|
| `CampaignFilters` | `list_campaigns` (optional filter argument; all fields optional) |
| `CreateCampaignRequest` / `UpdateCampaignRequest` | campaign mutation |
| `CreateAdRequest` / `UpdateAdRequest` | ad mutation |
| `KeywordSpec` | `add_keywords` (immutable creation spec) |
| `CreateAudienceRequest` | `create_audience` |
| `ExtensionRequest` | `add_extension` |

### Enums

| Enum | Members | Notes |
|---|---|---|
| `CampaignStatus` | `ENABLED`, `PAUSED`, `REMOVED` | `REMOVED` is the delete signal. |
| `AdStatus` | `ENABLED`, `PAUSED`, `REMOVED` | Same convention. |
| `KeywordStatus` | `ENABLED`, `PAUSED`, `REMOVED` | Same convention. |
| `AudienceStatus` | `ENABLED`, `REMOVED` | No `PAUSED` (audiences cannot be paused). |
| `ExtensionStatus` | `ENABLED`, `PAUSED`, `REMOVED` | Same convention. |
| `ExtensionKind` | `SITELINK`, `CALLOUT`, `CONVERSION` | Type-safe dispatch in `list_extensions` / `add_extension`. |
| `KeywordMatchType` | `EXACT`, `PHRASE`, `BROAD` | |
| `BidStrategy` | `MANUAL_CPC`, `TARGET_CPA`, `MAXIMIZE_CONVERSIONS` | |

### Currency and date conventions

- **Money**: integer "micros" (1/1,000,000 of the account currency)
  on every monetary field (`daily_budget_micros`, `cost_micros`,
  `cpc_bid_micros`). If your platform uses cents or full units, your
  adapter is responsible for converting at its boundary. A future
  `Money(amount_minor: int, currency: str)` abstraction may replace
  raw `_micros` fields in Phase 2; the change will be additive.
- **Dates**: `datetime.date` (day-grain in the account's timezone) on
  every reporting / scheduling field. No `int` epoch seconds at the
  Protocol boundary.

### Constructing entities

```python
from datetime import date

from mureo.core.providers import (
    Campaign,
    CampaignStatus,
    DailyReportRow,
)

campaign = Campaign(
    id="123",
    account_id="987",
    name="Holiday Sale 2026",
    status=CampaignStatus.ENABLED,
    daily_budget_micros=50_000_000,  # 50 units of account currency
)

row = DailyReportRow(
    date=date(2026, 5, 14),
    impressions=12_345,
    clicks=678,
    cost_micros=4_500_000,
    conversions=12.5,
)
```

Because every dataclass is frozen, mutating fields raises
`dataclasses.FrozenInstanceError` — use `dataclasses.replace(...)` to
produce a modified copy.

---

## 6. Skill matching

mureo ships 16 built-in skills (in
`mureo/_data/skills/<skill>/SKILL.md`) and supports third-party
skills via the `mureo.skills` entry-points group. Each skill is a
markdown file with YAML frontmatter declaring what it does and which
capabilities it needs.

### SKILL.md frontmatter

```yaml
---
name: my-skill
description: "Run analysis X on the connected ad accounts. Use when the user asks for ..."
capabilities:
  required:
    - read_campaigns
    - read_performance
  advisory_mode:
    - read_campaigns
metadata:
  version: "0.1.0"
---

# My Skill

(prose body — agent reads this as the skill prompt)
```

Frontmatter keys consumed by the parser:

- `name` (required) — matches `^_?[a-z][a-z0-9_-]*$`. Hyphens and a
  single leading underscore are allowed (skill names differ from
  provider names; see [ABI-stability.md](./ABI-stability.md) for the
  rationale).
- `description` (required) — non-empty string.
- `capabilities.required` — list of capability tokens needed for full
  execution. Empty / absent means the skill is universally executable.
- `capabilities.advisory_mode` — list of capability tokens that are
  sufficient for advisory (read-only) execution. Must be a subset of
  `required`.

Any other top-level keys (e.g. `metadata`) are preserved in
`SkillEntry.extra` for forward compatibility.

### Three-bucket classification

`mureo.core.skills.match_skills(skills, provider)` returns a
`SkillMatch` with three sorted tuples:

| Bucket | Condition |
|---|---|
| `executable` | `skill.required_capabilities <= provider.capabilities` (or skill declares no requirements). |
| `advisory_only` | Skill is NOT executable AND `skill.advisory_mode_capabilities` is non-empty AND it is a subset of provider capabilities. |
| `unavailable` | Otherwise. |

The inverse query (`providers_for_skill(skill, registry)`) returns a
`ProviderMatch` with the same three buckets, but enumerating
providers instead of skills.

### Worked example

```python
from mureo.core.providers import (
    Capability,
    discover_providers,
    get_provider,
)
from mureo.core.skills import discover_skills, match_skills

discover_providers()
discover_skills()

provider = get_provider("acme_ads")
skills = discover_skills()
match = match_skills(skills, provider)

print("Executable:", [s.name for s in match.executable])
print("Advisory:  ", [s.name for s in match.advisory_only])
print("Unavail.:  ", [s.name for s in match.unavailable])
```

### Skill name vs provider name regex (do not confuse them)

| Identifier | Regex | Example |
|---|---|---|
| Provider `name` | `^[a-z][a-z0-9_]*$` | `acme_ads` |
| Skill `name`    | `^_?[a-z][a-z0-9_-]*$` | `_mureo-shared`, `daily-check` |

The skill regex is deliberately looser because the 16 in-tree skills
already use hyphens and a single leading underscore (`_mureo-shared`,
`daily-check`, `weekly-report`). Provider names map to Python tool
prefixes and must remain snake_case identifiers.

---

## 7. Distribution patterns

mureo discovers providers via Python's standard entry-points
mechanism, so any installation channel pip supports is automatically
supported here. Four common patterns:

### 7.1 Public PyPI

The simplest path. Publish your plugin to PyPI; users install with:

```bash
pip install mureo-acme-ads
```

After installation, mureo picks up the `mureo.providers` entry point
automatically on the next `discover_providers()` call. No mureo
config change is required.

### 7.2 Private package index

For closed-source platforms or enterprise deployments. Host your
package on a private PyPI / GitHub Packages / AWS CodeArtifact /
Artifactory / etc., then:

```bash
pip install --index-url https://pypi.example.com/simple/ mureo-acme-ads
# or:
pip install --extra-index-url https://pypi.example.com/simple/ mureo-acme-ads
```

The plugin still goes through the same entry-points group; mureo
does not distinguish public-PyPI plugins from private-index plugins
at discovery time. `ProviderEntry.source_distribution` will be the
PEP 503 normalized name of the package (`mureo-acme-ads`) regardless
of where it came from.

### 7.3 Direct from Git

For pre-release plugins, monorepos, or forks:

```bash
pip install git+https://github.com/your-org/mureo-acme-ads.git@v0.1.0
pip install git+ssh://git@github.com/your-org/mureo-acme-ads.git@main
pip install git+https://github.com/your-org/mureo-acme-ads.git@<commit-sha>
```

Pinning to a tag or commit SHA is the recommended pattern — `@main`
can drift unexpectedly.

### 7.4 Vendored wheel / local path

For air-gapped environments or hermetic builds:

```bash
# Build once
pip wheel mureo-acme-ads -w ./wheels

# Install from the local wheel
pip install ./wheels/mureo_acme_ads-0.1.0-py3-none-any.whl
# or editable from source:
pip install -e ./path/to/mureo-acme-ads
```

This is also the recommended pattern during development — `pip
install -e .` gives you live re-loads without re-publishing.

### Choosing a pattern

| Constraint | Recommended pattern |
|---|---|
| Open-source plugin, widest reach | Public PyPI (7.1) |
| Closed-source, internal-only | Private index (7.2) |
| Pre-release, multiple stakeholders | Git URL pinned to commit SHA (7.3) |
| Air-gapped / regulated environment | Vendored wheel (7.4) |
| Active development | Editable install (`pip install -e .`) |

All four patterns share the same entry-points contract — your
`pyproject.toml` does not change.

---

## 8. Entry-points registration

mureo iterates the entry-points group named **`mureo.providers`** at
discovery time. The group name is a fixed ABI constant
(`mureo.core.providers.registry.PROVIDERS_ENTRY_POINT_GROUP`).

### Basic registration

```toml
[project.entry-points."mureo.providers"]
acme_ads = "mureo_acme_ads.adapter:AcmeAdsAdapter"
```

The key (`acme_ads`) is what mureo passes to `Registry._load_entry_point`
as `ep.name`. The value is a standard Python entry-point target
(`<module>:<attribute>`). The attribute must resolve to a **class**,
not an instance — mureo defers instantiation so plugin `__init__`
side effects (network, FS, credential loading) do not run during
discovery.

The entry-point key should match the class's `name` class attribute.
mureo trusts the class attribute (not the entry-point key) when
populating `ProviderEntry.name`, but mismatches are confusing for
operators reading discovery logs.

### Registering multiple providers from one package

A single package can ship multiple providers. Use unique entry-point
keys and ensure each class has a unique `name` attribute:

```toml
[project.entry-points."mureo.providers"]
acme_ads = "mureo_acme.adapters:AcmeAdsAdapter"
acme_search = "mureo_acme.adapters:AcmeSearchAdapter"
```

### First-wins on duplicate names

If two packages register a provider class with the same `name`, the
**first registered wins** and mureo emits a `RegistryWarning` for
the loser. This is a security property: a malicious package
installed after a legitimate one cannot silently take over its
slot. To detect duplicates in CI:

```python
import warnings

from mureo.core.providers import RegistryWarning, discover_providers

warnings.filterwarnings("error", category=RegistryWarning)
discover_providers()  # raises on first duplicate / malformed plugin
```

### Programmatic registration (tests, embedded use)

For tests and embedded scenarios you can also register a class in
process without going through entry points:

```python
from mureo.core.providers import register_provider_class

entry = register_provider_class(MyAdapter, source_distribution="my-package")
```

`register_provider_class` raises on validation failure (it is the
strict counterpart to entry-points discovery, which warns + skips).
Use it for fast feedback during development.

---

## 9. Shipping skills with your plugin

If your plugin wants to ship its own `SKILL.md` files (for workflows
specific to your platform), register a directory under the
`mureo.skills` entry-points group.

### `pyproject.toml`

```toml
[project.entry-points."mureo.skills"]
mureo-acme-ads = "mureo_acme_ads.skills:SKILLS_DIR"

[tool.hatch.build.targets.wheel]
packages = ["mureo_acme_ads"]
```

### `mureo_acme_ads/skills/__init__.py`

```python
"""Directory locator for mureo.skills entry-point."""

from pathlib import Path

SKILLS_DIR: Path = Path(__file__).resolve().parent
```

### Directory layout

```
mureo_acme_ads/skills/
├── __init__.py
├── acme-budget-rebalance/
│   └── SKILL.md
└── acme-creative-audit/
    └── SKILL.md
```

Each `SKILL.md` file is parsed by `mureo.core.skills.parse_skill_md`.
The discovery walker:

- recursively scans up to 4 directory levels deep,
- accepts at most 64 `SKILL.md` files per entry-point root,
- rejects files larger than 64 KiB,
- enforces UTF-8 strict decoding,
- uses `yaml.safe_load` only (never `yaml.load`),
- refuses symlinks that escape the entry-point root.

A malformed `SKILL.md` is skipped with a `SkillDiscoveryWarning`;
the rest of the plugin's skills still load.

### First-wins on duplicate skill names

Like providers, skill discovery is first-wins. A built-in skill
named `daily-check` cannot be silently replaced by a third-party
plugin. The shadow attempt emits a `SkillDiscoveryWarning`. Pick
plugin-prefixed skill names (e.g. `acme-budget-rebalance`) to avoid
collisions.

---

## 10. Security considerations

### Plugin-side responsibilities

Your plugin runs inside the mureo process. The mureo project treats
plugins as a known trust boundary but still expects basic hygiene:

1. **Never hardcode secrets.** Load credentials from environment
   variables, a credentials file under `~/.mureo/`, or a system
   secret store. mureo itself loads `~/.mureo/credentials.json` for
   built-in adapters; reuse that path or pick a clearly-namespaced
   alternative (`~/.mureo/<plugin>.json`).
2. **Validate inputs at adapter boundaries.** Your adapter receives
   user-controlled values via DTOs (campaign IDs, keyword text,
   URLs). Validate them before interpolating into platform-specific
   query languages — see `GoogleAdsAdapter._validate_campaign_id`
   for the digits-only GAQL-safety pattern.
3. **Do not perform I/O at import time.** mureo discovery loads
   your top-level module via `ep.load()` and then calls validation
   on the class object. Module import should be cheap. Defer
   credential loading, network calls, and FS scans to `__init__` or
   first-method-call time.
4. **Bound external calls.** Use timeouts on every HTTP call,
   bounded retries with jitter, and rate limits matching the
   platform's quota.
5. **Never trust third-party data as code.** If your adapter
   consumes user-supplied YAML/JSON/HTML, use `safe_load` /
   parameterized parsers — never `eval`, `exec`, or `yaml.load`.
6. **Log securely.** Do not log access tokens, refresh tokens,
   developer tokens, or PII. Mask secrets even in debug logs.

### What mureo does on your behalf

1. **Per-plugin fault isolation.** A broken `ep.load()` or a
   malformed class is caught by a per-entry try/except and surfaced
   as a `RegistryWarning`. One bad plugin cannot break discovery of
   the others.
2. **Class validation before registration.** Bad `name` / bad
   `capabilities` / wrong types are rejected with a clear error
   message embedding the class's `__qualname__`.
3. **Deferred instantiation.** mureo registers your class object,
   not an instance. Your `__init__` side effects do not run during
   discovery.
4. **First-wins on duplicate names.** A late-arriving malicious
   plugin cannot shadow an earlier legitimate one.
5. **Source-distribution tracking.** Every `ProviderEntry` records
   the PEP 503 normalized package name in `source_distribution`, so
   operators can identify which package supplied each provider.
   Treat the value as untrusted display data — do not interpolate
   it into shell / SQL / log-injection-sensitive sinks downstream.
6. **Strict-mode escape hatch.** Setting
   `warnings.filterwarnings("error", category=RegistryWarning)` (or
   the same for `SkillDiscoveryWarning`) turns the first malformed
   plugin into a startup failure — useful in CI and in
   security-conscious deployments.

### What mureo does NOT do (Phase 1)

- **No code signing / signature verification.** Plugin authenticity
  is the user's responsibility — they install you via pip, the same
  trust model as any pip package.
- **No sandboxing.** Your code runs with the same OS privileges as
  mureo itself. Operate accordingly.
- **No automatic secret redaction.** If your plugin logs secrets,
  they appear in mureo's logs verbatim.

---

## 11. End-to-end example

A complete plugin skeleton is reproduced below. It implements one
domain Protocol, ships one skill, and is ready to publish.

### Repository layout

```
mureo-acme-ads/
├── pyproject.toml
├── README.md
├── LICENSE
├── mureo_acme_ads/
│   ├── __init__.py
│   ├── adapter.py
│   ├── client.py
│   ├── mappers.py
│   └── skills/
│       ├── __init__.py
│       └── acme-budget-audit/
│           └── SKILL.md
└── tests/
    ├── test_adapter_protocol.py
    └── test_discovery.py
```

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mureo-acme-ads"
version = "0.1.0"
description = "ACME Ads provider and skills for mureo"
requires-python = ">=3.10"
license = "Apache-2.0"
authors = [{name = "Your Name"}]
dependencies = [
    "mureo>=0.8,<1",
    "httpx>=0.27,<1",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4,<9",
    "mypy>=1.8,<2",
    "ruff>=0.3,<1",
]

[project.entry-points."mureo.providers"]
acme_ads = "mureo_acme_ads.adapter:AcmeAdsAdapter"

[project.entry-points."mureo.skills"]
mureo-acme-ads = "mureo_acme_ads.skills:SKILLS_DIR"

[tool.hatch.build.targets.wheel]
packages = ["mureo_acme_ads"]
```

### `mureo_acme_ads/adapter.py`

```python
"""ACME Ads adapter — CampaignProvider implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import date
from typing import TypeVar

from mureo.core.providers import (
    Ad,
    AdStatus,
    Campaign,
    CampaignFilters,
    Capability,
    CreateAdRequest,
    CreateCampaignRequest,
    DailyReportRow,
    UpdateAdRequest,
    UpdateCampaignRequest,
)

from mureo_acme_ads.client import AcmeAdsClient
from mureo_acme_ads.mappers import to_ad, to_campaign, to_daily_row

_T = TypeVar("_T")


class AcmeAdsAdapter:
    """ACME Ads CampaignProvider with deferred async bridge."""

    name: str = "acme_ads"
    display_name: str = "ACME Ads"
    capabilities: frozenset[Capability] = frozenset(
        {
            Capability.READ_CAMPAIGNS,
            Capability.READ_PERFORMANCE,
            Capability.WRITE_BUDGET,
            Capability.WRITE_CREATIVE,
            Capability.WRITE_CAMPAIGN_STATUS,
        }
    )

    def __init__(self, client: AcmeAdsClient) -> None:
        self._client = client

    @staticmethod
    def _run(coro: Awaitable[_T]) -> _T:
        return asyncio.run(coro)

    def list_campaigns(
        self, filters: CampaignFilters | None = None
    ) -> tuple[Campaign, ...]:
        raw = self._run(self._client.list_campaigns(filters))
        return tuple(to_campaign(r) for r in raw)

    def get_campaign(self, campaign_id: str) -> Campaign:
        raw = self._run(self._client.get_campaign(campaign_id))
        return to_campaign(raw)

    # ... remaining methods elided for brevity; same shape.
    def create_campaign(self, request: CreateCampaignRequest) -> Campaign:
        raise NotImplementedError

    def update_campaign(
        self, campaign_id: str, request: UpdateCampaignRequest
    ) -> Campaign:
        raise NotImplementedError

    def list_ads(self, campaign_id: str) -> tuple[Ad, ...]:
        raw = self._run(self._client.list_ads(campaign_id))
        return tuple(to_ad(r) for r in raw)

    def get_ad(self, campaign_id: str, ad_id: str) -> Ad:
        raise NotImplementedError

    def create_ad(self, campaign_id: str, request: CreateAdRequest) -> Ad:
        raise NotImplementedError

    def update_ad(
        self, campaign_id: str, ad_id: str, request: UpdateAdRequest
    ) -> Ad:
        raise NotImplementedError

    def set_ad_status(
        self, campaign_id: str, ad_id: str, status: AdStatus
    ) -> Ad:
        raise NotImplementedError

    def daily_report(
        self, campaign_id: str, start_date: date, end_date: date
    ) -> tuple[DailyReportRow, ...]:
        raw = self._run(
            self._client.daily_report(campaign_id, start_date, end_date)
        )
        return tuple(to_daily_row(r) for r in raw)
```

### `mureo_acme_ads/skills/acme-budget-audit/SKILL.md`

```yaml
---
name: acme-budget-audit
description: "Audit ACME Ads campaigns for over-budget waste. Use when the user asks for an ACME budget review or efficiency check."
capabilities:
  required:
    - read_campaigns
    - read_performance
  advisory_mode:
    - read_campaigns
metadata:
  version: "0.1.0"
---

# ACME Budget Audit

(skill body)
```

### `tests/test_adapter_protocol.py`

```python
"""Verify adapter satisfies the Protocol structurally."""

from mureo.core.providers import (
    BaseProvider,
    CampaignProvider,
    validate_provider,
)

from mureo_acme_ads.adapter import AcmeAdsAdapter


def test_satisfies_base_provider() -> None:
    # Class-level isinstance against the runtime-checkable Protocol.
    assert isinstance(AcmeAdsAdapter, type)
    validate_provider(AcmeAdsAdapter)  # raises on contract failure


def test_satisfies_campaign_provider() -> None:
    # Instance-level structural check.
    client = ...  # mock
    adapter = AcmeAdsAdapter(client)
    assert isinstance(adapter, CampaignProvider)
    assert isinstance(adapter, BaseProvider)
```

---

## 12. Troubleshooting

### My plugin is not discovered

1. Confirm `pip show mureo-acme-ads` lists your package as installed.
2. Confirm the entry-points group is exactly `mureo.providers`:
   ```bash
   python -c "from importlib.metadata import entry_points; print(list(entry_points(group='mureo.providers')))"
   ```
3. Enable strict mode and run discovery to see why it was skipped:
   ```python
   import warnings
   from mureo.core.providers import RegistryWarning, discover_providers
   warnings.filterwarnings("error", category=RegistryWarning)
   discover_providers(refresh=True)
   ```
4. Common causes: `name` does not match `^[a-z][a-z0-9_]*$`,
   `capabilities` is a plain `set` instead of `frozenset`,
   `display_name` is empty, top-level import in your module raises.

### My skill is loaded but the matcher says `unavailable`

1. Check the provider's declared `capabilities`:
   ```python
   from mureo.core.providers import get_provider
   print(sorted(str(c) for c in get_provider("acme_ads").capabilities))
   ```
2. Check the skill's declared requirements:
   ```python
   from mureo.core.skills import discover_skills
   for s in discover_skills():
       if s.name == "my-skill":
           print(sorted(str(c) for c in s.required_capabilities))
   ```
3. The skill is `executable` only if the provider's set is a
   superset of the skill's required set.

### Discovery is slow / floods warnings

A hostile environment (many malformed plugins) can produce many
`RegistryWarning` entries. In production sinks, rate-limit at the
log layer or enable strict mode so the first malformed plugin is a
hard failure. Phase 2 may add in-module rate limiting; see
`mureo/core/providers/registry.py` module docstring.

### How do I clear the discovery cache (tests)?

```python
from mureo.core.providers import clear_registry
from mureo.core.skills import clear_skills_cache

clear_registry()
clear_skills_cache()
```

Both wipe the in-process cache; the next `discover_*` call
re-iterates entry points.

---

## Related documentation

- [ABI-stability.md](./ABI-stability.md) — what is breaking, what is
  not, deprecation policy.
- [architecture.md](./architecture.md) — overall mureo architecture
  (provider layer + workflow commands + skills + MCP server).
- [authentication.md](./authentication.md) — how mureo loads
  credentials for built-in adapters (reference for plugin
  credential loading).
- Built-in adapters in source — `mureo/adapters/google_ads/adapter.py`
  and `mureo/adapters/meta_ads/adapter.py` are reference
  implementations covering all four Protocols between them.
