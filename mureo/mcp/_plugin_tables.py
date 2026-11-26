"""The plugin tool maps, below :mod:`mureo.mcp.server` (#879).

``server`` imports :mod:`mureo.mcp._journal_hook` at load, and the hook reads
the plugin maps to classify a call. Holding the dict objects here, below
both, lets the hook import them at top level instead of reaching back into
the half-initialised ``server``. The third table, ``_SERVING_PROVIDERS``, is
here for the same reason: the platform handlers that read it are imported by
``server``.

Only the objects live here. ``server`` still fills them in its module body,
at load, IN PLACE (``clear`` then ``update``): the env-gating suite
re-triggers the whole registration by ``importlib.reload``-ing ``server``,
and refilling the same objects is what keeps every holder of them —
``server`` itself, the journal hook, a test that reached the map through
``mureo.mcp.server._PLUGIN_DISPATCH`` — answering from the current run.

A test that wants the journal hook to see a fake entry must change the dict
here in place (``monkeypatch.setitem``) or reload ``server``: rebinding
``server._PLUGIN_DISPATCH`` with ``monkeypatch.setattr`` replaces only
``server``'s name, and the hook keeps reading this object.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.mcp.plugin_semantics import ToolSemantics
    from mureo.mcp.serving_providers import ServingProvider
    from mureo.mcp.tool_provider import MCPToolProvider

#: Plugin tool name → the provider that serves it. Filled by ``server`` from
#: ``collect_plugin_tools`` at load.
_PLUGIN_DISPATCH: dict[str, MCPToolProvider] = {}

#: Plugin tool name → its derived safety semantics (#114). Filled by
#: ``server`` from the collected plugin tools at load.
_PLUGIN_SEMANTICS: dict[str, ToolSemantics] = {}

#: Built-in platform → the plugin providers serving it under their own tool
#: prefix (``serves_platform``), only for platforms whose built-in family this
#: run serves. Filled by ``server`` from
#: :func:`mureo.mcp.serving_providers.serving_providers` at load; read by the
#: handlers' no-credentials messages, which sit below ``server``.
_SERVING_PROVIDERS: dict[str, tuple[ServingProvider, ...]] = {}
