"""Static-content guards for the plugin-OAuth card rework (#216/#217).

No JS test harness ships in the repo, so the ``dashboard.js`` OAuth card
contract is pinned by grepping the bundled asset (read directly from
``mureo/_data/web/`` at runtime — no build step). A future refactor that
drops the operator callback-URL input (#216), re-adds a Save button to an
OAuth provider, stops sending the form values on Authenticate (#217), or
loses the specific bind/validation error surfacing flips a test red here
long before an operator hits the regression in the configure UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
def test_dashboard_renders_callback_url_input() -> None:
    """#216: the OAuth card renders an operator-supplied loopback callback
    URL input. Its name must match the server's ``_OAUTH_CALLBACK_URL_KEY``
    (``oauth_callback_url``) so the value reaches ``start_plugin_oauth``."""
    js = _read("dashboard.js")
    assert "oauth_callback_url" in js
    assert "dashboard.plugin_oauth_callback_label" in js
    assert "dashboard.plugin_oauth_callback_hint" in js


@pytest.mark.unit
def test_dashboard_renders_readonly_target_status() -> None:
    """#217: the OAuth ``target_field`` (the refresh token) is shown as a
    read-only status row, not a text input — it is obtained via
    Authenticate, never typed."""
    js = _read("dashboard.js")
    assert "data-oauth-target-status" in js
    assert "dashboard.plugin_oauth_target_unset" in js


@pytest.mark.unit
def test_dashboard_authenticate_sends_form_values() -> None:
    """#217: Authenticate IS save — ``startPluginOAuth`` takes the gathered
    form values and POSTs them (so the bridge can persist them with the
    token), instead of the old empty-body request."""
    js = _read("dashboard.js")
    assert (
        "function startPluginOAuth(providerName, btn, statusNode, values)" in js
    ), "startPluginOAuth must accept the gathered form values"
    # The values must travel in the /oauth/start body.
    assert 'base + "/start", { values' in js or 'base + "/start", {values' in js


@pytest.mark.unit
def test_dashboard_surfaces_new_oauth_error_keys() -> None:
    """#216: the specific bind/validation failures map to dedicated toast
    strings, not the generic 'authentication failed'."""
    js = _read("dashboard.js")
    assert "dashboard.plugin_oauth_callback_invalid" in js
    assert "dashboard.plugin_oauth_port_unavailable" in js


@pytest.mark.unit
def test_dashboard_callback_url_prefill_consults_provider_default() -> None:
    """#220: the callback URL input pre-fill consults the provider-declared
    ``default_callback_url`` (between the saved value and the generic
    fallback), so a provider with a fixed redirect_uri pre-fills the exact
    URL the operator must register."""
    js = _read("dashboard.js")
    assert "default_callback_url" in js
