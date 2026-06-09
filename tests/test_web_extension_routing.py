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
import threading
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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from http.server import BaseHTTPRequestHandler
    from pathlib import Path


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
def wizard_with_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ConfigureWizard]:
    """Pre-seed one extension, boot a wizard, yield it."""
    entry = _make_entry()
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (entry,))
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
    (home / ".mureo").mkdir()
    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


@pytest.fixture
def wizard_no_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ConfigureWizard]:
    """Boot a wizard with zero extensions registered."""
    monkeypatch.setattr("mureo.web.extensions._cached_entries", ())
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
    (home / ".mureo").mkdir()
    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _url(wiz: ConfigureWizard, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


def _get(wiz: ConfigureWizard, path: str) -> HTTPResponse:
    return urllib.request.urlopen(_url(wiz, path), timeout=2.0)


def _post(
    wiz: ConfigureWizard,
    path: str,
    payload: dict[str, Any] | None,
    *,
    csrf: str | None = "use_session",
) -> HTTPResponse:
    body = json.dumps(payload or {}).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if csrf == "use_session":
        headers["X-CSRF-Token"] = wiz.session.csrf_token
    elif csrf is not None:
        headers["X-CSRF-Token"] = csrf
    req = urllib.request.Request(_url(wiz, path), data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=2.0)


# ---------------------------------------------------------------------------
# /api/extensions index
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extensions_index_empty(wizard_no_extensions: ConfigureWizard) -> None:
    resp = _get(wizard_no_extensions, "/api/extensions")
    assert resp.status == 200
    payload = json.loads(resp.read().decode())
    assert payload == []


@pytest.mark.unit
def test_extensions_index_lists_registered(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    resp = _get(wizard_with_extensions, "/api/extensions")
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


@pytest.mark.unit
def test_extensions_index_includes_surface_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#189 — ``hidden_builtin_tabs`` / ``replaces_landing`` ride the
    index payload so ``extensions.js`` can hide built-in tabs and skip
    the landing for full-surface plugins."""
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
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
    (home / ".mureo").mkdir()
    wiz = ConfigureWizard(home=home)
    t = threading.Thread(target=wiz.serve, daemon=True)
    t.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        resp = _get(wiz, "/api/extensions")
        payload = json.loads(resp.read().decode())
        assert payload[0]["hidden_builtin_tabs"] == ["setup", "demo"]
        assert payload[0]["replaces_landing"] is True
    finally:
        wiz.shutdown()
        t.join(timeout=2.0)


@pytest.mark.unit
def test_extensions_index_includes_display_name_i18n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extension that ships per-locale labels surfaces them on
    ``/api/extensions`` so the renderer can swap nav labels when the
    operator toggles locale without round-tripping the server."""
    i18n_entry = WebExtensionEntry(
        name="i18n-demo",
        display_name="I18n demo",
        routes=(),
        view=ViewContribution(html_fragment="<p>i18n</p>"),
        source_distribution=None,
        display_name_i18n={"en": "Demo", "ja": "デモ"},
    )
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (i18n_entry,))
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
    (home / ".mureo").mkdir()
    wiz = ConfigureWizard(home=home)
    t = threading.Thread(target=wiz.serve, daemon=True)
    t.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        resp = _get(wiz, "/api/extensions")
        payload = json.loads(resp.read().decode())
        assert payload[0]["display_name_i18n"] == {"en": "Demo", "ja": "デモ"}
    finally:
        wiz.shutdown()
        t.join(timeout=2.0)


@pytest.mark.unit
def test_extensions_index_view_null_when_extension_has_no_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_view = WebExtensionEntry(
        name="nogui",
        display_name="No GUI",
        routes=(),
        view=None,
        source_distribution=None,
    )
    monkeypatch.setattr("mureo.web.extensions._cached_entries", (no_view,))
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
    (home / ".mureo").mkdir()
    wiz = ConfigureWizard(home=home)
    t = threading.Thread(target=wiz.serve, daemon=True)
    t.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        resp = _get(wiz, "/api/extensions")
        payload = json.loads(resp.read().decode())
        assert payload == [
            {
                "name": "nogui",
                "display_name": "No GUI",
                "display_name_i18n": {},
                "hidden_builtin_tabs": [],
                "replaces_landing": False,
                "view": None,
            }
        ]
    finally:
        wiz.shutdown()
        t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# GET /api/ext/<name>/<subpath>
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_extension_route_dispatches_to_handler(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    resp = _get(wizard_with_extensions, "/api/ext/demo/ping?q=hello&n=42")
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
    _get(wizard_with_extensions, "/api/ext/demo/ping?q=one&q=two&q=three")
    assert _recorded_calls == [("ping", {"q": "one"})]


@pytest.mark.unit
def test_get_unknown_extension_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard_with_extensions, "/api/ext/missing/ping")
    assert exc.value.code == 404


@pytest.mark.unit
def test_get_unknown_subpath_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard_with_extensions, "/api/ext/demo/nope")
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
        _get(wizard_with_extensions, path)
    assert exc.value.code == 404


@pytest.mark.unit
def test_get_extension_handler_exception_returns_500(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard_with_extensions, "/api/ext/demo/explode")
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
    resp = _post(wizard_with_extensions, "/api/ext/demo/save", {"key": "value"})
    assert resp.status == 200
    body = json.loads(resp.read().decode())
    assert body == {"saved": True, "received": {"key": "value"}}


@pytest.mark.unit
def test_post_extension_route_rejects_missing_csrf(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(wizard_with_extensions, "/api/ext/demo/save", {"key": "v"}, csrf=None)
    assert exc.value.code == 403


@pytest.mark.unit
def test_post_extension_route_rejects_bad_csrf(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            wizard_with_extensions,
            "/api/ext/demo/save",
            {"key": "v"},
            csrf="wrong-token",
        )
    assert exc.value.code == 403


@pytest.mark.unit
def test_post_unknown_extension_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(wizard_with_extensions, "/api/ext/missing/save", {})
    assert exc.value.code == 404


@pytest.mark.unit
def test_post_get_only_subpath_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    """``/api/ext/demo/ping`` is a GET-only route; POSTing must 404."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(wizard_with_extensions, "/api/ext/demo/ping", {})
    assert exc.value.code == 404


# ---------------------------------------------------------------------------
# GET /static/ext/<name>/<filename>
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_static_asset_served_with_correct_content_type(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    resp = _get(wizard_with_extensions, "/static/ext/demo/demo.js")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/javascript")
    assert resp.read() == b"console.log('demo');"


@pytest.mark.unit
def test_static_asset_unknown_filename_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard_with_extensions, "/static/ext/demo/missing.js")
    assert exc.value.code == 404


@pytest.mark.unit
def test_static_asset_unknown_extension_returns_404(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard_with_extensions, "/static/ext/missing/demo.js")
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
        _get(wizard_with_extensions, path)
    assert exc.value.code == 404


@pytest.mark.unit
def test_static_asset_response_carries_security_headers(
    wizard_with_extensions: ConfigureWizard,
) -> None:
    """Extension-served assets inherit the same CSP / X-Frame-Options /
    Cache-Control set the built-in static path applies — they share the
    ``send_bytes`` helper."""
    resp = _get(wizard_with_extensions, "/static/ext/demo/demo.css")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in (resp.headers["Content-Security-Policy"] or "")
