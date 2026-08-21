"""Exact money-argument paths for the bridged Amazon tool surface (#527).

Native ``google_ads_*`` / ``meta_ads_*`` writes are capped by exact argument
keys compiled into mureo. Bridged Amazon writes were capped by a best-effort
PATTERN scan over argument names (:mod:`mureo.policy.pattern_scan`): complete
against the manifest it was measured on, but inferential — a tool Amazon adds
later whose money key falls outside the vocabulary is not capped, and nothing
announces that.

Amazon's tool definitions are Amazon's, so they cannot carry
``_meta.mureo.budget`` / ``_meta.mureo.bid``. mureo therefore holds the
declarations for this surface itself: the table below maps a bridged tool name
to the exact nested paths its ``inputSchema`` carries money at, fed through the
same :class:`~mureo.policy.declarations.BudgetDeclaration` /
:class:`~mureo.policy.declarations.BidDeclaration` registry a plugin uses (see
``mureo.mcp._plugin_declarations._register_bridged_money_declarations``), and
enforced by the one built-in gate. The result is exact enforcement on the known
surface, best-effort on everything else — an Amazon tool that is NOT in this
table keeps the pattern fallback, so a newly added one still gets a cap rather
than none.

Provenance, and why that matters
--------------------------------
This table is **derived from one operator's Amazon manifest at a point in
time** — the same 85-tool snapshot :mod:`mureo.amazon_ads.reversal` reads its
pairs from — by enumerating every money-carrying numeric leaf in each tool's
``inputSchema``: 62 leaves across 13 of the 85 tools, and no others. It is a
snapshot of a surface mureo does not own, not a contract Amazon offers, so it
drifts exactly the way the manifest itself does.

Two properties keep that honest rather than dangerous:

- Path resolution is STRICT (:func:`mureo.policy.declarations._resolve_path`):
  a level that does not match ends the walk with "not found". A path can never
  drift onto a neighbouring field and cap the wrong number.
- A tool whose declared paths resolve NOTHING falls back to the best-effort
  pattern scan rather than reporting "no budget proposed" — see
  :func:`mureo.policy.strategy_gate._budget_inputs`. Drift costs precision,
  never enforcement.

Why every path is declared on BOTH channels of its family
---------------------------------------------------------
A schema path cannot say whether the amount under it is a daily budget or a
period total: an Amazon budget object carries its own ``recurrenceTimePeriod``,
per item, at call time. The pattern scan this replaces already held every
matched amount to BOTH budget caps for that reason, so declaring a path on the
daily channel only would silently drop ``max_lifetime_budget_per_campaign``
coverage that ships today. The same applies to bids
(``max_bid_amount_per_ad_set`` / ``max_cpc_bid_per_ad_group``). Over-detection
is the documented safe side here, exactly as in the scan.
"""

from __future__ import annotations

from mureo.policy.declarations import ArgumentPaths, BidDeclaration, BudgetDeclaration

#: Every money-carrying tool on the snapshot lives in this namespace. Bridged
#: tool names are forwarded verbatim, so the registry key is the full name.
TOOL_NAMESPACE = "campaign_management-"

#: Bridged tool (namespace stripped) → the budget paths its ``inputSchema``
#: declares. ``[]`` descends an array element-wise; ``*`` descends a dynamic
#: map whose keys are DATA (``add_country_campaign`` keys its per-country daily
#: budgets by marketplace code — 24 of them on the snapshot, each with its own
#: ``minimum: 1, maximum: 1000000``), which is why the wildcard is explicit.
BUDGET_PATHS: dict[str, tuple[str, ...]] = {
    "add_country_campaign": (
        "body.campaigns[].budgetCaps.countryMonetaryBudgetSettings.*.value",
    ),
    "create_ad_group": (
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
        "body.adGroups[].optimization.budgetSettings.dailyMinSpendValue",
    ),
    "create_campaign": (
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    "create_portfolio": (
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    "create_singleshot_portfolio": (
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    # The one-shot campaign tool nests ``budgets`` as an OBJECT, not an array,
    # and one level shallower than the general campaign tools.
    "create_singleshot_sp_campaign": (
        "body.oneshotCampaigns[].budgets.budgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    "update_ad_group": (
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.adGroups[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
        "body.adGroups[].optimization.budgetSettings.dailyMinSpendValue",
    ),
    "update_campaign": (
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    "update_campaign_budget": (
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.campaigns[].budgets[].budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
    "update_portfolio": (
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".monetaryBudget.value",
        "body.portfolios[].budget.budgetValue.monetaryBudgetValue"
        ".marketplaceSettings[].monetaryBudget.value",
    ),
}

#: Bridged tool (namespace stripped) → the bid paths its ``inputSchema``
#: declares. Ad groups carry three distinct bids plus a per-marketplace
#: override; targets carry one, likewise overridable per marketplace.
BID_PATHS: dict[str, tuple[str, ...]] = {
    "create_ad_group": (
        "body.adGroups[].bid.baseBid",
        "body.adGroups[].bid.defaultBid",
        "body.adGroups[].bid.maxAverageBid",
        "body.adGroups[].bid.marketplaceSettings[].defaultBid",
    ),
    "create_singleshot_sp_campaign": (
        "body.oneshotCampaigns[].bid.marketplaceSettings[].defaultBid",
    ),
    "create_target": (
        "body.targets[].bid.bid",
        "body.targets[].bid.marketplaceSettings[].bid",
    ),
    "update_ad_group": (
        "body.adGroups[].bid.baseBid",
        "body.adGroups[].bid.defaultBid",
        "body.adGroups[].bid.maxAverageBid",
        "body.adGroups[].bid.marketplaceSettings[].defaultBid",
    ),
    "update_target": (
        "body.targets[].bid.bid",
        "body.targets[].bid.marketplaceSettings[].bid",
    ),
    "update_target_bid": (
        "body.targets[].bid.bid",
        "body.targets[].bid.marketplaceSettings[].bid",
    ),
}


def _budget_declaration(specs: tuple[str, ...]) -> BudgetDeclaration:
    """One tool's budget declaration — the same paths on both cap channels."""
    paths = ArgumentPaths.parse(*specs)
    return BudgetDeclaration(daily_key=paths, lifetime_key=paths)


def _bid_declaration(specs: tuple[str, ...]) -> BidDeclaration:
    """One tool's bid declaration — the same paths on both cap channels."""
    paths = ArgumentPaths.parse(*specs)
    return BidDeclaration(bid_amount_key=paths, cpc_bid_key=paths)


#: Full bridged tool name → declaration, ready for the gate's registry.
#: Compiled at import so a malformed path in the tables above fails loudly in
#: testing rather than resolving to nothing — a path that silently never
#: matches is an unenforced cap.
BUDGET_DECLARATIONS: dict[str, BudgetDeclaration] = {
    TOOL_NAMESPACE + tool: _budget_declaration(specs)
    for tool, specs in BUDGET_PATHS.items()
}

BID_DECLARATIONS: dict[str, BidDeclaration] = {
    TOOL_NAMESPACE + tool: _bid_declaration(specs) for tool, specs in BID_PATHS.items()
}
