"""Static-content guards for the dashboard card treatment (#183) and the
toast-kind error surface (#184).

These tests pin the *shape* of the web assets that ship with mureo (no
build step — they are read directly from ``mureo/_data/web/`` at
runtime). A CSS rule or a toast call that gets accidentally reverted by
a future refactor flips a test red here long before an operator notices
the regression in the configure UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #183 — Dashboard provider rows look like cards (border + padding + radius)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dashboard_providers_list_has_card_selector() -> None:
    """``[data-dashboard-providers-list] > li`` must be styled as a
    card so each platform's row is visually demarcated from the next.
    Without a hairline border + radius + padding the list is flat and
    operators have to read the labels carefully to find the boundary.
    """
    css = _read("app.css")
    assert "[data-dashboard-providers-list] > li" in css


@pytest.mark.unit
def test_dashboard_plugin_credentials_list_has_card_selector() -> None:
    """Plugin credentials list uses a generic child selector
    (``> *``) so any plugin-rendered row participates in the same
    card treatment.
    """
    css = _read("app.css")
    assert "[data-dashboard-plugin-credentials-list] > *" in css


@pytest.mark.unit
def test_dashboard_card_rule_carries_border_radius_padding() -> None:
    """Pin the actual visual properties — the rule must visibly
    demarcate, not just exist as a selector.
    """
    css = _read("app.css")
    # Find the dashboard card block — both lists share one rule. The
    # marker is the human-grep-friendly prefix; the rest of the comment
    # may be a longer rationale across multiple lines.
    marker = "/* #183 dashboard provider card"
    assert marker in css, (
        "card block must be marked so future grep finds it; if you "
        "rename the marker, update this test too"
    )
    block_start = css.index(marker)
    # Read a window large enough to hold the rule body (comment +
    # selectors + the full declaration block, which has grown over time
    # with explanatory comments).
    window = css[block_start : block_start + 2400]
    assert "border:" in window
    assert "border-radius:" in window
    assert "padding:" in window


# ---------------------------------------------------------------------------
# #184 — Toast accepts a ``kind`` for color-coding + error sites use it
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_toast_helper_accepts_kind_argument() -> None:
    """``MUREO.toast`` must accept an optional kind argument so error /
    success can be color-coded. The signature is part of the public
    surface (every web asset bundled with mureo can call it).
    """
    js = _read("app.js")
    assert "function toast(message, kind)" in js


@pytest.mark.unit
def test_toast_applies_kind_class() -> None:
    """The kind argument must translate to a CSS class (``is-error`` /
    ``is-success`` / ``is-info``) so ``app.css`` can color-code without
    inline styles.
    """
    js = _read("app.js")
    assert (
        "is-" in js and "classList" in js
    ), "toast() must set a kind-derived className via classList"


@pytest.mark.unit
def test_toast_error_and_success_styles_exist() -> None:
    """``.app-toast.is-error`` and ``.app-toast.is-success`` must be
    declared in ``app.css`` — otherwise the kind argument has no visual
    effect.
    """
    css = _read("app.css")
    assert ".app-toast.is-error" in css
    assert ".app-toast.is-success" in css


@pytest.mark.unit
def test_auth_wizard_error_sites_also_toast() -> None:
    """Five known inline ``status.textContent = MUREO.t("...failed")``
    sites in ``auth_wizards.js`` must pair with a ``MUREO.toast(...,
    "error")`` call. The inline status stays for the accessible status
    node; the toast adds the scroll-resistant surface.

    Regression guard for #184: an operator scrolled to the bottom of a
    long Dashboard who triggers a wizard failure sees the toast at
    bottom-right regardless of where the inline status node sits.
    """
    js = _read("auth_wizards.js")
    assert js.count("MUREO.toast(") >= 5, (
        "auth_wizards.js must call MUREO.toast() on every inline "
        "error site; expected at least five (finalize, save x2, "
        "oauth start, oauth poll). See issue #184."
    )
    # Pin the kind argument at every site so a typo at one call
    # (e.g. ``"errr"``) cannot slip through while still passing a
    # global ``"error" in js`` check.
    assert js.count('"error"') >= 5, (
        'every wizard error toast must pass kind="error" — count '
        "below the expected sites suggests a typo or missing kind"
    )


# ---------------------------------------------------------------------------
# #214 — the toast overlay must live OUTSIDE <main class="app-main">
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_toast_node_lives_outside_main() -> None:
    """``.app-main`` carries a filled ``rise`` transform animation, and a
    transformed ancestor becomes the containing block for
    ``position: fixed`` descendants. A toast inside ``<main>`` therefore
    anchors to the bottom of the (tall) main element — ~1700px below the
    viewport on the dashboard — instead of the screen, making every
    dashboard toast invisible (#214). The overlay must be a body-level
    sibling, after ``</main>``.
    """
    html = _read("app.html")
    assert "data-toast" in html, "toast node missing from app.html"
    assert html.index("</main>") < html.index("data-toast"), (
        "the [data-toast] overlay must live OUTSIDE <main class='app-main'> "
        "(after </main>) — a transformed ancestor hijacks position:fixed. "
        "See #214."
    )


# ---------------------------------------------------------------------------
# Reports dashboard — read-only STATE.json summary (platform-agnostic).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reports_nav_item_present_after_setup() -> None:
    """The Reports nav item must exist and sit immediately after the Setup
    nav item (before Advanced) so the left-nav order is Setup → Reports →
    Advanced. dashboard.js toggles ``[data-dashboard-group]`` by the nav's
    ``data-dashboard-nav`` value, so the marker must be present verbatim.
    """
    html = _read("app.html")
    assert 'data-dashboard-nav="reports"' in html
    assert 'data-i18n="dashboard.nav_reports"' in html
    setup_idx = html.index('data-dashboard-nav="setup"')
    reports_idx = html.index('data-dashboard-nav="reports"')
    advanced_idx = html.index('data-dashboard-nav="advanced"')
    assert (
        setup_idx < reports_idx < advanced_idx
    ), "Reports nav item must be ordered Setup → Reports → Advanced"


@pytest.mark.unit
def test_reports_section_shell_present() -> None:
    """The reports group + the containers renderReports() populates (cards,
    latest, actions, empty state) must exist in app.html — otherwise the
    render function has nowhere to write.
    """
    html = _read("app.html")
    assert 'data-dashboard-group="reports"' in html
    assert "data-reports-cards" in html
    assert "data-reports-latest" in html
    assert "data-reports-actions" in html
    assert "data-reports-empty" in html
    # The multi-client overview grid (#307) replaced the old client dropdown.
    assert "data-reports-clients" in html


@pytest.mark.unit
def test_reports_card_css_uses_design_tokens() -> None:
    """The KPI card rule must carry the card treatment (surface bg, hairline
    border, radius, shadow) built on the existing tokens — a generic flat
    block would regress the design intent.
    """
    css = _read("app.css")
    assert ".report-card {" in css
    block_start = css.index(".report-card {")
    window = css[block_start : block_start + 600]
    assert "var(--surface)" in window
    assert "var(--hairline)" in window
    assert "border-radius:" in window
    assert "box-shadow: var(--shadow-sm)" in window
