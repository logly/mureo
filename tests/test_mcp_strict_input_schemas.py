"""Regression guard: every builtin MCP tool's inputSchema must close its
top-level object with ``additionalProperties: false``.

Historically these schemas omitted ``additionalProperties``, so unknown
parameters passed server-side validation (``server._validate_tool_input``)
and were then silently discarded by each handler's explicit
``_opt``/``_require`` whitelist. A caller who mistyped a parameter name
(``budgett`` for ``budget``) got a silent no-op instead of an error — a
real, field-reported footgun. Declaring ``additionalProperties: false``
turns that silent drop into an explicit validation failure.

Scope decisions:

* **Top level only.** This test asserts the *top-level* object schema is
  closed. Nested object properties (e.g. Meta's ``targeting`` blob) are
  intentionally left open: they mirror the platform Graph/GAQL sub-object
  surfaces, which evolve independently of mureo releases, and closing them
  would reject valid forward-compatible sub-fields the handler forwards
  wholesale. Only the top-level parameter set is a fixed, handler-owned
  whitelist, so only the top level is closed.
* **Builtin registries only.** Plugin-provided tools (entry-point plugins,
  logly bridges, etc.) are out of scope — their schemas are owned by the
  plugin author, and ``server._build_tool_validators`` already tolerates a
  permissive plugin schema. This test imports the builtin registry modules
  directly rather than the assembled ``server._ALL_TOOLS`` so the plugin
  surface never leaks in.
"""

from __future__ import annotations

import pytest


def _all_builtin_tools():
    """Return every Tool from the nine builtin registries.

    Imported straight from the registry modules (not ``server._ALL_TOOLS``)
    so env-gating and plugin tools cannot affect the set under test.
    """
    from mureo.mcp import (
        tools_analysis,
        tools_analytics_registry,
        tools_creative_studio,
        tools_google_ads,
        tools_learning,
        tools_meta_ads,
        tools_mureo_context,
        tools_rollback,
        tools_search_console,
    )

    out = []
    for mod in (
        tools_google_ads,
        tools_meta_ads,
        tools_search_console,
        tools_rollback,
        tools_analysis,
        tools_mureo_context,
        tools_analytics_registry,
        tools_learning,
        tools_creative_studio,
    ):
        out.extend(mod.TOOLS)
    return out


@pytest.mark.unit
def test_every_builtin_tool_declares_additional_properties_false() -> None:
    """Every builtin tool's top-level inputSchema is closed.

    A tool whose top-level schema omits ``additionalProperties: false`` lets
    unknown parameters through server-side validation, where the handler
    then silently drops them. Any newly added tool that forgets this fails
    here immediately.
    """
    offenders = []
    for tool in _all_builtin_tools():
        schema = getattr(tool, "inputSchema", None)
        if not isinstance(schema, dict):
            offenders.append((tool.name, "no inputSchema dict"))
            continue
        if schema.get("type") != "object":
            # Every builtin tool schema is an object; flag anything else so
            # the assumption stays true.
            offenders.append((tool.name, f"top-level type={schema.get('type')!r}"))
            continue
        if schema.get("additionalProperties") is not False:
            offenders.append(
                (
                    tool.name,
                    f"additionalProperties={schema.get('additionalProperties')!r}",
                )
            )
    assert not offenders, (
        "These builtin tool schemas do not declare "
        '`"additionalProperties": False` at the top level, so unknown '
        "parameters pass validation and are silently dropped by the "
        f"handler whitelist:\n{offenders}"
    )
