"""Creative guidance must never offer a change no tool can apply (#591).

Field report: asked about a Performance Max campaign, mureo offered to
rewrite the headlines, drafted replacements, took a "yes" — and only then
discovered that every write tool it knew (``google_ads_ads_create`` /
``google_ads_ads_update``) is RSA-only. The answer became "do it yourself in
the Google Ads UI" after the operator had already spent a round trip.

#590 landed ``google_ads_asset_group_assets_list`` /
``google_ads_asset_group_assets_replace`` and #626 widened the read to a
P-MAX asset group's images and added
``google_ads_asset_group_images_replace``, so P-MAX text and images are both
applicable now. That fixes two instances; it does not fix the shape of the
bug. The durable requirement is that the offer be scoped by *whether a write
tool exists for this exact surface*, decided **before** drafting — so the
same guidance keeps working for the surfaces still uncovered (video,
business name, and every other non-text non-image field type of a P-MAX
asset group) and for whatever the tool layer gains next.

The tests below therefore pin the rule's *shape* and its accuracy at this
moment, and are expected to be edited whenever the tool layer moves. Prose
that claims a surface is draft-only after it gained a write tool is the same
defect pointing the other way.

Pinned in BOTH the packaged copy and the repo-root mirror, kept
byte-identical.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills"
_MIRROR = _ROOT / "skills"

#: Every skill this issue touches: the one that makes the offer, the one
#: that routes into it, and the strategy playbook that names the write tool.
_SKILLS = ("creative-refresh", "ad-fatigue-check", "_mureo-strategy")

#: The heading that owns the rule. Referenced by name from the other two
#: skills, so it is part of the contract, not decoration.
_RULE_HEADING = "## Apply or draft"

#: The P-MAX ad-copy surface #590 added.
_PMAX_LIST = "google_ads_asset_group_assets_list"
_PMAX_REPLACE = "google_ads_asset_group_assets_replace"

#: The P-MAX image surface #626 added, on the same read.
_PMAX_IMAGE_REPLACE = "google_ads_asset_group_images_replace"


def _body(name: str) -> str:
    return (_PACKAGED / name / "SKILL.md").read_text(encoding="utf-8")


def _lines(body: str, needle: str) -> list[str]:
    lowered = needle.lower()
    return [ln for ln in body.splitlines() if lowered in ln.lower()]


def _section(body: str, heading: str) -> str:
    """Return the text under ``heading`` up to the next heading of the same
    or shallower depth."""
    depth = len(heading) - len(heading.lstrip("#"))
    out: list[str] = []
    inside = False
    for line in body.splitlines():
        if line.startswith(heading):
            inside = True
            continue
        if (
            inside
            and line.startswith("#")
            and len(line) - len(line.lstrip("#")) <= depth
        ):
            break
        if inside:
            out.append(line)
    assert out, f"section not found: {heading}"
    return "\n".join(out)


@pytest.mark.parametrize("name", _SKILLS)
def test_copies_are_byte_identical(name: str) -> None:
    packaged = _PACKAGED / name / "SKILL.md"
    mirror = _MIRROR / name / "SKILL.md"
    assert packaged.read_bytes() == mirror.read_bytes(), f"{name}: copies differ"


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


def test_creative_refresh_has_the_apply_or_draft_rule() -> None:
    """The skill that makes the offer owns the rule."""
    assert _RULE_HEADING in _body("creative-refresh")


def test_rule_is_decided_before_drafting() -> None:
    """Deciding after approval is the bug. The rule has to be applied at
    draft time, and the verdict has to travel with the draft."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING).lower()
    assert "before you draft" in rule
    assert "approval" in rule


def test_rule_offers_paste_in_copy_as_the_uncovered_outcome() -> None:
    """Drafting for the operator to paste in by hand is a fine outcome —
    stated as that from the start."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING).lower()
    assert "paste" in rule
    assert "draft" in rule


def test_rule_forbids_offering_to_apply_what_no_tool_writes() -> None:
    rule = _section(_body("creative-refresh"), _RULE_HEADING).lower()
    assert "never offer to apply" in rule


def test_rule_keys_on_tool_existence_not_on_campaign_type() -> None:
    """This is the anti-rot clause: a hard-coded list of campaign types is
    exactly how this issue came to exist. The named surfaces are a snapshot;
    the session's tool list is the boundary."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING).lower()
    assert "snapshot" in rule
    assert "not** the boundary" in rule or "not the boundary" in rule
    assert "tool list you can actually see in this session" in rule


def test_rule_covers_a_tool_that_is_named_but_absent() -> None:
    """The inverse direction: a surface the table calls writable is still
    draft-only in a session where that tool was not loaded."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING).lower()
    assert "absent" in rule


# ---------------------------------------------------------------------------
# What the tool layer covers today
# ---------------------------------------------------------------------------


def test_rule_names_the_pmax_text_route() -> None:
    """#590 landed: P-MAX text is applicable now. Saying otherwise would be
    the same defect pointing the other way."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING)
    assert _PMAX_LIST in rule
    assert _PMAX_REPLACE in rule


def test_rule_names_the_rsa_route_and_its_limit() -> None:
    rule = _section(_body("creative-refresh"), _RULE_HEADING)
    assert "google_ads_ads_update" in rule
    assert "google_ads_ads_create" in rule


def test_rule_names_the_pmax_image_route() -> None:
    """#626 landed: a P-MAX asset group's images are applicable now, from
    the same read. Calling them draft-only would be #591's defect pointing
    the other way."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING)
    assert _PMAX_IMAGE_REPLACE in rule
    for field_type in ("MARKETING_IMAGE", "LOGO"):
        assert field_type in rule


def test_rule_names_both_image_entry_points_on_one_tool() -> None:
    """The operator must not have to know whether the account already holds
    the image in order to pick a tool name."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING)
    image_lines = "\n".join(_lines(rule, _PMAX_IMAGE_REPLACE))
    assert "new_asset_id" in image_lines
    assert "new_image_path" in image_lines


def test_rule_still_marks_the_uncovered_asset_kinds_draft_only() -> None:
    """What the tool layer does NOT cover: video, business name, and every
    other non-text non-image field type of a P-MAX asset group."""
    rule = _section(_body("creative-refresh"), _RULE_HEADING).lower()
    assert "draft-only" in rule
    for kind in ("video", "business name"):
        assert kind in rule, f"the uncovered surfaces must name {kind}"
    uncovered = "\n".join(
        ln for ln in _lines(rule, "draft-only") if "video" in ln.lower()
    )
    assert "none" in uncovered, "an uncovered surface must show no write tool"


def test_audit_step_reads_pmax_copy_instead_of_missing_it() -> None:
    """``google_ads_ads_list`` returns no rows for a P-MAX campaign, so an
    audit that only calls it reports a P-MAX account as having no ad copy."""
    body = _body("creative-refresh")
    pmax_reads = [ln for ln in _lines(body, _PMAX_LIST) if "ads_list" in ln]
    assert pmax_reads, (
        "the creative audit must say that google_ads_ads_list misses P-MAX "
        f"and route to {_PMAX_LIST}"
    )


def test_execute_step_routes_pmax_to_the_replace_tool() -> None:
    """The swap takes asset_group_id + field_type + old_asset_id — not the
    ad-level arguments of google_ads_ads_update."""
    body = _body("creative-refresh")
    exec_lines = _lines(body, _PMAX_REPLACE)
    assert exec_lines
    joined = "\n".join(exec_lines)
    for arg in ("asset_group_id", "field_type", "old_asset_id"):
        assert arg in joined, f"the P-MAX swap must name {arg}"


def test_execute_step_routes_pmax_images_to_their_own_tool() -> None:
    """An image swap is not a text swap: it takes an asset id or a file
    path, not ``new_text``."""
    body = _body("creative-refresh")
    exec_lines = "\n".join(_lines(body, _PMAX_IMAGE_REPLACE))
    assert exec_lines
    for arg in ("asset_group_id", "field_type", "old_asset_id"):
        assert arg in exec_lines, f"the P-MAX image swap must name {arg}"


def test_audit_step_reads_pmax_images_not_only_its_text() -> None:
    """The read returns both kinds in one call; an audit that reports only
    the text is the same "P-MAX has no creative" blind spot one level in."""
    body = _body("creative-refresh")
    reads = "\n".join(_lines(body, _PMAX_LIST))
    assert "MARKETING_IMAGE" in reads
    assert "url" in reads


# ---------------------------------------------------------------------------
# The visual-evaluation instruction the issue calls out as unsatisfiable
# ---------------------------------------------------------------------------


def test_visual_evaluation_no_longer_claims_a_pmax_asset_is_retrievable() -> None:
    """``a Google image/Display/PMax asset`` was one undifferentiated
    promise. The surfaces differ and the skill has to say how."""
    body = _body("creative-refresh")
    assert "image/Display/PMax asset" not in body


def test_visual_evaluation_routes_pmax_images_to_the_asset_group_read() -> None:
    """#626 closed the gap #591 recorded: the images of a given P-MAX asset
    group are enumerable now, so the visual-evaluation instruction is
    satisfiable for P-MAX and must name the read that satisfies it."""
    body = _body("creative-refresh")
    section = _section(body, "### Getting the image in front of you")
    assert _PMAX_LIST in section
    assert "url" in section


def test_visual_evaluation_still_states_what_cannot_be_retrieved() -> None:
    """The account-wide caveat on ``google_ads_image_assets_list`` survives:
    outside a P-MAX asset group it still does not say which ad serves an
    asset, and no Google read returns video assets."""
    body = _body("creative-refresh")
    assert "google_ads_image_assets_list" in body
    section = _section(body, "### Getting the image in front of you").lower()
    assert "account-wide" in section
    assert "video" in section


def test_no_line_still_calls_the_pmax_read_text_only() -> None:
    """The #591 wording. Leaving it in place would send a reader looking for
    an image route that is now right there in the same result."""
    body = _body("creative-refresh")
    stale = [ln for ln in _lines(body, _PMAX_LIST) if "text only" in ln.lower()]
    assert not stale, f"stale text-only claim about {_PMAX_LIST}: {stale}"


# ---------------------------------------------------------------------------
# The hand-off must inherit the scoping, not bypass it
# ---------------------------------------------------------------------------


def test_ad_fatigue_handoff_inherits_the_rule() -> None:
    body = _body("ad-fatigue-check")
    handoff = _lines(body, "/creative-refresh")
    assert handoff
    joined = "\n".join(handoff)
    assert "Apply or draft" in joined, (
        "/ad-fatigue-check routes fatigued creatives into /creative-refresh "
        "without inheriting its apply-or-draft scoping"
    )


def test_ad_fatigue_does_not_promise_a_rewrite_it_cannot_price() -> None:
    """The routing skill does not know whether a write tool covers the
    fatigued creative, so it must not commit mureo to applying anything."""
    body = _body("ad-fatigue-check").lower()
    handoff = "\n".join(_lines(body, "/creative-refresh"))
    assert "do not" in handoff or "never" in handoff


# ---------------------------------------------------------------------------
# The strategy playbook routes drafted copy straight into RSA-only tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    ["### 1. Persona-Based Ad Copy Creation", "### 3. Brand Voice Compliance Check"],
)
def test_strategy_workflows_route_pmax_to_its_own_tools(heading: str) -> None:
    section = _section(_body("_mureo-strategy"), heading)
    assert _PMAX_REPLACE in section, (
        f"{heading} sends drafted copy into an RSA-only tool with no P-MAX " "branch"
    )


def test_strategy_workflows_defer_uncovered_surfaces_to_the_rule() -> None:
    body = _body("_mureo-strategy")
    assert "Apply or draft" in body, (
        "the strategy playbook must point at the creative-refresh rule for "
        "surfaces no write tool covers"
    )


def test_brand_voice_check_knows_ads_list_misses_pmax() -> None:
    """Listing ads to audit brand voice silently skips every P-MAX campaign."""
    section = _section(_body("_mureo-strategy"), "### 3. Brand Voice Compliance Check")
    assert _PMAX_LIST in section
