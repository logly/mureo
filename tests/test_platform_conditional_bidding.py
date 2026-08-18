"""Auction / bid-strategy semantics are platform-conditional (#647).

mureo's platform-agnostic instruction text and its shared entity vocabulary
used to state auction, smart-bidding and bid-strategy semantics as
unconditional facts. On a platform whose delivery is not selected by a bid
those statements are simply false, and the agent carries them over anyway —
describing such a campaign in another platform's terms, in a report or in a
stored learning entry.

Three properties keep that from coming back, and this module pins all three:

1. **The shared enum can say "not applicable".** ``BidStrategy`` has a member
   for a platform that has no bid strategy, kept distinct from ``None``
   ("unknown / not fetched"). A write path never accepts it.
2. **The always-loaded MCP schema says so too.** ``mureo_state_upsert_campaign``
   is the single cross-platform state-write tool, so its bidding fields carry
   descriptions that state the platform-conditional contract.
3. **The prose is qualified, not unconditional.** Each shared-skill line that
   asserted an auction / smart-bidding fact now names the platforms it holds
   for, the way ``budget-pacing`` and ``daily-check`` already did.

Skill assertions run against the PACKAGED copy (what PyPI users get) and
require the repo-root mirror to be byte-identical, matching the convention in
``test_ad_level_status_visibility.py``. ``_mureo-pro-diagnosis`` ships only
from the repo root, so it is read there.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent


def _skill_body(name: str) -> str:
    mirror = _ROOT / "skills" / name / "SKILL.md"
    packaged = _ROOT / "mureo" / "_data" / "skills" / name / "SKILL.md"
    if not packaged.exists():
        # Repo-root-only skill (e.g. the pro diagnosis framework).
        return mirror.read_text(encoding="utf-8")
    assert packaged.read_bytes() == mirror.read_bytes(), (
        f"{name}: packaged skill and repo-root mirror have drifted; "
        "they must stay byte-identical."
    )
    return packaged.read_text(encoding="utf-8")


def _line_with(body: str, anchor: str, *, skill: str) -> str:
    matches = [line for line in body.splitlines() if anchor in line]
    assert matches, f"{skill}: no line containing {anchor!r}"
    return "\n".join(matches)


# A platform condition is either a named platform or an explicit "the
# platforms that work this way" limb — the two shapes already in the tree
# (``budget-pacing`` line 63, ``daily-check``'s learning-state guard).
_QUALIFIER = re.compile(
    r"Google Ads|Meta|Amazon|platforms? that|platforms? whose|"
    r"where the platform|platform-conditional|has no bid strategy",
)


# ---------------------------------------------------------------------------
# 1. The shared enum can say "not applicable"
# ---------------------------------------------------------------------------


def test_bid_strategy_has_a_not_applicable_member() -> None:
    """A platform that selects delivery some other way than by a bid needs a
    value of its own — otherwise it must misreport itself as one of the
    auction strategies."""
    from mureo.core.providers.models import BidStrategy

    assert BidStrategy.NOT_APPLICABLE.value == "not_applicable"


def test_bid_strategy_values_are_the_documented_set() -> None:
    """The values are the ABI (``docs/ABI-stability.md`` section 5): additions
    are non-breaking, removals are not."""
    from mureo.core.providers.models import BidStrategy

    assert {member.value for member in BidStrategy} == {
        "manual_cpc",
        "target_cpa",
        "maximize_conversions",
        "not_applicable",
    }
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", m.value) for m in BidStrategy)


def test_not_applicable_is_distinguishable_from_unknown() -> None:
    """``None`` keeps its own meaning — *not fetched*. Collapsing the two
    would make an unasked platform read as a platform without bidding."""
    from mureo.core.providers.models import (
        BidStrategy,
        CreateCampaignRequest,
        UpdateCampaignRequest,
    )

    not_fetched = CreateCampaignRequest(name="c", daily_budget_micros=1_000_000)
    declared = CreateCampaignRequest(
        name="c",
        daily_budget_micros=1_000_000,
        bidding_strategy=BidStrategy.NOT_APPLICABLE,
    )
    assert not_fetched.bidding_strategy is None
    assert declared.bidding_strategy is BidStrategy.NOT_APPLICABLE
    assert declared.bidding_strategy != not_fetched.bidding_strategy

    assert UpdateCampaignRequest().bidding_strategy is None


def test_not_applicable_is_documented_for_plugin_authors() -> None:
    """Plugins implement the shared vocabulary from the docs, not the source."""
    abi = (_ROOT / "docs" / "ABI-stability.md").read_text(encoding="utf-8")
    authoring = (_ROOT / "docs" / "plugin-authoring.md").read_text(encoding="utf-8")
    for name, text in (("ABI-stability.md", abi), ("plugin-authoring.md", authoring)):
        assert "NOT_APPLICABLE" in text, f"{name}: NOT_APPLICABLE undocumented"


# ---------------------------------------------------------------------------
# 2. The always-loaded MCP schema
# ---------------------------------------------------------------------------


def _upsert_campaign_properties() -> dict:
    from mureo.mcp.tools_mureo_context import TOOLS

    tool = next(t for t in TOOLS if t.name == "mureo_state_upsert_campaign")
    return tool.inputSchema["properties"]["campaign"]["properties"]


def test_bidding_strategy_type_carries_a_description() -> None:
    """The single cross-platform state-write tool sits in context in every
    session the mureo server is loaded in — an undescribed bidding field is
    filled in from whatever vocabulary the model already has."""
    described = _upsert_campaign_properties()["bidding_strategy_type"]
    assert described.get("description"), "bidding_strategy_type has no description"


def test_bidding_field_descriptions_state_the_platform_condition() -> None:
    """Both bidding fields say the same thing the skill contract says: the
    platform's own vocabulary, omitted where the concept does not exist."""
    props = _upsert_campaign_properties()
    for field in ("bidding_strategy_type", "bidding_details"):
        description = props[field]["description"]
        assert "Omit" in description or "omit" in description, (
            f"{field}: description does not say to omit the field for a "
            "platform that has no bid strategy"
        )


def test_bidding_details_does_not_lead_with_one_platform() -> None:
    """The Google Ads key is a real, useful detail — but it is an example of
    the contract, not the contract itself, so it must not open the text."""
    description = _upsert_campaign_properties()["bidding_details"]["description"]
    assert "Google Ads" in description
    assert _QUALIFIER.search(description)
    assert description.index("own vocabulary") < description.index("Google Ads")


# ---------------------------------------------------------------------------
# 3. The prose is qualified, not unconditional
# ---------------------------------------------------------------------------


# (skill, the exact unconditional wording that must not come back)
_RETIRED_WORDINGS: tuple[tuple[str, str], ...] = (
    ("budget-rebalance", "(smart bidding learning risk)"),
    ("_mureo-learning", "Smart bidding needs ~7 days to re-learn"),
    ("_mureo-learning", "Full learning period for smart bidding"),
    ("_mureo-learning", "Did a competitor enter or exit the auction?"),
    ("daily-check", "Run auction/competitive insights on key campaigns."),
    ("incident-postmortem", "a holiday, a competitor entering the auction,"),
    ("incident-postmortem", "an auction/CPM shift"),
    ("_mureo-pro-diagnosis", "conversion data for the bidding strategy?"),
)


@pytest.mark.parametrize(("skill", "wording"), _RETIRED_WORDINGS)
def test_unconditional_wording_stays_retired(skill: str, wording: str) -> None:
    assert wording not in _skill_body(skill), (
        f"{skill}: {wording!r} states an auction fact unconditionally; "
        "qualify it with the platforms it holds for."
    )


# (skill, anchor that survives the edit)
_QUALIFIED_LINES: tuple[tuple[str, str], ...] = (
    ("budget-rebalance", "**Risk assessment**"),
    ("_mureo-learning", "| Budget change (>10%) |"),
    ("_mureo-learning", "| Bid strategy change | 21 days |"),
    ("_mureo-learning", "competitor"),
    ("daily-check", "**COMPETITOR_DEFENSE**"),
    ("incident-postmortem", "**Platform-side**"),
    ("incident-postmortem", "**External**"),
    ("sync-state", "Bidding strategy changes"),
    ("_mureo-pro-diagnosis", "2. Data "),
)


@pytest.mark.parametrize(("skill", "anchor"), _QUALIFIED_LINES)
def test_bidding_lines_name_their_platform_condition(skill: str, anchor: str) -> None:
    line = _line_with(_skill_body(skill), anchor, skill=skill)
    assert _QUALIFIER.search(line), (
        f"{skill}: the line at {anchor!r} states an auction / bid-strategy "
        "fact without naming the platforms it holds for."
    )


def test_impression_share_is_attributed_not_canonical() -> None:
    """``impression_share`` is not in the canonical metric vocabulary
    (``_mureo-strategy`` → *Performance Metrics*), so every mention has to say
    whose metric it is."""
    body = _skill_body("_mureo-learning")
    for line in body.splitlines():
        if "impression_share" in line:
            assert "Google Ads" in line, (
                "_mureo-learning: impression_share is listed as if it were a "
                f"canonical cross-platform metric: {line!r}"
            )


def test_shared_contract_covers_pricing_and_selection_fields() -> None:
    """The status-vocabulary contract is the one place that already says
    'store it verbatim, do not translate it, omit it where the platform has no
    such thing'. Pricing and delivery-selection fields live under the same
    rule — not under a second one written next to it."""
    body = _skill_body("_mureo-shared")
    start = body.index("### Status vocabulary contract")
    end = body.index("\n## ", start)
    section = body[start:end]

    assert "bidding_strategy_type" in section
    assert "bidding_details" in section
    assert "omits" in section
    # A platform whose primary figure has no canonical key must not borrow
    # one that means something else (the CPM / eCPM case).
    assert "canonical key" in section
