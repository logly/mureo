"""Exact, DECLARED money enforcement for the bridged Amazon surface (#527).

Native writes are capped by exact argument keys compiled into mureo; bridged
writes were capped by a best-effort pattern scan over argument NAMES. This
suite covers the third thing: mureo declaring the exact nested paths of a
bridged surface itself (:mod:`mureo.amazon_ads.money_paths`), fed through the
same declaration registry a plugin uses, with the pattern fallback preserved
for everything not in the table.

What is pinned here:

- the path mechanism (:class:`~mureo.policy.declarations.ArgumentPaths`) —
  array fan-out with a MAXIMUM across matches, the explicit dynamic-map
  wildcard, and strict resolution that yields "not found" rather than a
  neighbouring value;
- the table itself — exactly the 62 money leaves across 13 tools that were
  enumerated from a real 85-tool manifest, single-sourced from the enumeration
  in ``test_strategy_gate_pattern_fallback`` so the two cannot drift apart,
  plus a schema check against the operator's real manifest when one exists;
- enforcement through the DECLARATION rather than the scan (every test here
  that claims "the declaration did it" runs with the pattern scan stubbed to
  find nothing, so a pass cannot be the fallback in disguise);
- the FLOOR contract — a path declaration never causes LESS to be checked than
  the best-effort scan alone would have checked, so a declared tool's drifted
  or newly-added money field is still capped;
- and that a flat-key declaration (every ``_meta`` one) behaves exactly as it
  did before, scan suppression included.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mureo.amazon_ads.money_paths import (
    BID_DECLARATIONS,
    BID_PATHS,
    BUDGET_DECLARATIONS,
    BUDGET_PATHS,
    TOOL_NAMESPACE,
)
from mureo.policy import declaration_resolution as dr
from mureo.policy import strategy_gate as sg
from mureo.policy.declarations import _Descent, _parse_path
from mureo.policy.pattern_scan import (
    PatternAmount,
    has_pattern_fallback,
    register_pattern_fallback_tool,
    reset_pattern_fallback_tools,
)
from mureo.policy.strategy_gate import (
    ArgumentPaths,
    BidDeclaration,
    BudgetDeclaration,
    Guardrails,
    bid_declaration_for,
    budget_declaration_for,
    evaluate_guardrails,
)
from tests.test_strategy_gate_pattern_fallback import (
    _ADD_COUNTRY_MARKETPLACES,
    _REAL_MONEY_LEAVES,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_BUDGET_CAPS = Guardrails(max_daily_budget_per_campaign=10_000)
_BID_CAPS = Guardrails(max_bid_amount_per_ad_set=500)

#: Over every cap above, so a payload built at a declared path must deny.
_OVER_CAP = 25_000.0
_UNDER_CAP = 100.0


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    """Isolate the process-global registries WITHOUT destroying them.

    ``mureo.mcp.server`` populates all three once at import from real plugin
    discovery; a destructive clear would drop those registrations for the rest
    of the pytest session.
    """
    from mureo.policy.declarations import (
        _BID_DECLARATIONS,
        _BUDGET_DECLARATIONS,
        reset_bid_declarations,
        reset_budget_declarations,
    )
    from mureo.policy.pattern_scan import _PATTERN_FALLBACK_TOOLS

    saved_budget = dict(_BUDGET_DECLARATIONS)
    saved_bid = dict(_BID_DECLARATIONS)
    saved_fallback = set(_PATTERN_FALLBACK_TOOLS)
    reset_budget_declarations()
    reset_bid_declarations()
    reset_pattern_fallback_tools()
    yield
    reset_budget_declarations()
    reset_bid_declarations()
    reset_pattern_fallback_tools()
    _BUDGET_DECLARATIONS.update(saved_budget)
    _BID_DECLARATIONS.update(saved_bid)
    _PATTERN_FALLBACK_TOOLS.update(saved_fallback)


@pytest.fixture
def _no_pattern_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the best-effort scan find NOTHING, whatever the payload.

    The distinguishing move for every "the declaration did it" assertion in
    this file: with the scan blinded, a deny can only have come from a declared
    path. Without this, a payload built at a declared path would also match the
    pattern vocabulary and the test would prove nothing new.
    """
    monkeypatch.setattr(dr, "scan_budget_amount", lambda _arguments: PatternAmount())
    monkeypatch.setattr(dr, "scan_bid_amount", lambda _arguments: PatternAmount())


def _payload_for(spec: str, amount: Any, *, map_key: str = "US") -> dict[str, Any]:
    """Expand one declared path spec into the smallest payload carrying it.

    ``a.b[].c`` → ``{"a": {"b": [{"c": amount}]}}``; a ``*`` segment becomes one
    concrete map key, which is exactly the shape the wildcard exists to reach.
    """
    node: Any = amount
    for segment in reversed(spec.split(".")):
        if segment == "*":
            node = {map_key: node}
        elif segment.endswith("[]"):
            node = {segment[:-2]: [node]}
        else:
            node = {segment: node}
    assert isinstance(node, dict)
    return node


#: ``(family, tool, spec)`` for every declared path in the table.
_DECLARED_PATHS: list[tuple[str, str, str]] = [
    ("budget", tool, spec) for tool, specs in BUDGET_PATHS.items() for spec in specs
] + [("bid", tool, spec) for tool, specs in BID_PATHS.items() for spec in specs]


# ---------------------------------------------------------------------------
# The path mechanism
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPathParsing:
    def test_object_keys_and_arrays(self) -> None:
        assert _parse_path("body.campaigns[].value") == (
            "body",
            "campaigns",
            _Descent.ITEMS,
            "value",
        )

    def test_a_wildcard_is_its_own_segment(self) -> None:
        assert _parse_path("a.*.value") == ("a", _Descent.VALUES, "value")

    @pytest.mark.parametrize(
        "spec", ["", "a..b", "a.[].b", "a.b*", "a.*x", "a.b[]c", "."]
    )
    def test_a_malformed_spec_fails_loudly(self, spec: str) -> None:
        """A typo must not compile into a path that silently never matches —
        that is an unenforced cap wearing a declaration's clothes."""
        with pytest.raises(ValueError):
            _parse_path(spec)

    def test_a_declaration_needs_at_least_one_path(self) -> None:
        with pytest.raises(ValueError):
            ArgumentPaths.parse()


@pytest.mark.unit
class TestPathResolution:
    def _read(self, spec: str, arguments: dict[str, Any]) -> Any:
        from mureo.policy.declarations import _declared_amount

        return _declared_amount(arguments, ArgumentPaths.parse(spec), micros=False)

    def test_an_array_resolves_element_wise_and_takes_the_maximum(self) -> None:
        """The cap must be checked against the LARGEST amount the call
        proposes — the same contract the pattern scan reports."""
        payload = {"body": {"campaigns": [{"v": 100}, {"v": 25_000}, {"v": 900}]}}
        assert self._read("body.campaigns[].v", payload) == 25_000

    def test_a_wildcard_resolves_every_map_value(self) -> None:
        payload = {"caps": {"US": {"value": 100}, "JP": {"value": 25_000}}}
        assert self._read("caps.*.value", payload) == 25_000

    def test_a_map_level_is_never_guessed(self) -> None:
        """Without an explicit ``*`` the map key is an ordinary key, so the
        path does NOT resolve — the wildcard is opt-in by design."""
        payload = {"caps": {"US": {"value": 25_000}}}
        assert self._read("caps.value", payload) is None

    def test_a_missing_level_never_matches_something_adjacent(self) -> None:
        """``budgets`` is absent, and a ``value`` sits one level over. The
        declaration must report NOT FOUND rather than cap the neighbour."""
        payload = {"body": {"campaigns": [{"budgetValue": {"value": 25_000}}]}}
        assert self._read("body.campaigns[].budgets[].value", payload) is None

    def test_an_array_step_requires_an_actual_array(self) -> None:
        assert (
            self._read("body.campaigns[].v", {"body": {"campaigns": {"v": 5}}}) is None
        )

    def test_a_wildcard_step_requires_an_actual_object(self) -> None:
        assert self._read("caps.*.value", {"caps": [{"value": 5}]}) is None

    def test_a_stringified_amount_is_read(self) -> None:
        assert self._read("a.b", {"a": {"b": "1500"}}) == 1500.0

    def test_garbage_at_a_resolved_leaf_fails_closed(self) -> None:
        from mureo.policy.declarations import _Unreadable

        result = self._read("a.b", {"a": {"b": "over nine thousand"}})
        assert isinstance(result, _Unreadable)
        assert result.key == "a.b"

    def test_a_non_finite_amount_fails_closed(self) -> None:
        from mureo.policy.declarations import _Unreadable

        assert isinstance(self._read("a.b", {"a": {"b": float("inf")}}), _Unreadable)

    def test_one_bad_element_among_many_fails_closed(self) -> None:
        from mureo.policy.declarations import _Unreadable

        payload = {"a": [{"b": 100}, {"b": "nope"}]}
        assert isinstance(self._read("a[].b", payload), _Unreadable)

    def test_a_container_at_the_leaf_reads_as_not_found(self) -> None:
        """Shape drift, not content garbage: the number moved deeper. Reported
        as "not found" so the caller can degrade to the best-effort scan and
        cap the amount actually proposed, rather than refuse a call whose money
        nobody looked at."""
        assert self._read("a.b", {"a": {"b": {"amount": 25_000}}}) is None

    def test_micros_are_divided_like_a_flat_declared_key(self) -> None:
        from mureo.policy.declarations import _declared_amount

        payload = {"a": {"b": 5_000_000}}
        assert _declared_amount(payload, ArgumentPaths.parse("a.b"), micros=True) == 5.0

    def test_several_paths_on_one_channel_take_the_maximum(self) -> None:
        from mureo.policy.declarations import _declared_amount

        paths = ArgumentPaths.parse("a.b", "c.d")
        assert (
            _declared_amount({"a": {"b": 1}, "c": {"d": 9}}, paths, micros=False) == 9
        )


# ---------------------------------------------------------------------------
# The table, against the real manifest enumeration
# ---------------------------------------------------------------------------


def _declared_leaves() -> set[tuple[str, str, str]]:
    """Every ``(family, tool, leaf path)`` the shipped table declares.

    The wildcard is expanded over the marketplace codes the manifest
    enumeration lists, so the result is directly comparable to it.
    """
    leaves: set[tuple[str, str, str]] = set()
    for family, tool, spec in _DECLARED_PATHS:
        if "*" in spec:
            leaves.update(
                (family, tool, spec.replace("*", code))
                for code in _ADD_COUNTRY_MARKETPLACES
            )
        else:
            leaves.add((family, tool, spec))
    return leaves


@pytest.mark.unit
class TestTableMatchesTheManifestEnumeration:
    """The table must cover the real money surface EXACTLY.

    Single-sourced from ``_REAL_MONEY_LEAVES`` — the 62 leaves enumerated from
    one operator's real 85-tool manifest — so a path invented here, or one
    quietly dropped, fails rather than shrinking coverage in silence.
    """

    def test_the_declared_leaves_are_exactly_the_enumerated_ones(self) -> None:
        assert _declared_leaves() == set(_REAL_MONEY_LEAVES)

    def test_the_leaf_count_is_the_enumerated_62(self) -> None:
        assert len(_declared_leaves()) == 62

    def test_all_thirteen_money_tools_are_declared(self) -> None:
        declared = set(BUDGET_PATHS) | set(BID_PATHS)
        assert declared == {tool for _, tool, _ in _REAL_MONEY_LEAVES}
        assert len(declared) == 13

    def test_every_declaration_is_registered_under_the_bridged_name(self) -> None:
        assert set(BUDGET_DECLARATIONS) == {TOOL_NAMESPACE + t for t in BUDGET_PATHS}
        assert set(BID_DECLARATIONS) == {TOOL_NAMESPACE + t for t in BID_PATHS}

    def test_both_cap_channels_carry_the_paths(self) -> None:
        """A schema path cannot say whether an amount is a daily or a period
        total, so — like the scan it replaces — it is held to both caps."""
        budget = BUDGET_DECLARATIONS[TOOL_NAMESPACE + "update_campaign"]
        assert budget.daily_key == budget.lifetime_key
        bid = BID_DECLARATIONS[TOOL_NAMESPACE + "update_target_bid"]
        assert bid.bid_amount_key == bid.cpc_bid_key


# ---------------------------------------------------------------------------
# The table, against a real manifest's inputSchema
# ---------------------------------------------------------------------------

#: The three verdicts. ``unknown`` exists so the check can be strict without
#: crying wolf: a construct this walker does not resolve (a ``$ref``, a
#: schema that declares no ``properties`` at all and therefore permits
#: anything) means "cannot judge", never "absent".
_DECLARED, _ABSENT, _UNKNOWN = "declared", "absent", "unknown"

#: Amazon wraps its budget objects in ``oneOf`` branches, so a walker that
#: stopped at a combinator could judge barely half the table.
_COMBINATORS = ("oneOf", "anyOf", "allOf")

_STRUCTURAL = ("properties", "items", "additionalProperties", "patternProperties")


def _schema_declares(schema: Any, steps: tuple[Any, ...]) -> str:
    """Does ``schema`` declare the property chain ``steps``?

    A combinator's branches are each tried whole: the path exists if ANY
    branch declares it, because a value is free to take that branch.
    """
    if not isinstance(schema, dict):
        return _ABSENT
    if "$ref" in schema:
        return _UNKNOWN
    if not steps:
        return _DECLARED
    verdicts = {
        _schema_declares(branch, steps)
        for keyword in _COMBINATORS
        for branch in _branches(schema, keyword)
    }
    if any(key in schema for key in _STRUCTURAL):
        verdicts.add(_step_verdict(schema, steps[0], steps[1:]))
    if _DECLARED in verdicts:
        return _DECLARED
    if not verdicts or _UNKNOWN in verdicts:
        return _UNKNOWN
    return _ABSENT


def _branches(schema: dict[str, Any], keyword: str) -> list[Any]:
    raw = schema.get(keyword)
    return raw if isinstance(raw, list) else []


def _step_verdict(schema: dict[str, Any], step: Any, rest: tuple[Any, ...]) -> str:
    """One resolution step against one schema node."""
    if isinstance(step, str):
        if schema.get("type") == "array":
            return _ABSENT  # an object key asked of an array level
        props = schema.get("properties")
        if not isinstance(props, dict):
            return _UNKNOWN  # declares no properties ⇒ permits anything
        return _schema_declares(props[step], rest) if step in props else _ABSENT
    if step is _Descent.ITEMS:
        items = schema.get("items")
        return _schema_declares(items, rest) if isinstance(items, dict) else _ABSENT
    children = list((schema.get("properties") or {}).values()) or list(
        (schema.get("patternProperties") or {}).values()
    )
    if not children:
        extra = schema.get("additionalProperties")
        return _schema_declares(extra, rest) if isinstance(extra, dict) else _ABSENT
    verdicts = {_schema_declares(child, rest) for child in children}
    if _ABSENT in verdicts:
        return _ABSENT
    return _UNKNOWN if _UNKNOWN in verdicts else _DECLARED


#: The real ``update_campaign`` budget shape, trimmed to what the checker
#: walks. Proof that the checker judges the shape the table was derived from.
_REAL_SHAPE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "body": {
            "type": "object",
            "properties": {
                "campaigns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "budgets": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "budgetValue": {
                                            "type": "object",
                                            "properties": {
                                                "monetaryBudgetValue": {
                                                    "type": "object",
                                                    "properties": {
                                                        "monetaryBudget": {
                                                            "type": "object",
                                                            "properties": {
                                                                "value": {
                                                                    "type": "number",
                                                                    "minimum": 1,
                                                                }
                                                            },
                                                        }
                                                    },
                                                }
                                            },
                                        }
                                    },
                                },
                            }
                        },
                    },
                }
            },
        }
    },
}

_REAL_SHAPE_PATH = (
    "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue.monetaryBudget.value"
)


@pytest.mark.unit
class TestSchemaChecker:
    """The checker is proven here so the manifest test below means something."""

    def test_it_finds_a_path_the_schema_declares(self) -> None:
        steps = _parse_path(_REAL_SHAPE_PATH)
        assert _schema_declares(_REAL_SHAPE, steps) == _DECLARED

    def test_it_reports_a_path_the_schema_does_not_declare(self) -> None:
        steps = _parse_path(_REAL_SHAPE_PATH.replace("monetaryBudget", "moneyBudget"))
        assert _schema_declares(_REAL_SHAPE, steps) == _ABSENT

    def test_an_array_level_must_really_be_an_array(self) -> None:
        steps = _parse_path(_REAL_SHAPE_PATH.replace("budgets[]", "budgets"))
        # ``budgets`` is declared, but its ``items`` are skipped, so the next
        # key is looked up on the array schema itself and is not there.
        assert _schema_declares(_REAL_SHAPE, steps) == _ABSENT

    def test_a_wildcard_walks_every_declared_country(self) -> None:
        country = {
            "type": "object",
            "properties": {"value": {"type": "number", "maximum": 1_000_000}},
        }
        schema = {"type": "object", "properties": {"US": country, "JP": country}}
        assert _schema_declares(schema, _parse_path("*.value")) == _DECLARED
        assert _schema_declares(schema, _parse_path("*.amount")) == _ABSENT

    def test_an_unresolvable_construct_is_never_reported_as_absent(self) -> None:
        schema = {"type": "object", "properties": {"body": {"$ref": "#/$defs/Body"}}}
        assert _schema_declares(schema, _parse_path("body.campaigns")) == _UNKNOWN


@pytest.mark.unit
def test_every_declared_path_exists_in_the_operators_manifest() -> None:
    """The provenance check, against a REAL manifest when the machine has one.

    CI has no Amazon manifest, so this skips there; on an operator's machine it
    is the check that catches the table drifting away from the surface it was
    derived from. Tools the manifest does not carry are skipped rather than
    failed — an account need not expose all 85.
    """
    from mureo.amazon_ads.manifest import manifest_path

    path = manifest_path()
    if not path.is_file():
        pytest.skip("no Amazon manifest on this machine")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        schemas = {
            tool["name"]: tool.get("inputSchema")
            for tool in raw.get("tools", [])
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
    except (OSError, ValueError, TypeError, AttributeError) as exc:  # pragma: no cover
        pytest.skip(f"unreadable Amazon manifest: {exc}")
    checked = 0
    for _family, tool, spec in _DECLARED_PATHS:
        schema = schemas.get(TOOL_NAMESPACE + tool)
        if schema is None:
            continue
        checked += 1
        verdict = _schema_declares(schema, _parse_path(spec))
        assert (
            verdict != _ABSENT
        ), f"{TOOL_NAMESPACE + tool}: {spec} is not in the schema"
    if checked == 0:  # pragma: no cover — a manifest with none of the 13 tools
        pytest.skip("the manifest carries none of the money-carrying tools")


# ---------------------------------------------------------------------------
# Enforcement THROUGH the declaration
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.usefixtures("_no_pattern_scan")
class TestDeclaredEnforcement:
    """Every declared path caps a real payload — via the declaration.

    The pattern scan is stubbed to find nothing for the whole class, so a deny
    here cannot be the best-effort fallback wearing the declaration's name.
    """

    @pytest.mark.parametrize(
        ("family", "tool", "spec"),
        _DECLARED_PATHS,
        ids=[f"{t}:{s}" for _, t, s in _DECLARED_PATHS],
    )
    def test_an_over_cap_amount_at_a_declared_path_is_denied(
        self, family: str, tool: str, spec: str
    ) -> None:
        name = TOOL_NAMESPACE + tool
        over_cap = _OVER_CAP if family == "budget" else 900.0
        decision = evaluate_guardrails(
            name,
            _payload_for(spec, over_cap),
            _BUDGET_CAPS if family == "budget" else _BID_CAPS,
            budget_declaration=BUDGET_DECLARATIONS.get(name),
            bid_declaration=BID_DECLARATIONS.get(name),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        expected = (
            "max_daily_budget_per_campaign"
            if family == "budget"
            else "max_bid_amount_per_ad_set"
        )
        assert expected in (decision.reason or "")

    @pytest.mark.parametrize(
        ("family", "tool", "spec"),
        _DECLARED_PATHS,
        ids=[f"{t}:{s}" for _, t, s in _DECLARED_PATHS],
    )
    def test_the_same_payload_is_unenforced_without_the_declaration(
        self, family: str, tool: str, spec: str
    ) -> None:
        """The control for the test above: with the scan blinded and no
        declaration, nothing caps this call — so the deny above was the
        declared path and only the declared path."""
        decision = evaluate_guardrails(
            TOOL_NAMESPACE + tool,
            _payload_for(spec, _OVER_CAP if family == "budget" else 900.0),
            _BUDGET_CAPS if family == "budget" else _BID_CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is True

    @pytest.mark.parametrize(
        ("family", "tool", "spec"),
        _DECLARED_PATHS,
        ids=[f"{t}:{s}" for _, t, s in _DECLARED_PATHS],
    )
    def test_an_under_cap_amount_at_a_declared_path_is_allowed(
        self, family: str, tool: str, spec: str
    ) -> None:
        name = TOOL_NAMESPACE + tool
        decision = evaluate_guardrails(
            name,
            _payload_for(spec, _UNDER_CAP),
            _BUDGET_CAPS if family == "budget" else _BID_CAPS,
            budget_declaration=BUDGET_DECLARATIONS.get(name),
            bid_declaration=BID_DECLARATIONS.get(name),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_the_largest_element_of_a_batch_is_what_is_capped(self) -> None:
        name = TOOL_NAMESPACE + "update_campaign"
        spec = BUDGET_PATHS["update_campaign"][0]
        cheap = _payload_for(spec, _UNDER_CAP)
        dear = _payload_for(spec, _OVER_CAP)
        batch = {
            "body": {
                "campaigns": cheap["body"]["campaigns"] + dear["body"]["campaigns"]
            }
        }
        decision = evaluate_guardrails(
            name,
            batch,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[name],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "25,000" in (decision.reason or "")

    def test_the_dynamic_map_wildcard_reaches_every_country(self) -> None:
        name = TOOL_NAMESPACE + "add_country_campaign"
        settings = {code: {"value": _UNDER_CAP} for code in _ADD_COUNTRY_MARKETPLACES}
        settings["JP"] = {"value": _OVER_CAP}
        decision = evaluate_guardrails(
            name,
            {
                "body": {
                    "campaigns": [
                        {"budgetCaps": {"countryMonetaryBudgetSettings": settings}}
                    ]
                }
            },
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[name],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "25,000" in (decision.reason or "")

    def test_garbage_at_a_declared_path_fails_closed_naming_the_path(self) -> None:
        name = TOOL_NAMESPACE + "update_target_bid"
        spec = BID_PATHS["update_target_bid"][0]
        decision = evaluate_guardrails(
            name,
            _payload_for(spec, "very high"),
            _BID_CAPS,
            bid_declaration=BID_DECLARATIONS[name],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert spec in (decision.reason or "")

    def test_a_budget_only_tool_still_gets_the_bid_pattern_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Precedence is per FAMILY: declaring a budget must not switch the bid
        fallback off. ``update_campaign_budget`` is in the budget table and not
        in the bid one, so a bid-shaped argument still has to be caught."""
        monkeypatch.undo()  # the real scan, for the bid family
        name = TOOL_NAMESPACE + "update_campaign_budget"
        assert name not in BID_DECLARATIONS
        decision = evaluate_guardrails(
            name,
            {"body": {"targets": [{"defaultBid": 900}]}},
            _BID_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[name],
            bid_declaration=None,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_bid_amount_per_ad_set" in (decision.reason or "")


# ---------------------------------------------------------------------------
# Honest degradation — a declared path that resolves nothing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDegradesToTheScan:
    """A declared path is derived from a snapshot, so it can go stale.

    The scan therefore runs underneath every path declaration as a FLOOR, so a
    payload the declared paths cannot reach is still capped — precision is what
    drift costs, not enforcement.
    """

    _NAME = TOOL_NAMESPACE + "update_campaign"
    #: Money the declared paths cannot reach: the wrapper objects moved.
    _DRIFTED: dict[str, Any] = {"body": {"campaigns": [{"dailyBudget": _OVER_CAP}]}}

    def test_a_drifted_payload_is_still_capped(self) -> None:
        decision = evaluate_guardrails(
            self._NAME,
            self._DRIFTED,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[self._NAME],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_daily_budget_per_campaign" in (decision.reason or "")

    def test_the_scan_is_what_catches_it(self, _no_pattern_scan: None) -> None:
        """Same call with the scan blinded: nothing is left to catch it, which
        is what makes the test above a fallback test and not a path test."""
        decision = evaluate_guardrails(
            self._NAME,
            self._DRIFTED,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[self._NAME],
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_a_leaf_that_moved_deeper_degrades_the_same_way(self) -> None:
        """The likeliest drift: ``value`` became an object. The path resolves
        to a container, which reads as NOT FOUND, and the scan finds the number
        that actually carries the money."""
        spec = BUDGET_PATHS["update_campaign"][0]
        payload = _payload_for(spec, {"amount": _OVER_CAP})
        decision = evaluate_guardrails(
            self._NAME,
            payload,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[self._NAME],
            pattern_fallback=True,
        )
        assert decision.allowed is False

    def test_a_resolving_declaration_does_not_suppress_the_scan(self) -> None:
        """The FLOOR contract: a declaration that resolved something does NOT
        silence the scan. Before #527 these tools were scanned unconditionally,
        so suppressing the scan here would REMOVE shipped enforcement rather
        than prevent a false positive — and #517 measured zero false positives
        across all 62 money leaves of the real manifest."""
        spec = BUDGET_PATHS["update_campaign"][0]
        payload = _payload_for(spec, _UNDER_CAP)
        payload["stray_budget"] = _OVER_CAP
        decision = evaluate_guardrails(
            self._NAME,
            payload,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[self._NAME],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "25,000" in (decision.reason or "")

    def test_without_the_fallback_registration_there_is_nothing_to_degrade_to(
        self,
    ) -> None:
        decision = evaluate_guardrails(
            self._NAME,
            self._DRIFTED,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[self._NAME],
        )
        assert decision.allowed is True

    def test_the_bid_family_degrades_the_same_way(self) -> None:
        name = TOOL_NAMESPACE + "update_target"
        decision = evaluate_guardrails(
            name,
            {"body": {"targets": [{"bidAmount": 900}]}},
            _BID_CAPS,
            bid_declaration=BID_DECLARATIONS[name],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_bid_amount_per_ad_set" in (decision.reason or "")

    def test_an_exhausted_scan_on_the_drift_path_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Degrading to the scan means degrading to ALL of it, including its
        fail-closed exhaustion: a payload the scan could not finish reading is
        refused with the operator-facing reason, not waved through."""
        from mureo.policy.pattern_scan import SCAN_EXHAUSTED_NODES

        monkeypatch.setattr(
            dr,
            "scan_budget_amount",
            lambda _arguments: PatternAmount(unreadable_key=SCAN_EXHAUSTED_NODES),
        )
        decision = evaluate_guardrails(
            self._NAME,
            self._DRIFTED,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[self._NAME],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "too large" in (decision.reason or "")


# ---------------------------------------------------------------------------
# The FLOOR contract — a path declaration never checks LESS than the scan
# ---------------------------------------------------------------------------

#: Tools that carry two physically INDEPENDENT money fields in one channel, as
#: ``(tool, resolving path, drifted sibling payload, the amount hidden in it)``.
#: Each sibling pair is versionable on its own upstream, so one of them can
#: change shape while the other still resolves — the case that made the earlier
#: "suppress the scan once anything resolved" rule under-enforce.
_SIBLING_DRIFT: list[tuple[str, str, dict[str, Any]]] = [
    (
        "create_ad_group",
        "body.adGroups[].optimization.budgetSettings.dailyMinSpendValue",
        # ``budgets`` arrived as an object where the schema says array, so the
        # declared ``budgets[]…`` path stops resolving while its sibling
        # ``dailyMinSpendValue`` still does.
        {
            "budgets": {
                "budgetValue": {
                    "monetaryBudgetValue": {"monetaryBudget": {"value": _OVER_CAP}}
                }
            }
        },
    ),
    (
        "update_ad_group",
        "body.adGroups[].optimization.budgetSettings.dailyMinSpendValue",
        {
            "budgets": {
                "budgetValue": {
                    "monetaryBudgetValue": {"monetaryBudget": {"value": _OVER_CAP}}
                }
            }
        },
    ),
    (
        "create_campaign",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        # The flight budget's wrapper moved, so ``flights[].budget…`` stops
        # resolving while the plain campaign budget still does.
        {"flights": [{"budget": {"monetaryBudget": {"value": _OVER_CAP}}}]},
    ),
    (
        "update_campaign",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        {"flights": [{"budget": {"monetaryBudget": {"value": _OVER_CAP}}}]},
    ),
]


def _sibling_payload(spec: str, drifted: dict[str, Any]) -> dict[str, Any]:
    """A payload where ``spec`` resolves trivially and ``drifted`` does not."""
    payload = _payload_for(spec, _UNDER_CAP)
    collection = next(iter(payload["body"].values()))
    collection[0].update(drifted)
    return payload


@pytest.mark.unit
class TestScanFloorUnderADeclaration:
    """A path declaration raises the FLOOR; it does not replace the scan.

    The invariant is *never check less than the best-effort scan alone would
    have checked*. Every case here was ALLOWED by the earlier "suppress the
    scan once the declaration resolved anything" rule, while the same payload
    with no declaration at all was denied — i.e. declaring a tool made it less
    safe than #517 had left it.
    """

    @pytest.mark.parametrize(
        ("tool", "spec", "drifted"),
        _SIBLING_DRIFT,
        ids=[t for t, _s, _d in _SIBLING_DRIFT],
    )
    def test_a_drifted_sibling_field_is_still_capped(
        self, tool: str, spec: str, drifted: dict[str, Any]
    ) -> None:
        name = TOOL_NAMESPACE + tool
        payload = _sibling_payload(spec, drifted)
        caps = Guardrails(
            max_daily_budget_per_campaign=_BUDGET_CAPS.max_daily_budget_per_campaign,
            max_lifetime_budget_per_campaign=(
                _BUDGET_CAPS.max_daily_budget_per_campaign
            ),
        )
        decision = evaluate_guardrails(
            name,
            payload,
            caps,
            budget_declaration=BUDGET_DECLARATIONS[name],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "25,000" in (decision.reason or "")

    @pytest.mark.parametrize(
        ("tool", "spec", "drifted"),
        _SIBLING_DRIFT,
        ids=[t for t, _s, _d in _SIBLING_DRIFT],
    )
    def test_the_undeclared_call_was_already_capped(
        self, tool: str, spec: str, drifted: dict[str, Any]
    ) -> None:
        """The baseline the floor protects: #517's scan catches these with no
        declaration at all, so a declaration must never do worse."""
        decision = evaluate_guardrails(
            TOOL_NAMESPACE + tool,
            _sibling_payload(spec, drifted),
            _BUDGET_CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False

    def test_the_declared_amount_wins_when_it_is_the_larger(self) -> None:
        """Declaration > scan: the exact path supplies the figure."""
        spec = BUDGET_PATHS["update_campaign"][0]
        payload = _payload_for(spec, _OVER_CAP)
        payload["stray_budget"] = 17_777.0
        decision = evaluate_guardrails(
            TOOL_NAMESPACE + "update_campaign",
            payload,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[TOOL_NAMESPACE + "update_campaign"],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "25,000" in (decision.reason or "")
        assert "17,777" not in (decision.reason or "")

    def test_the_declared_path_is_quoted_when_its_leaf_is_unreadable(self) -> None:
        """What the declaration buys, and it needs no suppression to buy it:
        the operator is told WHICH declared path carried the garbage."""
        spec = BUDGET_PATHS["update_campaign"][0]
        payload = _payload_for(spec, "not a number")
        payload["stray_budget"] = 5_000.0
        decision = evaluate_guardrails(
            TOOL_NAMESPACE + "update_campaign",
            payload,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[TOOL_NAMESPACE + "update_campaign"],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert spec in (decision.reason or "")

    def test_the_scanned_amount_wins_when_it_is_the_larger(self) -> None:
        """Scan > declaration: the floor lifts the figure the cap sees."""
        spec = BUDGET_PATHS["update_campaign"][0]
        payload = _payload_for(spec, 5_000.0)
        payload["stray_budget"] = _OVER_CAP
        decision = evaluate_guardrails(
            TOOL_NAMESPACE + "update_campaign",
            payload,
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[TOOL_NAMESPACE + "update_campaign"],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "25,000" in (decision.reason or "")

    def test_the_bid_family_takes_the_same_floor(self) -> None:
        name = TOOL_NAMESPACE + "update_target"
        spec = BID_PATHS["update_target"][0]
        payload = _payload_for(spec, 10.0)
        payload["body"]["targets"][0]["legacyBidAmount"] = 900
        decision = evaluate_guardrails(
            name,
            payload,
            _BID_CAPS,
            bid_declaration=BID_DECLARATIONS[name],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_bid_amount_per_ad_set" in (decision.reason or "")

    def test_an_exhausted_scan_denies_even_when_the_declaration_resolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scan that could not finish may be hiding an amount LARGER than the
        declared paths found, so exhaustion outranks a resolved declaration."""
        from mureo.policy.pattern_scan import SCAN_EXHAUSTED_NODES

        monkeypatch.setattr(
            dr,
            "scan_budget_amount",
            lambda _arguments: PatternAmount(unreadable_key=SCAN_EXHAUSTED_NODES),
        )
        spec = BUDGET_PATHS["update_campaign"][0]
        decision = evaluate_guardrails(
            TOOL_NAMESPACE + "update_campaign",
            _payload_for(spec, _UNDER_CAP),
            _BUDGET_CAPS,
            budget_declaration=BUDGET_DECLARATIONS[TOOL_NAMESPACE + "update_campaign"],
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "too large" in (decision.reason or "")

    def test_a_flat_meta_declaration_still_replaces_the_scan(self) -> None:
        """The merge is gated on path declarations ONLY. A plugin that declares
        a flat key owns its argument vocabulary, so a stray budget-named field
        must not false-trip its cap — unchanged from #414."""
        decision = evaluate_guardrails(
            "acme_update",
            {"spend_limit": _UNDER_CAP, "stray_budget": _OVER_CAP},
            _BUDGET_CAPS,
            budget_declaration=BudgetDeclaration(daily_key="spend_limit"),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_a_flat_meta_bid_declaration_still_replaces_the_scan(self) -> None:
        decision = evaluate_guardrails(
            "acme_update",
            {"bid_cap": 10, "stray_bid": 900},
            _BID_CAPS,
            bid_declaration=BidDeclaration(bid_amount_key="bid_cap"),
            pattern_fallback=True,
        )
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Everything NOT in the table keeps the best-effort fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUndeclaredToolsKeepThePatternFallback:
    def test_a_tool_amazon_adds_later_is_still_capped_best_effort(self) -> None:
        name = TOOL_NAMESPACE + "create_experimental_campaign"
        assert name not in BUDGET_DECLARATIONS
        decision = evaluate_guardrails(
            name,
            {"body": {"campaigns": [{"dailyBudget": _OVER_CAP}]}},
            _BUDGET_CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False

    def test_and_its_bids_too(self) -> None:
        decision = evaluate_guardrails(
            TOOL_NAMESPACE + "create_experimental_target",
            {"body": {"targets": [{"bid": {"bid": 900}}]}},
            _BID_CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False


# ---------------------------------------------------------------------------
# Flat-key declarations are untouched
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFlatKeyDeclarationsAreUnchanged:
    """The #414 / bid-twin contract, byte-identical after #527."""

    def test_an_absent_flat_key_still_means_no_proposal(self) -> None:
        """The one behaviour a path declaration changes must NOT leak to a flat
        key: the plugin owns that argument name, so its absence is a fact about
        the call, not drift — no fallback, even with one registered."""
        decision = evaluate_guardrails(
            "acme_update",
            {"stray_budget": _OVER_CAP},
            _BUDGET_CAPS,
            budget_declaration=BudgetDeclaration(daily_key="spend_limit"),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_an_absent_flat_bid_key_still_means_no_proposal(self) -> None:
        decision = evaluate_guardrails(
            "acme_update",
            {"stray_bid": 900},
            _BID_CAPS,
            bid_declaration=BidDeclaration(bid_amount_key="bid_cap"),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_a_flat_key_still_caps(self) -> None:
        decision = evaluate_guardrails(
            "acme_update",
            {"spend_limit": _OVER_CAP},
            _BUDGET_CAPS,
            budget_declaration=BudgetDeclaration(daily_key="spend_limit"),
        )
        assert decision.allowed is False

    def test_a_flat_key_deny_still_quotes_the_key(self) -> None:
        decision = evaluate_guardrails(
            "acme_update",
            {"spend_limit": "nope"},
            _BUDGET_CAPS,
            budget_declaration=BudgetDeclaration(daily_key="spend_limit"),
        )
        assert decision.allowed is False
        assert "'spend_limit'" in (decision.reason or "")

    def test_meta_declarations_still_parse_to_flat_keys(self) -> None:
        from mcp.types import Tool

        from mureo.mcp.plugin_semantics import derive_semantics

        tool = Tool(
            name="acme_ads_update_budget",
            description="x",
            inputSchema={"type": "object", "properties": {}},
            _meta={
                "mureo": {"budget": {"daily": "daily_budget_micros", "unit": "micros"}}
            },
        )
        semantics = derive_semantics(tool)
        assert semantics.budget == BudgetDeclaration(
            daily_key="daily_budget_micros", micros=True
        )


# ---------------------------------------------------------------------------
# Server wiring
# ---------------------------------------------------------------------------


def _semantics_for(*names: str) -> dict[str, Any]:
    """Semantics for tools that declare NOTHING — the manifest-snapshot shape."""
    from mcp.types import Tool

    from mureo.mcp.plugin_semantics import derive_semantics

    tools = [
        Tool(
            name=name, description="x", inputSchema={"type": "object", "properties": {}}
        )
        for name in names
    ]
    return {t.name: derive_semantics(t) for t in tools}


class _StampedProvider:
    """A provider instance carrying the distribution breadcrumb.

    ``collect_plugin_tools`` stamps ``_mureo_source_distribution`` on every
    provider it collects, and that is the only plugin identity the tool name
    itself does not carry — so it is what the bridged table is scoped by.
    """

    def __init__(self, distribution: str) -> None:
        self._mureo_source_distribution = distribution


def _dispatch_for(*names: str, distribution: str | None = None) -> dict[str, Any]:
    """A dispatch map attributing ``names`` to the Amazon bridge by default."""
    from mureo.amazon_ads.provider import AMAZON_SOURCE_DISTRIBUTION

    provider = _StampedProvider(distribution or AMAZON_SOURCE_DISTRIBUTION)
    return {name: provider for name in names}


@pytest.mark.unit
class TestServerRegistration:
    def test_a_bridged_money_tool_gets_the_declaration(self) -> None:
        from mureo.mcp.server import _register_bridged_money_declarations

        name = TOOL_NAMESPACE + "update_campaign"
        _register_bridged_money_declarations(_semantics_for(name), _dispatch_for(name))
        assert budget_declaration_for(name) is BUDGET_DECLARATIONS[name]

    def test_both_families_are_registered_for_a_tool_that_carries_both(self) -> None:
        from mureo.mcp.server import _register_bridged_money_declarations

        name = TOOL_NAMESPACE + "update_ad_group"
        _register_bridged_money_declarations(_semantics_for(name), _dispatch_for(name))
        assert budget_declaration_for(name) is BUDGET_DECLARATIONS[name]
        assert bid_declaration_for(name) is BID_DECLARATIONS[name]

    def test_a_budget_only_tool_gets_no_bid_declaration(self) -> None:
        """So the bid pattern fallback stays available for it."""
        from mureo.mcp.server import _register_bridged_money_declarations

        name = TOOL_NAMESPACE + "update_campaign_budget"
        _register_bridged_money_declarations(_semantics_for(name), _dispatch_for(name))
        assert budget_declaration_for(name) is not None
        assert bid_declaration_for(name) is None

    def test_a_tool_the_server_does_not_have_is_not_registered(self) -> None:
        from mureo.mcp.server import _register_bridged_money_declarations

        _register_bridged_money_declarations(
            _semantics_for("some_other_tool"), _dispatch_for("some_other_tool")
        )
        assert budget_declaration_for(TOOL_NAMESPACE + "update_campaign") is None

    def test_another_plugin_with_the_same_tool_name_is_not_declared(self) -> None:
        """Tool names carry no plugin identity, and Amazon's are generic enough
        that another provider could ship the same string. Amazon's exact money
        paths must not be hung on someone else's arguments."""
        from mureo.mcp.server import _register_bridged_money_declarations

        name = TOOL_NAMESPACE + "update_campaign"
        _register_bridged_money_declarations(
            _semantics_for(name), _dispatch_for(name, distribution="acme-ads-bridge")
        )
        assert budget_declaration_for(name) is None

    def test_a_tool_with_no_dispatch_entry_is_not_declared(self) -> None:
        from mureo.mcp.server import _register_bridged_money_declarations

        name = TOOL_NAMESPACE + "update_campaign"
        _register_bridged_money_declarations(_semantics_for(name), {})
        assert budget_declaration_for(name) is None

    def test_a_read_only_tool_is_not_registered(self) -> None:
        from mcp.types import Tool, ToolAnnotations

        from mureo.mcp.plugin_semantics import derive_semantics
        from mureo.mcp.server import _register_bridged_money_declarations

        name = TOOL_NAMESPACE + "update_campaign"
        tool = Tool(
            name=name,
            description="x",
            inputSchema={"type": "object", "properties": {}},
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        _register_bridged_money_declarations(
            {name: derive_semantics(tool)}, _dispatch_for(name)
        )
        assert budget_declaration_for(name) is None

    def test_a_plugins_own_declaration_wins_over_the_table(self) -> None:
        """The tool author knows their vocabulary better than a snapshot."""
        from mcp.types import Tool

        from mureo.mcp.plugin_semantics import derive_semantics
        from mureo.mcp.server import (
            _register_bridged_money_declarations,
            _register_plugin_budget_declarations,
        )

        name = TOOL_NAMESPACE + "update_campaign"
        tool = Tool(
            name=name,
            description="x",
            inputSchema={"type": "object", "properties": {}},
            _meta={"mureo": {"budget": {"daily": "their_own_key"}}},
        )
        semantics = {name: derive_semantics(tool)}
        _register_plugin_budget_declarations(semantics)
        _register_bridged_money_declarations(semantics, _dispatch_for(name))
        assert budget_declaration_for(name) == BudgetDeclaration(
            daily_key="their_own_key"
        )

    def test_the_gate_enforces_a_registered_bridged_declaration_end_to_end(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.core.runtime_context import reset_runtime_context
        from mureo.mcp.server import _register_bridged_money_declarations

        name = TOOL_NAMESPACE + "update_campaign"
        _register_bridged_money_declarations(_semantics_for(name), _dispatch_for(name))
        register_pattern_fallback_tool(name)
        assert has_pattern_fallback(name) is True

        strategy = tmp_path / "STRATEGY.md"
        strategy.write_text(
            "## Guardrails\n- max_daily_budget_per_campaign: 10000\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        reset_runtime_context()
        sg._cache.clear()
        try:
            spec = BUDGET_PATHS["update_campaign"][0]
            decision = sg.StrategyPolicyGate().evaluate(
                name, _payload_for(spec, _OVER_CAP)
            )
            assert decision.allowed is False
            assert "max_daily_budget_per_campaign" in (decision.reason or "")
        finally:
            reset_runtime_context()
            sg._cache.clear()
