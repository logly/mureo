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
* **Builtin tools only.** Plugin-provided tools (entry-point plugins, logly
  bridges, etc.) are out of scope — their schemas are owned by the plugin
  author, and ``_tool_validation.LazyToolValidators`` already tolerates a
  permissive plugin schema (and checks it at startup, where the author can see
  it). Two sources of builtin tools are used, deliberately:
  :func:`_all_builtin_tools` reads the registry modules, which is where a schema
  is *authored* and is unaffected by env gating; :func:`_server_builtin_tools`
  takes ``server._ALL_TOOLS`` minus the plugin names, which is what the server
  *validates*. They are not the same objects — ``_reason_param`` rebuilds every
  mutating tool with an extra property — so a check that only reads the registry
  is one rewrite away from the thing it claims to cover.
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


def _server_builtin_tools():
    """Return the builtin tools the server actually validates.

    ``server._ALL_TOOLS`` after ``inject_reason_params`` — which REBINDS the
    catalog with rebuilt ``Tool`` objects for every mutating tool — with the
    plugin-owned names removed. This is the exact set
    ``server._TOOL_VALIDATORS`` is built from, minus the part this test does not
    own.
    """
    from mureo.mcp import server

    return [tool for tool in server._ALL_TOOLS if tool.name not in server._PLUGIN_NAMES]


@pytest.mark.unit
def test_every_builtin_tool_schema_is_a_valid_json_schema() -> None:
    """Every builtin tool's inputSchema passes the Draft 2020-12 metaschema.

    ``_tool_validation.LazyToolValidators`` compiles a tool's validator on that
    tool's first call rather than for the whole catalog at import, because the
    metaschema check costs a median of 3.1 ms per tool and 0.82 s summed over
    the 228-tool catalog (the 2026-10-08 measurement quoted, with its method, in
    ``mureo/mcp/_tool_validation.py``) and the server has an MCP connect budget
    to meet (#807). A malformed **builtin** schema is therefore reported on first use
    instead of at startup: in production the right trade, but it would let an
    authoring mistake reach a release unnoticed. This test is where that is
    caught instead, in CI, and it checks both the schema as authored (the
    registry module's ``Tool``) and the schema as served (the server's catalog,
    after the ``reason`` property is injected into every mutating tool) — the
    second being the one the server compiles, and a different object. (A
    *plugin's* schema is still checked at startup: a plugin author never gets a
    run of this suite.)
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    sources = {
        "as authored (registry module)": _all_builtin_tools(),
        "as served (server catalog)": _server_builtin_tools(),
    }
    offenders = []
    for label, tools in sources.items():
        assert tools, f"no builtin tools found {label}"
        for tool in tools:
            try:
                Draft202012Validator.check_schema(tool.inputSchema)
            except SchemaError as exc:
                offenders.append((label, tool.name, str(exc).splitlines()[0]))
    assert not offenders, (
        "These builtin tool schemas are not valid JSON Schema, so the server "
        "would skip input validation for them (and log a warning on their "
        f"first call):\n{offenders}"
    )
