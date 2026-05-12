"""Unit tests for ``mureo.mcp.server`` env-var-driven tool gating.

When ``MUREO_DISABLE_GOOGLE_ADS`` / ``MUREO_DISABLE_META_ADS`` /
``MUREO_DISABLE_GA4`` are set to the exact string ``"1"`` in the process
environment at mureo-MCP-server import time, the server must exclude the
corresponding tool families from ``_ALL_TOOLS`` and from the per-namespace
dispatch tables. Search Console is *always* registered regardless of env
vars (mureo is canonical for SC; no official MCP exists).

Tests use ``monkeypatch.setenv`` + ``importlib.reload`` to re-trigger the
module-level evaluation. A function-scoped ``reload_mcp_server_clean``
fixture reloads with the env vars stripped on teardown so cross-test
contamination is impossible.

See planner HANDOFF ``feat-providers-cli-phase1.md`` → "Disable-mureo
Extension" → ``tests/test_mcp_server_env_gating.py`` test plan.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_DISABLE_ENV_VARS = (
    "MUREO_DISABLE_GOOGLE_ADS",
    "MUREO_DISABLE_META_ADS",
    "MUREO_DISABLE_GA4",
    "MUREO_DISABLE_SEARCH_CONSOLE",  # deliberately unhonored — defensive
)


@pytest.fixture
def reload_mcp_server_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Yield, then reload ``mureo.mcp.server`` with all DISABLE env vars cleared.

    Each gating test sets one or more ``MUREO_DISABLE_*`` env vars and reloads
    the server module to re-trigger module-level env reads. On teardown this
    fixture strips every DISABLE env var and reloads once more so subsequent
    tests / test files see the default-all-enabled state. ``monkeypatch``
    autoreverts process-env mutations at scope end, but module-level constants
    on ``mureo.mcp.server`` (``_ALL_TOOLS`` etc.) are not reverted by
    monkeypatch — only by an explicit reload.
    """
    yield
    # Teardown: ensure no DISABLE env var leaks to the next test.
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    import mureo.mcp.server as server_mod

    importlib.reload(server_mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_server() -> Any:
    """Reload ``mureo.mcp.server`` and return the module object."""
    import mureo.mcp.server as server_mod

    return importlib.reload(server_mod)


def _tool_names(server_mod: Any) -> set[str]:
    """Return the set of tool names registered in ``_ALL_TOOLS``."""
    return {t.name for t in server_mod._ALL_TOOLS}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_env_var_means_all_tools_registered(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
) -> None:
    """With no ``MUREO_DISABLE_*`` env vars set, every tool family registers.

    Regression guard: the default (env-var-absent) behavior must match
    today's baseline exactly so users who never touched ``mureo providers``
    see no change.
    """
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    server_mod = _reload_server()
    names = _tool_names(server_mod)

    # At least one tool from each family is present.
    assert any(n.startswith("google_ads_") for n in names)
    assert any(n.startswith("meta_ads_") for n in names)
    assert any(n.startswith("search_console_") for n in names)
    # Total count is positive and matches the current production baseline.
    assert len(server_mod._ALL_TOOLS) >= 100


@pytest.mark.unit
def test_google_ads_tools_skipped_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
) -> None:
    """``MUREO_DISABLE_GOOGLE_ADS=1`` removes all ``google_ads_*`` tools."""
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUREO_DISABLE_GOOGLE_ADS", "1")

    server_mod = _reload_server()
    names = _tool_names(server_mod)

    assert not any(n.startswith("google_ads_") for n in names), (
        "no google_ads_* tool should remain when MUREO_DISABLE_GOOGLE_ADS=1; "
        f"found: {sorted(n for n in names if n.startswith('google_ads_'))}"
    )
    # Other families are unaffected.
    assert any(n.startswith("meta_ads_") for n in names)
    assert any(n.startswith("search_console_") for n in names)


@pytest.mark.unit
def test_meta_ads_tools_skipped_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
) -> None:
    """``MUREO_DISABLE_META_ADS=1`` removes all ``meta_ads_*`` tools."""
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUREO_DISABLE_META_ADS", "1")

    server_mod = _reload_server()
    names = _tool_names(server_mod)

    assert not any(n.startswith("meta_ads_") for n in names), (
        "no meta_ads_* tool should remain when MUREO_DISABLE_META_ADS=1; "
        f"found: {sorted(n for n in names if n.startswith('meta_ads_'))}"
    )
    assert any(n.startswith("google_ads_") for n in names)
    assert any(n.startswith("search_console_") for n in names)


@pytest.mark.unit
def test_ga4_env_set_is_currently_noop_but_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
) -> None:
    """``MUREO_DISABLE_GA4=1`` is wired in but a no-op today (no GA4 tools).

    Forward-compat guarantee: setting the env var must not raise during
    module reload and must not affect other tool families. Once mureo ships
    native GA4 tools, this test will be expanded to assert exclusion.
    """
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUREO_DISABLE_GA4", "1")

    server_mod = _reload_server()
    names = _tool_names(server_mod)

    # Other families still present.
    assert any(n.startswith("google_ads_") for n in names)
    assert any(n.startswith("meta_ads_") for n in names)
    assert any(n.startswith("search_console_") for n in names)


@pytest.mark.unit
def test_search_console_always_registered_regardless_of_env(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
) -> None:
    """``MUREO_DISABLE_SEARCH_CONSOLE`` is deliberately unhonored.

    Search Console has no official MCP equivalent — mureo is canonical for
    it. Even with every other ``MUREO_DISABLE_*`` env var set AND a
    defensive (unsupported) ``MUREO_DISABLE_SEARCH_CONSOLE=1`` set, the
    Search Console tools must remain registered.
    """
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUREO_DISABLE_GOOGLE_ADS", "1")
    monkeypatch.setenv("MUREO_DISABLE_META_ADS", "1")
    monkeypatch.setenv("MUREO_DISABLE_GA4", "1")
    monkeypatch.setenv("MUREO_DISABLE_SEARCH_CONSOLE", "1")  # deliberately ignored

    server_mod = _reload_server()
    names = _tool_names(server_mod)

    assert "search_console_sites_list" in names, (
        "Search Console tools must always be registered "
        "(no MUREO_DISABLE_SEARCH_CONSOLE support)"
    )
    # Negative side: the other three families ARE disabled.
    assert not any(n.startswith("google_ads_") for n in names)
    assert not any(n.startswith("meta_ads_") for n in names)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_value",
    ["0", "", "true", "yes", "True", "  1  "],
)
def test_truthy_coercion_does_not_disable(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
    raw_value: str,
) -> None:
    """Only the exact string ``"1"`` disables. Anything else keeps tools on.

    Locks in the exact-string comparison contract documented in the
    planner spec. Whitespace-padded ``"  1  "`` is included because a
    permissive ``str.strip().lower() == "1"`` coercion would falsely
    disable — we want the exact ``== "1"`` comparison.
    """
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUREO_DISABLE_GOOGLE_ADS", raw_value)

    server_mod = _reload_server()
    names = _tool_names(server_mod)

    assert any(n.startswith("google_ads_") for n in names), (
        f"value {raw_value!r} must NOT disable google_ads tools — only "
        f"the exact string '1' is honored"
    )


@pytest.mark.unit
def test_all_three_set_disables_three_keeps_search_console(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
) -> None:
    """All three DISABLE vars set ⇒ only Search Console (+ rollback/analysis/context) remain."""
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUREO_DISABLE_GOOGLE_ADS", "1")
    monkeypatch.setenv("MUREO_DISABLE_META_ADS", "1")
    monkeypatch.setenv("MUREO_DISABLE_GA4", "1")

    server_mod = _reload_server()
    names = _tool_names(server_mod)

    assert not any(n.startswith("google_ads_") for n in names)
    assert not any(n.startswith("meta_ads_") for n in names)
    assert any(n.startswith("search_console_") for n in names)
    # mureo-specific families (rollback / analysis / context) must remain.
    assert any("rollback" in n for n in names)


@pytest.mark.unit
async def test_handle_call_tool_unknown_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    reload_mcp_server_clean: None,
) -> None:
    """Dispatcher raises ``ValueError`` for disabled-tool calls.

    When ``MUREO_DISABLE_META_ADS=1`` is set, the corresponding handler
    must never even be invoked — ``handle_call_tool`` rejects the name
    with ``ValueError("Unknown tool: ...")`` before dispatch.
    """
    for var in _DISABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUREO_DISABLE_META_ADS", "1")

    server_mod = _reload_server()

    with pytest.raises(ValueError, match="Unknown tool"):
        await server_mod.handle_call_tool(
            "meta_ads_campaigns_list", {"account_id": "act_1"}
        )
