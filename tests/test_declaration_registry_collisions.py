"""#589: a declaration-registry collision must never be silent.

The three registries in :mod:`mureo.policy.declarations` are keyed by BARE
tool name, with no plugin or distribution identity, and every one of them is
last-write-wins. Two things are pinned here:

1. **The collection layer already drops the duplicate.**
   :func:`~mureo.mcp.tool_provider.collect_plugin_tools` dedupes plugin tool
   names first-wins *before* ``_PLUGIN_SEMANTICS`` is built, so a second
   distribution shipping the same tool name never reaches the registries at
   all — the surviving tool keeps its OWN declaration and the dropped one
   contributes nothing. What was missing is that the drop did not name the
   two distributions involved, so an operator could not see whose guardrail
   went away. The message must now name both, and it must not be fatal.

2. **A direct re-registration under the same name is announced.**
   ``register_budget_declaration`` / ``register_bid_declaration`` /
   ``register_read_only_hint`` are public API (re-exported from
   ``mureo.policy.strategy_gate`` for the sibling bridges), so an out-of-tree
   caller can still replace a declaration the collection layer got right.
   Last write still wins — reversing that would silently break a deliberate
   override — but a CONFLICTING write is logged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest
from mcp.types import TextContent, Tool

from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import ProviderEntry
from mureo.mcp.tool_provider import PluginToolWarning, collect_plugin_tools
from mureo.policy.declarations import (
    _BID_DECLARATIONS,
    _BUDGET_DECLARATIONS,
    _READ_ONLY_HINTS,
    BidDeclaration,
    BudgetDeclaration,
    bid_declaration_for,
    budget_declaration_for,
    declared_read_only_hint,
    register_bid_declaration,
    register_budget_declaration,
    register_read_only_hint,
    reset_bid_declarations,
    reset_budget_declarations,
    reset_read_only_hints,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

DECLARATIONS_LOGGER = "mureo.policy.declarations"
TOOL_PROVIDER_LOGGER = "mureo.mcp.tool_provider"


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    """Isolate the three process-global registries WITHOUT destroying them.

    ``mureo.mcp.server`` populates them once at import from real plugin
    discovery, and a developer machine with bridges installed has non-empty
    ones; a destructive clear would drop those for the rest of the session.
    """
    saved_budget = dict(_BUDGET_DECLARATIONS)
    saved_bid = dict(_BID_DECLARATIONS)
    saved_hints = dict(_READ_ONLY_HINTS)
    reset_budget_declarations()
    reset_bid_declarations()
    reset_read_only_hints()
    yield
    reset_budget_declarations()
    reset_bid_declarations()
    reset_read_only_hints()
    _BUDGET_DECLARATIONS.update(saved_budget)
    _BID_DECLARATIONS.update(saved_bid)
    _READ_ONLY_HINTS.update(saved_hints)


# ---------------------------------------------------------------------------
# (1) A conflicting re-registration is logged; an identical one is not.
# ---------------------------------------------------------------------------


def test_conflicting_budget_registration_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_budget_declaration("update_campaign", BudgetDeclaration(daily_key="a"))
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_budget_declaration("update_campaign", BudgetDeclaration(daily_key="b"))
    message = "\n".join(r.getMessage() for r in caplog.records)
    assert "update_campaign" in message
    # Both sides quoted: an operator cannot act on "something changed".
    assert "'a'" in message
    assert "'b'" in message


def test_conflicting_budget_registration_still_takes_the_last_write(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Announced, not refused — reversing this breaks a deliberate override."""
    register_budget_declaration("update_campaign", BudgetDeclaration(daily_key="a"))
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_budget_declaration("update_campaign", BudgetDeclaration(daily_key="b"))
    declaration = budget_declaration_for("update_campaign")
    assert declaration is not None
    assert declaration.daily_key == "b"


def test_identical_budget_re_registration_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A re-discovery re-registers the same value; that is not a collision."""
    register_budget_declaration("update_campaign", BudgetDeclaration(daily_key="a"))
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_budget_declaration("update_campaign", BudgetDeclaration(daily_key="a"))
    assert caplog.records == []


def test_first_budget_registration_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_budget_declaration("update_campaign", BudgetDeclaration(daily_key="a"))
    assert caplog.records == []


def test_conflicting_bid_registration_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_bid_declaration("update_bid", BidDeclaration(cpc_bid_key="a"))
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_bid_declaration("update_bid", BidDeclaration(cpc_bid_key="b"))
    message = "\n".join(r.getMessage() for r in caplog.records)
    assert "update_bid" in message
    assert "'a'" in message
    assert "'b'" in message
    declaration = bid_declaration_for("update_bid")
    assert declaration is not None
    assert declaration.cpc_bid_key == "b"


def test_identical_bid_re_registration_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_bid_declaration("update_bid", BidDeclaration(cpc_bid_key="a"))
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_bid_declaration("update_bid", BidDeclaration(cpc_bid_key="a"))
    assert caplog.records == []


def test_conflicting_read_only_hint_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one that flips a mutation into a "read" and drops both its gates."""
    register_read_only_hint("update_campaign", False)
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_read_only_hint("update_campaign", True)
    message = "\n".join(r.getMessage() for r in caplog.records)
    assert "update_campaign" in message
    assert "False" in message
    assert "True" in message
    assert declared_read_only_hint("update_campaign") is True


def test_identical_read_only_hint_re_registration_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_read_only_hint("update_campaign", False)
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_read_only_hint("update_campaign", False)
    assert caplog.records == []


def test_registering_a_hint_over_an_absent_one_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``False`` is a declared value, not "absent" — absence must not warn."""
    with caplog.at_level(logging.WARNING, logger=DECLARATIONS_LOGGER):
        register_read_only_hint("update_campaign", False)
    assert caplog.records == []
    assert declared_read_only_hint("update_campaign") is False


# ---------------------------------------------------------------------------
# (2) The collection-time duplicate names both distributions, and is survivable.
# ---------------------------------------------------------------------------

_SHARED_TOOL = "update_campaign"


def _colliding_tool() -> Tool:
    return Tool(
        name=_SHARED_TOOL,
        description="moves money",
        inputSchema={"type": "object", "properties": {}},
        annotations={"readOnlyHint": False},  # type: ignore[arg-type]
        _meta={"mureo": {"budget": {"daily": "daily_budget"}}},
    )


class _FirstProvider:
    name = "acme_ads"
    display_name = "Acme Ads"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})

    def mcp_tools(self) -> tuple[Tool, ...]:
        return (_colliding_tool(),)

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        return [TextContent(type="text", text="acme")]


class _SecondProvider:
    name = "zenith_ads"
    display_name = "Zenith Ads"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})

    def mcp_tools(self) -> tuple[Tool, ...]:
        return (_colliding_tool(),)

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        return [TextContent(type="text", text="zenith")]


def _entry(cls: type, distribution: str | None) -> ProviderEntry:
    return ProviderEntry(
        name=cls.name,
        display_name=cls.display_name,
        capabilities=cls.capabilities,
        provider_class=cls,
        source_distribution=distribution,
    )


def _discover_colliding_pair() -> Any:
    def _fn(**_kw: Any) -> tuple[ProviderEntry, ...]:
        return (
            _entry(_FirstProvider, "mureo-acme-bridge"),
            _entry(_SecondProvider, "mureo-zenith-bridge"),
        )

    return _fn


def test_duplicate_tool_name_warning_names_both_distributions() -> None:
    with pytest.warns(PluginToolWarning) as caught:
        collect_plugin_tools(reserved_names=set(), discover=_discover_colliding_pair())
    message = "\n".join(str(w.message) for w in caught)
    assert "mureo-acme-bridge" in message
    assert "mureo-zenith-bridge" in message
    assert _SHARED_TOOL in message


def test_duplicate_tool_name_is_logged_not_only_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stderr ``warnings`` line an MCP client swallows is not a signal."""
    with (
        caplog.at_level(logging.WARNING, logger=TOOL_PROVIDER_LOGGER),
        pytest.warns(PluginToolWarning),
    ):
        collect_plugin_tools(reserved_names=set(), discover=_discover_colliding_pair())
    message = "\n".join(r.getMessage() for r in caplog.records)
    assert "mureo-acme-bridge" in message
    assert "mureo-zenith-bridge" in message
    assert _SHARED_TOOL in message


def test_duplicate_tool_name_does_not_take_the_server_down() -> None:
    """Deliberate: one bad plugin pair must not stop mureo from starting."""
    with pytest.warns(PluginToolWarning):
        tools, dispatch = collect_plugin_tools(
            reserved_names=set(), discover=_discover_colliding_pair()
        )
    assert [t.name for t in tools] == [_SHARED_TOOL]
    assert type(dispatch[_SHARED_TOOL]).__name__ == "_FirstProvider"


def test_an_unknown_distribution_is_labelled_not_rendered_as_none() -> None:
    def _fn(**_kw: Any) -> tuple[ProviderEntry, ...]:
        return (
            _entry(_FirstProvider, None),
            _entry(_SecondProvider, "mureo-zenith-bridge"),
        )

    with pytest.warns(PluginToolWarning) as caught:
        collect_plugin_tools(reserved_names=set(), discover=_fn)
    message = "\n".join(str(w.message) for w in caught)
    assert "None" not in message
    assert "unknown" in message


def test_the_dropped_duplicate_contributes_no_declaration() -> None:
    """The premise #589 assumed was broken, pinned as the reason it is not.

    ``_PLUGIN_SEMANTICS`` is built from the tool list ``collect_plugin_tools``
    returns, and that list already holds ONE tool per name. So the registry
    ends up with the declaration of the tool that is actually dispatchable —
    the two can never disagree — and re-keying by identity would buy nothing
    a bare name does not already give.
    """
    from mureo.mcp.plugin_semantics import derive_semantics
    from mureo.mcp.server import (
        _register_plugin_budget_declarations,
        _register_plugin_read_only_hints,
    )

    with pytest.warns(PluginToolWarning):
        tools, dispatch = collect_plugin_tools(
            reserved_names=set(), discover=_discover_colliding_pair()
        )
    semantics = {t.name: derive_semantics(t) for t in tools}
    assert len(semantics) == 1

    _register_plugin_budget_declarations(semantics)
    _register_plugin_read_only_hints(semantics)

    declaration = budget_declaration_for(_SHARED_TOOL)
    assert declaration is not None
    assert declaration.daily_key == "daily_budget"
    assert declared_read_only_hint(_SHARED_TOOL) is False
    # The winner of the registry is the winner of dispatch, by construction.
    assert type(dispatch[_SHARED_TOOL]).__name__ == "_FirstProvider"
