"""Static-content guards for the dashboard form action-row layout.

No JS test harness runs the dashboard DOM code, so the contract is pinned
by grepping the bundled assets (the ``test_web_assets_*`` convention):

- ``.dashboard-section label`` flows inline (two-up on a wide card), so a
  button appended straight after the fields was laid INTO the fields' row
  and top-aligned beside the last field whenever that row had room for it
  (a single field, or an odd count at two-up). The stylesheet now ends the
  flow at an action control: a button that follows a field starts a row
  of its own, sized to its text;
- a button and the status line it reports into (OAuth Authenticate, the
  account picker's Load) and the Demo card's Browse + Create pair share one
  ``.form-actions`` row instead of being appended bare.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector!r}"
    return m.group(1)


@pytest.mark.unit
def test_label_flow_is_still_inline() -> None:
    # The fix is relative to this: labels flow inline, so the button needs
    # its own row. If the flow itself changes, revisit the rules below.
    body = _rule(_read("app.css"), ".dashboard-section label")
    assert "display: inline-block" in body


@pytest.mark.unit
def test_button_after_a_field_starts_its_own_row() -> None:
    body = _rule(_read("app.css"), ".dashboard-section label + .btn:not([hidden])")
    assert "display: flex" in body
    # Block-level so it leaves the fields' row, but sized to its text, not
    # stretched across the card.
    assert "width: fit-content" in body


@pytest.mark.unit
def test_form_actions_row_is_a_wrapping_flex_row() -> None:
    body = _rule(_read("app.css"), ".dashboard-section .form-actions")
    assert "display: flex" in body
    assert "flex-wrap: wrap" in body
    assert "align-items: center" in body


@pytest.mark.unit
def test_plugin_oauth_button_and_status_share_an_actions_row() -> None:
    js = _read("dashboard_plugins.js")
    start = js.index("function appendOAuthControls")
    oauth = js[start : js.index("function appendManualSave")]
    assert 'actions.className = "form-actions"' in oauth
    assert "actions.appendChild(authBtn)" in oauth
    assert "actions.appendChild(status)" in oauth
    assert "form.appendChild(actions)" in oauth
    assert "form.appendChild(authBtn)" not in oauth


@pytest.mark.unit
def test_account_picker_load_and_status_share_an_actions_row() -> None:
    js = _read("dashboard_plugins.js")
    start = js.index("function appendAccountPicker")
    picker = js[start : js.index("function accountsErrorKey")]
    assert 'actions.className = "form-actions"' in picker
    assert "actions.appendChild(loadBtn)" in picker
    assert "actions.appendChild(status)" in picker
    assert "form.appendChild(actions)" in picker
    assert "form.appendChild(loadBtn)" not in picker


@pytest.mark.unit
def test_amazon_exchange_button_and_status_share_an_actions_row() -> None:
    js = _read("amazon_oauth.js")
    start = js.index("const exchangeBtn = labelledText")
    block = js[start : js.index("authorizeBtn.addEventListener", start)]
    assert 'actions.className = "form-actions"' in block
    assert "actions.appendChild(exchangeBtn)" in block
    assert "actions.appendChild(status)" in block
    assert "box.appendChild(actions)" in block
    assert "box.appendChild(exchangeBtn)" not in block


@pytest.mark.unit
def test_demo_browse_and_create_share_an_actions_row() -> None:
    html = _read("app.html")
    m = re.search(
        r'<div class="form-actions">\s*<button[^>]*data-demo-browse[^>]*>.*?</button>'
        r"\s*<button[^>]*data-demo-create[^>]*>.*?</button>\s*</div>",
        html,
        re.S,
    )
    assert m, "Demo card's Browse + Create are not wrapped in .form-actions"


_FIELD_SCOPES = (".dashboard-pane", ".dashboard-section", ".wizard-step")
_SINGLE_LINE_TYPES = ("text", "password", "number", "url", "email")


@pytest.mark.unit
def test_single_line_inputs_share_the_field_rule() -> None:
    # An extension's number / url / email field must not fall back to the
    # browser default next to the styled text fields.
    css = _read("app.css")
    head = css.index(".dashboard-pane select,")
    selectors = css[head : css.index("{", head)]
    for scope in _FIELD_SCOPES:
        for kind in _SINGLE_LINE_TYPES:
            assert f'{scope} input[type="{kind}"]' in selectors


@pytest.mark.unit
def test_guardrails_number_rule_still_follows_the_field_rule() -> None:
    # Same specificity as ``.dashboard-section input[type="number"]``, so
    # the narrower guardrails width wins only by coming later.
    css = _read("app.css")
    field = css.index('.dashboard-section input[type="number"]')
    guardrails = css.index('.dashboard-guardrails-value input[type="number"]')
    assert field < guardrails
