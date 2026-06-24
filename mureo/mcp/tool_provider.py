"""Plugin → MCP tool exposure layer (Issue #89 follow-up: P1 wiring).

The provider registry (``mureo.core.providers.registry``) already
discovers third-party providers via the ``mureo.providers``
entry-point group, and the skill matcher gates them by capability.
What was missing was the *MCP boundary*: a discovered provider had no
way to surface its operations as ``mcp__mureo__*`` tools.

This module adds that boundary, deliberately as an **opt-in secondary
Protocol** rather than expanding ``BaseProvider`` (whose docstring
mandates exactly this: "new behaviour should be added via secondary
Protocols"). A provider that wants MCP exposure *also* implements
:class:`MCPToolProvider`; one that doesn't is still discovered and
skill-matched, just not exposed as tools (graceful, no crash).

Design constraints
------------------
- **Additive**: built-in platforms (google_ads, meta_ads, …) keep
  their static ``TOOLS`` and are *not* routed through here. Only
  entry-point–discovered providers contribute plugin tools, so there
  is no double-exposure.
- **Credential-free introspection**: ``mcp_tools()`` MUST be a pure,
  static description (no network, no API key). Providers resolve
  credentials lazily when a tool is actually *invoked*, so the server
  starts even when a plugin's secrets are absent.
- **No-arg constructible**: a provider class exposed for MCP must be
  instantiable with no arguments (lazy config). This mirrors the
  registry's "instantiation deferred to consumers" contract.
- **Fault isolation**: a broken plugin (raising on import, construct,
  or ``mcp_tools()``) is skipped with a :class:`PluginToolWarning`; it
  can never crash the MCP server *via a raised exception* (including
  ``SystemExit`` — ``KeyboardInterrupt`` is deliberately re-raised).
  A plugin that *hangs* (infinite loop, blocking I/O in ``__init__``
  or ``mcp_tools()``) is outside this boundary's control — that is an
  inherent property of synchronous entry-point discovery, pre-existing
  in the registry, not a guarantee this layer can make.
- **Built-ins win on name collision**; first plugin wins on
  plugin↔plugin collision — mirroring the registry's dedupe policy so
  a later-installed plugin cannot shadow a core tool.
"""

from __future__ import annotations

import contextlib
import inspect
import warnings
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from mcp.types import Tool

    from mureo.core.providers.registry import ProviderEntry


class PluginToolWarning(UserWarning):
    """Emitted when a plugin's MCP tools are skipped.

    A distinct subclass so strict deployments can opt into
    ``warnings.filterwarnings("error", category=PluginToolWarning)``.
    """


@runtime_checkable
class MCPToolProvider(Protocol):
    """Opt-in contract for exposing a provider's operations as MCP tools.

    Implemented *in addition to* a domain Protocol (e.g.
    ``CampaignProvider``). The two methods intentionally mirror the
    shape every built-in platform module already uses
    (``TOOLS`` + ``async handle_tool``), so the server dispatch path
    is uniform.
    """

    def mcp_tools(self) -> tuple[Tool, ...]:
        """Return this provider's MCP tool definitions.

        MUST be pure and credential-free — called at server start to
        build the tool list. No network, no secret access.
        """
        ...

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        """Execute the named tool. Called only for names this provider
        contributed via :meth:`mcp_tools`.
        """
        ...


@runtime_checkable
class MCPReversibleToolProvider(Protocol):
    """Opt-in contract for **runtime-correct** reversal capture (#327).

    A static ``meta["mureo"]["reversal"]`` on a :class:`Tool` is fixed at
    server-start and therefore cannot carry the actual entity id of *this*
    call, nor the entity's *prior* state — so it is useless for a real
    status toggle (``set_ad_status(ad_id, status)``) or value edit. This
    secondary Protocol closes that gap, mirroring mureo's native
    before-state capture (:mod:`mureo.mcp.native_reversal`): the provider —
    which owns the platform client and entity knowledge — builds the
    reversal itself, capturing any prior state via its own read.

    A provider opts in by *also* implementing this method. mureo calls it
    **before** a mutating tool runs; the returned reversal (if any) is what
    gets recorded into the ``action_log`` instead of the static ``meta``
    reversal. The reversal's ``operation`` must name a registered,
    non-destructive tool of the same plugin for ``rollback_apply`` to
    execute it (the rollback planner enforces this — see
    :mod:`mureo.rollback.planner`).
    """

    async def capture_reversal(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Return ``{"operation": <tool>, "params": {...}}`` that reverses the
        mutation ``name`` is *about to* perform, or ``None`` when it is not
        reversible.

        Called **before** :meth:`MCPToolProvider.handle_mcp_tool`, so an
        implementation can read the entity's prior state (e.g. GET the
        current status) and bake a runtime-correct reversal. MUST be
        best-effort from the caller's view: mureo swallows any exception so a
        capture failure never blocks the actual mutation — but the
        implementation should still avoid slow/expensive work on the hot
        path.
        """
        ...


def _warn(message: str) -> None:
    warnings.warn(message, PluginToolWarning, stacklevel=3)


def collect_plugin_tools(
    *,
    reserved_names: Iterable[str],
    discover: Callable[..., tuple[ProviderEntry, ...]] | None = None,
) -> tuple[list[Tool], dict[str, MCPToolProvider]]:
    """Discover entry-point providers and collect their MCP tools.

    Args:
        reserved_names: Tool names already owned by built-in platforms.
            Plugin tools colliding with these are dropped (built-ins
            win) so a plugin can never shadow a core tool.
        discover: Injectable discovery function (defaults to the
            registry's entry-point discovery). Tests pass a stub;
            production uses the real registry.

    Returns:
        ``(tools, dispatch)`` where ``tools`` is the ordered list of
        plugin :class:`Tool` objects to append to the server's tool
        list, and ``dispatch`` maps each plugin tool name to the
        provider instance that handles it.

    Never raises: total discovery failure or any per-plugin fault is
    contained and reported via :class:`PluginToolWarning`.
    """
    reserved = set(reserved_names)
    tools: list[Tool] = []
    dispatch: dict[str, MCPToolProvider] = {}

    if discover is None:
        # Resolve live (not via default-arg binding) so a monkeypatched
        # registry — and module reloads — are honoured at call time.
        from mureo.core.providers import registry as _registry

        discover = _registry.discover_providers

    try:
        entries = discover()
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 — server must still start
        # BaseException (not just Exception): a plugin's discovery hook
        # raising SystemExit must not abort MCP server startup. Only
        # KeyboardInterrupt is honoured.
        _warn(f"provider discovery failed; no plugin tools loaded: {exc!r}")
        return tools, dispatch

    for entry in entries:
        _collect_one(entry, reserved, tools, dispatch)

    return tools, dispatch


def _collect_one(
    entry: ProviderEntry,
    reserved: set[str],
    tools: list[Tool],
    dispatch: dict[str, MCPToolProvider],
) -> None:
    """Instantiate one provider and absorb its tools, fault-isolated."""
    label = entry.name

    try:
        instance = entry.provider_class()
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 — one bad plugin, not fatal
        _warn(
            f"provider {label!r}: not instantiable with no arguments; "
            f"skipped for MCP exposure ({exc!r})"
        )
        return

    if not isinstance(instance, MCPToolProvider):
        # Discovered & skill-matchable, just no MCP surface. Not a fault.
        return

    # Stamp the originating distribution onto the instance so the server
    # dispatch path can attribute audit records without changing the
    # (test-depended-on) collect_plugin_tools return signature. Best-
    # effort: some objects forbid attribute assignment (__slots__).
    with contextlib.suppress(AttributeError, TypeError):
        instance._mureo_source_distribution = entry.source_distribution  # type: ignore[attr-defined]

    # ``runtime_checkable`` only proves the attributes exist, not that
    # ``handle_mcp_tool`` is awaitable. The server dispatch path
    # (``await provider.handle_mcp_tool(...)``) is NOT fault-isolated,
    # so reject a sync/non-coroutine handler here, at collection time,
    # rather than letting it surface as an unhandled TypeError mid-call.
    if not inspect.iscoroutinefunction(getattr(instance, "handle_mcp_tool", None)):
        _warn(
            f"provider {label!r}: handle_mcp_tool must be an async "
            f"coroutine function; skipped for MCP exposure"
        )
        return

    try:
        provider_tools = tuple(instance.mcp_tools())
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 — one bad plugin, not fatal
        _warn(f"provider {label!r}: mcp_tools() failed; skipped ({exc!r})")
        return

    for tool in provider_tools:
        tool_name = getattr(tool, "name", None)
        if not isinstance(tool_name, str) or not tool_name:
            _warn(f"provider {label!r}: a tool has no usable name; skipped")
            continue
        if tool_name in reserved:
            _warn(
                f"provider {label!r}: tool {tool_name!r} collides with a "
                f"built-in tool; plugin tool dropped (built-in wins)"
            )
            continue
        if tool_name in dispatch:
            _warn(
                f"provider {label!r}: tool {tool_name!r} already provided by "
                f"an earlier plugin; duplicate dropped (first wins)"
            )
            continue
        tools.append(tool)
        dispatch[tool_name] = instance


def plugin_source(provider: object) -> str:
    """Return the pip distribution that supplied ``provider``.

    Read back the breadcrumb stamped in ``_collect_one``. Empty string
    when unknown (older instance, ``__slots__``, or a non-plugin).
    """
    value = getattr(provider, "_mureo_source_distribution", "")
    return value if isinstance(value, str) else ""


__all__ = [
    "MCPReversibleToolProvider",
    "MCPToolProvider",
    "PluginToolWarning",
    "collect_plugin_tools",
    "plugin_source",
]
