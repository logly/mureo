"""Warning categories a strict deployment can promote to errors.

Top-level and import-free on purpose. A deployment that wants a plugin fault
to be fatal has to name the category *before* the fault happens:

    import warnings

    from mureo.plugin_warnings import PluginToolWarning

    warnings.filterwarnings("error", category=PluginToolWarning)

    from mureo.mcp.server import main  # now raises on a plugin fault

While this class lived in :mod:`mureo.mcp.tool_provider`, that sequence could
not work: importing anything under ``mureo.mcp`` runs ``mureo/mcp/__init__.py``,
which imports the server, so the plugin faults were already reported by the time
the filter was installed — the documented strict mode silently did nothing
(#807 review). ``-W error::...`` is no help either; the interpreter cannot
import a third-party category while parsing ``-W`` and skips the option with
``Invalid -W option ignored``.

So this module imports nothing from ``mureo`` and must keep it that way.
:mod:`mureo.mcp.tool_provider` re-exports the name for compatibility.
"""

from __future__ import annotations

__all__ = ["PluginToolWarning"]


class PluginToolWarning(UserWarning):
    """Emitted when a plugin's MCP tools are degraded or skipped.

    Raised for a plugin that cannot be instantiated, whose ``mcp_tools()``
    fails, whose tool name collides with a built-in or another plugin's, or
    whose ``inputSchema`` cannot be compiled (that last one costs the tool its
    input validation; the tool still dispatches).

    A distinct subclass so a strict deployment can opt into
    ``warnings.filterwarnings("error", category=PluginToolWarning)`` and refuse
    to start instead.
    """
