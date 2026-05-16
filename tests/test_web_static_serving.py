"""Static asset serving and path-traversal defense for ``handlers.py``.

The configure UI ships its frontend as bundled static files under
``mureo/_data/web/``. The handler exposes them via
``GET /static/<file>`` — but ONLY filenames on a closed allow-list,
and only when they exist as regular files inside ``wizard.static_dir``.

Security invariants enforced:
* Closed allow-list (``_STATIC_ALLOWLIST``) — no walk of the FS.
* Path traversal via ``..`` / URL-encoded ``%2e%2e`` cannot escape the
  ``static_dir`` prefix (the filename never appears in the allow-list).
* Returned bytes match the bundled asset.
* Content-Type derived from extension via ``_static_content_type``.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mureo.web.handlers import (
    _STATIC_ALLOWLIST,
    _STATIC_CONTENT_TYPES,
    _resolve_static_body,
    _static_content_type,
)
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse


@pytest.fixture
def wizard(tmp_path: Path) -> Iterator[ConfigureWizard]:
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


def _get(wiz: ConfigureWizard, path: str) -> HTTPResponse:
    return urllib.request.urlopen(f"http://127.0.0.1:{wiz.port}{path}", timeout=2.0)


@pytest.mark.unit
class TestStaticAllowList:
    def test_allow_list_is_tuple(self) -> None:
        assert isinstance(_STATIC_ALLOWLIST, tuple)

    def test_allow_list_contains_app_html(self) -> None:
        assert "app.html" in _STATIC_ALLOWLIST

    def test_allow_list_entries_are_pure_filenames(self) -> None:
        for name in _STATIC_ALLOWLIST:
            assert "/" not in name
            assert "\\" not in name
            assert ".." not in name

    def test_allow_list_contains_expected_assets(self) -> None:
        for asset in (
            "app.html",
            "app.css",
            "app.js",
            "landing.js",
            "wizard.js",
            "auth_wizards.js",
            "dashboard.js",
            "i18n.json",
        ):
            assert asset in _STATIC_ALLOWLIST


@pytest.mark.unit
class TestContentTypeMap:
    @pytest.mark.parametrize(
        "filename,expected_prefix",
        [
            ("app.html", "text/html"),
            ("app.css", "text/css"),
            ("app.js", "application/javascript"),
            ("i18n.json", "application/json"),
        ],
    )
    def test_known_extensions_map_to_correct_mime(
        self, filename: str, expected_prefix: str
    ) -> None:
        ct = _static_content_type(filename)
        assert ct.startswith(expected_prefix)

    def test_unknown_extension_falls_back_to_octet_stream(self) -> None:
        assert _static_content_type("file.xyz") == "application/octet-stream"

    def test_all_mapped_extensions_are_present(self) -> None:
        for suffix in (".html", ".css", ".js", ".json", ".svg", ".png", ".ico"):
            assert suffix in _STATIC_CONTENT_TYPES


@pytest.mark.unit
class TestResolveStaticBody:
    def test_unknown_filename_returns_none(self, wizard: ConfigureWizard) -> None:
        assert _resolve_static_body(wizard, "secret.txt") is None

    def test_allowed_filename_returns_bytes(self, wizard: ConfigureWizard) -> None:
        body = _resolve_static_body(wizard, "app.html")
        assert isinstance(body, bytes)
        assert body

    def test_missing_file_returns_none(
        self, wizard: ConfigureWizard, tmp_path: Path
    ) -> None:
        wizard.static_dir = tmp_path / "empty"
        wizard.static_dir.mkdir(exist_ok=True)
        assert _resolve_static_body(wizard, "app.html") is None

    def test_path_traversal_attempt_returns_none(self, wizard: ConfigureWizard) -> None:
        for evil in (
            "../../../etc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "../app.html",
            "subdir/app.html",
            "./app.html",
            "app.html/",
        ):
            assert (
                _resolve_static_body(wizard, evil) is None
            ), f"Path traversal candidate {evil!r} resolved to a body"

    def test_oserror_during_read_returns_none(self, wizard: ConfigureWizard) -> None:
        original = Path.read_bytes

        def _fake_read(self: Path) -> bytes:
            if self.name == "app.html":
                raise OSError("read failed")
            return original(self)

        with patch.object(Path, "read_bytes", _fake_read):
            assert _resolve_static_body(wizard, "app.html") is None


@pytest.mark.unit
class TestServeStaticRoute:
    @pytest.mark.parametrize(
        "asset",
        ["app.html", "app.css", "app.js", "i18n.json"],
    )
    def test_allowed_asset_serves_with_correct_mime(
        self, wizard: ConfigureWizard, asset: str
    ) -> None:
        resp = _get(wizard, f"/static/{asset}")
        assert resp.status == 200
        ct = resp.headers["Content-Type"]
        assert ct == _static_content_type(asset)

    def test_unallowed_filename_returns_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(wizard, "/static/secret.txt")
        assert exc.value.code == 404

    def test_root_dir_traversal_returns_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(
                wizard,
                "/static/" + urllib.parse.quote("../../../etc/passwd"),
            )
        assert exc.value.code == 404

    def test_dotdot_in_path_returns_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(wizard, "/static/..")
        assert exc.value.code == 404

    def test_static_route_includes_security_headers(
        self, wizard: ConfigureWizard
    ) -> None:
        resp = _get(wizard, "/static/app.html")
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'none'" in resp.headers["Content-Security-Policy"]

    def test_static_route_body_is_valid_json(self, wizard: ConfigureWizard) -> None:
        resp = _get(wizard, "/static/i18n.json")
        body = resp.read()
        json.loads(body.decode("utf-8"))

    def test_missing_app_html_returns_404(
        self, wizard: ConfigureWizard, tmp_path: Path
    ) -> None:
        wizard.static_dir = tmp_path / "empty"
        wizard.static_dir.mkdir(exist_ok=True)
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(wizard, "/static/app.css")
        assert exc.value.code == 404


@pytest.mark.unit
class TestStaticContentTypeIsKnown:
    """Every allow-listed asset must map to a known MIME type — if a
    new asset is added without updating ``_STATIC_CONTENT_TYPES`` it
    would silently serve as ``application/octet-stream``, which could
    confuse the browser."""

    @pytest.mark.parametrize("asset", list(_STATIC_ALLOWLIST))
    def test_allow_listed_asset_has_explicit_mime(self, asset: str) -> None:
        ct = _static_content_type(asset)
        assert ct != "application/octet-stream", (
            f"Asset {asset!r} on the allow-list has no explicit MIME — "
            "add an entry to _STATIC_CONTENT_TYPES."
        )
