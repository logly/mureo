"""i18n key-presence guard for the Desktop Connectors instruction note.

A remote MCP (hosted_http, e.g. meta-ads-official) cannot be wired into
Claude Desktop via the config file: Desktop rejects the native http
shape and the mcp-remote bridge fails on Meta's no-DCR OAuth server. The
dashboard surfaces a one-time instruction (key
``dashboard.provider_desktop_connectors_note``) telling the user to add
it via Settings → Connectors. There is NO JS test harness in the repo,
so the EN/JA parity of the key is asserted here against the bundled
``mureo/_data/web/i18n.json`` content directly. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import pytest

_NEW_KEY = "dashboard.provider_desktop_connectors_note"
# Existing key — present today; used as a structural sanity anchor so a
# failure clearly isolates the NEW key rather than a path/shape problem.
_EXISTING_KEY = "dashboard.provider_hosted_oauth_note"


def _load_i18n() -> dict[str, Any]:
    ref = resources.files("mureo") / "_data" / "web" / "i18n.json"
    with resources.as_file(ref) as path:
        return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.unit
class TestI18nNodeNoteKeyParity:
    def test_i18n_json_has_en_and_ja_blocks(self) -> None:
        """Structural anchor: the bundled i18n has both locale blocks and
        the pre-existing hosted-oauth note (isolates the new-key failure)."""
        data = _load_i18n()
        assert "en" in data and isinstance(data["en"], dict)
        assert "ja" in data and isinstance(data["ja"], dict)
        assert _EXISTING_KEY in data["en"]
        assert _EXISTING_KEY in data["ja"]

    def test_node_note_present_in_english(self) -> None:
        """RED: ``dashboard.provider_desktop_node_note`` not yet in EN."""
        data = _load_i18n()
        en = data["en"]
        assert _NEW_KEY in en, f"{_NEW_KEY} missing from i18n.json 'en'"
        value = en[_NEW_KEY]
        assert isinstance(value, str)
        assert value.strip() != ""
        assert value != _NEW_KEY  # not an untranslated placeholder

    def test_node_note_present_in_japanese(self) -> None:
        """RED: ``dashboard.provider_desktop_node_note`` not yet in JA."""
        data = _load_i18n()
        ja = data["ja"]
        assert _NEW_KEY in ja, f"{_NEW_KEY} missing from i18n.json 'ja'"
        value = ja[_NEW_KEY]
        assert isinstance(value, str)
        assert value.strip() != ""
        assert value != _NEW_KEY

    def test_node_note_en_and_ja_are_distinct_translations(self) -> None:
        """The JA value must not be a copy of the EN value (real
        localization, mirrors the existing oauth-note convention)."""
        data = _load_i18n()
        assert data["en"][_NEW_KEY] != data["ja"][_NEW_KEY]


@pytest.mark.unit
class TestConfirmHostFixKeysParity:
    """EN/JA parity for the keys added by the host-confirm desync fix
    (no JS test harness — assert against bundled i18n.json directly)."""

    _KEYS = (
        "connector.finalize_unverifiable",
        "connector.finalize_affirm",
        "connector.finalize_affirming",
        "connector.finalize_manual",
        "wizard.host.sync_failed",
    )

    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in self._KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_manual_message_no_longer_dead_ends(self) -> None:
        """The reworded manual copy must point at the affirm action,
        not just say 'can't auto-detect'."""
        data = _load_i18n()
        assert "verified" in data["en"]["connector.finalize_manual"].lower()
        assert "確認" in data["ja"]["connector.finalize_manual"]


@pytest.mark.unit
class TestPluginOAuthCallbackKeysParity:
    """EN/JA parity for the #216/#217 plugin-OAuth card keys: the operator
    callback-URL label + hint, the read-only target status, and the two
    specific bind/validation error strings (no JS harness — asserted
    against bundled i18n.json directly)."""

    _KEYS = (
        "dashboard.plugin_oauth_callback_label",
        "dashboard.plugin_oauth_callback_hint",
        "dashboard.plugin_oauth_target_unset",
        "dashboard.plugin_oauth_callback_invalid",
        "dashboard.plugin_oauth_port_unavailable",
    )

    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in self._KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_keys_are_distinct_translations(self) -> None:
        data = _load_i18n()
        for key in self._KEYS:
            assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
class TestTikTokHostedNoteKeysParity:
    """EN/JA parity for the TikTok hosted-provider dashboard setup notes
    (Claude Code / Desktop / Codex). TikTok is a ``hosted_http`` provider
    like Meta but supports OAuth dynamic client registration, so it carries
    its own note set distinct from Meta's (asserted against the bundled
    i18n.json directly — no JS harness)."""

    _KEYS = (
        "dashboard.provider_tiktok_oauth_note",
        "dashboard.provider_tiktok_desktop_note",
        "dashboard.provider_tiktok_codex_note",
    )

    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in self._KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_keys_are_distinct_translations(self) -> None:
        data = _load_i18n()
        for key in self._KEYS:
            assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
class TestTikTokWizardKeysParity:
    """EN/JA presence for the TikTok wizard keys: the platforms checkbox
    label, the providers_install slot banner, and the completed-screen
    pending reminder. The label + banner are proper nouns ("TikTok Ads",
    identical in both locales like the other platform labels), so only the
    prose reminder is asserted to be a distinct translation."""

    _PRESENCE_KEYS = (
        "wizard.platforms.tiktok_ads",
        "wizard.provider_banner.tiktok_ads",
        "wizard.completed.pending_tiktok",
    )

    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in self._PRESENCE_KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_prose_reminder_is_distinct_translation(self) -> None:
        data = _load_i18n()
        key = "wizard.completed.pending_tiktok"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
class TestAdvancedAdvisorKeysParity:
    """EN/JA parity for the Advanced → External advisor MCP card keys: the
    nav label + section/card titles, the form field labels + transport
    options, the security note, and the toast/confirm/error strings (no JS
    harness — asserted against bundled i18n.json directly)."""

    # Distinct EN/JA strings — ``dashboard.advisors_url_label`` ("URL") is
    # intentionally NOT here: "URL" is a universal term with the same form
    # in both locales, so the distinctness assertion would falsely fail.
    _KEYS = (
        "dashboard.nav_advanced",
        "dashboard.advanced_title",
        "dashboard.advisors_title",
        "dashboard.advisors_desc",
        "dashboard.advisors_security_note",
        "dashboard.advisors_add_summary",
        "dashboard.advisors_name_label",
        "dashboard.advisors_tool_label",
        "dashboard.advisors_transport_label",
        "dashboard.advisors_transport_stdio",
        "dashboard.advisors_transport_sse",
        "dashboard.advisors_transport_http",
        "dashboard.advisors_command_label",
        "dashboard.advisors_args_label",
        "dashboard.advisors_env_label",
        "dashboard.advisors_headers_label",
        "dashboard.advisors_add_button",
        "dashboard.advisors_empty",
        "dashboard.advisors_remove",
        "dashboard.advisors_confirm_remove",
        "dashboard.advisors_added",
        "dashboard.advisors_removed",
        "dashboard.advisors_add_failed",
        "dashboard.advisors_remove_failed",
        "dashboard.advisors_name_required",
        "dashboard.advisors_err_duplicate_name",
        "dashboard.advisors_err_invalid",
    )

    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in self._KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_url_label_present_in_both_locales(self) -> None:
        """The URL label is exempt from the distinctness check (universal
        term) but must still exist + be non-empty in both locales."""
        data = _load_i18n()
        for locale in ("en", "ja"):
            value = data[locale].get("dashboard.advisors_url_label")
            assert isinstance(value, str) and value.strip()

    def test_keys_are_distinct_translations(self) -> None:
        data = _load_i18n()
        for key in self._KEYS:
            assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
class TestReportsDashboardKeysParity:
    """EN/JA parity for the read-only Reports dashboard keys: the nav label,
    section title + hint, client selector, freshness, KPI labels, the
    no-metrics/empty states, the latest-report + recent-actions titles, and
    the relative-age strings (no JS harness — asserted against the bundled
    i18n.json directly)."""

    # Distinct EN/JA strings. ``dashboard.reports_kpi_cpa`` ("CPA") and
    # ``dashboard.reports_kpi_ctr`` ("CTR") are intentionally NOT here:
    # they are universal acronyms with the same form in both locales (the
    # same exemption the Advanced-advisor suite makes for "URL"), so the
    # distinctness assertion would falsely fail.
    _KEYS = (
        "dashboard.nav_reports",
        "dashboard.reports_title",
        "dashboard.reports_hint",
        "dashboard.reports_client_label",
        "dashboard.reports_period_yesterday",
        "dashboard.reports_period_last_7_days",
        "dashboard.reports_period_last_30_days",
        "dashboard.reports_synced",
        "dashboard.reports_kpi_spend",
        "dashboard.reports_kpi_conversions",
        "dashboard.reports_kpi_clicks",
        "dashboard.reports_kpi_impressions",
        "dashboard.reports_flag_cpa_over_target",
        "dashboard.reports_flag_cpa_under_target",
        "dashboard.reports_flag_cv_below_target",
        "dashboard.reports_flag_cv_above_target",
        "dashboard.reports_flag_operation_mode_mismatch",
        "dashboard.reports_flag_low_cvr",
        "dashboard.reports_flag_low_cvr_lp",
        "dashboard.reports_flag_tracking_suspect",
        "dashboard.reports_flag_zero_conversions",
        "dashboard.reports_flag_budget_overspend",
        "dashboard.reports_flag_spend_spike",
        "dashboard.reports_flag_sc_no_property",
        "dashboard.reports_no_metrics",
        "dashboard.reports_campaign_count",
        "dashboard.reports_back",
        "dashboard.reports_latest_title",
        "dashboard.reports_generated",
        "dashboard.reports_actions_title",
        "dashboard.reports_observation_due",
        "dashboard.reports_empty",
        "dashboard.reports_empty_hint",
        "dashboard.reports_age_just_now",
        "dashboard.reports_age_minutes",
        "dashboard.reports_age_hours",
        "dashboard.reports_age_days",
    )

    # Universal acronym KPI labels — present + non-empty in both locales,
    # but exempt from the distinctness check.
    _UNIVERSAL_KEYS = (
        "dashboard.reports_kpi_cpa",
        "dashboard.reports_kpi_ctr",
    )

    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in self._KEYS + self._UNIVERSAL_KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_keys_are_distinct_translations(self) -> None:
        data = _load_i18n()
        for key in self._KEYS:
            assert data["en"][key] != data["ja"][key], f"{key} not localized"
