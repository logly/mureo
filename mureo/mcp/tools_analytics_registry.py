"""MCP tools exposing the analytics-module registry (Issue #120 / #440).

Two read-only tools:

- ``mureo_analytics_modules_list`` — which platforms have an analytics
  module registered and what capabilities each advertises. Workflow
  skills consult it to decide whether to run deep analytics or honestly
  report ``analytics_not_available_for_<platform>``. No parameters, no
  network, no filesystem — just a snapshot of the in-process registry.
- ``mureo_analytics_run`` (#440) — actually *invoke* a registered
  module's capability (``detect_anomalies`` / ``diagnose_performance`` /
  ``audit_creative`` / ``analyze_budget_efficiency``). Before this
  existed a plugin could advertise a capability via ``modules_list`` but
  had no way to have its analysis run, so plugin analytics logic was
  dead code. The dispatch is credential-lazy (the module builds its
  client only when invoked), read-only (diagnostics never mutate), and
  fault-isolated (a broken module returns a structured error rather than
  crashing the workflow). No new plugin ABI: it drives the existing
  ``AnalyticsModule`` protocol.

Both tools route through the standard analysis dispatcher so they
participate in the same handler-call audit path as other analysis tools.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from enum import Enum
from typing import Any

from mcp.types import TextContent, Tool

from mureo.analytics.models import PerformanceScope
from mureo.analytics.protocol import AnalyticsCapability
from mureo.analytics.registry import (
    default_analytics_registry,
    discover_analytics_modules,
    get_analytics_module,
    plugin_source,
)
from mureo.core.control_flow import STOP_EXCEPTIONS
from mureo.core.platform_keys import (
    is_plugin_platform_key,
    plugin_platform_key,
    plugin_platform_key_matches,
    plugin_platform_parts,
)
from mureo.mcp._helpers import _require

logger = logging.getLogger(__name__)

TOOLS: list[Tool] = [
    Tool(
        name="mureo_analytics_modules_list",
        description=(
            "List analytics modules registered for each integrated "
            "platform. Returns one entry per platform with its "
            "advertised capabilities (detect_anomalies, "
            "diagnose_performance, audit_creative, "
            "analyze_budget_efficiency). Workflow skills consult this "
            "to decide whether to run deep analytics for a platform or "
            "honestly report `analytics_not_available_for_<platform>`. "
            "Built-in (google_ads, meta_ads) and plugin-supplied "
            "modules appear in the same shape. `platform` is the "
            "canonical platform key — the same key STATE.json's "
            "`platforms` map and action_log entries use, which for a "
            "plugin-supplied module is "
            "`plugin:<distribution>:<registry_name>`; look analytics up "
            "by that key. One distribution can ship several platforms, "
            "so the key carries both halves. `registry_name` is the "
            "entry-point name the module registered itself under and "
            "`source_distribution` the pip distribution that shipped "
            "it; neither is a key on its own (for a built-in, "
            "`registry_name` equals `platform`)."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="mureo_analytics_run",
        description=(
            "Run one capability of the analytics module registered for a "
            "platform and return its structured result. Use after "
            "mureo_analytics_modules_list confirms the platform advertises "
            "the capability. capability is one of detect_anomalies, "
            "diagnose_performance, audit_creative, "
            "analyze_budget_efficiency, detect_delivery_collapse. "
            "detect_delivery_collapse (#546) flags campaigns whose delivery "
            "collapsed while their status still says they should be serving; "
            "its result carries status=ok | no_credentials | data_unavailable "
            "— only status=ok means an empty signals list is an all-clear. "
            "window_days applies only to "
            "detect_anomalies (trailing window, default 7); scope applies "
            "only to diagnose_performance (account | campaign | deep, "
            "default account); both are ignored for the other capabilities "
            "(detect_delivery_collapse uses its own multi-week history "
            "window, because a same-weekday baseline needs weeks of daily "
            "data). "
            "Read-only diagnostics — never mutates the ad account. Returns "
            "status=ok with a result payload, or a structured status "
            "(no_analytics_module / capability_not_available / error) that "
            "the caller reports without failing the workflow."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": (
                        "Canonical platform key (e.g. google_ads, meta_ads, "
                        "or plugin:<distribution>:<registry_name> for a "
                        "plugin platform). Pass the `platform` value "
                        "mureo_analytics_modules_list reported — the same key "
                        "STATE.json platforms uses. The older "
                        "plugin:<distribution> form is still accepted."
                    ),
                },
                "capability": {
                    "type": "string",
                    "enum": sorted(c.value for c in AnalyticsCapability),
                    "description": "Which analytics method to invoke.",
                },
                "account_id": {
                    "type": "string",
                    "description": "Account identifier passed to the module.",
                },
                "window_days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Trailing window for detect_anomalies (default 7). "
                        "Ignored by other capabilities."
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": sorted(s.value for s in PerformanceScope),
                    "description": (
                        "Diagnosis depth for diagnose_performance (default "
                        "account). Ignored by other capabilities."
                    ),
                },
            },
            "required": ["platform", "capability", "account_id"],
            "additionalProperties": False,
        },
    ),
]


async def _handle_modules_list(
    _arguments: dict[str, Any],
) -> list[TextContent]:
    """Return registered analytics modules as JSON text."""
    all_capabilities = sorted(c.value for c in AnalyticsCapability)
    payload: list[dict[str, Any]] = []
    # Shared traversal (triggers discovery, sorted, warns on a distribution
    # claimed by two registry names) so the listing and the resolver can
    # never disagree about membership or the tie-break.
    for registry_name, module, distribution in _registry_entries():
        caps = module.capabilities()
        # Issues #481 / #537: report the CANONICAL platform key, not the
        # name the module happens to be registered under. For a
        # plugin-supplied module that key is ``plugin:<dist>:<registry
        # name>`` — what STATE.json, the action_log promoter, and the
        # dashboard all join on — so a skill holding a STATE.json key
        # resolves analytics for it. The registry name is BOTH the second
        # half of the key and reported alongside as ``registry_name`` (it
        # is what ``mureo_analytics_run`` was historically keyed by), and a
        # built-in, having no plugin source, keeps its registry name as
        # the platform key so both fields are always present.
        platform = (
            plugin_platform_key(distribution, registry_name)
            if distribution
            else registry_name
        )
        payload.append(
            {
                "platform": platform,
                "registry_name": registry_name,
                "capabilities": sorted(c.value for c in caps),
                "source_distribution": distribution,
                "all_capabilities": all_capabilities,
            }
        )

    return [TextContent(type="text", text=json.dumps({"modules": payload}))]


def _jsonable(value: Any) -> Any:
    """Recursively convert an analytics result model into JSON-native data.

    Frozen dataclasses become dicts, enums become their ``.value``, and
    tuples become lists — so the mixed ``tuple[dataclass, ...]`` /
    nested-tuple shapes the models use serialize deterministically without
    leaking ``repr`` artifacts.
    """
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


async def _invoke_capability(
    module: Any,
    capability: AnalyticsCapability,
    account_id: str,
    *,
    window_days: int,
    scope: PerformanceScope,
) -> Any:
    """Call the module method that ``capability`` names and return its result.

    ``window_days`` is forwarded only to ``detect_anomalies`` and ``scope``
    only to ``diagnose_performance``; the other capabilities take just
    ``account_id`` (extra params are ignored, matching the tool contract).
    """
    if capability is AnalyticsCapability.DETECT_ANOMALIES:
        return await module.detect_anomalies(account_id, window_days=window_days)
    if capability is AnalyticsCapability.DIAGNOSE_PERFORMANCE:
        return await module.diagnose_performance(account_id, scope=scope)
    if capability is AnalyticsCapability.AUDIT_CREATIVE:
        return await module.audit_creative(account_id)
    if capability is AnalyticsCapability.DETECT_DELIVERY_COLLAPSE:
        # No ``window_days``: a same-weekday baseline needs weeks of daily
        # history, so the module's own multi-week window applies and the
        # 7-day default that suits detect_anomalies would silently make
        # the baseline unusable.
        return await module.detect_delivery_collapse(account_id)
    return await module.analyze_budget_efficiency(account_id)


def _text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload))]


def _registry_entries() -> list[tuple[str, Any, str]]:
    """Return ``(registry_name, module, distribution)`` in sorted-name order.

    One traversal shared by the listing and the resolver so both agree on
    membership and on the tie-break. ``registry.platforms()`` is already
    sorted, which is what makes duplicate-distribution resolution
    deterministic (see :func:`_warn_on_duplicate_distributions`).
    """
    # Idempotent + cached; the resolver may be the first caller in-process.
    discover_analytics_modules()

    registry = default_analytics_registry()
    entries: list[tuple[str, Any, str]] = []
    for registry_name in registry.platforms():
        module = registry.get(registry_name)
        if module is None:  # pragma: no cover — defensive
            continue
        entries.append((registry_name, module, plugin_source(module)))

    _warn_on_duplicate_distributions(entries)
    return entries


def _warn_on_duplicate_distributions(entries: list[tuple[str, Any, str]]) -> None:
    """Log when one distribution ships modules under several registry names.

    Still needed after #537, for a *different* reason than it was written
    for. It no longer reports a collision on the canonical key: that key
    now carries the registry name (``plugin:<dist>:<registry name>``), so
    each of these modules has its own, and shipping several analytics
    modules from one distribution is a legitimate packaging choice rather
    than a mistake.

    What it reports now is that the **legacy** ``plugin:<dist>`` key —
    still valid on read, and what state written before #537 holds —
    cannot name one of these modules. mureo does not guess: the listing
    emits every entry under its own canonical key (so the unambiguous
    key an operator should move to is visible), and
    :func:`_resolve_module` resolves a legacy key to the
    alphabetically-first registry name, unchanged from #481. Log it
    rather than absorb it — silently running one of two modules is the
    failure mode #481 is about. Once per call; not a hot path.
    """
    by_distribution: dict[str, list[str]] = {}
    for registry_name, _module, distribution in entries:
        if distribution:
            by_distribution.setdefault(distribution, []).append(registry_name)

    for distribution, registry_names in by_distribution.items():
        if len(registry_names) > 1:
            logger.warning(
                "analytics distribution %r registered %d modules (%s) — each "
                "has its own canonical platform key (%s), but the legacy key "
                "%r cannot name one of them, so a caller passing it gets %r "
                "by sorted registry name; pass the canonical key instead",
                distribution,
                len(registry_names),
                ", ".join(registry_names),
                ", ".join(
                    repr(plugin_platform_key(distribution, name))
                    for name in registry_names
                ),
                plugin_platform_key(distribution),
                registry_names[0],
            )


def _resolve_module(platform: str) -> Any | None:
    """Resolve the module a ``platform`` value names (#481, #537).

    ``mureo_analytics_modules_list`` reports the canonical key
    (``plugin:<dist>:<registry name>`` for a plugin module) and the tool
    contract says to call ``mureo_analytics_run`` with what that listing
    reported — but the registry is keyed by each module's own registry
    name, so the two need reconciling.

    The two input shapes are resolved by **disjoint** paths, never by
    falling through from one to the other:

    - A plugin platform key resolves **only** by matching the source
      distribution (and, when the key names one, the registry name).
      The distribution is authoritative because mureo derives it from
      the entry point rather than taking it from the module. Unmatched ⇒
      ``None``. Crucially there is no direct-registry attempt first: a
      module registered under a *literal* ``plugin:<other-dist>`` name
      would otherwise win by name and hijack that distribution's key.
      (Registration refuses that shape outright — this is the second,
      independent layer.)
    - Anything else (a registry name, a built-in key) uses the direct
      registry lookup, unchanged.

    The legacy ``plugin:<dist>`` short form keeps resolving, so state and
    skills written before #537 keep working. It names a distribution
    rather than a platform: with one module for that distribution it is
    exact, and with several it takes the first in sorted registry-name
    order — unchanged from #481, and logged by
    :func:`_warn_on_duplicate_distributions`.

    ``None`` means no module — the caller turns that into the
    ``no_analytics_module`` status.
    """
    if is_plugin_platform_key(platform):
        distribution, _provider = plugin_platform_parts(platform)
        for registry_name, module, module_distribution in _registry_entries():
            if module_distribution != distribution:
                continue
            if plugin_platform_key_matches(platform, distribution, registry_name):
                return module
        return None

    return get_analytics_module(platform)


async def _handle_analytics_run(arguments: dict[str, Any]) -> list[TextContent]:
    """Invoke one capability of a platform's analytics module (#440).

    Returns a structured status rather than raising for the expected
    "cannot run" cases (unknown platform, capability not advertised, module
    failure) so a workflow skill can degrade gracefully. Malformed input is
    already rejected by the tool's inputSchema before dispatch.
    """
    # ``_require`` mirrors the other MCP handlers; the schema already enforces
    # these, but a bypassing caller gets a clear ValueError, not a KeyError.
    platform = _require(arguments, "platform")
    account_id = _require(arguments, "account_id")
    # ``capability`` / ``scope`` are enum-constrained by the schema.
    capability = AnalyticsCapability(_require(arguments, "capability"))
    window_days = int(arguments.get("window_days", 7))
    scope = PerformanceScope(arguments.get("scope", PerformanceScope.ACCOUNT.value))

    # Credential-lazy: the module builds its client only when a method runs.
    module = _resolve_module(platform)
    if module is None:
        return _text(
            {
                "status": "no_analytics_module",
                "platform": platform,
                "capability": capability.value,
            }
        )

    # Everything that touches the (possibly third-party) module — capability
    # introspection, the async invocation, AND serializing its result — is
    # inside the fault boundary: a module that raises OR returns a
    # non-JSON-serializable object becomes a structured error, never a raw
    # exception escaping to the MCP framework. ``CancelledError`` is a
    # BaseException and MUST propagate so structured-concurrency cleanup runs
    # (mirrors mureo.learning.federation).
    try:
        advertised = module.capabilities()
        if capability not in advertised:
            return _text(
                {
                    "status": "capability_not_available",
                    "platform": platform,
                    "capability": capability.value,
                    "available_capabilities": sorted(c.value for c in advertised),
                }
            )
        result = await _invoke_capability(
            module,
            capability,
            account_id,
            window_days=window_days,
            scope=scope,
        )
        return _text(
            {
                "status": "ok",
                "platform": platform,
                "capability": capability.value,
                "account_id": account_id,
                "source_distribution": plugin_source(module),
                "result": _jsonable(result),
            }
        )
    except STOP_EXCEPTIONS:
        raise
    except BaseException as exc:  # noqa: BLE001 — per-module fault isolation
        return _text(
            {
                "status": "error",
                "platform": platform,
                "capability": capability.value,
                "error_type": type(exc).__name__,
                "detail": str(exc),
            }
        )


_HANDLERS = {
    "mureo_analytics_modules_list": _handle_modules_list,
    "mureo_analytics_run": _handle_analytics_run,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch an analytics-registry tool call."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)


__all__ = ["TOOLS", "handle_tool"]
