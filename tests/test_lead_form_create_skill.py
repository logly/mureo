"""Tests for the ``lead-form-create`` skill (v0.9.21).

Operator feedback: when the user says "create a form", the agent
should interview them one question at a time instead of either
making up parameters or dumping every field on screen. Pin the
interview pattern + image step + confirmation gate so a future
edit cannot silently drop those properties.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_PATHS = (
    REPO_ROOT / "skills" / "lead-form-create" / "SKILL.md",
    REPO_ROOT / "mureo" / "_data" / "skills" / "lead-form-create" / "SKILL.md",
)


def _read_skill(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestLeadFormCreateSkillStructure:
    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_skill_file_exists(self, path: Path) -> None:
        assert path.exists(), f"missing skill file: {path}"

    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_references_lead_forms_create_tool(self, path: Path) -> None:
        """The skill must point the agent at the right tool. Without
        this pin, a rewrite could silently route the agent elsewhere."""
        assert "meta_ads_lead_forms_create" in _read_skill(path)

    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_explicit_one_question_at_a_time_directive(self, path: Path) -> None:
        """The whole point of the skill (from the operator feedback)
        is that the agent asks ONE question at a time rather than
        dumping every parameter in one prompt."""
        body = _read_skill(path).lower()
        assert "one question at a time" in body

    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_image_step_covers_upload_and_reuse(self, path: Path) -> None:
        """Operator feedback explicitly called out the image — the
        agent should ask whether the user wants one AND offer both
        upload-new and reuse-existing paths so the user is not stuck
        when they have an existing creative library."""
        body = _read_skill(path)
        assert "image" in body.lower()
        # Both code paths must be discoverable from the skill text.
        assert "meta_ads_creatives_upload_image" in body
        assert "image_hash" in body or "reuse" in body.lower()

    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_privacy_policy_url_required(self, path: Path) -> None:
        """Meta rejects forms without an HTTPS privacy policy URL —
        the skill must collect it AND validate the https:// prefix."""
        body = _read_skill(path)
        assert "privacy_policy_url" in body or "privacy policy" in body.lower()
        # Pin the actual validation directive rather than the bare
        # "https://" token (which would pass on any URL example).
        lower = body.lower()
        assert "does not start with `https://`" in lower or (
            "https" in lower and "re-prompt" in lower
        )

    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_confirmation_gate_before_mutation(self, path: Path) -> None:
        """``meta_ads_lead_forms_create`` is mutating. The skill must
        instruct the agent to summarise + confirm before firing."""
        body = _read_skill(path).lower()
        assert "confirm" in body or "review" in body

    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_post_create_next_step_suggested(self, path: Path) -> None:
        """After form creation the natural next step is wiring it
        into a creative — surface that so the operator does not have
        to discover the connection separately."""
        assert "meta_ads_creatives_create_lead" in _read_skill(path)

    @pytest.mark.parametrize("path", _SKILL_PATHS)
    def test_higher_intent_tradeoff_explained(self, path: Path) -> None:
        """The 3-step form is a real lever with a CVR-vs-volume
        trade-off — the skill must explain it, not just expose the
        boolean."""
        body = _read_skill(path).lower()
        assert "higher_intent" in body or "higher-intent" in body
        # Both directions of the trade-off must appear so the agent
        # can quote them rather than guessing.
        assert "quality" in body or "junk" in body
        assert "volume" in body
