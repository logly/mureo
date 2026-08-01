"""Pattern fallback for declaration-less plugin mutations (audit #17/#18).

A plugin whose tools come from a manifest snapshot cannot carry mureo
``_meta`` declarations, so :class:`BudgetDeclaration` / :class:`BidDeclaration`
are unavailable to it and every ``## Guardrails`` budget/bid cap was silently
unenforced for its mutations — on a surface where real money moves.

This adds a conservative, best-effort pattern scan: for a MUTATING plugin tool
with no registered declaration, numeric arguments under budget-shaped /
bid-shaped key names are read as proposals and held to the same caps, with the
same fail-closed discipline and the same deny envelope as the built-in scan.
Exact-key declarations always take precedence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.policy.pattern_scan import (
    SCAN_EXHAUSTED_DEPTH,
    SCAN_EXHAUSTED_NODES,
    has_pattern_fallback,
    is_bid_key,
    is_budget_key,
    register_pattern_fallback_tool,
    reset_pattern_fallback_tools,
    scan_bid_amount,
    scan_budget_amount,
)
from mureo.policy.strategy_gate import (
    BidDeclaration,
    BudgetDeclaration,
    Guardrails,
    evaluate_guardrails,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_CAPS = Guardrails(max_daily_budget_per_campaign=10_000)
_BID_CAPS = Guardrails(max_bid_amount_per_ad_set=500)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Isolate the process-global fallback registry WITHOUT destroying it.

    ``mureo.mcp.server`` populates it once at import from real plugin
    discovery; a destructive clear would drop those registrations for the
    rest of the pytest session.
    """
    from mureo.policy.pattern_scan import _PATTERN_FALLBACK_TOOLS

    saved = set(_PATTERN_FALLBACK_TOOLS)
    reset_pattern_fallback_tools()
    yield
    reset_pattern_fallback_tools()
    _PATTERN_FALLBACK_TOOLS.update(saved)


# ---------------------------------------------------------------------------
# Key predicates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBudgetKeyPredicate:
    @pytest.mark.parametrize(
        "key",
        [
            "budget",
            "daily_budget",
            "dailyBudget",
            "BUDGET",
            "budget_amount_micros",
            "campaign_budget",
            # A bridged surface caps daily outlay under "spend", not "budget"
            # (Amazon: adGroups[].optimization.budgetSettings.dailyMinSpendValue).
            "spend",
            "daily_spend",
            "dailyMinSpendValue",
        ],
    )
    def test_budget_shaped_keys_match(self, key: str) -> None:
        assert is_budget_key(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            # Too generic to mean anything alone; only a budget-named ancestor
            # can make it a budget (see TestAncestorContext).
            "amount",
            "value",
            "spend_id",
            # mureo's own caller-supplied convention keys are context, not a
            # proposal — reading them as one would deny a decrease.
            "current_daily_budget",
            "projected_total_daily_budget",
            # identifiers are never amounts
            "budget_id",
            "budget_ids",
            "budgetId",
        ],
    )
    def test_non_proposal_keys_do_not_match(self, key: str) -> None:
        assert is_budget_key(key) is False


@pytest.mark.unit
class TestBidKeyPredicate:
    @pytest.mark.parametrize(
        "key",
        [
            "bid",
            "bid_amount",
            "bidAmount",
            "default_bid",
            "maxBid",
            "cpc_bid_micros",
            "BID",
        ],
    )
    def test_bid_shaped_keys_match(self, key: str) -> None:
        assert is_bid_key(key) is True

    @pytest.mark.parametrize(
        "key",
        ["forbidden", "forbidden_zone", "budget", "morbidity", "bid_id", "bidId"],
    )
    def test_false_positives_are_excluded(self, key: str) -> None:
        assert is_bid_key(key) is False


# ---------------------------------------------------------------------------
# The scan itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScan:
    def test_absent_is_none(self) -> None:
        assert scan_budget_amount({"name": "x"}).value is None

    def test_reads_a_top_level_numeric(self) -> None:
        assert scan_budget_amount({"daily_budget": 250.0}).value == 250.0

    def test_reads_through_nested_dicts_and_lists(self) -> None:
        args = {"campaigns": [{"settings": {"dailyBudget": 400}}]}
        assert scan_budget_amount(args).value == 400

    def test_takes_the_maximum_of_several_matches(self) -> None:
        args = {"budget": 100, "nested": {"weekly_budget": 900}}
        assert scan_budget_amount(args).value == 900

    def test_micros_keys_are_scaled(self) -> None:
        assert scan_budget_amount({"budget_micros": 12_000_000}).value == 12.0

    def test_numeric_strings_are_read(self) -> None:
        assert scan_budget_amount({"daily_budget": "250"}).value == 250.0

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1,000", 1000.0),
            ("1,000,000", 1_000_000.0),
            ("1,234,567.89", 1_234_567.89),
            ("-2,500", -2500.0),
            ("  12,000  ", 12_000.0),
        ],
    )
    def test_comma_grouped_numeric_strings_are_read(
        self, text: str, expected: float
    ) -> None:
        """A form encoder / spreadsheet export groups its numerals; without
        this, a real budget read as 'no proposal' and sailed past the cap."""
        assert scan_budget_amount({"daily_budget": text}).value == expected
        assert scan_bid_amount({"bid_amount": text}).value == expected

    @pytest.mark.parametrize(
        "text",
        [
            # European decimal comma — reading this as 15 would be a 10x
            # over-read of a real-money figure, so ambiguous grouping is
            # ignored rather than guessed at.
            "1,5",
            "1,23",
            "12,34567",
            "1,000,00",
            ",000",
            "1,,000",
            "1,000,",
            "USD 1,000",
            "1,000 JPY",
        ],
    )
    def test_ambiguous_or_malformed_grouping_is_ignored(self, text: str) -> None:
        assert scan_budget_amount({"daily_budget": text}).value is None
        assert scan_bid_amount({"bid_amount": text}).value is None

    def test_a_grouped_micros_string_is_still_scaled(self) -> None:
        assert scan_budget_amount({"budget_micros": "12,000,000"}).value == 12.0

    def test_non_numeric_strings_are_ignored(self) -> None:
        assert scan_budget_amount({"budget_type": "DAILY"}).value is None

    def test_booleans_are_ignored(self) -> None:
        assert scan_budget_amount({"budget_enabled": True}).value is None

    @pytest.mark.parametrize("value", [float("inf"), float("nan"), 10**400])
    def test_a_non_finite_match_is_unreadable(self, value: Any) -> None:
        result = scan_budget_amount({"daily_budget": value})
        assert result.value is None
        assert result.unreadable_key == "daily_budget"

    def test_bid_scan_reads_bid_shaped_keys(self) -> None:
        assert scan_bid_amount({"ad_groups": [{"default_bid": 4.5}]}).value == 4.5

    def test_deeply_nested_beyond_the_depth_limit_is_ignored(self) -> None:
        """Past the depth bound the amount is not read. Nothing about the
        wrappers suggested money, so this stays SILENT — see TestScanBounds
        for the case where the cut lands inside a money-named subtree."""
        node: dict[str, Any] = {"daily_budget": 99_999}
        for _ in range(20):
            node = {"wrap": node}
        result = scan_budget_amount(node)
        assert result.value is None
        assert result.unreadable_key is None


# ---------------------------------------------------------------------------
# The bounds: depth follows real schemas, nodes bound the work, and running
# out of either is reported as UNKNOWN rather than as "no money" (issue #517)
# ---------------------------------------------------------------------------


def _buried(payload: dict[str, Any], wrappers: int) -> dict[str, Any]:
    """``payload`` under ``wrappers`` layers of anonymous nesting."""
    node = payload
    for _ in range(wrappers):
        node = {"wrap": node}
    return node


def _tiny_node_cap(monkeypatch: pytest.MonkeyPatch, cap: int = 200) -> int:
    """Shrink the node bound so exhaustion BEHAVIOUR can be tested in
    milliseconds.

    ``_scan`` reads the module global at call time, so this is exact. The
    tests below are about what happens when the bound is reached, not about
    the shipped value — that is a separate concern, pinned by
    :class:`TestNodeCapHeadroom` against the real constant.
    """
    monkeypatch.setattr("mureo.policy.pattern_scan._MAX_NODES", cap)
    return cap


@pytest.mark.unit
class TestScanBounds:
    def test_a_real_world_wrapper_depth_is_reachable(self) -> None:
        """Six wrapper objects and two arrays is an ordinary bridged payload,
        not a pathological one — the old bound of 8 truncated it."""
        node: dict[str, Any] = {"monetaryBudget": {"value": 25_000}}
        for wrapper in ("monetaryBudgetValue", "budgetValue"):
            node = {wrapper: node}
        node = {"budgets": [node]}
        node = {"body": {"campaigns": [node]}}
        assert scan_budget_amount(node).value == 25_000

    # -- money must never be starved by an unrelated sibling ----------------

    def test_a_huge_unrelated_sibling_does_not_starve_the_money(self) -> None:
        """The regression that made this whole section necessary: with a plain
        LIFO stack charged at PUSH time, the filler was drained first and
        exhausted the budget, so the scan reported no budget at all — and the
        gate reads 'no budget' as 'nothing to check'. A payload-order-dependent
        silent bypass of every cap."""
        args: dict[str, Any] = {
            "budget_settings": {"value": 12345},
            "unrelated_filler": [{"note": i} for i in range(15_000)],
        }
        assert scan_budget_amount(args).value == 12345

    def test_the_same_holds_when_the_money_comes_last(self) -> None:
        """Mirror of the above: the fix must not merely reverse which order
        happens to win."""
        args: dict[str, Any] = {
            "unrelated_filler": [{"note": i} for i in range(15_000)],
            "budget_settings": {"value": 12345},
        }
        assert scan_budget_amount(args).value == 12345

    def test_a_bid_is_equally_un_starvable(self) -> None:
        args: dict[str, Any] = {
            "filler": [{"note": i} for i in range(15_000)],
            "ad_group": {"defaultBid": 4.5},
        }
        assert scan_bid_amount(args).value == 4.5

    # -- a realistic bulk payload stays well inside the bound ---------------

    def test_a_realistic_bulk_payload_is_fully_scanned(self) -> None:
        """Hundreds of campaigns, each with a budget: the largest must be the
        one that meets the cap, and nothing may be reported as unreadable."""
        args = {
            "body": {
                "campaigns": [
                    {
                        "campaignId": f"{i:010d}",
                        "budgets": [{"budgetValue": _amazon_budget_value(100 + i)}],
                    }
                    for i in range(500)
                ]
            }
        }
        result = scan_budget_amount(args)
        assert result.unreadable_key is None
        assert result.value == 100 + 499

    # -- document order within a priority group -----------------------------

    def test_promising_children_keep_document_order(self) -> None:
        """``appendleft`` per child while iterating forward REVERSED a node's
        promising children, so a matching key's big collection was walked
        end→front and its first entries were dropped under pressure. The leaf
        of the first child must be examined before the leaf of the second."""
        from mureo.policy.pattern_scan import _scan

        seen: list[str] = []

        def _matches(key: str) -> bool:
            seen.append(key)
            return is_budget_key(key)

        _scan({"budget_a": {"leaf_a": 1}, "budget_b": {"leaf_b": 2}}, _matches)
        assert seen.index("leaf_a") < seen.index("leaf_b")

    def test_promising_list_items_keep_document_order(self) -> None:
        from mureo.policy.pattern_scan import _scan

        seen: list[str] = []

        def _matches(key: str) -> bool:
            seen.append(key)
            return is_budget_key(key)

        _scan({"budgets": [{"leaf_a": 1}, {"leaf_b": 2}]}, _matches)
        assert seen.index("leaf_a") < seen.index("leaf_b")

    # -- the reviewer's guardrail-bypass repro ------------------------------

    def test_a_big_collection_under_a_matching_key_cannot_hide_a_proposal(
        self,
    ) -> None:
        """Verbatim repro of the bypass. Order reversal walked this list
        end→front so only the trailing ``1``s were seen, and that partial read
        was returned as if it were the maximum — ``value=1.0``. Both fixes now
        apply: document order reaches the front entry, and 60k items are
        comfortably inside the node bound, so the TRUE maximum is reported."""
        n = 60000
        items = [{"value": 1} for _ in range(n)]
        items[0] = {"value": 999_999_999}
        result = scan_budget_amount({"monetaryBudget": items})
        assert result.value == 999_999_999
        assert result.unreadable_key is None

    def test_the_same_holds_for_dict_children(self) -> None:
        n = 60000
        children: dict[str, Any] = {f"k{i}": {"value": 1} for i in range(n)}
        children["k0"] = {"value": 999_999_999}
        result = scan_budget_amount({"monetaryBudget": children})
        assert result.value == 999_999_999
        assert result.unreadable_key is None

    def test_the_bypass_now_denies_end_to_end(self) -> None:
        """The demonstrated bypass: 99,000,000 proposed against a 10,000 cap
        returned ``allowed=True``. It is now denied — and for the RIGHT
        reason: the proposal is read correctly and exceeds the cap, rather
        than the call being refused for being unscannable. The bid channel is
        declared so the budget channel is unambiguously the one deciding."""
        n = 60000
        items = [{"value": 1} for _ in range(n)]
        items[0] = {"value": 99_000_000}
        decision = evaluate_guardrails(
            "acme-bulk_update",
            {"monetaryBudget": items},
            _CAPS,
            bid_declaration=BidDeclaration(bid_amount_key="declared_bid"),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        reason = decision.reason or ""
        assert "99,000,000" in reason
        assert "max_daily_budget_per_campaign" in reason

    # -- exhaustion is UNKNOWN, not "no money" ------------------------------

    def test_exhausting_the_node_cap_with_nothing_read_is_unreadable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A flat dict is depth 1, so only the node cap bounds it. Returning
        ``value=None`` here would tell the gate 'no money in this call' when
        the truth is 'I could not finish looking'."""
        cap = _tiny_node_cap(monkeypatch)
        wide: dict[str, Any] = {f"filler_{i}": i for i in range(cap + 50)}
        result = scan_budget_amount(wide)
        assert result.value is None
        assert result.unreadable_key == SCAN_EXHAUSTED_NODES

    def test_a_wide_list_is_bounded_the_same_way(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cap = _tiny_node_cap(monkeypatch)
        args = {"campaigns": [{"n": i} for i in range(cap)]}
        result = scan_budget_amount(args)
        assert result.value is None
        assert result.unreadable_key == SCAN_EXHAUSTED_NODES

    def test_the_node_cap_fails_closed_with_or_without_a_money_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike the depth bound, the node cap stopped the walk GLOBALLY —
        there is no subtree left to say anything about."""
        cap = _tiny_node_cap(monkeypatch)
        for wrapper in ("filler", "budgets"):
            args: dict[str, Any] = {wrapper: [{"note": i} for i in range(cap)]}
            assert scan_budget_amount(args).unreadable_key == SCAN_EXHAUSTED_NODES

    # -- depth exhaustion: only inside a money context -----------------------

    def test_a_depth_cut_with_no_money_context_stays_silent(self) -> None:
        """An ordinary deeply-nested payload carrying nothing money-shaped is
        bounded-heuristic truncation, not an unknown. Denying it would cost
        availability for no safety."""
        result = scan_budget_amount(_buried({"note": "x", "count": 3}, 20))
        assert result.value is None
        assert result.unreadable_key is None

    def test_a_depth_cut_inside_a_money_subtree_is_unreadable(self) -> None:
        """The cut lands under a budget-named key, whose leaf is never
        reached: precisely where an unchecked amount would hide."""
        buried = _buried({"budgets": {"inner": {"value": 999}}}, 11)
        result = scan_budget_amount(buried)
        assert result.value is None
        assert result.unreadable_key == SCAN_EXHAUSTED_DEPTH

    def test_the_gate_allows_a_deep_payload_with_no_money_context(self) -> None:
        """The availability half of the contract, end to end."""
        decision = evaluate_guardrails(
            "acme-bulk_update",
            _buried({"note": "x", "count": 3}, 20),
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_the_gate_denies_a_depth_cut_inside_a_money_subtree(self) -> None:
        decision = evaluate_guardrails(
            "acme-bulk_update",
            _buried({"budgets": {"inner": {"value": 999}}}, 11),
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        reason = decision.reason or ""
        # Names the NESTING cause, not the size one.
        assert "deeper than" in reason
        assert "too large" not in reason
        assert "_meta['mureo']['budget']" in reason
        assert SCAN_EXHAUSTED_DEPTH not in reason  # never leak the sentinel

    def test_a_partial_read_does_not_mask_exhaustion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deliberately replaces the earlier "a reading survives exhaustion"
        behaviour. ``PatternAmount.value`` promises the LARGEST amount and the
        gate compares exactly that against the cap, so a small figure found
        before the walk stopped is not an answer — a larger one may sit in the
        part never reached."""
        cap = _tiny_node_cap(monkeypatch)
        args: dict[str, Any] = {
            "daily_budget": 777,
            "filler": [{"note": i} for i in range(cap)],
        }
        result = scan_budget_amount(args)
        assert result.value is None
        assert result.unreadable_key == SCAN_EXHAUSTED_NODES

    def test_a_depth_cut_in_context_outranks_a_reading_too(self) -> None:
        buried = _buried({"budgets": {"inner": {"value": 999_999}}}, 11)
        buried["daily_budget"] = 10
        result = scan_budget_amount(buried)
        assert result.value is None
        assert result.unreadable_key == SCAN_EXHAUSTED_DEPTH

    def test_an_ordinary_payload_is_never_reported_as_exhausted(self) -> None:
        assert scan_budget_amount({"name": "x"}).unreadable_key is None
        assert scan_budget_amount({"daily_budget": 5}).unreadable_key is None
        assert scan_bid_amount({"nothing": {"here": 1}}).unreadable_key is None

    # -- and the gate must DENY on it ---------------------------------------

    def test_the_gate_denies_an_exhausted_scan_instead_of_allowing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cap = _tiny_node_cap(monkeypatch)
        args: dict[str, Any] = {f"filler_{i}": i for i in range(cap + 50)}
        decision = evaluate_guardrails(
            "acme-bulk_update", args, _CAPS, pattern_fallback=True
        )
        assert decision.allowed is False
        reason = decision.reason or ""
        # Actionable: names the cause AND the way out.
        assert "too large" in reason
        assert "_meta['mureo']['budget']" in reason
        assert SCAN_EXHAUSTED_NODES not in reason  # never leak the sentinel

    def test_the_gate_denies_an_exhausted_bid_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Budget is checked first and would deny on the same payload, so the
        budget channel is declared here to isolate the bid message."""
        cap = _tiny_node_cap(monkeypatch)
        args: dict[str, Any] = {f"filler_{i}": i for i in range(cap + 50)}
        decision = evaluate_guardrails(
            "acme-bulk_update",
            args,
            _BID_CAPS,
            budget_declaration=BudgetDeclaration(daily_key="declared_budget"),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "_meta['mureo']['bid']" in (decision.reason or "")

    def test_a_declaration_is_unaffected_by_payload_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The documented way out actually works: a declared key is read
        directly, so an oversized payload no longer denies."""
        cap = _tiny_node_cap(monkeypatch)
        args: dict[str, Any] = {f"filler_{i}": i for i in range(cap + 50)}
        args["spend_limit"] = 100
        decision = evaluate_guardrails(
            "acme-bulk_update",
            args,
            _CAPS,
            budget_declaration=BudgetDeclaration(daily_key="spend_limit"),
            bid_declaration=BidDeclaration(bid_amount_key="declared_bid"),
            pattern_fallback=True,
        )
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Parent-object context for generically named leaves (issue #517)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAncestorContext:
    """A bridged surface wraps the number in a named object, so the family
    lives on an ANCESTOR and the leaf is a bare ``value`` / ``amount``."""

    def test_a_generic_leaf_takes_its_enclosing_objects_family(self) -> None:
        assert scan_budget_amount({"monetaryBudget": {"value": 500}}).value == 500
        assert scan_budget_amount({"budget": {"amount": 12}}).value == 12
        assert scan_bid_amount({"bid": {"value": 3.0}}).value == 3.0

    def test_a_list_passes_its_own_key_to_its_items(self) -> None:
        assert scan_budget_amount({"budgets": [{"value": 700}]}).value == 700

    def test_context_does_not_make_sibling_identifiers_readable(self) -> None:
        """The whole reason the scan never credits everything under a match:
        a ten-digit resource id would exceed every cap."""
        args = {"monetaryBudget": {"value": 500, "campaignId": 1_234_567_890}}
        assert scan_budget_amount(args).value == 500

    def test_an_opaque_map_key_between_the_family_and_the_number(self) -> None:
        """The real ``add_country_campaign`` shape: the only semantic word is
        two objects above the number, and the level in between is a country
        code that carries no vocabulary of its own."""
        args = {
            "budgetCaps": {"countryMonetaryBudgetSettings": {"US": {"value": 25_000}}}
        }
        assert scan_budget_amount(args).value == 25_000

    def test_the_context_window_is_bounded(self) -> None:
        """Inside the window the family carries; past it the context lapses,
        so an arbitrarily distant ``value`` is not credited to it."""
        from mureo.policy.pattern_scan import _MAX_CONTEXT_SPAN

        node: dict[str, Any] = {"value": 25_000}
        for _ in range(_MAX_CONTEXT_SPAN):
            node = {"opaque": node}
        assert scan_budget_amount({"budget": node}).value == 25_000

        assert scan_budget_amount({"budget": {"opaque": node}}).value is None

    def test_a_nearer_family_name_resets_the_window(self) -> None:
        args = {"budget": {"a": {"b": {"monetaryBudget": {"value": 900}}}}}
        assert scan_budget_amount(args).value == 900

    def test_only_value_and_amount_are_contextual(self) -> None:
        assert scan_budget_amount({"budget": {"threshold": 9_000}}).value is None
        assert (
            scan_budget_amount({"budgetCaps": {"US": {"threshold": 9_000}}}).value
            is None
        )

    def test_context_does_not_make_a_distant_identifier_readable(self) -> None:
        """Widening the window must not widen WHAT it credits: ids stay
        excluded however close the family name is."""
        args = {"budgetCaps": {"US": {"campaignId": 1_234_567_890, "value": 500}}}
        assert scan_budget_amount(args).value == 500

    def test_an_unrelated_parent_does_not_credit_its_leaves(self) -> None:
        """Real Amazon shapes that must stay silent: ``tags[].value`` and
        ``contentCategoriesWithRisk.value``."""
        assert scan_budget_amount({"tags": [{"key": "env", "value": 7}]}).value is None
        assert scan_bid_amount({"tags": [{"key": "env", "value": 7}]}).value is None
        assert (
            scan_budget_amount({"contentCategoriesWithRisk": {"value": 3}}).value
            is None
        )

    def test_the_family_of_the_ancestor_is_what_decides(self) -> None:
        assert scan_bid_amount({"monetaryBudget": {"value": 500}}).value is None
        assert scan_budget_amount({"bid": {"value": 3.0}}).value is None

    def test_the_two_families_never_blur_across_the_window(self) -> None:
        """A bid ancestor never credits a budget leaf, at any span."""
        args = {"bid": {"marketplaceSettings": {"JP": {"value": 4.0}}}}
        assert scan_bid_amount(args).value == 4.0
        assert scan_budget_amount(args).value is None

    def test_micros_scaling_follows_the_matching_key(self) -> None:
        assert (
            scan_budget_amount({"budget_micros": {"value": 12_000_000}}).value == 12.0
        )

    def test_a_contextual_unreadable_reports_the_enclosing_key(self) -> None:
        """``value`` names nothing in a deny message; ``monetaryBudget`` does."""
        result = scan_budget_amount({"monetaryBudget": {"value": float("inf")}})
        assert result.value is None
        assert result.unreadable_key == "monetaryBudget"


# ---------------------------------------------------------------------------
# The REAL Amazon payload shapes (issue #517) — built from the shipped
# manifest's inputSchema for each tool, trimmed to the asserted fields.
# ---------------------------------------------------------------------------


def _amazon_budget_value(amount: float) -> dict[str, Any]:
    """``budgetValue`` as Amazon declares it: the number is a bare ``value``
    under ``monetaryBudget``, three objects below the word "budget"."""
    return {"monetaryBudgetValue": {"monetaryBudget": {"value": amount}}}


@pytest.mark.unit
class TestRealAmazonShapes:
    def test_update_campaign_budget_is_read(self) -> None:
        args = {
            "body": {
                "accessRequestedAccount": {"advertiserAccountId": "AD1"},
                "campaigns": [
                    {
                        "campaignId": "1234567890",
                        "budgets": [
                            {
                                "budgetType": "MONETARY",
                                "budgetValue": _amazon_budget_value(25_000),
                                "recurrenceTimePeriod": "DAILY",
                            }
                        ],
                    }
                ],
            }
        }
        assert scan_budget_amount(args).value == 25_000

    def test_update_ad_group_budget_and_daily_min_spend_are_read(self) -> None:
        args = {
            "body": {
                "adGroups": [
                    {
                        "adGroupId": "AG1",
                        "budgets": [
                            {
                                "budgetType": "MONETARY",
                                "budgetValue": _amazon_budget_value(900),
                                "recurrenceTimePeriod": "DAILY",
                            }
                        ],
                        "optimization": {
                            "bidStrategy": "AUTO_FOR_SALES",
                            "budgetSettings": {
                                "budgetAllocation": "UNRESTRICTED",
                                "dailyMinSpendValue": 40,
                            },
                        },
                    }
                ]
            }
        }
        assert scan_budget_amount(args).value == 900

    def test_daily_min_spend_alone_is_read(self) -> None:
        """``spend`` in the vocabulary — the key names itself, no context
        needed."""
        args = {
            "body": {
                "adGroups": [
                    {"optimization": {"budgetSettings": {"dailyMinSpendValue": 12_000}}}
                ]
            }
        }
        assert scan_budget_amount(args).value == 12_000

    def test_ad_group_bids_are_still_read(self) -> None:
        """Bids already worked; the context rule must not regress them."""
        args = {
            "body": {
                "adGroups": [
                    {
                        "adGroupId": "AG1",
                        "bid": {
                            "baseBid": 0.5,
                            "defaultBid": 1.25,
                            "maxAverageBid": 2.0,
                        },
                    }
                ]
            }
        }
        assert scan_bid_amount(args).value == 2.0

    def test_target_bids_are_still_read(self) -> None:
        args = {
            "body": {
                "targets": [
                    {
                        "targetId": "T1",
                        "bid": {
                            "bid": 3.5,
                            "marketplaceSettings": [{"marketplace": "JP", "bid": 4.0}],
                        },
                    }
                ]
            }
        }
        assert scan_bid_amount(args).value == 4.0
        assert scan_budget_amount(args).value is None

    def test_the_gate_now_blocks_an_over_cap_amazon_budget(self) -> None:
        """End to end: the shape that sailed past every cap until #517."""
        decision = evaluate_guardrails(
            "campaign_management-update_campaign_budget",
            {
                "body": {
                    "campaigns": [
                        {
                            "campaignId": "1234567890",
                            "budgets": [{"budgetValue": _amazon_budget_value(25_000)}],
                        }
                    ]
                }
            },
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_daily_budget_per_campaign" in (decision.reason or "")


@pytest.mark.unit
class TestNodeCapHeadroom:
    """The SHIPPED :data:`_MAX_NODES`, against the worst realistic shape.

    Cost per campaign varies ~10x across the real Amazon budget shapes,
    because a global campaign repeats its budget once per marketplace
    (23 in the enum): ~10 nodes/campaign without ``marketplaceSettings``,
    ~103 with the full set. Sizing the bound off the cheap shape is how a
    legitimate bulk call gets refused — at the previous 100,000 the
    full-marketplace shape exhausted at only 971 campaigns, and no
    ``maxItems`` anywhere in the money tools' schemas prevents such a call.
    """

    def _global_campaign(self, i: int, marketplaces: int) -> dict[str, Any]:
        """One campaign in the deepest real budget shape."""
        settings = [
            {"marketplace": code, "monetaryBudget": {"value": 100 + i}}
            for code in _ADD_COUNTRY_MARKETPLACES[:marketplaces]
        ]
        return {
            "campaignId": f"{i:010d}",
            "budgets": [
                {
                    "budgetType": "MONETARY",
                    "budgetValue": {
                        "monetaryBudgetValue": {
                            "monetaryBudget": {"value": 100 + i},
                            "marketplaceSettings": settings,
                        }
                    },
                    "recurrenceTimePeriod": "DAILY",
                }
            ],
        }

    def _bulk(self, campaigns: int, marketplaces: int) -> dict[str, Any]:
        return {
            "body": {
                "campaigns": [
                    self._global_campaign(i, marketplaces) for i in range(campaigns)
                ]
            }
        }

    def test_a_full_marketplace_bulk_call_is_not_denied(self) -> None:
        """2,000 global campaigns × 23 marketplaces ≈ 206k nodes ≈ 21% of the
        shipped bound. This is the case the old 100,000 refused."""
        result = scan_budget_amount(self._bulk(2_000, 23))
        assert result.unreadable_key is None
        assert result.value == 100 + 1_999

    def test_the_cheap_shape_has_even_more_room(self) -> None:
        result = scan_budget_amount(self._bulk(2_000, 0))
        assert result.unreadable_key is None
        assert result.value == 100 + 1_999

    def test_the_bound_is_sized_off_the_worst_shape(self) -> None:
        """Pins the decision, not just the constant: the shipped bound must
        still admit a few thousand campaigns of the MOST expensive real
        shape (~103 nodes each)."""
        from mureo.policy.pattern_scan import _MAX_NODES

        worst_nodes_per_campaign = 103
        assert _MAX_NODES / worst_nodes_per_campaign > 5_000


# ---------------------------------------------------------------------------
# Reachability across the WHOLE real manifest (issue #517)
#
# Every numeric leaf that carries money on a real 85-tool Amazon Ads manifest,
# as a dotted schema path (``[]`` = an array level). Enumerated once from the
# manifest's own ``inputSchema`` blocks — the manifest itself is NOT vendored
# here; only the paths are, so the table is readable and reviewable. Each path
# is expanded into a minimal payload and the scan must find it: 62 of 62, no
# unreachable money, across the 13 money-carrying tools.
#
# Two separate gaps are pinned here. Twelve of these (every
# ``marketplaceSettings[]`` and ``flights[]`` budget) were out of reach at the
# old DEPTH bound of 8; the 24 ``add_country_campaign`` country budgets were
# out of reach of the old one-level CONTEXT rule. Both were real budgets that
# sailed past every ``## Guardrails`` cap.
# ---------------------------------------------------------------------------

_REAL_MONEY_LEAVES: list[tuple[str, str, str]] = [
    ("bid", "create_ad_group", "body.adGroups[].bid.baseBid"),
    ("bid", "create_ad_group", "body.adGroups[].bid.defaultBid"),
    ("bid", "create_ad_group", "body.adGroups[].bid.marketplaceSettings[].defaultBid"),
    ("bid", "create_ad_group", "body.adGroups[].bid.maxAverageBid"),
    (
        "bid",
        "create_singleshot_sp_campaign",
        "body.oneshotCampaigns[].bid.marketplaceSettings[].defaultBid",
    ),
    ("bid", "create_target", "body.targets[].bid.bid"),
    ("bid", "create_target", "body.targets[].bid.marketplaceSettings[].bid"),
    ("bid", "update_ad_group", "body.adGroups[].bid.baseBid"),
    ("bid", "update_ad_group", "body.adGroups[].bid.defaultBid"),
    ("bid", "update_ad_group", "body.adGroups[].bid.marketplaceSettings[].defaultBid"),
    ("bid", "update_ad_group", "body.adGroups[].bid.maxAverageBid"),
    ("bid", "update_target", "body.targets[].bid.bid"),
    ("bid", "update_target", "body.targets[].bid.marketplaceSettings[].bid"),
    ("bid", "update_target_bid", "body.targets[].bid.bid"),
    ("bid", "update_target_bid", "body.targets[].bid.marketplaceSettings[].bid"),
    (
        "budget",
        "create_ad_group",
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "create_ad_group",
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "create_ad_group",
        "body.adGroups[].optimization.budgetSettings.dailyMinSpendValue",
    ),
    (
        "budget",
        "create_campaign",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "create_campaign",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "create_campaign",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "create_campaign",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "create_portfolio",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "create_portfolio",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "create_singleshot_portfolio",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "create_singleshot_portfolio",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "create_singleshot_sp_campaign",
        "body.oneshotCampaigns[].budgets.budgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "update_ad_group",
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "update_ad_group",
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "update_ad_group",
        "body.adGroups[].optimization.budgetSettings.dailyMinSpendValue",
    ),
    (
        "budget",
        "update_campaign",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "update_campaign",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "update_campaign",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "update_campaign",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "update_campaign_budget",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "update_campaign_budget",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
    (
        "budget",
        "update_portfolio",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    (
        "budget",
        "update_portfolio",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
    ),
]

#: ``add_country_campaign`` declares one daily budget PER marketplace, keyed by
#: country code — 24 of them, each ``{"value": <number>}`` with its own
#: ``minimum: 1, maximum: 1000000``. The country code is an opaque map key, so
#: the nearest word with any meaning (``countryMonetaryBudgetSettings``) sits
#: two objects above the number: the shape the bounded context window exists
#: for. Generated rather than typed out — 24 identical paths differing by two
#: letters is a table nobody would proofread.
_ADD_COUNTRY_MARKETPLACES = (
    "US",
    "CA",
    "UK",
    "GB",
    "DE",
    "FR",
    "IT",
    "ES",
    "IN",
    "JP",
    "AU",
    "MX",
    "AE",
    "SA",
    "BR",
    "NL",
    "SG",
    "TR",
    "PL",
    "SE",
    "EG",
    "BE",
    "ZA",
    "IE",
)
_REAL_MONEY_LEAVES += [
    (
        "budget",
        "add_country_campaign",
        f"body.campaigns[].budgetCaps.countryMonetaryBudgetSettings.{code}.value",
    )
    for code in _ADD_COUNTRY_MARKETPLACES
]


def _payload_for(path: str, amount: float) -> dict[str, Any]:
    """Expand one dotted schema path into the smallest payload carrying it.

    ``a.b[].c`` → ``{"a": {"b": [{"c": amount}]}}``.
    """
    node: Any = amount
    for segment in reversed(path.split(".")):
        node = {segment[:-2]: [node]} if segment.endswith("[]") else {segment: node}
    assert isinstance(node, dict)
    return node


@pytest.mark.unit
class TestRealAmazonManifestReachability:
    def test_the_table_covers_the_whole_manifest(self) -> None:
        """Guards the table itself: 62 money leaves were enumerated across the
        85 tools, so a silent truncation of this list cannot pass unnoticed."""
        assert len(_REAL_MONEY_LEAVES) == 62
        assert len(_ADD_COUNTRY_MARKETPLACES) == 24
        assert len({t for _, t, _ in _REAL_MONEY_LEAVES}) == 13

    @pytest.mark.parametrize(
        ("family", "tool", "path"),
        _REAL_MONEY_LEAVES,
        ids=[f"{t}:{p}" for _, t, p in _REAL_MONEY_LEAVES],
    )
    def test_every_real_money_leaf_is_reachable(
        self, family: str, tool: str, path: str
    ) -> None:
        scan = scan_budget_amount if family == "budget" else scan_bid_amount
        assert scan(_payload_for(path, 4_321.0)).value == 4_321.0

    @pytest.mark.parametrize(
        ("family", "tool", "path"),
        _REAL_MONEY_LEAVES,
        ids=[f"{t}:{p}" for _, t, p in _REAL_MONEY_LEAVES],
    )
    def test_a_money_leaf_never_reads_as_the_other_family(
        self, family: str, tool: str, path: str
    ) -> None:
        """Deeper reach must not blur budget and bid into each other."""
        other = scan_bid_amount if family == "budget" else scan_budget_amount
        assert other(_payload_for(path, 4_321.0)).value is None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegistry:
    def test_register_and_lookup(self) -> None:
        assert has_pattern_fallback("acme-do_thing") is False
        register_pattern_fallback_tool("acme-do_thing")
        assert has_pattern_fallback("acme-do_thing") is True

    def test_reset_clears(self) -> None:
        register_pattern_fallback_tool("acme-do_thing")
        reset_pattern_fallback_tools()
        assert has_pattern_fallback("acme-do_thing") is False


# ---------------------------------------------------------------------------
# Enforcement through evaluate_guardrails
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateWithFallback:
    def test_over_cap_is_blocked(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign": {"dailyBudget": 25_000}},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_daily_budget_per_campaign" in (decision.reason or "")
        assert "25,000" in (decision.reason or "")

    def test_under_cap_is_allowed(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign": {"dailyBudget": 900}},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_without_the_fallback_it_sails_past(self) -> None:
        """The gap this closes: no declaration, no fallback ⇒ unenforced."""
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign": {"dailyBudget": 25_000}},
            _CAPS,
        )
        assert decision.allowed is True

    def test_a_declaration_takes_precedence(self) -> None:
        """An exact-key declaration owns the tool's vocabulary; the
        best-effort scan must not second-guess it."""
        decision = evaluate_guardrails(
            "acme_update",
            {"stray_budget": 25_000, "spend_limit": 100},
            _CAPS,
            budget_declaration=BudgetDeclaration(daily_key="spend_limit"),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_increase_pct_uses_the_convention_baseline(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"dailyBudget": 5_000, "current_daily_budget": 1_000},
            Guardrails(max_daily_budget_increase_pct=20),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_daily_budget_increase_pct" in (decision.reason or "")

    def test_lifetime_cap_also_constrains_a_pattern_match(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"campaign_budget": 900_000},
            Guardrails(max_lifetime_budget_per_campaign=500_000),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_lifetime_budget_per_campaign" in (decision.reason or "")

    def test_a_non_finite_pattern_match_fails_closed(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"dailyBudget": float("inf")},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "dailyBudget" in (decision.reason or "")

    def test_no_guardrails_still_fails_open(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"dailyBudget": float("inf")},
            Guardrails(),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_bid_over_cap_is_blocked(self) -> None:
        decision = evaluate_guardrails(
            "ad_group_management-update_bid",
            {"ad_group": {"defaultBid": 900}},
            _BID_CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_bid_amount_per_ad_set" in (decision.reason or "")

    def test_cpc_bid_cap_also_constrains_a_pattern_match(self) -> None:
        decision = evaluate_guardrails(
            "ad_group_management-update_bid",
            {"bid_micros": 9_000_000},
            Guardrails(max_cpc_bid_per_ad_group=5),
            pattern_fallback=True,
        )
        assert decision.allowed is False
        assert "max_cpc_bid_per_ad_group" in (decision.reason or "")

    def test_a_bid_declaration_takes_precedence(self) -> None:
        decision = evaluate_guardrails(
            "acme_update",
            {"stray_bid": 900, "bid_cap": 10},
            _BID_CAPS,
            bid_declaration=BidDeclaration(bid_amount_key="bid_cap"),
            pattern_fallback=True,
        )
        assert decision.allowed is True

    def test_the_builtin_scan_still_applies_alongside(self) -> None:
        """The fallback is additive: built-in spellings keep working."""
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"daily_budget": 25_000},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is False

    def test_an_identifier_argument_does_not_false_trip(self) -> None:
        decision = evaluate_guardrails(
            "campaign_management-update_campaign",
            {"budget_id": 1234567890123, "dailyBudget": 100},
            _CAPS,
            pattern_fallback=True,
        )
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Gate + registry integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGateIntegration:
    def test_gate_applies_the_fallback_for_a_registered_tool(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        import mureo.policy.strategy_gate as sg
        from mureo.core.runtime_context import reset_runtime_context
        from mureo.policy.strategy_gate import StrategyPolicyGate

        (tmp_path / "STRATEGY.md").write_text(
            "## Guardrails\n- max_daily_budget_per_campaign: 10000\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        reset_runtime_context()
        sg._cache.clear()
        try:
            register_pattern_fallback_tool("campaign_management-update_campaign")
            gate = StrategyPolicyGate()
            denied = gate.evaluate(
                "campaign_management-update_campaign", {"dailyBudget": 25_000}
            )
            assert denied.allowed is False
            allowed = gate.evaluate("some_unregistered_tool", {"dailyBudget": 25_000})
            assert allowed.allowed is True
        finally:
            reset_runtime_context()
            sg._cache.clear()


@pytest.mark.unit
def test_server_registers_mutating_plugin_tools_for_the_fallback() -> None:
    """A declaration-less MUTATING plugin tool is registered; a read is not."""
    from mcp.types import Tool, ToolAnnotations

    from mureo.mcp.plugin_semantics import derive_semantics
    from mureo.mcp.server import _register_plugin_pattern_fallbacks

    mutating = Tool(
        name="campaign_management-update_campaign",
        description="x",
        inputSchema={"type": "object", "properties": {}},
    )
    read_only = Tool(
        name="campaign_management-list_campaigns",
        description="x",
        inputSchema={"type": "object", "properties": {}},
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    semantics = {t.name: derive_semantics(t) for t in (mutating, read_only)}
    _register_plugin_pattern_fallbacks(semantics)

    assert has_pattern_fallback("campaign_management-update_campaign") is True
    assert has_pattern_fallback("campaign_management-list_campaigns") is False


def _semantics_for(*names: str) -> dict[str, Any]:
    """Semantics for tools that declare NOTHING — no annotations, no meta.

    This is the shape a manifest snapshot produces, and it is exactly the case
    that matters: ``derive_semantics`` defaults an undeclared tool to
    *mutating*, so the name is the only signal available.
    """
    from mcp.types import Tool

    from mureo.mcp.plugin_semantics import derive_semantics

    tools = [
        Tool(
            name=name,
            description="x",
            inputSchema={"type": "object", "properties": {}},
        )
        for name in names
    ]
    return {t.name: derive_semantics(t) for t in tools}


@pytest.mark.unit
class TestReadNameExemption:
    """A read tool without ``readOnlyHint`` must not be denial-gated.

    ``derive_semantics`` treats an undeclared tool as mutating (the right
    default for auditing), and a manifest snapshot declares nothing — so every
    read from a bridged surface arrived here as "mutating". Handing those to a
    heuristic budget/bid scan can only produce FALSE DENIALS: a listing call
    with a numeric budget-shaped *filter* argument would be refused.

    The exemption is keyed on read-shaped NAMES rather than on a mutation
    allow-list because the error costs are asymmetric: platform mutations are
    consistently verb-named (``create_`` / ``update_`` / ``delete_`` /
    ``set_``), so a read-shaped name is almost never a mutation, while a
    mutation-shaped name that is really a read costs only a scan of arguments
    that carry no budget.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "campaign_management-list_campaigns",
            "account_management-query_advertiser_account",
            "reporting-get_report",
            "reporting-search_terms",
            "insights-analyze_performance",
            # Native (hyphen-free) read names are exempted on the same rule.
            "list_campaigns",
        ],
    )
    def test_read_shaped_names_are_not_registered(self, name: str) -> None:
        from mureo.mcp.server import _register_plugin_pattern_fallbacks

        _register_plugin_pattern_fallbacks(_semantics_for(name))
        assert has_pattern_fallback(name) is False

    @pytest.mark.parametrize(
        "name",
        [
            "campaign_management-create_campaign",
            "campaign_management-update_campaign",
            "campaign_management-set_budget",
            "campaign_management-delete_campaign",
            # A mid-word hit is not a read prefix, so it stays registered.
            "campaign_management-listing_update",
            "acme_ads_update_budget",
        ],
    )
    def test_mutation_shaped_names_are_still_registered(self, name: str) -> None:
        from mureo.mcp.server import _register_plugin_pattern_fallbacks

        _register_plugin_pattern_fallbacks(_semantics_for(name))
        assert has_pattern_fallback(name) is True

    def test_the_exemption_uses_the_shared_read_vocabulary(self) -> None:
        """One list, two safety surfaces — see mureo.core.tool_names."""
        from mureo.core.tool_names import is_read_only_tool_name
        from mureo.rollback import planner

        assert planner._READ_ONLY_PREFIXES is not None
        assert is_read_only_tool_name("campaign_management-list_x") is True
        assert planner._is_read_only("campaign_management-list_x") is True

    def test_a_read_with_a_budget_shaped_filter_is_not_denied(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        """The bug this closes, end to end through the real gate."""
        import mureo.policy.strategy_gate as sg
        from mureo.core.runtime_context import reset_runtime_context
        from mureo.mcp.server import _register_plugin_pattern_fallbacks
        from mureo.policy.strategy_gate import StrategyPolicyGate

        (tmp_path / "STRATEGY.md").write_text(
            "## Guardrails\n- max_daily_budget_per_campaign: 10000\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        reset_runtime_context()
        sg._cache.clear()
        try:
            name = "campaign_management-list_campaigns"
            _register_plugin_pattern_fallbacks(_semantics_for(name))
            decision = StrategyPolicyGate().evaluate(
                name, {"min_daily_budget_filter": 50_000}
            )
            assert decision.allowed is True
        finally:
            reset_runtime_context()
            sg._cache.clear()
