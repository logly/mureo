"""Static guards for the secret-field status mark.

A secret credential value never reaches the browser, so each secret input
now says whether a value is stored: a ✓ / ✗ mark plus "Configured" /
"Not set", and an unset secret without a provider placeholder asks for a
value. The rendering itself is exercised by
``tests/js/secret_field_status.test.js`` against the real assets; this file
pins the i18n strings in both locales and the wiring in each renderer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"

_KEYS = (
    "dashboard.credential_secret_configured",
    "dashboard.credential_secret_unset",
    "dashboard.plugin_credentials_secret_unset_placeholder",
)

# Every renderer that shows the status text next to a secret field.
_RENDERERS = (
    "dashboard_plugins.js",
    "auth_wizards.js",
    "auth_wizards_meta.js",
    "dashboard_setup.js",
)


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _load_i18n() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_read("i18n.json"))
    return data


@pytest.mark.unit
class TestSecretFieldStatusKeys:
    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in _KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_keys_are_distinct_translations(self) -> None:
        data = _load_i18n()
        for key in _KEYS:
            assert data["en"][key] != data["ja"][key], f"{key} not localized"

    def test_english_wording(self) -> None:
        en = _load_i18n()["en"]
        assert en["dashboard.credential_secret_configured"] == "Configured"
        assert en["dashboard.credential_secret_unset"] == "Not set"
        assert (
            en["dashboard.plugin_credentials_secret_unset_placeholder"]
            == "(not set — enter a value)"
        )


@pytest.mark.unit
class TestSecretFieldStatusWiring:
    @pytest.mark.parametrize("name", _RENDERERS)
    def test_renderer_uses_the_status_keys(self, name: str) -> None:
        js = _read(name)
        assert "dashboard.credential_secret_configured" in js
        assert "dashboard.credential_secret_unset" in js
        assert "mark-ok" in js
        assert "mark-no" in js

    @pytest.mark.parametrize("name", _RENDERERS)
    def test_unset_secret_falls_back_to_the_unset_placeholder(self, name: str) -> None:
        js = _read(name)
        assert "dashboard.plugin_credentials_secret_unset_placeholder" in js

    @pytest.mark.parametrize("name", _RENDERERS)
    def test_renderer_builds_the_mark_without_inner_html(self, name: str) -> None:
        js = _read(name)
        start = js.index("function statusMark(")
        body = js[start : js.index("\n  }\n", start)]
        assert "innerHTML" not in body
        assert "createElement" in body

    def test_env_form_has_a_status_holder_next_to_the_value_input(self) -> None:
        """The advanced credentials form shows the selected field's status in
        a holder without data-i18n, so a re-translation cannot wipe it."""
        html = _read("app.html")
        assert "<span data-env-value-status></span>" in html
        js = _read("dashboard_setup.js")
        assert "renderEnvValueStatus" in js
        assert "[data-env-value-status]" in js
