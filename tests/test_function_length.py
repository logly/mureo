"""The function- and file-length limits only ever tighten (#917).

The repository's limits are 50 lines per function and 800 lines per file;
the file limit covers the bundled web JS (``mureo/_data/web/*.js``) as well.
Code written before they were enforced is over them, so the two lists below
freeze what was over at the time this ratchet landed, each with its length
then. A function or file not on a list must be within the limit; a listed one
may not grow, and once it is back within the limit its entry has to be
removed, so the lists can only shrink.

A function's length is ``end_lineno - lineno + 1`` from :mod:`ast` (the
``def`` line through the last line of its body, docstring included,
decorators excluded); nested functions and methods are measured on their own
under their qualified name (``Outer.inner``). A qualified name defined more
than once in one file (a property setter, an ``if``/``else`` pair) is keyed
``name@<def line>`` instead, so no definition is hidden behind another; none
exists today. A file's length is its line count. Function length is
measured for Python only: the web JS has no parser here, so only its file
length is held to the limit.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

import mureo

_PACKAGE_ROOT = Path(mureo.__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parent

FUNCTION_LINE_LIMIT = 50
FILE_LINE_LIMIT = 800

# shrink-only; remove an entry when you fix it, never add one
KNOWN_OVER_LIMIT: dict[tuple[str, str], int] = {
    ("mureo/_image_validation.py", "_validate_media_file"): 56,
    ("mureo/adapters/google_ads/adapter.py", "GoogleAdsAdapter.create_campaign"): 52,
    ("mureo/amazon_ads/bridge.py", "AmazonAdsBridge.capture_reversal"): 54,
    ("mureo/amazon_ads/bridge.py", "_normalize_failure"): 53,
    ("mureo/amazon_ads/failure_text.py", "_flatten_for_display"): 55,
    ("mureo/amazon_ads/lwa.py", "exchange_authorization_code"): 55,
    ("mureo/amazon_ads/lwa.py", "refresh_access_token"): 61,
    ("mureo/amazon_ads/reversal.py", "_build_reversal"): 58,
    ("mureo/amazon_ads/reversal.py", "_read_prior_state"): 65,
    ("mureo/amazon_ads/session_auth.py", "SessionCredentials.refresh_and_persist"): 60,
    ("mureo/analysis/delivery_collapse.py", "delivery_series_from_rows"): 59,
    ("mureo/analysis/delivery_collapse.py", "fill_missing_delivery_days"): 87,
    ("mureo/analysis/exclusion_impact/estimator.py", "estimate_exclusion_impact"): 94,
    ("mureo/analysis/outcome_eval.py", "evaluate_metric"): 54,
    ("mureo/analysis/outcome_eval.py", "evaluate_outcome"): 54,
    ("mureo/analytics/builtin/_budget_efficiency.py", "score_budget_efficiency"): 98,
    ("mureo/analytics/builtin/_creative_audit.py", "_audit_rda"): 54,
    ("mureo/analytics/builtin/_creative_audit.py", "_audit_rsa"): 56,
    ("mureo/analytics/builtin/_creative_audit.py", "audit_meta_ads_creatives"): 82,
    ("mureo/analytics/builtin/_delivery_clients.py", "run_delivery_collapse"): 56,
    ("mureo/analytics/builtin/google_ads.py", "_summarise_performance"): 114,
    ("mureo/analytics/builtin/meta_ads.py", "_summarise_meta_performance"): 114,
    ("mureo/analytics/registry.py", "AnalyticsRegistry._collect_one"): 66,
    ("mureo/auth.py", "_call_refresh_api"): 76,
    ("mureo/auth.py", "_should_refresh"): 53,
    ("mureo/auth.py", "create_google_ads_client"): 52,
    ("mureo/auth.py", "refresh_meta_token_if_needed"): 76,
    ("mureo/auth.py", "save_amazon_access_token"): 71,
    ("mureo/auth_setup.py", "_merge_meta_section"): 56,
    ("mureo/auth_setup.py", "_register_user_scope_mcp"): 64,
    ("mureo/auth_setup.py", "_select_account"): 64,
    ("mureo/auth_setup.py", "install_credential_guard"): 57,
    ("mureo/auth_setup.py", "run_meta_oauth"): 80,
    ("mureo/auth_setup.py", "save_credentials"): 54,
    ("mureo/auth_setup.py", "setup_google_ads"): 118,
    ("mureo/auth_setup.py", "setup_mcp_config"): 52,
    ("mureo/auth_setup.py", "setup_meta_ads"): 100,
    ("mureo/byod/_client_common.py", "_byod_delivery_rows"): 56,
    ("mureo/byod/_meta_client.py", "ByodMetaAdsClient.get_performance_report"): 61,
    (
        "mureo/byod/adapters/google_ads.py",
        "GoogleAdsWorkbookAdapter.normalize_from_workbook",
    ): 197,
    (
        "mureo/byod/adapters/meta_ads.py",
        "MetaAdsWorkbookAdapter.normalize_from_workbook",
    ): 690,
    ("mureo/byod/bundle.py", "import_bundle"): 173,
    ("mureo/byod/clients.py", "ByodGoogleAdsClient.get_search_terms_report"): 70,
    ("mureo/change_import/builtin/google_ads.py", "_row_identity"): 52,
    ("mureo/change_import/importer.py", "_import_one_platform"): 113,
    ("mureo/cli/_repair_preview.py", "echo_undecidable_duplicates"): 52,
    ("mureo/cli/byod_cmd.py", "import_"): 54,
    ("mureo/cli/configure_cmd.py", "configure"): 81,
    ("mureo/cli/demo_cmd.py", "init"): 81,
    ("mureo/cli/install_desktop_cmd.py", "install_desktop_cmd"): 60,
    ("mureo/cli/journal_cmd.py", "show_journal"): 71,
    ("mureo/cli/native_skills.py", "install_native_skills"): 57,
    ("mureo/cli/providers_cmd.py", "confirm_cmd"): 81,
    ("mureo/cli/repair_cmd.py", "_repair_every_client"): 67,
    ("mureo/cli/repair_cmd.py", "_repair_one_workspace"): 61,
    ("mureo/cli/repair_cmd.py", "repair_platform_key"): 60,
    ("mureo/cli/settings_remove.py", "remove_mcp_config"): 64,
    ("mureo/cli/setup_cmd.py", "remove_skills"): 51,
    ("mureo/cli/setup_cmd.py", "setup_claude_code"): 81,
    ("mureo/cli/setup_cmd.py", "setup_codex"): 77,
    ("mureo/cli/setup_cmd.py", "setup_cursor"): 58,
    ("mureo/cli/setup_cmd.py", "setup_gemini"): 53,
    ("mureo/cli/setup_gemini.py", "install_gemini_extension"): 54,
    ("mureo/cli/upgrade_cmd.py", "upgrade"): 61,
    ("mureo/context/daily.py", "_completeness_anchor"): 53,
    ("mureo/context/daily.py", "with_platform_daily"): 100,
    ("mureo/context/monthly_budget.py", "resolve_monthly_budget"): 78,
    ("mureo/context/platform_repair.py", "apply_state_file_repairs"): 75,
    ("mureo/context/platform_repair.py", "plan_platform_keys"): 59,
    ("mureo/core/account_scope.py", "resolve_customer_id"): 53,
    ("mureo/core/providers/base.py", "validate_provider"): 71,
    ("mureo/core/providers/registry.py", "Registry._load_entry_point"): 51,
    ("mureo/core/providers/registry.py", "get_account_credential_fields"): 51,
    ("mureo/core/providers/registry.py", "get_account_oauth_config"): 65,
    ("mureo/core/runtime_context.py", "get_runtime_context"): 59,
    ("mureo/core/runtime_context.py", "runtime_credentials_path"): 63,
    ("mureo/core/tool_names.py", "_write_verbs"): 55,
    ("mureo/creative_studio/composer.py", "compose"): 86,
    ("mureo/creative_studio/composer.py", "render_html"): 59,
    ("mureo/creative_studio/fonts.py", "ensure_font"): 67,
    (
        "mureo/creative_studio/providers/codex_cli.py",
        "CodexCliImageProvider._run_codex",
    ): 59,
    ("mureo/demo/installer.py", "_readme_md"): 99,
    ("mureo/demo/installer.py", "materialize"): 138,
    ("mureo/desktop_installer.py", "install_desktop"): 125,
    ("mureo/google_ads/_ads.py", "_AdsMixin.list_ads"): 107,
    ("mureo/google_ads/_ads.py", "_AdsMixin.update_ad"): 107,
    ("mureo/google_ads/_ads.py", "_AdsMixin.update_ad_status"): 73,
    ("mureo/google_ads/_ads_display.py", "_DisplayAdsMixin._build_rda_operation"): 55,
    ("mureo/google_ads/_ads_display.py", "_DisplayAdsMixin.create_display_ad"): 127,
    (
        "mureo/google_ads/_analysis_auction.py",
        "_AuctionAnalysisMixin._generate_cpc_insights",
    ): 54,
    (
        "mureo/google_ads/_analysis_auction.py",
        "_AuctionAnalysisMixin.analyze_auction_insights",
    ): 77,
    (
        "mureo/google_ads/_analysis_auction.py",
        "_AuctionAnalysisMixin.analyze_device_performance",
    ): 79,
    (
        "mureo/google_ads/_analysis_auction.py",
        "_AuctionAnalysisMixin.detect_cpc_trend",
    ): 72,
    (
        "mureo/google_ads/_analysis_auction.py",
        "_AuctionAnalysisMixin.get_auction_insights",
    ): 99,
    (
        "mureo/google_ads/_analysis_btob.py",
        "_BtoBAnalysisMixin._check_device_for_btob",
    ): 60,
    (
        "mureo/google_ads/_analysis_budget.py",
        "_BudgetAnalysisMixin.analyze_budget_efficiency",
    ): 128,
    (
        "mureo/google_ads/_analysis_budget.py",
        "_BudgetAnalysisMixin.suggest_budget_reallocation",
    ): 117,
    (
        "mureo/google_ads/_analysis_keywords.py",
        "_KeywordsAnalysisMixin._evaluate_keyword",
    ): 64,
    (
        "mureo/google_ads/_analysis_keywords.py",
        "_KeywordsAnalysisMixin._extract_duplicate_groups",
    ): 69,
    (
        "mureo/google_ads/_analysis_keywords.py",
        "_KeywordsAnalysisMixin.find_cross_adgroup_duplicates",
    ): 65,
    (
        "mureo/google_ads/_analysis_performance.py",
        "_PerformanceAnalysisMixin._analyze_search_term_changes",
    ): 52,
    (
        "mureo/google_ads/_analysis_performance.py",
        "_PerformanceAnalysisMixin.analyze_performance",
    ): 88,
    (
        "mureo/google_ads/_analysis_performance.py",
        "_PerformanceAnalysisMixin.compare_ad_performance",
    ): 103,
    (
        "mureo/google_ads/_analysis_performance.py",
        "_PerformanceAnalysisMixin.health_check_all_campaigns",
    ): 92,
    (
        "mureo/google_ads/_analysis_performance.py",
        "_PerformanceAnalysisMixin.investigate_cost_increase",
    ): 87,
    ("mureo/google_ads/_analysis_rsa.py", "_RsaAnalysisMixin.analyze_rsa_assets"): 110,
    ("mureo/google_ads/_analysis_rsa.py", "_RsaAnalysisMixin.audit_rsa_assets"): 65,
    (
        "mureo/google_ads/_analysis_search_terms.py",
        "_SearchTermsAnalysisMixin._classify_search_term",
    ): 135,
    (
        "mureo/google_ads/_analysis_search_terms.py",
        "_SearchTermsAnalysisMixin.analyze_search_terms",
    ): 122,
    (
        "mureo/google_ads/_analysis_search_terms.py",
        "_SearchTermsAnalysisMixin.review_search_terms",
    ): 69,
    (
        "mureo/google_ads/_analysis_search_terms.py",
        "_SearchTermsAnalysisMixin.suggest_negative_keywords",
    ): 134,
    (
        "mureo/google_ads/_asset_groups_images.py",
        "_AssetGroupImagesMixin.replace_asset_group_image_asset",
    ): 52,
    ("mureo/google_ads/_creative.py", "_CreativeMixin._fetch_existing_ads"): 52,
    ("mureo/google_ads/_creative.py", "_CreativeMixin.research_creative"): 77,
    (
        "mureo/google_ads/_extensions_conversions.py",
        "_ConversionsMixin.create_conversion_action",
    ): 58,
    (
        "mureo/google_ads/_extensions_conversions.py",
        "_ConversionsMixin.get_conversion_performance",
    ): 133,
    (
        "mureo/google_ads/_extensions_conversions.py",
        "_ConversionsMixin.update_conversion_action",
    ): 77,
    ("mureo/google_ads/_extensions_sitelinks.py", "_SitelinksMixin.list_sitelinks"): 70,
    (
        "mureo/google_ads/_extensions_targeting.py",
        "_TargetingMixin.list_change_history",
    ): 52,
    (
        "mureo/google_ads/_extensions_targeting.py",
        "_TargetingMixin.set_device_targeting",
    ): 121,
    ("mureo/google_ads/_keywords.py", "_KeywordsMixin.diagnose_keywords"): 148,
    ("mureo/google_ads/_media.py", "_MediaMixin.upload_image_asset"): 55,
    ("mureo/google_ads/_message_match.py", "LPScreenshotter.capture"): 52,
    (
        "mureo/google_ads/_monitoring.py",
        "_MonitoringMixin._build_cv_recommendations",
    ): 71,
    (
        "mureo/google_ads/_monitoring.py",
        "_MonitoringMixin.diagnose_zero_conversions",
    ): 198,
    ("mureo/google_ads/_monitoring.py", "_MonitoringMixin.evaluate_cpa_goal"): 116,
    ("mureo/google_ads/_monitoring.py", "_MonitoringMixin.evaluate_cv_goal"): 142,
    ("mureo/google_ads/_monitoring.py", "_MonitoringMixin.evaluate_delivery_goal"): 116,
    ("mureo/google_ads/_rda_validator.py", "validate_rda_inputs"): 138,
    ("mureo/google_ads/_rsa_validator.py", "validate_rsa_texts"): 91,
    ("mureo/google_ads/accounts.py", "list_accessible_accounts"): 60,
    ("mureo/google_ads/client.py", "GoogleAdsApiClient._set_bidding_strategy"): 58,
    ("mureo/google_ads/client.py", "GoogleAdsApiClient.create_budget"): 92,
    ("mureo/google_ads/client.py", "GoogleAdsApiClient.create_campaign"): 81,
    (
        "mureo/google_ads/client.py",
        "GoogleAdsApiClient.get_network_performance_report",
    ): 54,
    ("mureo/google_ads/client.py", "GoogleAdsApiClient.update_ad_group"): 70,
    ("mureo/google_ads/client.py", "GoogleAdsApiClient.update_budget"): 57,
    ("mureo/google_ads/client.py", "GoogleAdsApiClient.update_campaign"): 60,
    ("mureo/google_ads/client.py", "_resolve_amount_micros"): 58,
    ("mureo/learning/context_builder.py", "build_query"): 63,
    ("mureo/learning/federation.py", "_open_session"): 52,
    ("mureo/learning/federation.py", "_parse_fragments"): 54,
    ("mureo/learning/insight_sources.py", "load_insight_sources"): 56,
    ("mureo/mcp/_handlers_analysis.py", "_resolve_state_file"): 53,
    (
        "mureo/mcp/_handlers_delivery_collapse.py",
        "handle_delivery_collapse_diagnose",
    ): 62,
    ("mureo/mcp/_handlers_mureo_context.py", "handle_state_action_log_append"): 82,
    ("mureo/mcp/_handlers_rollback.py", "handle_plan_get"): 57,
    ("mureo/mcp/_plugin_declarations.py", "_register_plugin_pattern_fallbacks"): 72,
    ("mureo/mcp/_result_decorations.py", "_capture_plugin_reversal"): 57,
    ("mureo/mcp/_tool_validation.py", "LazyToolValidators.validate_tool_input"): 52,
    ("mureo/mcp/native_reversal.py", "record_native_mutation"): 51,
    ("mureo/mcp/plugin_audit.py", "mask_arguments"): 56,
    ("mureo/mcp/plugin_semantics.py", "record_mutation_action_log"): 65,
    ("mureo/mcp/server.py", "_dispatch_tool"): 156,
    ("mureo/mcp/server.py", "_evaluate_policy_gates"): 73,
    ("mureo/mcp/tool_provider.py", "_collect_one"): 82,
    ("mureo/mcp/tools_analytics_registry.py", "_handle_analytics_run"): 74,
    ("mureo/mcp/tools_creative_studio.py", "_handle_compose"): 90,
    ("mureo/mcp/tools_creative_studio.py", "_handle_edit_visual"): 65,
    ("mureo/mcp/tools_creative_studio.py", "_handle_generate_visual"): 91,
    ("mureo/meta_ads/_ad_sets.py", "AdSetsMixin.create_ad_set"): 76,
    ("mureo/meta_ads/_analysis.py", "AnalysisMixin.analyze_placements"): 69,
    ("mureo/meta_ads/_analysis.py", "AnalysisMixin.compare_ads"): 82,
    ("mureo/meta_ads/_analysis.py", "AnalysisMixin.investigate_cost"): 75,
    ("mureo/meta_ads/_analysis.py", "AnalysisMixin.suggest_creative_improvements"): 89,
    ("mureo/meta_ads/_audiences.py", "AudiencesMixin.create_custom_audience"): 68,
    ("mureo/meta_ads/_campaigns.py", "CampaignsMixin.create_campaign"): 58,
    ("mureo/meta_ads/_creatives.py", "CreativesMixin.create_ad_creative"): 143,
    ("mureo/meta_ads/_creatives.py", "CreativesMixin.create_carousel_creative"): 57,
    ("mureo/meta_ads/_creatives.py", "CreativesMixin.create_dynamic_creative"): 55,
    ("mureo/meta_ads/_creatives.py", "CreativesMixin.create_lead_ad_creative"): 148,
    ("mureo/meta_ads/_creatives.py", "CreativesMixin.upload_ad_image"): 72,
    ("mureo/meta_ads/_creatives.py", "CreativesMixin.upload_ad_image_file"): 62,
    ("mureo/meta_ads/_creatives.py", "_validate_video_creative_mode"): 60,
    ("mureo/meta_ads/_insights.py", "InsightsMixin.analyze_audience"): 82,
    ("mureo/meta_ads/_insights.py", "InsightsMixin.analyze_performance"): 75,
    ("mureo/meta_ads/_leads.py", "LeadsMixin.create_lead_form"): 95,
    ("mureo/meta_ads/_leads.py", "LeadsMixin.duplicate_lead_form"): 104,
    ("mureo/meta_ads/_leads.py", "LeadsMixin.export_leads_to_csv"): 101,
    ("mureo/meta_ads/_period.py", "previous_period"): 79,
    ("mureo/meta_ads/_videos.py", "VideosMixin.upload_ad_video_file"): 68,
    ("mureo/meta_ads/accounts.py", "inspect_meta_access_token"): 120,
    ("mureo/meta_ads/accounts.py", "list_meta_ad_accounts"): 71,
    ("mureo/meta_ads/accounts.py", "validate_meta_access_token"): 135,
    ("mureo/meta_ads/client.py", "MetaAdsApiClient._request"): 120,
    ("mureo/oauth_authcode.py", "exchange_authorization_code"): 80,
    ("mureo/policy/declaration_resolution.py", "_bid_inputs"): 70,
    ("mureo/policy/declaration_resolution.py", "_budget_inputs"): 129,
    ("mureo/policy/learning_reset.py", "classify_change"): 51,
    ("mureo/policy/learning_reset.py", "learning_reset_denial"): 58,
    ("mureo/policy/pattern_scan.py", "_scan"): 122,
    ("mureo/policy/strategy_gate.py", "evaluate_guardrails"): 244,
    ("mureo/providers/coexistence.py", "coexistence_warning"): 51,
    ("mureo/providers/config_writer.py", "add_provider_to_claude_settings"): 97,
    ("mureo/providers/config_writer.py", "hosted_provider_connectivity"): 61,
    ("mureo/providers/installer.py", "run_install"): 53,
    ("mureo/providers/mureo_env.py", "add_provider_and_disable_in_mureo"): 64,
    ("mureo/providers/mureo_env.py", "set_mureo_disable_env"): 53,
    ("mureo/rollback/executor.py", "execute_rollback"): 131,
    ("mureo/rollback/planner.py", "plan_rollback"): 125,
    ("mureo/web/about.py", "collect_about_info"): 70,
    ("mureo/web/auth_wizard.py", "_WizardHandler._handle_google_callback"): 121,
    ("mureo/web/auth_wizard.py", "_WizardHandler._handle_google_submit"): 74,
    ("mureo/web/auth_wizard.py", "_WizardHandler._handle_meta_callback"): 124,
    ("mureo/web/auth_wizard.py", "_WizardHandler._handle_plugin_oauth_callback"): 87,
    ("mureo/web/auth_wizard.py", "render_google_account_picker"): 65,
    ("mureo/web/env_var_writer.py", "_clear_stale_refresh_clock"): 55,
    ("mureo/web/env_var_writer.py", "write_credential_env_var"): 58,
    ("mureo/web/extensions.py", "_load_entry_point"): 194,
    ("mureo/web/extensions.py", "discover_web_extensions"): 55,
    ("mureo/web/handlers.py", "ConfigureHandler._post_amazon_oauth_exchange"): 59,
    ("mureo/web/handlers.py", "ConfigureHandler._post_credentials_meta_token"): 246,
    ("mureo/web/handlers.py", "ConfigureHandler._post_plugin_oauth_start"): 88,
    ("mureo/web/handlers.py", "ConfigureHandler.do_GET"): 126,
    ("mureo/web/oauth_bridge.py", "OAuthBridge.start"): 72,
    ("mureo/web/oauth_bridge.py", "OAuthBridge.start_plugin_oauth"): 123,
    ("mureo/web/plugin_credentials.py", "list_oauth_accounts"): 107,
    ("mureo/web/plugin_credentials.py", "list_plugin_credential_fields"): 83,
    ("mureo/web/plugin_credentials.py", "save_plugin_credentials"): 138,
    ("mureo/web/report_document.py", "_build_platform_conflicts"): 52,
    ("mureo/web/report_labels.py", "platform_display_name"): 58,
    ("mureo/web/reports.py", "build_report_summary"): 144,
    ("mureo/web/server.py", "run_configure_wizard"): 152,
    ("mureo/web/setup_actions.py", "_install_provider_code"): 59,
    ("mureo/web/setup_actions.py", "_install_provider_codex"): 52,
    ("mureo/web/setup_actions.py", "_install_provider_desktop"): 75,
    ("mureo/web/setup_actions.py", "confirm_hosted_provider"): 97,
    ("mureo/web/setup_actions.py", "set_native_preference"): 53,
    ("mureo/web/status_collector.py", "_detect_meta_token"): 77,
    ("mureo/web/version_check.py", "_run_pip_report"): 68,
}

# shrink-only; remove an entry when you fix it, never add one
KNOWN_LONG_FILES: dict[str, int] = {
    "mureo/_data/web/auth_wizards_meta.js": 855,
    "mureo/_data/web/dashboard_plugins.js": 858,
    "mureo/_data/web/dashboard_reports_detail.js": 910,
    "mureo/_data/web/dashboard_reports_report.js": 845,
    "mureo/_data/web/dashboard_setup.js": 833,
    "mureo/_data/web/reports_triage.js": 1021,
    "mureo/auth.py": 1043,
    "mureo/auth_setup.py": 1555,
    "mureo/byod/adapters/meta_ads.py": 1330,
    "mureo/demo/scenarios/strategy_drift.py": 812,
    "mureo/google_ads/client.py": 1289,
    "mureo/mcp/_tools_google_ads_analysis.py": 944,
    "mureo/mcp/_tools_google_ads_campaigns.py": 944,
    "mureo/mcp/_tools_google_ads_extensions.py": 1060,
    "mureo/mcp/_tools_meta_ads_campaigns.py": 859,
    "mureo/mcp/server.py": 1223,
    "mureo/mcp/tools_creative_studio.py": 806,
    "mureo/mcp/tools_mureo_context.py": 1569,
    "mureo/web/auth_wizard.py": 1482,
    "mureo/web/extensions.py": 801,
    "mureo/web/handlers.py": 2318,
    "mureo/web/setup_actions.py": 1131,
}


def _package_files() -> list[Path]:
    return sorted(_PACKAGE_ROOT.rglob("*.py"))


def _web_js_files() -> list[Path]:
    return sorted((_PACKAGE_ROOT / "_data" / "web").glob("*.js"))


def _relative(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _function_lengths(node: ast.AST, prefix: str = "") -> list[tuple[str, int, int]]:
    """Every function under ``node`` as ``(qualified name, def line, length)``."""
    found: list[tuple[str, int, int]] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = f"{prefix}{child.name}"
            if not isinstance(child, ast.ClassDef):
                end = child.end_lineno or child.lineno
                found.append((name, child.lineno, end - child.lineno + 1))
            found.extend(_function_lengths(child, f"{name}."))
        else:
            found.extend(_function_lengths(child, prefix))
    return found


def _keyed_lengths(functions: list[tuple[str, int, int]]) -> dict[str, int]:
    """One file's functions as ``{key: length}``, every definition its own key.

    The key is the qualified name, or ``name@<def line>`` for a name defined
    more than once in the file. A collision left after that is a bug in this
    test, and fails it rather than letting one definition hide another.
    """
    counts = Counter(name for name, _, _ in functions)
    keyed = {
        (name if counts[name] == 1 else f"{name}@{line}"): length
        for name, line, length in functions
    }
    assert len(keyed) == len(functions), f"duplicate function keys: {counts}"
    return keyed


def _over_limit_functions() -> dict[tuple[str, str], int]:
    """Every function under ``mureo/`` over the limit, with its length."""
    over: dict[tuple[str, str], int] = {}
    for path in _package_files():
        lengths = _keyed_lengths(_function_lengths(ast.parse(path.read_text("utf-8"))))
        over.update(
            ((_relative(path), key), length)
            for key, length in lengths.items()
            if length > FUNCTION_LINE_LIMIT
        )
    return over


def _long_files() -> dict[str, int]:
    """Every Python file under ``mureo/`` and every bundled web JS file over
    the limit, with its line count."""
    lengths = {
        _relative(path): len(path.read_text("utf-8").splitlines())
        for path in [*_package_files(), *_web_js_files()]
    }
    return {rel: n for rel, n in lengths.items() if n > FILE_LINE_LIMIT}


def _ratchet_failures(
    measured: dict[str, int], allowed: dict[str, int], limit: int
) -> list[str]:
    """What breaks the ratchet: a new offender, growth, or a stale entry."""
    failures = [
        f"{key}: {length} lines (limit {limit}; not on the list)"
        for key, length in sorted(measured.items())
        if key not in allowed
    ]
    failures += [
        f"{key}: grew from {allowed[key]} to {length} lines"
        for key, length in sorted(measured.items())
        if key in allowed and length > allowed[key]
    ]
    failures += [
        f"{key}: now within {limit} lines; remove its entry"
        for key in sorted(allowed)
        if key not in measured
    ]
    return failures


@pytest.mark.unit
def test_no_function_grows_past_the_line_limit() -> None:
    measured = {f"{p}::{n}": v for (p, n), v in _over_limit_functions().items()}
    allowed = {f"{p}::{n}": v for (p, n), v in KNOWN_OVER_LIMIT.items()}
    assert _ratchet_failures(measured, allowed, FUNCTION_LINE_LIMIT) == []


@pytest.mark.unit
def test_no_file_grows_past_the_line_limit() -> None:
    assert _ratchet_failures(_long_files(), KNOWN_LONG_FILES, FILE_LINE_LIMIT) == []


@pytest.mark.unit
def test_a_name_defined_twice_is_measured_twice() -> None:
    source = "def f():\n    pass\n\n\ndef f():\n    x = 1\n    return x\n"
    keyed = _keyed_lengths(_function_lengths(ast.parse(source)))
    assert keyed == {"f@1": 2, "f@5": 3}


@pytest.mark.unit
def test_the_lists_hold_only_offenders() -> None:
    """An entry at or under the limit could never fail the ratchet."""
    assert [k for k, v in KNOWN_OVER_LIMIT.items() if v <= FUNCTION_LINE_LIMIT] == []
    assert [k for k, v in KNOWN_LONG_FILES.items() if v <= FILE_LINE_LIMIT] == []
