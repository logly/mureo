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
    "goal-review.md",
    "weekly-report.md",
    "learn.md",
]

# Workflow commands (exclude utility commands like learn)
WORKFLOW_COMMANDS = [c for c in EXPECTED_COMMANDS if c != "learn.md"]

# Known MCP tool names extracted from SKILL.md files
# Google Ads tools (82 tools from mureo-google-ads/SKILL.md)
GOOGLE_ADS_TOOLS: set[str] = {
    "google_ads_campaigns_list",
    "google_ads_campaigns_get",
    "google_ads_campaigns_create",
    "google_ads_campaigns_update",
    "google_ads_campaigns_update_status",
    "google_ads_campaigns_diagnose",
    "google_ads_ad_groups_list",
    "google_ads_ad_groups_create",
    "google_ads_ad_groups_update",
    "google_ads_ads_list",
    "google_ads_ads_create",
    "google_ads_ads_update",
    "google_ads_ads_update_status",
    "google_ads_ads_policy_details",
    "google_ads_keywords_list",
    "google_ads_keywords_add",
    "google_ads_keywords_remove",
    "google_ads_keywords_suggest",
    "google_ads_keywords_diagnose",
    "google_ads_keywords_pause",
    "google_ads_keywords_audit",
    "google_ads_keywords_cross_adgroup_duplicates",
    "google_ads_negative_keywords_list",
    "google_ads_negative_keywords_add",
    "google_ads_negative_keywords_remove",
    "google_ads_negative_keywords_add_to_ad_group",
    "google_ads_negative_keywords_suggest",
    "google_ads_budget_get",
    "google_ads_budget_update",
    "google_ads_budget_create",
    "google_ads_accounts_list",
    "google_ads_search_terms_report",
    "google_ads_search_terms_review",
    "google_ads_search_terms_analyze",
    "google_ads_sitelinks_list",
    "google_ads_sitelinks_create",
    "google_ads_sitelinks_remove",
    "google_ads_callouts_list",
    "google_ads_callouts_create",
    "google_ads_callouts_remove",
    "google_ads_conversions_list",
    "google_ads_conversions_get",
    "google_ads_conversions_performance",
    "google_ads_conversions_create",
    "google_ads_conversions_update",
    "google_ads_conversions_remove",
    "google_ads_conversions_tag",
    "google_ads_recommendations_list",
    "google_ads_recommendations_apply",
    "google_ads_device_targeting_get",
    "google_ads_device_targeting_set",
    "google_ads_bid_adjustments_get",
    "google_ads_bid_adjustments_update",
    "google_ads_location_targeting_list",
    "google_ads_location_targeting_update",
    "google_ads_schedule_targeting_list",
    "google_ads_schedule_targeting_update",
    "google_ads_change_history_list",
    "google_ads_performance_report",
    "google_ads_performance_analyze",
    "google_ads_cost_increase_investigate",
    "google_ads_health_check_all",
    "google_ads_ad_performance_compare",
    "google_ads_ad_performance_report",
    "google_ads_network_performance_report",
    "google_ads_budget_efficiency",
    "google_ads_budget_reallocation",
    "google_ads_auction_insights_get",
    "google_ads_auction_insights_analyze",
    "google_ads_rsa_assets_analyze",
    "google_ads_rsa_assets_audit",
    "google_ads_cpc_detect_trend",
    "google_ads_device_analyze",
    "google_ads_btob_optimizations",
    "google_ads_landing_page_analyze",
    "google_ads_creative_research",
    "google_ads_monitoring_delivery_goal",
    "google_ads_monitoring_cpa_goal",
    "google_ads_monitoring_cv_goal",
    "google_ads_monitoring_zero_conversions",
    "google_ads_capture_screenshot",
    "google_ads_assets_upload_image",
}

# Meta Ads tools (77 tools from mureo-meta-ads/SKILL.md)
META_ADS_TOOLS: set[str] = {
    "meta_ads_campaigns_list",
    "meta_ads_campaigns_get",
    "meta_ads_campaigns_create",
    "meta_ads_campaigns_update",
    "meta_ads_campaigns_pause",
    "meta_ads_campaigns_enable",
    "meta_ads_ad_sets_list",
    "meta_ads_ad_sets_get",
    "meta_ads_ad_sets_create",
    "meta_ads_ad_sets_update",
    "meta_ads_ad_sets_pause",
    "meta_ads_ad_sets_enable",
    "meta_ads_ads_list",
    "meta_ads_ads_get",
    "meta_ads_ads_create",
    "meta_ads_ads_update",
    "meta_ads_ads_pause",
    "meta_ads_ads_enable",
    "meta_ads_insights_report",
    "meta_ads_insights_breakdown",
    "meta_ads_analysis_performance",
    "meta_ads_analysis_audience",
    "meta_ads_analysis_placements",
    "meta_ads_analysis_cost",
    "meta_ads_analysis_compare_ads",
    "meta_ads_analysis_suggest_creative",
    "meta_ads_audiences_list",
    "meta_ads_audiences_get",
    "meta_ads_audiences_create",
    "meta_ads_audiences_delete",
    "meta_ads_audiences_create_lookalike",
    "meta_ads_pixels_list",
    "meta_ads_pixels_get",
    "meta_ads_pixels_stats",
    "meta_ads_pixels_events",
    "meta_ads_conversions_send",
    "meta_ads_conversions_send_purchase",
    "meta_ads_conversions_send_lead",
    "meta_ads_creatives_list",
    "meta_ads_creatives_create",
    "meta_ads_creatives_create_dynamic",
    "meta_ads_creatives_upload_image",
    "meta_ads_creatives_create_carousel",
    "meta_ads_creatives_create_collection",
    "meta_ads_images_upload_file",
    "meta_ads_catalogs_list",
    "meta_ads_catalogs_get",
    "meta_ads_catalogs_create",
    "meta_ads_catalogs_delete",
    "meta_ads_products_list",
    "meta_ads_products_get",
    "meta_ads_products_add",
    "meta_ads_products_update",
    "meta_ads_products_delete",
    "meta_ads_feeds_list",
    "meta_ads_feeds_create",
    "meta_ads_lead_forms_list",
    "meta_ads_lead_forms_get",
    "meta_ads_lead_forms_create",
    "meta_ads_leads_get",
    "meta_ads_leads_get_by_ad",
    "meta_ads_videos_upload",
    "meta_ads_videos_upload_file",
    "meta_ads_split_tests_list",
    "meta_ads_split_tests_get",
    "meta_ads_split_tests_create",
    "meta_ads_split_tests_end",
    "meta_ads_ad_rules_list",
    "meta_ads_ad_rules_get",
    "meta_ads_ad_rules_create",
    "meta_ads_ad_rules_update",
    "meta_ads_ad_rules_delete",
    "meta_ads_page_posts_list",
    "meta_ads_page_posts_boost",
    "meta_ads_instagram_accounts",
    "meta_ads_instagram_media",
    "meta_ads_instagram_boost",
}

ALL_KNOWN_TOOLS: set[str] = GOOGLE_ADS_TOOLS | META_ADS_TOOLS

# Regex to extract tool names like `google_ads.xxx.yyy` and `meta_ads.xxx.yyy`
TOOL_NAME_PATTERN = re.compile(r"`((?:google_ads|meta_ads)\.\w+\.\w+)`")


def _extract_tool_references(content: str) -> set[str]:
    """Extract MCP tool name references from markdown content."""
    return set(TOOL_NAME_PATTERN.findall(content))


class TestCommandFilesExist:
    """Verify all 10 command files exist in .claude/commands/."""

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_command_file_exists(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        assert filepath.exists(), f"Command file missing: {filepath}"

    @pytest.mark.unit
    def test_commands_directory_exists(self) -> None:
        assert COMMANDS_DIR.is_dir(), f"Commands directory missing: {COMMANDS_DIR}"

    @pytest.mark.unit
    def test_exactly_ten_commands(self) -> None:
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
        assert (
            len(first_line) > 10
        ), f"Command file {filename} first line too short: '{first_line}'"
        assert not first_line.startswith(
            "---"
        ), f"Command file {filename} should not start with YAML frontmatter"

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_command_file_has_steps_section(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8")
        assert (
            "## Steps" in content or "## steps" in content
        ), f"Command file {filename} missing ## Steps section"


class TestCommandToolReferences:
    """Verify commands follow orchestration patterns (no hardcoded tool names)."""

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", EXPECTED_COMMANDS)
    def test_no_hardcoded_tool_names(self, filename: str) -> None:
        """Commands should use intent-based descriptions, not hardcoded tool names."""
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8")
        referenced_tools = _extract_tool_references(content)

        assert len(referenced_tools) == 0, (
            f"Command {filename} contains hardcoded tool names: {sorted(referenced_tools)}. "
            f"Commands should use intent-based descriptions for platform-agnostic orchestration."
        )

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", WORKFLOW_COMMANDS)
    def test_command_has_platform_discovery(self, filename: str) -> None:
        """Workflow commands should discover platforms or reference STATE.json platforms."""
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8").lower()
        has_discovery = (
            "discover platform" in content
            or "discover available" in content
            or "platforms" in content
            or "platform" in content
        )
        assert (
            has_discovery
        ), f"Command {filename} does not include platform discovery pattern"


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
        assert "version: 0.3.0" in content

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
            assert mode in content, f"SKILL.md missing operation mode: {mode}"

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


class TestGoalAndCrossPlatformCommands:
    """Verify goal-review and weekly-report commands are valid and well-formed."""

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", ["goal-review.md", "weekly-report.md"])
    def test_new_command_exists(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        assert filepath.exists(), f"Command file missing: {filepath}"

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", ["goal-review.md", "weekly-report.md"])
    def test_new_command_uses_orchestration_pattern(self, filename: str) -> None:
        """Goal/weekly commands should follow orchestration pattern."""
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8")
        # Should not have hardcoded tool names
        referenced_tools = _extract_tool_references(content)
        assert (
            len(referenced_tools) == 0
        ), f"Command {filename} contains hardcoded tool names: {sorted(referenced_tools)}"
        # Should reference platform discovery
        assert (
            "platform" in content.lower()
        ), f"Command {filename} does not reference platform discovery"

    @pytest.mark.unit
    @pytest.mark.parametrize("filename", ["goal-review.md", "weekly-report.md"])
    def test_new_command_has_steps_section(self, filename: str) -> None:
        filepath = COMMANDS_DIR / filename
        content = filepath.read_text(encoding="utf-8")
        assert "## Steps" in content, f"Command {filename} missing ## Steps section"

    @pytest.mark.unit
    def test_all_commands_reference_strategy_or_state(self) -> None:
        """Verify workflow commands reference STRATEGY.md or STATE.json."""
        for filename in WORKFLOW_COMMANDS:
            filepath = COMMANDS_DIR / filename
            content = filepath.read_text(encoding="utf-8")
            has_strategy = "STRATEGY.md" in content
            has_state = "STATE.json" in content
            assert (
                has_strategy or has_state
            ), f"Command {filename} does not reference STRATEGY.md or STATE.json"
