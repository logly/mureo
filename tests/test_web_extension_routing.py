"""End-to-end routing tests for the web-extension layer.

Boots a real :class:`ConfigureWizard` on 127.0.0.1:0 with a controlled
set of extensions pre-seeded into ``mureo.web.extensions._cached_entries``
and exercises every dispatch branch added by this commit:

* ``GET /api/extensions`` — index for the configure-UI client
* ``GET /api/ext/<name>/<subpath>`` — extension GET route
* ``POST /api/ext/<name>/<subpath>`` — extension POST route (CSRF gated)
* ``GET /static/ext/<name>/<filename>`` — extension-shipped asset
* 404 / 403 / 500 paths for unknown / unauthorised / faulty routes
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from mureo.web.extensions import (
    RouteContribution,
    StaticAsset,
    ViewContribution,
    WebExtensionEntry,
    reset_web_extensions,
)
from mureo.web.server import ConfigureWizard
from tests.web_support import get_raw, post

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.server import BaseHTTPRequestHandler


# ---------------------------------------------------------------------------
# Reference extension used across the suite
# ---------------------------------------------------------------------------


_recorded_calls: list[tuple[str, dict[str, Any]]] = []


def _record_ping(_req: BaseHTTPRequestHandler, payload: dict[str, Any]) -> None:
    from mureo.web._helpers import send_json

    _recorded_calls.append(("ping", dict(payload)))
    send_json(_req, {"echo": payload})


def _record_save(_req: BaseHTTPRequestHandler, payload: dict[str, Any]) -> None:
    from mureo.web._helpers import send_json

    _recorded_calls.append(("save", dict(payload)))
    send_json(_req, {"saved": True, "received": payload})


def _record_explode(_req: BaseHTTPRequestHandler, _payload: dict[str, Any]) -> None:
    raise RuntimeError("handler exploded")


def _make_entry() -> WebExtensionEntry:
    return WebExtensionEntry(
        name="demo",
        display_name="Demo extension",
        routes=(
            RouteContribution(method="GET", subpath="/ping", handler=_record_ping),
            RouteContribution(method="POST", subpath="/save", handler=_record_save),
            RouteContribution(
                method="GET", subpath="/explode", handler=_record_explode
            ),
        ),
        view=ViewContribution(
            html_fragment="<section><h2 data-demo>Demo</h2></section>",
            scripts=(
                StaticAsset(
                    filename="demo.js",
                    content_type="application/javascript",
                    body=b"console.log('demo');",
                ),
            ),
            styles=(
                StaticAsset(
                    filename="demo.css",
                    content_type="text/css",
                    body=b".demo{color:red}",
                ),
            ),
        ),
        source_distribution="mureo-demo",
    )


@pytest.fixture(autouse=True)
def _reset_extensions_state() -> Iterator[None]:
    """Clean extension cache + call recorder for every test."""
    reset_web_extensions()
    _recorded_calls.clear()
    yield
    reset_web_extensions()
    _recorded_calls.clear()


@pytest.fixture
def _demo_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (_make_entry(),))


@pytest.fixture
def _no_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.web.extensions._cached_entries", ())


@pytest.fixture
def wizard_with_extensions(
    _demo_entries: None, wizard: ConfigureWizard
) -> ConfigureWizard:
    """The shared ``wizard``, booted with one extension pre-seeded."""
    return wizard


@pytest.fixture
def wizard_no_extensions(_no_entries: None, wizard: ConfigureWizard) -> ConfigureWizard:
    """The shared ``wizard``, booted with zero extensions registered."""
    return wizard


# ---------------------------------------------------------------------------
# /api/extensions index
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extensions_index_empty(wizard_no_extensions: ConfigureWizard) -> None:
    resp = get_raw(wizard_no_extensions, "/api/extensions")
    assert resp.status == 200
    payload = json.loads(resp.read().decode())
    assert payload == []


@pytest.mark.unit
def test_extensions_index_lists_registered(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    resp = get_raw(wizard_with_extensions, "/api/extensions")
    payload = json.loads(resp.read().decode())
    assert isinstance(payload, list)
    assert len(payload) == 1
    item = payload[0]
    assert item["name"] == "demo"
    assert item["display_name"] == "Demo extension"
    assert item["display_name_i18n"] == {}
    # #189 — surface-override keys are always present (no-op defaults)
    # so the renderer never needs an existence check.
    assert item["hidden_builtin_tabs"] == []
    assert item["replaces_landing"] is False
    assert item["view"]["html_fragment"].startswith("<section")
    assert item["view"]["scripts"] == ["demo.js"]
    assert item["view"]["styles"] == ["demo.css"]


@pytest.fixture
def _surface_override_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    override_entry = WebExtensionEntry(
        name="full-surface",
        display_name="Full surface",
        routes=(),
        view=ViewContribution(html_fragment="<p>fs</p>"),
        source_distribution=None,
        hidden_builtin_tabs=("setup", "demo"),
        replaces_landing=True,
    )
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (override_entry,))


@pytest.mark.unit
def test_extensions_index_includes_surface_overrides(
    _surface_override_entries: None, wizard: ConfigureWizard
) -> None:
    """#189 — ``hidden_builtin_tabs`` / ``replaces_landing`` ride the
    index payload so ``extensions.js`` can hide built-in tabs and skip
    the landing for full-surface plugins."""
    resp = get_raw(wizard, "/api/extensions")
    payload = json.loads(resp.read().decode())
    assert payload[0]["hidden_builtin_tabs"] == ["setup", "demo"]
    assert payload[0]["replaces_landing"] is True


@pytest.fixture
def _i18n_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    i18n_entry = WebExtensionEntry(
        name="i18n-demo",
        display_name="I18n demo",
        routes=(),
        view=ViewContribution(html_fragment="<p>i18n</p>"),
        source_distribution=None,
        display_name_i18n={"en": "Demo", "ja": "デモ"},
    )
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (i18n_entry,))


@pytest.mark.unit
def test_extensions_index_includes_display_name_i18n(
    _i18n_entries: None, wizard: ConfigureWizard
) -> None:
    """An extension that ships per-locale labels surfaces them on
    ``/api/extensions`` so the renderer can swap nav labels when the
    operator toggles locale without round-tripping the server."""
    resp = get_raw(wizard, "/api/extensions")
    payload = json.loads(resp.read().decode())
    assert payload[0]["display_name_i18n"] == {"en": "Demo", "ja": "デモ"}


@pytest.fixture
def _no_view_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    no_view = WebExtensionEntry(
        name="nogui",
        display_name="No GUI",
        routes=(),
        view=None,
        source_distribution=None,
    )
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (no_view,))


@pytest.mark.unit
def test_extensions_index_view_null_when_extension_has_no_view(
    _no_view_entries: None, wizard: ConfigureWizard
) -> None:
    resp = get_raw(wizard, "/api/extensions")
    payload = json.loads(resp.read().decode())
    assert payload == [
        {
            "name": "nogui",
            "display_name": "No GUI",
            "display_name_i18n": {},
            "hidden_builtin_tabs": [],
            "replaces_landing": False,
            "dashboard_cards": [],
            "view": None,
        }
    ]


# ---------------------------------------------------------------------------
# GET /api/ext/<name>/<subpath>
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_extension_route_dispatches_to_handler(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    resp = get_raw(wizard_with_extensions, "/api/ext/demo/ping?q=hello&n=42")
    assert resp.status == 200
    body = json.loads(resp.read().decode())
    assert body == {"echo": {"q": "hello", "n": "42"}}
    assert _recorded_calls == [("ping", {"q": "hello", "n": "42"})]


@pytest.mark.unit
def test_get_extension_route_first_value_wins_for_repeated_keys(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    """``urllib.parse.parse_qs`` lists values; the dispatcher flattens
    each list to its first element. Handlers that need full multi-value
    semantics can still read ``self.path`` directly."""
    get_raw(wizard_with_extensions, "/api/ext/demo/ping?q=one&q=two&q=three")
    assert _recorded_calls == [("ping", {"q": "one"})]


@pytest.mark.unit
def test_get_unknown_extension_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(wizard_with_extensions, "/api/ext/missing/ping")
    assert exc.value.code == 404


@pytest.mark.unit
def test_get_unknown_subpath_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(wizard_with_extensions, "/api/ext/demo/nope")
    assert exc.value.code == 404


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/api/ext/demo/../etc/passwd",
        "/api/ext/demo/ping/../save",
        "/api/ext/demo//ping",
        "/api/ext/DEMO/ping",
        "/api/ext/demo",
    ],
)
def test_get_traversal_or_malformed_paths_return_404(
    wizard_with_extensions: ConfigureWizard, path: str
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(wizard_with_extensions, path)
    assert exc.value.code == 404


@pytest.mark.unit
def test_get_extension_handler_exception_returns_500(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(wizard_with_extensions, "/api/ext/demo/explode")
    assert exc.value.code == 500
    body = json.loads(exc.value.read().decode())
    assert "error" in body


# ---------------------------------------------------------------------------
# POST /api/ext/<name>/<subpath>
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_post_extension_route_dispatches_with_csrf(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    status, body = post(wizard_with_extensions, "/api/ext/demo/save", {"key": "value"})
    assert status == 200
    assert body == {"saved": True, "received": {"key": "value"}}


@pytest.mark.unit
def test_post_extension_route_rejects_missing_csrf(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    status, body = post(
        wizard_with_extensions, "/api/ext/demo/save", {"key": "v"}, csrf=None
    )
    assert status == 403


@pytest.mark.unit
def test_post_extension_route_rejects_bad_csrf(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    status, body = post(
        wizard_with_extensions,
        "/api/ext/demo/save",
        {"key": "v"},
        csrf="wrong-token",
    )
    assert status == 403


@pytest.mark.unit
def test_post_unknown_extension_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    status, body = post(wizard_with_extensions, "/api/ext/missing/save", {})
    assert status == 404


@pytest.mark.unit
def test_post_get_only_subpath_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    """``/api/ext/demo/ping`` is a GET-only route; POSTing must 404."""
    status, body = post(wizard_with_extensions, "/api/ext/demo/ping", {})
    assert status == 404


# ---------------------------------------------------------------------------
# GET /static/ext/<name>/<filename>
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_static_asset_served_with_correct_content_type(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    resp = get_raw(wizard_with_extensions, "/static/ext/demo/demo.js")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/javascript")
    assert resp.read() == b"console.log('demo');"


@pytest.mark.unit
def test_static_asset_unknown_filename_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(wizard_with_extensions, "/static/ext/demo/missing.js")
    assert exc.value.code == 404


@pytest.mark.unit
def test_static_asset_unknown_extension_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(wizard_with_extensions, "/static/ext/missing/demo.js")
    assert exc.value.code == 404


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/static/ext/demo/../app.html",
        "/static/ext/demo/sub/dir.js",
        "/static/ext/demo/.hidden",
        "/static/ext/DEMO/demo.js",
    ],
)
def test_static_asset_traversal_paths_return_404(
    wizard_with_extensions: ConfigureWizard, path: str
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(wizard_with_extensions, path)
    assert exc.value.code == 404


@pytest.mark.unit
def test_static_asset_response_carries_security_headers(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    """Extension-served assets inherit the same CSP / X-Frame-Options /
    Cache-Control set the built-in static path applies — they share the
    ``send_bytes`` helper."""
    resp = get_raw(wizard_with_extensions, "/static/ext/demo/demo.css")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in (resp.headers["Content-Security-Policy"] or "")


# ---------------------------------------------------------------------------
# Dashboard cards — index payload + card asset serving
# ---------------------------------------------------------------------------


def _make_card_entry() -> WebExtensionEntry:
    from mureo.web.extensions import DashboardCard

    return WebExtensionEntry(
        name="cardful",
        display_name="Cardful extension",
        routes=(),
        view=None,
        source_distribution="mureo-cardful",
        dashboard_cards=(
            DashboardCard(
                group="advanced",
                html_fragment="<section data-cardful>Cardful</section>",
                scripts=(
                    StaticAsset(
                        filename="cardful.js",
                        content_type="application/javascript",
                        body=b"console.log('cardful');",
                    ),
                ),
                styles=(
                    StaticAsset(
                        filename="cardful.css",
                        content_type="text/css",
                        body=b".cardful{color:blue}",
                    ),
                ),
            ),
        ),
    )


@pytest.fixture
def _card_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (_make_card_entry(),))


@pytest.fixture
def wizard_with_card_extension(
    _card_entries: None, wizard: ConfigureWizard
) -> ConfigureWizard:
    """The shared ``wizard``, booted with one headless, card-bearing extension."""
    return wizard


@pytest.mark.unit
def test_extensions_index_includes_dashboard_cards(
    wizard_with_card_extension: ConfigureWizard,
) -> None:
    resp = get_raw(wizard_with_card_extension, "/api/extensions")
    payload = json.loads(resp.read().decode())
    assert len(payload) == 1
    item = payload[0]
    assert item["view"] is None  # cards do not require a view
    assert item["dashboard_cards"] == [
        {
            "group": "advanced",
            "html_fragment": "<section data-cardful>Cardful</section>",
            "scripts": ["cardful.js"],
            "styles": ["cardful.css"],
        }
    ]


@pytest.mark.unit
def test_extensions_index_dashboard_cards_default_to_empty_list(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    resp = get_raw(wizard_with_extensions, "/api/extensions")
    payload = json.loads(resp.read().decode())
    assert payload[0]["dashboard_cards"] == []


@pytest.mark.unit
def test_dashboard_card_static_assets_are_served(
    wizard_with_card_extension: ConfigureWizard,
) -> None:
    resp = get_raw(wizard_with_card_extension, "/static/ext/cardful/cardful.js")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/javascript")
    assert resp.read() == b"console.log('cardful');"

    resp = get_raw(wizard_with_card_extension, "/static/ext/cardful/cardful.css")
    assert resp.status == 200
    assert resp.read() == b".cardful{color:blue}"


@pytest.mark.unit
def test_dashboard_card_unknown_asset_still_404s(
    wizard_with_card_extension: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get_raw(wizard_with_card_extension, "/static/ext/cardful/absent.js")
    assert excinfo.value.code == 404
