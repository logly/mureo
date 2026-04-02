"""Tests for mureo slash commands and workflow skill."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Project root and command directory
PROJECT_ROOT = Path(__file__).parent.parent
COMMANDS_DIR = PROJECT_ROOT / ".claude" / "commands"
SKILL_FILE = PROJECT_ROOT / "skills" / "mureo-workflows" / "SKILL.md"

# All expected command files
EXPECTED_COMMANDS = [
    "onboard.md",
    "daily-check.md",
    "rescue.md",
    "search-term-cleanup.md",
    "creative-refresh.md",
    "budget-rebalance.md",
    "competitive-scan.md",
    "sync-state.md",
]

# Known MCP tool names extracted from SKILL.md files
# Google Ads tools (82 tools from mureo-google-ads/SKILL.md)
GOOGLE_ADS_TOOLS: set[str] = {
    "google_ads.campaigns.list",
    "google_ads.campaigns.get",
    "google_ads.campaigns.create",
    "google_ads.campaigns.update",
    "google_ads.campaigns.update_status",
    "google_ads.campaigns.diagnose",
    "google_ads.ad_groups.list",
    "google_ads.ad_groups.create",
    "google_ads.ad_groups.update",
    "google_ads.ads.list",
    "google_ads.ads.create",
    "google_ads.ads.update",
    "google_ads.ads.update_status",
    "google_ads.ads.policy_details",
    "google_ads.keywords.list",
    "google_ads.keywords.add",
    "google_ads.keywords.remove",
    "google_ads.keywords.suggest",
    "google_ads.keywords.diagnose",
    "google_ads.keywords.pause",
    "google_ads.keywords.audit",
    "google_ads.keywords.cross_adgroup_duplicates",
    "google_ads.negative_keywords.list",
    "google_ads.negative_keywords.add",
    "google_ads.negative_keywords.remove",
    "google_ads.negative_keywords.add_to_ad_group",
    "google_ads.negative_keywords.suggest",
    "google_ads.budget.get",
    "google_ads.budget.update",
    "google_ads.budget.create",
    "google_ads.accounts.list",
    "google_ads.search_terms.report",
    "google_ads.search_terms.review",
    "google_ads.search_terms.analyze",
    "google_ads.sitelinks.list",
    "google_ads.sitelinks.create",
    "google_ads.sitelinks.remove",
    "google_ads.callouts.list",
    "google_ads.callouts.create",
    "google_ads.callouts.remove",
    "google_ads.conversions.list",
    "google_ads.conversions.get",
    "google_ads.conversions.performance",
    "google_ads.conversions.create",
    "google_ads.conversions.update",
    "google_ads.conversions.remove",
    "google_ads.conversions.tag",
    "google_ads.recommendations.list",
    "google_ads.recommendations.apply",
    "google_ads.device_targeting.get",
    "google_ads.device_targeting.set",
    "google_ads.bid_adjustments.get",
    "google_ads.bid_adjustments.update",
    "google_ads.location_targeting.list",
    "google_ads.location_targeting.update",
    "google_ads.schedule_targeting.list",
    "google_ads.schedule_targeting.update",
    "google_ads.change_history.list",
    "google_ads.performance.report",
    "google_ads.performance.analyze",
    "google_ads.cost_increase.investigate",
    "google_ads.health_check.all",
    "google_ads.ad_performance.compare",
    "google_ads.ad_performance.report",
    "google_ads.network_performance.report",
    "google_ads.budget.efficiency",
    "google_ads.budget.reallocation",
    "google_ads.auction_insights.get",
    "google_ads.auction_insights.analyze",
    "google_ads.rsa_assets.analyze",
    "google_ads.rsa_assets.audit",
    "google_ads.cpc.detect_trend",
    "google_ads.device.analyze",
    "google_ads.btob.optimizations",
    "google_ads.landing_page.analyze",
    "google_ads.creative.research",
    "google_ads.monitoring.delivery_goal",
    "google_ads.monitoring.cpa_goal",
    "google_ads.monitoring.cv_goal",
    "google_ads.monitoring.zero_conversions",
    "google_ads.capture.screenshot",
    "google_ads.assets.upload_image",
}

# Meta Ads tools (77 tools from mureo-meta-ads/SKILL.md)
META_ADS_TOOLS: set[str] = {
    "meta_ads.campaigns.list",
    "meta_ads.campaigns.get",
    "meta_ads.campaigns.create",
    "meta_ads.campaigns.update",
    "meta_ads.campaigns.pause",
    "meta_ads.campaigns.enable",
    "meta_ads.ad_sets.list",
    "meta_ads.ad_sets.get",
    "meta_ads.ad_sets.create",
    "meta_ads.ad_sets.update",
    "meta_ads.ad_sets.pause",
    "meta_ads.ad_sets.enable",
    "meta_ads.ads.list",
    "meta_ads.ads.get",
    "meta_ads.ads.create",
    "meta_ads.ads.update",
    "meta_ads.ads.pause",
    "meta_ads.ads.enable",
    "meta_ads.insights.report",
    "meta_ads.insights.breakdown",
    "meta_ads.analysis.performance",
    "meta_ads.analysis.audience",
    "meta_ads.analysis.placements",
    "meta_ads.analysis.cost",
    "meta_ads.analysis.compare_ads",
    "meta_ads.analysis.suggest_creative",
    "meta_ads.audiences.list",
    "meta_ads.audiences.get",
    "meta_ads.audiences.create",
    "meta_ads.audiences.delete",
    "meta_ads.audiences.create_lookalike",
    "meta_ads.pixels.list",
    "meta_ads.pixels.get",
    "meta_ads.pixels.stats",
    "meta_ads.pixels.events",
    "meta_ads.conversions.send",
    "meta_ads.conversions.send_purchase",
    "meta_ads.conversions.send_lead",
    "meta_ads.creatives.list",
    "meta_ads.creatives.create",
    "meta_ads.creatives.create_dynamic",
    "meta_ads.creatives.upload_image",
    "meta_ads.creatives.create_carousel",
    "meta_ads.creatives.create_collection",
    "meta_ads.images.upload_file",
    "meta_ads.catalogs.list",
    "meta_ads.catalogs.get",
    "meta_ads.catalogs.create",
    "meta_ads.catalogs.delete",
    "meta_ads.products.list",
    "meta_ads.products.get",
    "meta_ads.products.add",
    "meta_ads.products.update",
    "meta_ads.products.delete",
    "meta_ads.feeds.list",
    "meta_ads.feeds.create",
    "meta_ads.lead_forms.list",
    "meta_ads.lead_forms.get",
    "meta_ads.lead_forms.create",
    "meta_ads.leads.get",
    "meta_ads.leads.get_by_ad",
    "meta_ads.videos.upload",
    "meta_ads.videos.upload_file",
    "meta_ads.split_tests.list",
    "meta_ads.split_tests.get",
    "meta_ads.split_tests.create",
    "meta_ads.split_tests.end",
    "meta_ads.ad_rules.list",
    "meta_ads.ad_rules.get",
    "meta_ads.ad_rules.create",
    "meta_ads.ad_rules.update",
    "meta_ads.ad_rules.delete",
    "meta_ads.page_posts.list",
    "meta_ads.page_posts.boost",
    "meta_ads.instagram.accounts",
    "meta_ads.instagram.media",
    "meta_ads.instagram.boost",
}

ALL_KNOWN_TOOLS: set[str] = GOOGLE_ADS_TOOLS | META_ADS_TOOLS

# Regex to extract tool names like `google_ads.xxx.yyy` and `meta_ads.xxx.yyy`
TOOL_NAME_PATTERN = re.compile(r"`((?:google_ads|meta_ads)\.\w+\.\w+)`")


def _extract_tool_references(content: str) -> set[str]:
    """Extract MCP tool name references from markdown content."""
    return set(TOOL_NAME_PATTERN.findall(content))


class TestCommandFilesExist:
    """Verify all 8 command files exist in .claude/commands/."""

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_command_file_exists(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        assert filepath.exists(), f"Command file missing: {filepath}"

    @pytest.mark.unit
    def test_commands_directory_exists(self) -> None:
        assert COMMANDS_DIR.is_dir(), f"Commands directory missing: {COMMANDS_DIR}"

    @pytest.mark.unit
    def test_exactly_eight_commands(self) -> None:
        md_files = list(COMMANDS_DIR.glob("*.md"))
        assert len(md_files) == len(EXPECTED_COMMANDS), (
            f"Expected {len(EXPECTED_COMMANDS)} command files, "
            f"found {len(md_files)}: {[f.name for f in md_files]}"
        )


class TestCommandFilesValid:
    """Verify each command file is valid (non-empty, starts with a description)."""

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_command_file_is_non_empty(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8")
        assert len(content.strip()) > 0, f"Command file is empty: {filename}"

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_command_file_starts_with_description(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8").strip()
        first_line = content.split("\n")[0].strip()
        # First line should be a plain text description (not a heading or empty)
        assert len(first_line) > 10, (
            f"Command file {filename} first line too short: '{first_line}'"
        )
        assert not first_line.startswith("---"), (
            f"Command file {filename} should not start with YAML frontmatter"
        )

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_command_file_has_steps_section(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8")
        assert "## Steps" in content or "## steps" in content, (
            f"Command file {filename} missing ## Steps section"
        )


class TestCommandToolReferences:
    """Verify MCP tool names referenced in commands exist in the tool registry."""

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_tool_references_are_valid(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8")
        referenced_tools = _extract_tool_references(content)

        invalid_tools = referenced_tools - ALL_KNOWN_TOOLS
        assert not invalid_tools, (
            f"Command {filename} references unknown tools: {sorted(invalid_tools)}"
        )

    @pytest.mark.unit
    def test_all_commands_reference_at_least_one_tool(self) -> None:
        for filename in EXPECTED_COMMANDS:
            filepath = COMMANDS_DIR / filename
            content = filepath.read_text(encoding="utf-8")
            referenced_tools = _extract_tool_references(content)
            assert len(referenced_tools) > 0, (
                f"Command {filename} does not reference any MCP tools"
            )

    @pytest.mark.unit
    def test_total_tool_coverage(self) -> None:
        """Verify commands collectively reference a meaningful subset of tools."""
        all_referenced: set[str] = set()
        for filename in EXPECTED_COMMANDS:
            filepath = COMMANDS_DIR / filename
            content = filepath.read_text(encoding="utf-8")
            all_referenced |= _extract_tool_references(content)

        # Commands should reference at least 15 distinct tools
        assert len(all_referenced) >= 15, (
            f"Commands only reference {len(all_referenced)} distinct tools, "
            f"expected at least 15"
        )


class TestWorkflowSkill:
    """Verify the mureo-workflows SKILL.md exists and is well-formed."""

    @pytest.mark.unit
    def test_skill_file_exists(self) -> None:
        assert SKILL_FILE.exists(), f"Workflow skill missing: {SKILL_FILE}"

    @pytest.mark.unit
    def test_skill_has_frontmatter(self) -> None:
        content = SKILL_FILE.read_text(encoding="utf-8")
        assert content.startswith("---"), "SKILL.md should start with YAML frontmatter"
        # Should have closing frontmatter delimiter
        parts = content.split("---", maxsplit=2)
        assert len(parts) >= 3, "SKILL.md should have complete YAML frontmatter"

    @pytest.mark.unit
    def test_skill_has_required_metadata(self) -> None:
        content = SKILL_FILE.read_text(encoding="utf-8")
        assert "name: mureo-workflows" in content
        assert "version: 0.2.0" in content

    @pytest.mark.unit
    def test_skill_has_operation_mode_matrix(self) -> None:
        content = SKILL_FILE.read_text(encoding="utf-8")
        modes = [
            "ONBOARDING_LEARNING",
            "EFFICIENCY_STABILIZE",
            "TURNAROUND_RESCUE",
            "SCALE_EXPANSION",
            "COMPETITOR_DEFENSE",
            "CREATIVE_TESTING",
            "LTV_QUALITY_FOCUS",
        ]
        for mode in modes:
            assert mode in content, (
                f"SKILL.md missing operation mode: {mode}"
            )

    @pytest.mark.unit
    def test_skill_has_kpi_thresholds(self) -> None:
        content = SKILL_FILE.read_text(encoding="utf-8")
        kpis = ["CPA", "CVR", "Impression Share", "CTR", "Budget Utilization"]
        for kpi in kpis:
            assert kpi in content, f"SKILL.md missing KPI threshold: {kpi}"

    @pytest.mark.unit
    def test_skill_has_command_reference(self) -> None:
        content = SKILL_FILE.read_text(encoding="utf-8")
        commands = [
            "/onboard",
            "/daily-check",
            "/rescue",
            "/search-term-cleanup",
            "/creative-refresh",
            "/budget-rebalance",
            "/competitive-scan",
            "/sync-state",
        ]
        for cmd in commands:
            assert cmd in content, f"SKILL.md missing command reference: {cmd}"
