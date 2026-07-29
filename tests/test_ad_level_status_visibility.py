"""Ad-level delivery status must be visible to the standard flows (#468).

Manual operation in the platform UI and mureo-driven operation coexist —
especially during onboarding. An ad paused by hand, stopped because its ad
set/campaign went down, or rejected by policy still spends (or stops
spending) and still shapes the numbers mureo advises on. Three properties
keep that visible, and this module pins all three:

1. **Truthful tool descriptions.** A Meta ad tool that advertises a status
   field must actually request it. The historical bug was the reverse: the
   descriptions promised ``effective_status`` / ``configured_status`` /
   ``issues_info`` / ``ad_review_feedback`` while the request asked only for
   ``status``, so an agent filtered on a field that never arrived.
2. **Ad-level state in the standard flows.** ``/sync-state`` and
   ``/daily-check`` must fetch, persist, and diff ad-level status — and say
   so — otherwise the next run starts from the same blind spot.
3. **Mixed-operation framing.** Both skills must state that changes made
   outside mureo are first-class facts and that ``action_log`` is not the
   full history.

Skill assertions run against the PACKAGED copy (what PyPI users get) and
require the repo-root mirror to be byte-identical, matching the convention
in ``test_daily_check_structured_flags.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent

# The four Ad-node delivery-status fields this issue is about.
_AD_STATUS_FIELDS = (
    "effective_status",
    "configured_status",
    "issues_info",
    "ad_review_feedback",
)


def _skill_pair(name: str) -> tuple[Path, Path]:
    return (
        _ROOT / "mureo" / "_data" / "skills" / name / "SKILL.md",
        _ROOT / "skills" / name / "SKILL.md",
    )


def _skill_body(name: str) -> str:
    packaged, mirror = _skill_pair(name)
    assert packaged.read_bytes() == mirror.read_bytes(), (
        f"{name}: packaged skill and repo-root mirror have drifted; "
        "they must stay byte-identical."
    )
    return packaged.read_text(encoding="utf-8")


def _meta_tools() -> list:
    from mureo.mcp import tools_meta_ads

    return list(tools_meta_ads.TOOLS)


def _tool(name: str):
    return next(t for t in _meta_tools() if t.name == name)


# ---------------------------------------------------------------------------
# Part A — tool descriptions tell the truth about what is requested
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["meta_ads_ads_list", "meta_ads_ads_get"])
def test_ad_tool_description_status_claims_are_requested(tool_name: str) -> None:
    """Every ad-status field named in the description is in ``_AD_FIELDS``."""
    from mureo.meta_ads._ads import AdsMixin

    description = _tool(tool_name).description or ""
    claimed = [f for f in _AD_STATUS_FIELDS if f in description]
    assert claimed, f"{tool_name} should still document its status fields"
    for field_name in claimed:
        assert field_name in AdsMixin._AD_FIELDS, (
            f"{tool_name} advertises {field_name!r} but the ad request never "
            "asks for it — the description would be a lie the agent acts on."
        )


def test_ads_get_still_documents_all_four_status_fields() -> None:
    """``meta_ads_ads_get`` is the drill-down tool for a WITH_ISSUES ad, so it
    must keep documenting the full status quartet (now genuinely returned)."""
    description = _tool("meta_ads_ads_get").description or ""
    for field_name in _AD_STATUS_FIELDS:
        assert field_name in description


def test_no_meta_tool_description_promises_delivery_estimate() -> None:
    """``delivery_estimate`` is an ad-set *edge*, not a node field mureo
    requests anywhere. Promising it in a description sends the agent looking
    for a key that never arrives."""
    offenders = [
        t.name for t in _meta_tools() if "delivery_estimate" in (t.description or "")
    ]
    assert not offenders, (
        "These Meta tool descriptions promise delivery_estimate, which mureo "
        f"never requests: {offenders}"
    )


def test_campaign_and_ad_set_status_claims_are_requested() -> None:
    """Same truthfulness rule one level up: an ad set or campaign stopped
    outside mureo is exactly what leaves an ACTIVE ad not delivering."""
    from mureo.meta_ads._ad_sets import AdSetsMixin
    from mureo.meta_ads._campaigns import CampaignsMixin

    for tool_name, fields in (
        ("meta_ads_campaigns_list", CampaignsMixin._CAMPAIGN_FIELDS),
        ("meta_ads_campaigns_get", CampaignsMixin._CAMPAIGN_FIELDS),
        ("meta_ads_ad_sets_list", AdSetsMixin._AD_SET_FIELDS),
        ("meta_ads_ad_sets_get", AdSetsMixin._AD_SET_FIELDS),
    ):
        description = _tool(tool_name).description or ""
        for field_name in ("effective_status", "issues_info"):
            if field_name in description:
                assert field_name in fields, (
                    f"{tool_name} advertises {field_name!r} but it is not " "requested."
                )


# A snake_case token in a description that names a returned field. Tool ids are
# excluded by prefix; the rest are call parameters / prose, not response keys.
_FIELD_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_NOT_A_RESPONSE_FIELD = frozenset(
    {
        # Request parameter, and the response spells the same value ``id``.
        "campaign_id",
        "ad_set_id",
        "ad_id",
        "account_id",
        "status_filter",
        # Prose, not a field name.
        "read_only",
    }
)
_TOOL_ID_PREFIXES = ("meta_ads_", "google_ads_", "mureo_", "search_console_")


def _claimed_field_names(description: str) -> set[str]:
    return {
        token
        for token in _FIELD_TOKEN_RE.findall(description)
        if not token.startswith(_TOOL_ID_PREFIXES)
        and token not in _NOT_A_RESPONSE_FIELD
    }


@pytest.mark.parametrize(
    "tool_name", ["meta_ads_campaigns_list", "meta_ads_campaigns_get"]
)
def test_campaign_descriptions_claim_only_requested_fields(tool_name: str) -> None:
    """EVERY field name a campaign description promises must be requested.

    Checking only the status fields let ``buying_type`` (never requested) and
    ``spend_cap`` (the requested field is ``budget_remaining``) survive — the
    same description-vs-implementation drift as #274 and #468, just on other
    field names. Pinning the whole claim set closes the class, not one case.
    """
    from mureo.meta_ads._campaigns import CampaignsMixin

    description = _tool(tool_name).description or ""
    claimed = _claimed_field_names(description)
    assert claimed, f"{tool_name} should still document its returned fields"
    missing = sorted(f for f in claimed if f not in CampaignsMixin._CAMPAIGN_FIELDS)
    assert not missing, (
        f"{tool_name} advertises fields mureo never requests: {missing}. "
        "Either request them or drop the claim."
    )


def test_ads_list_qualifies_conditionally_returned_fields() -> None:
    """``issues_info`` / ``ad_review_feedback`` are only populated when Meta
    reports a problem. An unqualified promise reads as "always present", so an
    agent seeing them absent could conclude the ad was checked and is clean."""
    description = _tool("meta_ads_ads_list").description or ""
    qualifier_window = description[description.index("ad_review_feedback") :]
    assert "when" in qualifier_window, (
        "meta_ads_ads_list must qualify that issues_info / ad_review_feedback "
        "appear only when Meta returns them."
    )


# ---------------------------------------------------------------------------
# Part A — the ad-fatigue skill's Meta filter is now workable
# ---------------------------------------------------------------------------


def test_ad_fatigue_check_effective_status_filter_is_grounded() -> None:
    """The skill filters Meta ads by ``effective_status``; the wording must
    name the field mureo actually returns and the value that means
    'delivering'."""
    body = _skill_body("ad-fatigue-check")
    assert "effective_status" in body
    assert "ACTIVE" in body


# ---------------------------------------------------------------------------
# Part B — ad-level state in the standard flows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill", ["sync-state", "daily-check"])
def test_standard_flow_fetches_ad_level_status(skill: str) -> None:
    """The flow must list ads with their status for ACTIVE campaigns."""
    body = _skill_body(skill)
    assert "meta_ads_ads_list" in body
    assert "effective_status" in body


@pytest.mark.parametrize("skill", ["sync-state", "daily-check"])
def test_standard_flow_persists_ads_via_upsert(skill: str) -> None:
    """Fetching without persisting means the next run is blind again — the
    ads must be written through ``mureo_state_upsert_campaign``'s ``ads``."""
    body = _skill_body(skill)
    assert "mureo_state_upsert_campaign" in body
    assert "`ads`" in body


@pytest.mark.parametrize("skill", ["sync-state", "daily-check"])
def test_standard_flow_bounds_ad_fetch_to_active_campaigns(skill: str) -> None:
    """API cost guard: ad-level fetch is scoped to ACTIVE campaigns."""
    body = _skill_body(skill)
    assert "ACTIVE campaign" in body


@pytest.mark.parametrize("skill", ["sync-state", "daily-check"])
def test_standard_flow_diffs_ad_level_status(skill: str) -> None:
    """ "Status changes" must genuinely cover ad-level changes, including the
    ones made outside mureo."""
    body = _skill_body(skill)
    assert "Ad-level status changes" in body


@pytest.mark.parametrize("skill", ["sync-state", "daily-check"])
def test_standard_flow_documents_mixed_operation(skill: str) -> None:
    """Manual and mureo-driven operation coexist; an externally-made change is
    a fact to report, never something to absorb silently."""
    body = _skill_body(skill)
    assert "Mixed operation" in body
    assert "action_log" in body
    assert "outside mureo" in body


# ---------------------------------------------------------------------------
# Part C — every skill that calls a BYOD-wrapped read knows to unwrap it
# ---------------------------------------------------------------------------


# (skill, tool) for every workflow-skill bullet that CONSUMES rows from a tool
# whose BYOD response is wrapped by ``_entity_result``. Reference-only mentions
# are deliberately excluded: ``_mureo-meta-ads`` lists these tools in its
# capability table and ``_mureo-shared`` names one as a connectivity check —
# neither reads rows, so neither needs the unwrap instruction.
_BYOD_WRAPPED_CALL_SITES = [
    ("sync-state", "meta_ads_campaigns_list"),
    ("sync-state", "meta_ads_ads_list"),
    ("daily-check", "meta_ads_campaigns_list"),
    ("daily-check", "meta_ads_ads_list"),
    ("ad-fatigue-check", "meta_ads_ads_list"),
    ("audience-review", "meta_ads_ad_sets_list"),
    ("experiment", "meta_ads_ad_sets_list"),
]


@pytest.mark.parametrize(("skill", "tool"), _BYOD_WRAPPED_CALL_SITES)
def test_byod_wrapped_call_sites_document_the_unwrap(skill: str, tool: str) -> None:
    """A BYOD-served read comes back wrapped; a bullet that reads its rows
    without saying so sends the agent indexing into an envelope.

    The marker was added for the ad-level reads, but these tools were already
    being called from older bullets — leaving those unqualified would turn a
    freshness improvement into a breakage for BYOD users.
    """
    body = _skill_body(skill)
    call_lines = [line for line in body.splitlines() if tool in line]
    assert call_lines, f"{skill} no longer calls {tool} — update the call-site list"
    unqualified = [line for line in call_lines if "byod_import" not in line]
    assert not unqualified, (
        f"{skill} calls {tool} without telling the agent that a BYOD response "
        f"is wrapped in a data envelope:\n" + "\n".join(unqualified)
    )
