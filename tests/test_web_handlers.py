"""Route dispatch / Host-header / CSRF gate for ``mureo.web.handlers``.

These tests boot a real ``ConfigureWizard`` on 127.0.0.1:0 in a daemon
thread and exercise every route via ``urllib.request``. Heavy
dependencies (OAuth bridge, install_basic_setup, install_provider,
remove_provider, env_var writer, legacy_commands) are patched so the
test never makes outbound calls or mutates the real filesystem.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path


@pytest.fixture
def wizard(tmp_path: Path) -> Iterator[ConfigureWizard]:
    """Start a ConfigureWizard bound to 127.0.0.1:0."""
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
    extra_headers: dict[str, str] | None = None,
    raw_body: bytes | None = None,
) -> HTTPResponse:
    body = raw_body if raw_body is not None else json.dumps(payload or {}).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if csrf == "use_session":
        headers["X-CSRF-Token"] = wiz.session.csrf_token
    elif csrf is not None:
        headers["X-CSRF-Token"] = csrf
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(_url(wiz, path), data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=2.0)


@pytest.mark.unit
class TestHostHeaderValidation:
    def test_get_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        req = urllib.request.Request(_url(wizard, "/api/csrf"))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403

    def test_post_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({"locale": "ja"}).encode()
        req = urllib.request.Request(
            _url(wizard, "/api/locale"), data=body, method="POST"
        )
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc

    def test_localhost_host_header_accepted(self, wizard: ConfigureWizard) -> None:
        url = f"http://localhost:{wizard.port}/api/csrf"
        resp = urllib.request.urlopen(url, timeout=2.0)
        assert resp.status == 200


@pytest.mark.unit
class TestServeAppHtml:
    def test_root_serves_html(self, wizard: ConfigureWizard) -> None:
        resp = _get(wizard, "/")
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        body = resp.read()
        assert b"<" in body

    def test_index_html_alias(self, wizard: ConfigureWizard) -> None:
        resp = _get(wizard, "/index.html")
        assert resp.status == 200

    def test_missing_app_html_returns_500(
        self, wizard: ConfigureWizard, tmp_path: Path
    ) -> None:
        wizard.static_dir = tmp_path / "empty"
        wizard.static_dir.mkdir(exist_ok=True)
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(wizard, "/")
        assert exc.value.code == 500


@pytest.mark.unit
class TestServeCsrf:
    def test_csrf_endpoint_returns_session_token(self, wizard: ConfigureWizard) -> None:
        resp = _get(wizard, "/api/csrf")
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"csrf_token": wizard.session.csrf_token}


@pytest.mark.unit
class TestServeStatus:
    def test_status_returns_snapshot_keys(self, wizard: ConfigureWizard) -> None:
        resp = _get(wizard, "/api/status")
        body = json.loads(resp.read().decode("utf-8"))
        for key in (
            "host",
            "setup_parts",
            "providers_installed",
            "credentials_present",
            "legacy_commands_present",
        ):
            assert key in body


@pytest.mark.unit
class TestServeAbout:
    """#229 — ``GET /api/about`` returns the version/package payload."""

    def test_about_returns_documented_shape(self, wizard: ConfigureWizard) -> None:
        fake_info = {
            "mureo": {"name": "mureo", "version": "9.9.9"},
            "packages": [
                {"name": "mureo", "version": "9.9.9"},
                {"name": "mureo-agency", "version": "0.1.12"},
            ],
        }
        with patch(
            "mureo.web.handlers.collect_about_info", return_value=fake_info
        ) as mock_collect:
            resp = _get(wizard, "/api/about")
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("application/json")
        body = json.loads(resp.read().decode("utf-8"))
        assert body == fake_info
        mock_collect.assert_called_once()

    def test_about_unmocked_lists_mureo(self, wizard: ConfigureWizard) -> None:
        """Smoke test against the real collector: mureo is always present.

        Deliberately tolerant of extra rows — the machine running the
        suite may have real mureo plugins installed.
        """
        resp = _get(wizard, "/api/about")
        body = json.loads(resp.read().decode("utf-8"))
        assert body["mureo"]["name"] == "mureo"
        names = [pkg["name"] for pkg in body["packages"]]
        assert "mureo" in names
        assert names == sorted(names)

    def test_about_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        """Same Host-header gate as every other GET endpoint."""
        req = urllib.request.Request(_url(wizard, "/api/about"))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPingGet:
    """``GET /api/ping`` — #241 single-instance probe endpoint.

    Unauthenticated (no CSRF — it is a GET), Host-gated like every other
    GET, and exposes only the app name + mureo version. No secrets, no
    paths: a second ``mureo configure`` launch hits it to tell our own
    server apart from a foreign process that grabbed the port.
    """

    def test_ping_returns_app_signature_and_version(
        self, wizard: ConfigureWizard
    ) -> None:
        from mureo import __version__ as expected_version

        resp = _get(wizard, "/api/ping")
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("application/json")
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"app": "mureo-configure", "version": expected_version}

    def test_ping_exposes_only_app_and_version(self, wizard: ConfigureWizard) -> None:
        """Security: the body carries exactly two keys — no secrets/paths."""
        resp = _get(wizard, "/api/ping")
        body = json.loads(resp.read().decode("utf-8"))
        assert set(body.keys()) == {"app", "version"}

    def test_ping_requires_no_csrf(self, wizard: ConfigureWizard) -> None:
        """It is a GET, so no CSRF token is ever supplied — must still 200."""
        resp = _get(wizard, "/api/ping")
        assert resp.status == 200

    def test_ping_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        """Same Host-header gate as every other GET endpoint."""
        req = urllib.request.Request(_url(wizard, "/api/ping"))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestOauthStatusGet:
    def test_known_provider_returns_status(self, wizard: ConfigureWizard) -> None:
        resp = _get(wizard, "/api/oauth/google/status")
        body = json.loads(resp.read().decode("utf-8"))
        assert set(body.keys()) == {"pending", "success", "error"}

    def test_unknown_provider_returns_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(wizard, "/api/oauth/twitter/status")
        assert exc.value.code == 404


@pytest.mark.unit
class TestUnknownRoute:
    def test_get_unknown_returns_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(wizard, "/does-not-exist")
        assert exc.value.code == 404

    def test_post_unknown_returns_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/does-not-exist", {})
        assert exc.value.code == 404


@pytest.mark.unit
class TestPostPreflight:
    def test_post_without_csrf_returns_403(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/locale", {"locale": "ja"}, csrf=None)
        assert exc.value.code == 403

    def test_post_with_wrong_csrf_returns_403(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/locale",
                {"locale": "ja"},
                csrf="not-the-real-token",
            )
        assert exc.value.code == 403

    def test_post_with_empty_csrf_returns_403(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/locale", {"locale": "ja"}, csrf="")
        assert exc.value.code == 403

    def test_post_oversize_body_returns_413(self, wizard: ConfigureWizard) -> None:
        huge = b"a" * (20 * 1024)
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/locale", None, raw_body=huge)
        assert exc.value.code == 413

    def test_post_invalid_json_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/locale", None, raw_body=b"this is not json")
        assert exc.value.code == 400

    def test_post_non_object_json_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/locale", None, raw_body=b"[1,2,3]")
        assert exc.value.code == 400


@pytest.mark.unit
class TestPostLocale:
    @pytest.mark.parametrize("locale", ["en", "ja"])
    def test_known_locale_accepted(self, wizard: ConfigureWizard, locale: str) -> None:
        resp = _post(wizard, "/api/locale", {"locale": locale})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"locale": locale}
        assert wizard.session.locale == locale

    def test_unknown_locale_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/locale", {"locale": "fr"})
        assert exc.value.code == 400

    def test_missing_locale_field_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/locale", {})
        assert exc.value.code == 400


@pytest.mark.unit
class TestPostHost:
    @pytest.mark.parametrize("host", ["claude-code", "claude-desktop"])
    def test_known_host_accepted(self, wizard: ConfigureWizard, host: str) -> None:
        resp = _post(wizard, "/api/host", {"host": host})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"host": host}
        assert wizard.session.host == host

    def test_unknown_host_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/host", {"host": "vscode"})
        assert exc.value.code == 400


@pytest.mark.unit
class TestPostSetupBasic:
    def test_invokes_install_basic_setup(self, wizard: ConfigureWizard) -> None:
        fake_result = {
            "mureo_mcp": {"status": "ok"},
            "auth_hook": {"status": "ok"},
            "skills": {"status": "ok"},
        }
        with patch(
            "mureo.web.handlers.install_basic_setup", return_value=fake_result
        ) as mock_install:
            resp = _post(wizard, "/api/setup/basic", {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == fake_result
        mock_install.assert_called_once()


@pytest.mark.unit
class TestSetupBasicMultiAccountGate:
    """#222 — a multi-account backend must not get the bare ``mureo`` MCP
    entry. Mirrors the #198 account-picker gate: resolve the capability
    ONLY in production (``home is None``); a home-injected (sandboxed)
    wizard must never consult the process-global factory."""

    def test_skip_mcp_false_when_home_injected(self, wizard: ConfigureWizard) -> None:
        with (
            patch("mureo.web.handlers.runtime_multi_account_auth", return_value=True),
            patch(
                "mureo.web.handlers.install_basic_setup",
                return_value={"mureo_mcp": {"status": "ok"}},
            ) as mock_install,
        ):
            _post(wizard, "/api/setup/basic", {})
        assert mock_install.call_args.kwargs["skip_mcp_registration"] is False

    def test_skip_mcp_true_when_home_none(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "runtime" / "credentials.json"
        with patch(
            "mureo.web.server.runtime_credentials_path", lambda _default: sentinel
        ):
            wiz = ConfigureWizard(home=None)
        thread = threading.Thread(target=wiz.serve, daemon=True)
        thread.start()
        wiz.wait_until_ready(timeout=5.0)
        try:
            with (
                patch(
                    "mureo.web.handlers.runtime_multi_account_auth",
                    return_value=True,
                ),
                patch(
                    "mureo.web.handlers.install_basic_setup",
                    return_value={"mureo_mcp": {"status": "skipped"}},
                ) as mock_install,
            ):
                _post(wiz, "/api/setup/basic", {})
            assert mock_install.call_args.kwargs["skip_mcp_registration"] is True
        finally:
            wiz.shutdown()
            thread.join(timeout=2.0)


@pytest.mark.unit
class TestServeStatusMultiAccount:
    """#222 — ``GET /api/status`` surfaces ``multi_account_auth`` behind the
    same ``home is None`` gate so the UI can suppress the MCP section."""

    def test_status_false_when_home_injected(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.runtime_multi_account_auth", return_value=True):
            resp = _get(wizard, "/api/status")
        body = json.loads(resp.read().decode("utf-8"))
        assert body["multi_account_auth"] is False

    def test_status_true_when_home_none(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "runtime" / "credentials.json"
        with patch(
            "mureo.web.server.runtime_credentials_path", lambda _default: sentinel
        ):
            wiz = ConfigureWizard(home=None)
        thread = threading.Thread(target=wiz.serve, daemon=True)
        thread.start()
        wiz.wait_until_ready(timeout=5.0)
        try:
            with patch(
                "mureo.web.handlers.runtime_multi_account_auth", return_value=True
            ):
                resp = _get(wiz, "/api/status")
            body = json.loads(resp.read().decode("utf-8"))
            assert body["multi_account_auth"] is True
        finally:
            wiz.shutdown()
            thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Session-host propagation into setup_actions (planner HANDOFF
# feat-web-config-ui-phase1-desktop-host.md, Q5). The 5 setup handler
# methods must read ``self.wizard.session.host`` and pass it as the new
# ``host=`` kwarg into setup_actions. ``host`` defaults to "claude-code"
# everywhere, so a session with no explicit host keeps today's behaviour.
# setup_actions is mocked at the handler's imported symbol so no real FS
# write occurs; we assert only the propagated ``host`` kwarg.
# ---------------------------------------------------------------------------


def _set_host(wiz: ConfigureWizard, host: str) -> None:
    """Drive ``POST /api/host`` so the session host is set the real way."""
    resp = _post(wiz, "/api/host", {"host": host})
    body = json.loads(resp.read().decode("utf-8"))
    assert body == {"host": host}


def _host_kwarg(mock: MagicMock) -> Any:
    """Extract the propagated ``host`` (kwarg or trailing positional)."""
    kwargs = mock.call_args.kwargs
    if "host" in kwargs:
        return kwargs["host"]
    return None


@pytest.mark.unit
class TestSetupBasicHostPropagation:
    """``POST /api/setup/basic`` forwards the session host."""

    ROUTE = "/api/setup/basic"

    def test_default_session_uses_claude_code(self, wizard: ConfigureWizard) -> None:
        """No explicit host set → handler passes ``host="claude-code"``."""
        with patch(
            "mureo.web.handlers.install_basic_setup",
            return_value={"mureo_mcp": {"status": "ok"}},
        ) as mock_install:
            _post(wizard, self.ROUTE, {})

        assert _host_kwarg(mock_install) == "claude-code"

    def test_desktop_session_propagates_desktop_host(
        self, wizard: ConfigureWizard
    ) -> None:
        """Session host = claude-desktop → ``host="claude-desktop"``
        forwarded into ``install_basic_setup``."""
        _set_host(wizard, "claude-desktop")
        with patch(
            "mureo.web.handlers.install_basic_setup",
            return_value={"mureo_mcp": {"status": "ok"}},
        ) as mock_install:
            _post(wizard, self.ROUTE, {})

        assert _host_kwarg(mock_install) == "claude-desktop"

    def test_home_still_propagated_alongside_host(
        self, wizard: ConfigureWizard
    ) -> None:
        """Adding ``host`` must not drop the existing ``home`` kwarg."""
        with patch(
            "mureo.web.handlers.install_basic_setup",
            return_value={},
        ) as mock_install:
            _post(wizard, self.ROUTE, {})

        assert mock_install.call_args.kwargs.get("home") == wizard.home


@pytest.mark.unit
class TestSetupBasicClearHostPropagation:
    """``POST /api/setup/basic/clear`` forwards the session host."""

    ROUTE = "/api/setup/basic/clear"

    def test_default_session_uses_claude_code(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.clear_all_setup", return_value={}) as mock_clear:
            _post(wizard, self.ROUTE, {})

        assert _host_kwarg(mock_clear) == "claude-code"

    def test_desktop_session_propagates_desktop_host(
        self, wizard: ConfigureWizard
    ) -> None:
        _set_host(wizard, "claude-desktop")
        with patch("mureo.web.handlers.clear_all_setup", return_value={}) as mock_clear:
            _post(wizard, self.ROUTE, {})

        assert _host_kwarg(mock_clear) == "claude-desktop"

    def test_home_still_propagated_alongside_host(
        self, wizard: ConfigureWizard
    ) -> None:
        with patch("mureo.web.handlers.clear_all_setup", return_value={}) as mock_clear:
            _post(wizard, self.ROUTE, {})

        assert mock_clear.call_args.kwargs.get("home") == wizard.home


@pytest.mark.unit
class TestSetupRemoveRoutesHostPropagation:
    """``/api/setup/{mcp,hook,skills}/remove`` forward the session host."""

    def test_mcp_remove_default_host(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_mureo_mcp", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/setup/mcp/remove", {})

        assert _host_kwarg(mock_remove) == "claude-code"

    def test_mcp_remove_desktop_host(self, wizard: ConfigureWizard) -> None:
        _set_host(wizard, "claude-desktop")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_mureo_mcp", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/setup/mcp/remove", {})

        assert _host_kwarg(mock_remove) == "claude-desktop"

    def test_hook_remove_desktop_host(self, wizard: ConfigureWizard) -> None:
        _set_host(wizard, "claude-desktop")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "noop"}
        with patch(
            "mureo.web.handlers.remove_auth_hook", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/setup/hook/remove", {})

        assert _host_kwarg(mock_remove) == "claude-desktop"

    def test_skills_remove_desktop_host(self, wizard: ConfigureWizard) -> None:
        _set_host(wizard, "claude-desktop")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_workflow_skills", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/setup/skills/remove", {})

        assert _host_kwarg(mock_remove) == "claude-desktop"


@pytest.mark.unit
class TestPostProviders:
    def test_install_provider_requires_provider_id(
        self, wizard: ConfigureWizard
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/providers/install", {})
        assert exc.value.code == 400

    def test_install_provider_dispatches(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "p1"}
        with patch(
            "mureo.web.handlers.install_provider", return_value=fake
        ) as mock_install:
            resp = _post(wizard, "/api/providers/install", {"provider_id": "p1"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "detail": "p1"}
        # ``home``/``host`` are now forwarded (provider-host change); the
        # provider_id stays the first positional arg.
        mock_install.assert_called_once()
        assert mock_install.call_args.args[0] == "p1"

    def test_hosted_status_dispatches(self, wizard: ConfigureWizard) -> None:
        with patch(
            "mureo.web.handlers.hosted_provider_status",
            return_value={"meta-ads-official": True},
        ) as mock_hosted:
            resp = _post(wizard, "/api/providers/hosted-status", {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"hosted_connected": {"meta-ads-official": True}}
        mock_hosted.assert_called_once()

    def test_native_toggle_dispatches(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "google_ads"}
        with patch(
            "mureo.web.handlers.set_native_preference", return_value=fake
        ) as mock_fn:
            resp = _post(
                wizard,
                "/api/providers/native-toggle",
                {"platform": "google_ads", "prefer_official": True},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "detail": "google_ads"}
        mock_fn.assert_called_once()
        args, kwargs = mock_fn.call_args
        assert args[0] == "google_ads"
        assert args[1] is True
        assert kwargs["home"] == wizard.home
        assert kwargs["host"] == wizard.session.host

    def test_native_toggle_requires_platform(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/providers/native-toggle", {"platform": ""})
        assert exc.value.code == 400

    def test_remove_provider_requires_provider_id(
        self, wizard: ConfigureWizard
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/providers/remove", {"provider_id": ""})
        assert exc.value.code == 400

    def test_remove_provider_dispatches(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "p1"}
        with patch(
            "mureo.web.handlers.remove_provider", return_value=fake
        ) as mock_remove:
            resp = _post(wizard, "/api/providers/remove", {"provider_id": "p1"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "detail": "p1"}
        # ``home``/``host`` are now forwarded (provider-host change); the
        # provider_id stays the first positional arg.
        mock_remove.assert_called_once()
        assert mock_remove.call_args.args[0] == "p1"


# ---------------------------------------------------------------------------
# Provider install/remove must forward the SESSION HOST (planner HANDOFF
# feat-web-config-ui-phase1-provider-host.md L25): ``_post_providers_install``
# / ``_post_providers_remove`` read ``self.wizard.session.host`` and pass it
# as the new ``host=`` kwarg into ``install_provider`` / ``remove_provider``
# (with ``home=self.wizard.home``). ``host`` defaults to "claude-code" so a
# session with no explicit host keeps today's behaviour. RED until the
# handler forwards these kwargs.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostProvidersHostPropagation:
    def test_install_default_session_uses_claude_code(
        self, wizard: ConfigureWizard
    ) -> None:
        """No explicit host → ``install_provider`` gets
        ``host="claude-code"``."""
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.install_provider", return_value=fake
        ) as mock_install:
            _post(wizard, "/api/providers/install", {"provider_id": "p1"})

        assert _host_kwarg(mock_install) == "claude-code"

    def test_install_desktop_session_propagates_desktop_host(
        self, wizard: ConfigureWizard
    ) -> None:
        _set_host(wizard, "claude-desktop")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.install_provider", return_value=fake
        ) as mock_install:
            _post(wizard, "/api/providers/install", {"provider_id": "p1"})

        assert _host_kwarg(mock_install) == "claude-desktop"

    def test_install_propagates_home_alongside_host(
        self, wizard: ConfigureWizard
    ) -> None:
        """Adding ``host`` must not drop ``home=self.wizard.home``."""
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.install_provider", return_value=fake
        ) as mock_install:
            _post(wizard, "/api/providers/install", {"provider_id": "p1"})

        assert mock_install.call_args.kwargs.get("home") == wizard.home

    def test_install_still_passes_provider_id(self, wizard: ConfigureWizard) -> None:
        """The provider_id remains the first positional arg."""
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.install_provider", return_value=fake
        ) as mock_install:
            _post(wizard, "/api/providers/install", {"provider_id": "p1"})

        assert mock_install.call_args.args[0] == "p1"

    def test_remove_default_session_uses_claude_code(
        self, wizard: ConfigureWizard
    ) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_provider", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/providers/remove", {"provider_id": "p1"})

        assert _host_kwarg(mock_remove) == "claude-code"

    def test_remove_desktop_session_propagates_desktop_host(
        self, wizard: ConfigureWizard
    ) -> None:
        _set_host(wizard, "claude-desktop")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_provider", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/providers/remove", {"provider_id": "p1"})

        assert _host_kwarg(mock_remove) == "claude-desktop"

    def test_remove_propagates_home_alongside_host(
        self, wizard: ConfigureWizard
    ) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_provider", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/providers/remove", {"provider_id": "p1"})

        assert mock_remove.call_args.kwargs.get("home") == wizard.home

    def test_remove_still_passes_provider_id(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_provider", return_value=fake
        ) as mock_remove:
            _post(wizard, "/api/providers/remove", {"provider_id": "p1"})

        assert mock_remove.call_args.args[0] == "p1"


@pytest.mark.unit
class TestPostEnvVar:
    def test_disallowed_name_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/credentials/env-var",
                {"name": "EVIL_VAR", "value": "x"},
            )
        assert exc.value.code == 400

    def test_empty_value_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/credentials/env-var",
                {"name": "GOOGLE_ADS_DEVELOPER_TOKEN", "value": ""},
            )
        assert exc.value.code == 400

    def test_success_does_not_echo_value(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.write_credential_env_var") as mock_write:
            resp = _post(
                wizard,
                "/api/credentials/env-var",
                {
                    "name": "GOOGLE_ADS_DEVELOPER_TOKEN",
                    "value": "secret_token_xxx",
                },
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "name": "GOOGLE_ADS_DEVELOPER_TOKEN"}
        assert "secret_token_xxx" not in json.dumps(body)
        mock_write.assert_called_once()

    def test_section_passed_through_to_writer(self, wizard: ConfigureWizard) -> None:
        """#102 B2: an optional ``section`` routes a shared env name to the
        right credentials.json section (Google Ads service-account path uses
        the shared GOOGLE_APPLICATION_CREDENTIALS name but section google_ads)."""
        with patch("mureo.web.handlers.write_credential_env_var") as mock_write:
            resp = _post(
                wizard,
                "/api/credentials/env-var",
                {
                    "name": "GOOGLE_APPLICATION_CREDENTIALS",
                    "value": "/p/ads-sa.json",
                    "section": "google_ads",
                },
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {
            "status": "ok",
            "name": "GOOGLE_APPLICATION_CREDENTIALS",
        }
        assert mock_write.call_args.kwargs["section"] == "google_ads"

    def test_omitted_section_passes_none(self, wizard: ConfigureWizard) -> None:
        """No ``section`` in the payload → writer called with section=None
        (canonical 1:1 binding, unchanged behaviour)."""
        with patch("mureo.web.handlers.write_credential_env_var") as mock_write:
            _post(
                wizard,
                "/api/credentials/env-var",
                {"name": "GOOGLE_ADS_DEVELOPER_TOKEN", "value": "x"},
            )
        assert mock_write.call_args.kwargs["section"] is None

    def test_write_failure_value_error_returns_400(
        self, wizard: ConfigureWizard
    ) -> None:
        with patch(
            "mureo.web.handlers.write_credential_env_var",
            side_effect=ValueError("bad"),
        ):
            with pytest.raises(urllib.error.HTTPError) as exc:
                _post(
                    wizard,
                    "/api/credentials/env-var",
                    {
                        "name": "GOOGLE_ADS_DEVELOPER_TOKEN",
                        "value": "x",
                    },
                )
            assert exc.value.code == 400

    def test_write_failure_other_returns_500(self, wizard: ConfigureWizard) -> None:
        with patch(
            "mureo.web.handlers.write_credential_env_var",
            side_effect=RuntimeError("disk full"),
        ):
            with pytest.raises(urllib.error.HTTPError) as exc:
                _post(
                    wizard,
                    "/api/credentials/env-var",
                    {
                        "name": "GOOGLE_ADS_DEVELOPER_TOKEN",
                        "value": "x",
                    },
                )
            assert exc.value.code == 500

    def test_ga4_write_refused_under_multi_account(
        self, wizard: ConfigureWizard
    ) -> None:
        # #442: GA4 auth is a single service account. Under a multi-account
        # backend, writing it into the shared credentials.json would let one SA
        # reach every account/property -- refuse it (mirrors Search Console's
        # multi-account fail-closed). The write must NOT be attempted.
        with (
            patch(
                "mureo.web.handlers.ConfigureHandler._multi_account_active",
                return_value=True,
            ),
            patch("mureo.web.handlers.write_credential_env_var") as mock_write,
        ):
            with pytest.raises(urllib.error.HTTPError) as exc:
                _post(
                    wizard,
                    "/api/credentials/env-var",
                    {"name": "GOOGLE_APPLICATION_CREDENTIALS", "value": "/p/sa.json"},
                )
            assert exc.value.code == 403
        mock_write.assert_not_called()

    def test_ga4_project_id_refused_under_multi_account(
        self, wizard: ConfigureWizard
    ) -> None:
        with (
            patch(
                "mureo.web.handlers.ConfigureHandler._multi_account_active",
                return_value=True,
            ),
            patch("mureo.web.handlers.write_credential_env_var") as mock_write,
        ):
            with pytest.raises(urllib.error.HTTPError) as exc:
                _post(
                    wizard,
                    "/api/credentials/env-var",
                    {"name": "GOOGLE_PROJECT_ID", "value": "proj-1"},
                )
            assert exc.value.code == 403
        mock_write.assert_not_called()

    def test_google_ads_sa_path_allowed_under_multi_account(
        self, wizard: ConfigureWizard
    ) -> None:
        # The GA4 guard keys off the EFFECTIVE section, not the env NAME:
        # GOOGLE_APPLICATION_CREDENTIALS is shared with google_ads, whose
        # service-account path (section="google_ads") must still be writable.
        with (
            patch(
                "mureo.web.handlers.ConfigureHandler._multi_account_active",
                return_value=True,
            ),
            patch("mureo.web.handlers.write_credential_env_var") as mock_write,
        ):
            resp = _post(
                wizard,
                "/api/credentials/env-var",
                {
                    "name": "GOOGLE_APPLICATION_CREDENTIALS",
                    "value": "/p/ads-sa.json",
                    "section": "google_ads",
                },
            )
        assert json.loads(resp.read().decode("utf-8"))["status"] == "ok"
        mock_write.assert_called_once()

    def test_ga4_write_allowed_when_not_multi_account(
        self, wizard: ConfigureWizard
    ) -> None:
        # Standalone OSS (no multi-account backend): the GA4 wizard writes
        # exactly as before -- the guard must not regress the single-tenant path.
        with patch("mureo.web.handlers.write_credential_env_var") as mock_write:
            resp = _post(
                wizard,
                "/api/credentials/env-var",
                {"name": "GOOGLE_APPLICATION_CREDENTIALS", "value": "/p/sa.json"},
            )
        assert json.loads(resp.read().decode("utf-8"))["status"] == "ok"
        mock_write.assert_called_once()


@pytest.mark.unit
class TestPostCredentialsRemove:
    def test_removes_present_section(self, wizard: ConfigureWizard) -> None:
        creds = wizard.host_paths.credentials_path
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text(
            json.dumps(
                {
                    "google_ads": {"developer_token": "X"},
                    "meta_ads": {"access_token": "Y"},
                }
            ),
            encoding="utf-8",
        )
        resp = _post(wizard, "/api/credentials/remove", {"section": "google_ads"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "section": "google_ads"}
        payload = json.loads(creds.read_text(encoding="utf-8"))
        assert "google_ads" not in payload
        assert payload["meta_ads"] == {"access_token": "Y"}

    def test_absent_section_is_noop(self, wizard: ConfigureWizard) -> None:
        creds = wizard.host_paths.credentials_path
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text(
            json.dumps({"meta_ads": {"access_token": "Y"}}), encoding="utf-8"
        )
        resp = _post(wizard, "/api/credentials/remove", {"section": "google_ads"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "noop", "section": "google_ads"}
        assert json.loads(creds.read_text(encoding="utf-8")) == {
            "meta_ads": {"access_token": "Y"}
        }


@pytest.mark.unit
class TestPostShutdown:
    def test_materializes_empty_credentials_file(self, wizard: ConfigureWizard) -> None:
        """#210: finishing the wizard writes an empty credentials file at
        the runtime write path so the filesystem records 'setup completed'
        even when every platform was skipped (no OAuth ran)."""
        creds = wizard.host_paths.credentials_path
        assert not creds.exists()
        resp = _post(wizard, "/api/shutdown", {})
        assert json.loads(resp.read().decode("utf-8")) == {"status": "stopping"}
        assert creds.exists()
        assert json.loads(creds.read_text(encoding="utf-8")) == {}

    def test_does_not_clobber_existing_credentials(
        self, wizard: ConfigureWizard
    ) -> None:
        creds = wizard.host_paths.credentials_path
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text(
            json.dumps({"meta_ads": {"access_token": "Y"}}), encoding="utf-8"
        )
        _post(wizard, "/api/shutdown", {})
        assert json.loads(creds.read_text(encoding="utf-8")) == {
            "meta_ads": {"access_token": "Y"}
        }

    def test_disallowed_section_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/credentials/remove",
                {"section": "search_console"},
            )
        assert exc.value.code == 400

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/credentials/remove",
                {"section": "google_ads"},
                csrf=False,
            )
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostLegacyCleanup:
    def test_returns_removed_list(self, wizard: ConfigureWizard) -> None:
        with patch(
            "mureo.web.handlers.remove_legacy_commands",
            return_value=["onboard.md"],
        ) as mock_remove:
            resp = _post(wizard, "/api/legacy/cleanup", {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"removed": ["onboard.md"]}
        mock_remove.assert_called_once()

    def test_returns_empty_when_nothing_to_remove(
        self, wizard: ConfigureWizard
    ) -> None:
        with patch("mureo.web.handlers.remove_legacy_commands", return_value=[]):
            resp = _post(wizard, "/api/legacy/cleanup", {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"removed": []}


@pytest.mark.unit
class TestPostOauthStart:
    def test_known_provider_returns_url(self, wizard: ConfigureWizard) -> None:
        fake_result = MagicMock()
        fake_result.as_dict.return_value = {
            "url": "https://example.com/oauth",
            "redirect_url": "https://example.com/oauth",
            "state": "pending",
            "provider": "google",
        }
        with patch.object(
            wizard.oauth_bridge, "start", return_value=fake_result
        ) as mock_start:
            resp = _post(wizard, "/api/oauth/google/start", {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["url"] == "https://example.com/oauth"
        mock_start.assert_called_once()
        status = wizard.session.get_oauth_status("google")
        assert status["pending"] is True

    def test_unknown_provider_returns_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/oauth/twitter/start", {})
        assert exc.value.code == 404

    def test_bridge_value_error_returns_400(self, wizard: ConfigureWizard) -> None:
        with patch.object(wizard.oauth_bridge, "start", side_effect=ValueError("nope")):
            with pytest.raises(urllib.error.HTTPError) as exc:
                _post(wizard, "/api/oauth/google/start", {})
            assert exc.value.code == 400

    def test_multi_account_suppressed_when_home_injected(
        self, wizard: ConfigureWizard
    ) -> None:
        """SAFETY (#195/#198): a home-injected wizard must NEVER enable
        multi-account auth, even when the process-global factory
        advertises it — that factory's store lives outside the injected
        sandbox (in dev/CI it resolves against the operator's real
        ~/.mureo). The ``home is None`` gate forces the flag to ``False``
        so a sandboxed wizard cannot inherit real-backend behavior."""
        fake_result = MagicMock()
        fake_result.as_dict.return_value = {"state": "pending", "provider": "google"}
        with (
            patch("mureo.web.handlers.runtime_multi_account_auth", return_value=True),
            patch.object(
                wizard.oauth_bridge, "start", return_value=fake_result
            ) as mock_start,
        ):
            _post(wizard, "/api/oauth/google/start", {})
        assert mock_start.call_args.kwargs["multi_account_auth"] is False

    def test_multi_account_forwarded_when_home_none(self, tmp_path: Path) -> None:
        """Production path (``home is None``): the handler resolves the
        multi-account capability and forwards it to the bridge.
        ``runtime_credentials_path`` is patched to a tmp sentinel so
        constructing the home=None wizard never resolves the real factory
        or touches the operator's ~/.mureo."""
        sentinel = tmp_path / "runtime" / "credentials.json"
        with patch(
            "mureo.web.server.runtime_credentials_path", lambda _default: sentinel
        ):
            wiz = ConfigureWizard(home=None)
        thread = threading.Thread(target=wiz.serve, daemon=True)
        thread.start()
        wiz.wait_until_ready(timeout=5.0)
        try:
            fake_result = MagicMock()
            fake_result.as_dict.return_value = {
                "state": "pending",
                "provider": "google",
            }
            with (
                patch(
                    "mureo.web.handlers.runtime_multi_account_auth", return_value=True
                ),
                patch.object(
                    wiz.oauth_bridge, "start", return_value=fake_result
                ) as mock_start,
            ):
                _post(wiz, "/api/oauth/google/start", {})
            assert mock_start.call_args.kwargs["multi_account_auth"] is True
        finally:
            wiz.shutdown()
            thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Dashboard uninstall routes (planner HANDOFF
# feat-web-config-ui-phase1-uninstall.md). Four new CSRF + Host gated
# POST endpoints. The remove wrappers themselves are tested in
# test_web_setup_actions_remove.py; here we pin only the route layer.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostSetupMcpRemove:
    """``POST /api/setup/mcp/remove`` — uninstall the mureo MCP block."""

    ROUTE = "/api/setup/mcp/remove"

    def test_ok_dispatches_to_remove_mureo_mcp(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "/tmp/settings.json"}
        with patch(
            "mureo.web.handlers.remove_mureo_mcp", return_value=fake
        ) as mock_remove:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "detail": "/tmp/settings.json"}
        mock_remove.assert_called_once()

    def test_noop_envelope_when_already_removed(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "noop"}
        with patch("mureo.web.handlers.remove_mureo_mcp", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "noop"}

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        """Acceptance criteria L150-L153."""
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf="not-the-real-token")
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        """Acceptance criteria L148-L150 — Host header gate."""
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestPostSetupHookRemove:
    """``POST /api/setup/hook/remove`` — uninstall the credential-guard hook."""

    ROUTE = "/api/setup/hook/remove"

    def test_ok_dispatches_to_remove_auth_hook(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.remove_auth_hook", return_value=fake
        ) as mock_remove:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok"}
        mock_remove.assert_called_once()

    def test_noop_envelope_when_already_removed(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "noop"}
        with patch("mureo.web.handlers.remove_auth_hook", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "noop"}

    def test_error_envelope_surfaces_to_client(self, wizard: ConfigureWizard) -> None:
        """The wrapper catches its own exceptions and returns
        ``ActionResult(status="error")``; the route MUST surface this as
        a 200 envelope (not a 500). 500 is reserved for genuine route
        bugs."""
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "error", "detail": "OSError"}
        with patch("mureo.web.handlers.remove_auth_hook", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "error", "detail": "OSError"}

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestPostSetupSkillsRemove:
    """``POST /api/setup/skills/remove`` — uninstall workflow skills."""

    ROUTE = "/api/setup/skills/remove"

    def test_ok_dispatches_to_remove_workflow_skills(
        self, wizard: ConfigureWizard
    ) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "removed 15 skills"}
        with patch(
            "mureo.web.handlers.remove_workflow_skills", return_value=fake
        ) as mock_remove:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "detail": "removed 15 skills"}
        mock_remove.assert_called_once()

    def test_noop_envelope_when_nothing_to_remove(
        self, wizard: ConfigureWizard
    ) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "noop"}
        with patch("mureo.web.handlers.remove_workflow_skills", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "noop"}

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf="bad")
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "evil.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostSetupHookInstall:
    """``POST /api/setup/hook/install`` — (re)install the credential-guard
    hook without re-running the full basic-setup wizard."""

    ROUTE = "/api/setup/hook/install"

    def test_ok_dispatches_to_install_auth_hook(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "written"}
        with patch(
            "mureo.web.handlers.install_auth_hook", return_value=fake
        ) as mock_install:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "detail": "written"}
        mock_install.assert_called_once()

    def test_noop_envelope_when_already_installed(
        self, wizard: ConfigureWizard
    ) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "noop"}
        with patch("mureo.web.handlers.install_auth_hook", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "noop"}

    def test_error_envelope_surfaces_to_client(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "error", "detail": "OSError"}
        with patch("mureo.web.handlers.install_auth_hook", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "error", "detail": "OSError"}

    def test_forwards_client_host_and_home(self, wizard: ConfigureWizard) -> None:
        """The client-authoritative payload host must reach the install
        function (the desync ``_resolve_host`` exists to prevent), along
        with the session home."""
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.install_auth_hook", return_value=fake
        ) as mock_install:
            _post(wizard, self.ROUTE, {"host": "codex"})
        _, kwargs = mock_install.call_args
        assert kwargs["host"] == "codex"
        assert kwargs["home"] == wizard.home

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostSetupSkillsInstall:
    """``POST /api/setup/skills/install`` — (re)install workflow skills
    without re-running the full basic-setup wizard."""

    ROUTE = "/api/setup/skills/install"

    def test_ok_dispatches_to_install_workflow_skills(
        self, wizard: ConfigureWizard
    ) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "installed 15 skills"}
        with patch(
            "mureo.web.handlers.install_workflow_skills", return_value=fake
        ) as mock_install:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "detail": "installed 15 skills"}
        mock_install.assert_called_once()

    def test_error_envelope_surfaces_to_client(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "error", "detail": "OSError"}
        with patch("mureo.web.handlers.install_workflow_skills", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "error", "detail": "OSError"}

    def test_forwards_client_host_and_home(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.install_workflow_skills", return_value=fake
        ) as mock_install:
            _post(wizard, self.ROUTE, {"host": "codex"})
        _, kwargs = mock_install.call_args
        assert kwargs["host"] == "codex"
        assert kwargs["home"] == wizard.home

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf="bad")
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "evil.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


# ---------------------------------------------------------------------------
# Dashboard demo + byod routes (planner HANDOFF
# feat-web-config-ui-phase1-demo-byod.md). 6 new endpoints:
#   GET  /api/demo/scenarios   (Host-gated only, no CSRF for GET)
#   POST /api/demo/init        (CSRF + Host gated)
#   GET  /api/byod/status      (Host-gated only)
#   POST /api/byod/import      (CSRF + Host gated)
#   POST /api/byod/remove      (CSRF + Host gated)
#   POST /api/byod/clear       (CSRF + Host gated)
# The demo_actions / byod_actions wrappers themselves are tested in
# test_web_demo_actions.py / test_web_byod_actions.py; here we pin only
# the route layer (dispatch, gating, payload validation, JSON shape).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDemoScenarios:
    """``GET /api/demo/scenarios`` — list registered demo scenarios."""

    ROUTE = "/api/demo/scenarios"

    def test_returns_scenarios_payload(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "ok",
            "scenarios": [
                {
                    "name": "seasonality-trap",
                    "title": "T",
                    "blurb": "B",
                    "default": True,
                },
            ],
        }
        with patch(
            "mureo.web.handlers.list_demo_scenarios", return_value=fake
        ) as mock_list:
            resp = _get(wizard, self.ROUTE)
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert body["scenarios"][0]["name"] == "seasonality-trap"
        mock_list.assert_called_once()

    def test_get_does_not_require_csrf(self, wizard: ConfigureWizard) -> None:
        """GET routes are Host-gated only per existing pattern."""
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "scenarios": []}
        with patch("mureo.web.handlers.list_demo_scenarios", return_value=fake):
            resp = _get(wizard, self.ROUTE)
        assert resp.status == 200

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        req = urllib.request.Request(_url(wizard, self.ROUTE))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostDemoInit:
    """``POST /api/demo/init`` — scaffold a demo workspace."""

    ROUTE = "/api/demo/init"

    def test_dispatches_to_init_demo(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "ok",
            "created_path": "/tmp/mureo-demo",
            "imported": True,
        }
        with patch("mureo.web.handlers.init_demo", return_value=fake) as mock_init:
            resp = _post(
                wizard,
                self.ROUTE,
                {
                    "scenario_name": "seasonality-trap",
                    "target": "/tmp/mureo-demo",
                    "force": False,
                    "skip_import": False,
                },
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert body["created_path"] == "/tmp/mureo-demo"
        mock_init.assert_called_once()

    def test_missing_target_returns_400(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.init_demo") as mock_init:
            with pytest.raises(urllib.error.HTTPError) as exc:
                _post(
                    wizard,
                    self.ROUTE,
                    {"scenario_name": "seasonality-trap"},
                )
            assert exc.value.code == 400
        mock_init.assert_not_called()

    def test_error_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        """The wrapper catches its own exceptions and returns an
        ``error`` envelope; the route surfaces it as 200, not 500."""
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "error",
            "detail": "DemoInitError",
        }
        with patch("mureo.web.handlers.init_demo", return_value=fake):
            resp = _post(
                wizard,
                self.ROUTE,
                {
                    "scenario_name": "seasonality-trap",
                    "target": "/tmp/x",
                },
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "error"

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                self.ROUTE,
                {"scenario_name": "x", "target": "/tmp/x"},
                csrf=None,
            )
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                self.ROUTE,
                {"scenario_name": "x", "target": "/tmp/x"},
                csrf="bad",
            )
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({"scenario_name": "x", "target": "/tmp/x"}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestGetByodStatus:
    """``GET /api/byod/status`` — per-platform byod/live status."""

    ROUTE = "/api/byod/status"

    def test_returns_status_payload(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "ok",
            "platforms": [
                {
                    "platform": "google_ads",
                    "mode": "byod",
                    "rows": 10,
                    "date_range": {
                        "start": "2026-01-01",
                        "end": "2026-01-31",
                    },
                },
                {"platform": "meta_ads", "mode": "live"},
            ],
        }
        with patch("mureo.web.handlers.byod_status", return_value=fake) as mock_status:
            resp = _get(wizard, self.ROUTE)
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert {p["platform"] for p in body["platforms"]} == {
            "google_ads",
            "meta_ads",
        }
        mock_status.assert_called_once()

    def test_get_does_not_require_csrf(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "platforms": []}
        with patch("mureo.web.handlers.byod_status", return_value=fake):
            resp = _get(wizard, self.ROUTE)
        assert resp.status == 200

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        req = urllib.request.Request(_url(wizard, self.ROUTE))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostByodImport:
    """``POST /api/byod/import`` — import a Sheet bundle XLSX."""

    ROUTE = "/api/byod/import"

    def test_dispatches_to_byod_import(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "ok",
            "platforms": {"google_ads": {"rows": 42}},
        }
        with patch("mureo.web.handlers.byod_import", return_value=fake) as mock_imp:
            resp = _post(
                wizard,
                self.ROUTE,
                {"file_path": "/tmp/bundle.xlsx", "replace": False},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        mock_imp.assert_called_once()

    def test_missing_file_path_returns_400(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.byod_import") as mock_imp:
            with pytest.raises(urllib.error.HTTPError) as exc:
                _post(wizard, self.ROUTE, {"replace": True})
            assert exc.value.code == 400
        mock_imp.assert_not_called()

    def test_validation_error_envelope_surfaces_as_200(
        self, wizard: ConfigureWizard
    ) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "error",
            "detail": "not_xlsx",
        }
        with patch("mureo.web.handlers.byod_import", return_value=fake):
            resp = _post(
                wizard,
                self.ROUTE,
                {"file_path": "/tmp/data.csv", "replace": False},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "error"

    def test_does_not_echo_file_bytes(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "platforms": {}}
        with patch("mureo.web.handlers.byod_import", return_value=fake):
            resp = _post(
                wizard,
                self.ROUTE,
                {"file_path": "/tmp/bundle.xlsx", "replace": False},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert "PK\x03\x04" not in json.dumps(body)

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                self.ROUTE,
                {"file_path": "/tmp/b.xlsx"},
                csrf=None,
            )
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({"file_path": "/tmp/b.xlsx"}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestPostByodRemove:
    """``POST /api/byod/remove`` — drop one platform's BYOD data."""

    ROUTE = "/api/byod/remove"

    def test_dispatches_to_byod_remove(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "google_ads"}
        with patch("mureo.web.handlers.byod_remove", return_value=fake) as mock_rm:
            resp = _post(
                wizard,
                self.ROUTE,
                {"google_ads": True, "meta_ads": False},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        mock_rm.assert_called_once()

    def test_error_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "error",
            "detail": "select exactly one",
        }
        with patch("mureo.web.handlers.byod_remove", return_value=fake):
            resp = _post(
                wizard,
                self.ROUTE,
                {"google_ads": True, "meta_ads": True},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "error"

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                self.ROUTE,
                {"google_ads": True},
                csrf=None,
            )
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({"google_ads": True}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestPostByodClear:
    """``POST /api/byod/clear`` — wipe all BYOD data."""

    ROUTE = "/api/byod/clear"

    def test_dispatches_to_byod_clear(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch("mureo.web.handlers.byod_clear", return_value=fake) as mock_clear:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        mock_clear.assert_called_once()

    def test_noop_envelope_when_nothing_present(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "noop"}
        with patch("mureo.web.handlers.byod_clear", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "noop"

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf="bad")
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


# ---------------------------------------------------------------------------
# Native OS file/dir picker routes (planner HANDOFF
# feat-web-config-ui-phase1-native-picker.md). 2 new CSRF + Host gated
# POST endpoints:
#   POST /api/pick/directory   body {title?}        -> pick_directory
#   POST /api/pick/file        body {title?, kind}  -> pick_file (xlsx)
# The native_picker module itself is tested in
# test_web_native_picker.py; here we pin only the route layer (dispatch,
# gating, JSON shape). The picker is mocked at the handler's imported
# symbol (``mureo.web.handlers.pick_directory`` / ``.pick_file``) so no
# real subprocess / Tk window is ever spawned.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostPickDirectory:
    """``POST /api/pick/directory`` — native OS folder picker."""

    ROUTE = "/api/pick/directory"

    def test_dispatches_to_pick_directory(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "ok",
            "path": "/Users/me/projects/demo",
        }
        with patch("mureo.web.handlers.pick_directory", return_value=fake) as mock_pick:
            resp = _post(wizard, self.ROUTE, {"title": "Pick a folder"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert body["path"] == "/Users/me/projects/demo"
        mock_pick.assert_called_once()

    def test_cancelled_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        """A user-cancelled dialog is a normal outcome, not a 500."""
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "cancelled", "path": None}
        with patch("mureo.web.handlers.pick_directory", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "cancelled"

    def test_forwards_session_locale(self, wizard: ConfigureWizard) -> None:
        """#228 — the macOS prompt is keyed by the SERVER-side session
        locale, so the route must forward it to the picker."""
        wizard.session.set_locale("ja")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "cancelled", "path": None}
        with patch("mureo.web.handlers.pick_directory", return_value=fake) as mock_pick:
            _post(wizard, self.ROUTE, {"title": "t"})
        assert mock_pick.call_args.kwargs["locale"] == "ja"

    def test_request_body_locale_cannot_override_session(
        self, wizard: ConfigureWizard
    ) -> None:
        """A ``locale`` field smuggled into the request body must NOT
        influence the prompt — only the session locale may."""
        wizard.session.set_locale("en")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "cancelled", "path": None}
        with patch("mureo.web.handlers.pick_directory", return_value=fake) as mock_pick:
            _post(wizard, self.ROUTE, {"title": "t", "locale": "ja"})
        assert mock_pick.call_args.kwargs["locale"] == "en"

    def test_error_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        """tkinter-unavailable degrades to an error envelope (UI falls
        back to manual entry), never a 500."""
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "error",
            "detail": "tkinter_unavailable",
        }
        with patch("mureo.web.handlers.pick_directory", return_value=fake):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "error"

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf="not-the-real-token")
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestPostPickFile:
    """``POST /api/pick/file`` — native OS Excel-file picker."""

    ROUTE = "/api/pick/file"

    def test_dispatches_to_pick_file(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "ok",
            "path": "/Users/me/data/bundle.xlsx",
        }
        with patch("mureo.web.handlers.pick_file", return_value=fake) as mock_pick:
            resp = _post(
                wizard,
                self.ROUTE,
                {"title": "Pick xlsx", "kind": "xlsx"},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert body["path"] == "/Users/me/data/bundle.xlsx"
        mock_pick.assert_called_once()

    def test_cancelled_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "cancelled", "path": None}
        with patch("mureo.web.handlers.pick_file", return_value=fake):
            resp = _post(wizard, self.ROUTE, {"kind": "xlsx"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "cancelled"

    def test_forwards_session_locale(self, wizard: ConfigureWizard) -> None:
        """#228 — same server-side locale forwarding as the directory
        route."""
        wizard.session.set_locale("ja")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "cancelled", "path": None}
        with patch("mureo.web.handlers.pick_file", return_value=fake) as mock_pick:
            _post(wizard, self.ROUTE, {"kind": "xlsx"})
        assert mock_pick.call_args.kwargs["locale"] == "ja"

    def test_request_body_locale_cannot_override_session(
        self, wizard: ConfigureWizard
    ) -> None:
        """Same smuggling guard as the directory route — the file route
        parses extra body fields (``kind``), so pin it independently."""
        wizard.session.set_locale("en")
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "cancelled", "path": None}
        with patch("mureo.web.handlers.pick_file", return_value=fake) as mock_pick:
            _post(wizard, self.ROUTE, {"kind": "xlsx", "locale": "ja"})
        assert mock_pick.call_args.kwargs["locale"] == "en"

    def test_error_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {
            "status": "error",
            "detail": "tkinter_unavailable",
        }
        with patch("mureo.web.handlers.pick_file", return_value=fake):
            resp = _post(wizard, self.ROUTE, {"kind": "xlsx"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "error"

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {"kind": "xlsx"}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({"kind": "xlsx"}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestPostSetupBasicClear:
    """``POST /api/setup/basic/clear`` — bulk uninstall (clear all)."""

    ROUTE = "/api/setup/basic/clear"

    def test_ok_dispatches_to_clear_all_setup(self, wizard: ConfigureWizard) -> None:
        """Returns the bulk envelope verbatim."""
        envelope: dict[str, Any] = {
            "mureo_mcp": {"status": "ok"},
            "auth_hook": {"status": "noop"},
            "skills": {"status": "ok"},
            "legacy_commands": ["onboard.md"],
            "providers": {"google-ads-official": {"status": "ok"}},
        }
        with patch(
            "mureo.web.handlers.clear_all_setup", return_value=envelope
        ) as mock_clear:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == envelope
        mock_clear.assert_called_once()

    def test_partial_failure_surfaces_in_envelope(
        self, wizard: ConfigureWizard
    ) -> None:
        """Acceptance criteria L132-L134: a step failure is reported in
        the envelope, not as a 500."""
        envelope: dict[str, Any] = {
            "mureo_mcp": {"status": "error", "detail": "OSError"},
            "auth_hook": {"status": "ok"},
            "skills": {"status": "ok"},
            "legacy_commands": [],
        }
        with patch("mureo.web.handlers.clear_all_setup", return_value=envelope):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["mureo_mcp"]["status"] == "error"
        assert body["auth_hook"]["status"] == "ok"

    def test_passes_wizard_home_through(self, wizard: ConfigureWizard) -> None:
        """The handler propagates ``self.wizard.home`` to ``clear_all_setup``
        so every per-step remove operates on the same tree (the tests sandbox
        that home; in production it is ``None`` and the real one is used)."""
        with patch("mureo.web.handlers.clear_all_setup", return_value={}) as mock_clear:
            _post(wizard, self.ROUTE, {})

        kwargs = mock_clear.call_args.kwargs
        home_arg: Any = kwargs.get("home")
        if home_arg is None and mock_clear.call_args.args:
            home_arg = mock_clear.call_args.args[0]
        assert home_arg == wizard.home

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf="bad")
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestConfirmHostResolution:
    """``/api/providers/confirm`` is client-host-authoritative: a valid
    payload ``host`` wins over a stale/reset server session (the root
    cause of the Desktop user getting the Code-path 'not connected'),
    self-heals the session, and forwards ``affirm``."""

    ROUTE = "/api/providers/confirm"

    def _patch(self):
        m = patch("mureo.web.handlers.confirm_hosted_provider")
        return m

    def test_payload_host_wins_over_default_session(
        self, wizard: ConfigureWizard
    ) -> None:
        # session is the claude-code default (never set)
        with self._patch() as mock:
            mock.return_value.as_dict.return_value = {"status": "manual"}
            _post(
                wizard,
                self.ROUTE,
                {"provider_id": "meta-ads-official", "host": "claude-desktop"},
            )
        assert mock.call_args.kwargs["host"] == "claude-desktop"
        # session self-healed so later host-dependent calls agree
        assert wizard.session.host == "claude-desktop"

    def test_affirm_forwarded(self, wizard: ConfigureWizard) -> None:
        with self._patch() as mock:
            mock.return_value.as_dict.return_value = {"status": "ok"}
            _post(
                wizard,
                self.ROUTE,
                {
                    "provider_id": "meta-ads-official",
                    "host": "claude-desktop",
                    "affirm": True,
                },
            )
        assert mock.call_args.kwargs["affirm"] is True

    def test_invalid_payload_host_falls_back_to_session(
        self, wizard: ConfigureWizard
    ) -> None:
        _set_host(wizard, "claude-desktop")
        with self._patch() as mock:
            mock.return_value.as_dict.return_value = {"status": "manual"}
            _post(
                wizard,
                self.ROUTE,
                {"provider_id": "meta-ads-official", "host": "vscode"},
            )
        assert mock.call_args.kwargs["host"] == "claude-desktop"

    def test_absent_payload_host_uses_session(self, wizard: ConfigureWizard) -> None:
        with self._patch() as mock:
            mock.return_value.as_dict.return_value = {"status": "not_connected"}
            _post(wizard, self.ROUTE, {"provider_id": "meta-ads-official"})
        assert mock.call_args.kwargs["host"] == "claude-code"
        assert mock.call_args.kwargs["affirm"] is False


@pytest.mark.unit
class TestNativeToggleHostResolution:
    """``/api/providers/native-toggle`` uses the same client-authoritative
    host resolution so a reset session can't misroute the guard."""

    ROUTE = "/api/providers/native-toggle"

    def test_payload_host_wins(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.set_native_preference") as mock:
            mock.return_value.as_dict.return_value = {"status": "ok"}
            _post(
                wizard,
                self.ROUTE,
                {
                    "platform": "meta_ads",
                    "prefer_official": True,
                    "host": "claude-desktop",
                },
            )
        assert mock.call_args.kwargs["host"] == "claude-desktop"
        assert wizard.session.host == "claude-desktop"


# ---------------------------------------------------------------------------
# Update-availability + one-click upgrade (#239). 2 new endpoints:
#   GET  /api/updates    (Host-gated only, no CSRF for GET) -> get_update_status
#   POST /api/upgrade    (CSRF + Host gated)                -> run_upgrade_all
# The version_check / upgrade_action wrappers are tested in
# test_web_version_check.py / test_web_upgrade_action.py; here we pin only
# the route layer (dispatch, gating, JSON shape). Both wrappers are mocked
# at the handler's imported symbol so no real pip subprocess ever runs.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestServeUpdates:
    """``GET /api/updates`` returns the update-availability payload."""

    ROUTE = "/api/updates"

    def test_returns_documented_shape(self, wizard: ConfigureWizard) -> None:
        fake_result = {
            "status": "ok",
            "any_update": True,
            "packages": [
                {"name": "mureo", "installed": "0.9.31", "latest": "0.9.32"},
            ],
        }
        with patch(
            "mureo.web.handlers.get_update_status", return_value=fake_result
        ) as mock_check:
            resp = _get(wizard, self.ROUTE)
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("application/json")
        body = json.loads(resp.read().decode("utf-8"))
        assert body == fake_result
        mock_check.assert_called_once()

    def test_error_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        """A degraded pip check is a normal outcome, never a 500."""
        fake_result = {"status": "error", "any_update": False, "packages": []}
        with patch("mureo.web.handlers.get_update_status", return_value=fake_result):
            resp = _get(wizard, self.ROUTE)
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "error"
        assert body["any_update"] is False

    def test_get_does_not_require_csrf(self, wizard: ConfigureWizard) -> None:
        fake_result = {"status": "ok", "any_update": False, "packages": []}
        with patch("mureo.web.handlers.get_update_status", return_value=fake_result):
            resp = _get(wizard, self.ROUTE)
        assert resp.status == 200

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        req = urllib.request.Request(_url(wizard, self.ROUTE))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestRestartRunner:
    """The exit-to-restart runner: graceful stop then a hard os._exit backstop.

    The danger code path (it calls ``os._exit``) is exercised directly with
    ``time.sleep`` / ``os._exit`` patched so the suite never actually exits.
    """

    def test_stops_then_hard_exits(self) -> None:
        from unittest.mock import MagicMock

        import mureo.web.handlers as handlers_mod

        wizard = MagicMock()
        with (
            patch("mureo.web.handlers.time.sleep"),
            patch("mureo.web.handlers.os._exit") as mock_exit,
        ):
            handlers_mod._restart_runner(wizard)
        wizard.request_stop.assert_called_once()
        mock_exit.assert_called_once_with(0)

    def test_hard_exits_even_if_request_stop_raises(self) -> None:
        """``request_stop`` is best-effort; the supervisor must still get its
        exit even when graceful shutdown throws."""
        from unittest.mock import MagicMock

        import mureo.web.handlers as handlers_mod

        wizard = MagicMock()
        wizard.request_stop.side_effect = RuntimeError("boom")
        with (
            patch("mureo.web.handlers.time.sleep"),
            patch("mureo.web.handlers.os._exit") as mock_exit,
        ):
            handlers_mod._restart_runner(wizard)
        mock_exit.assert_called_once_with(0)


@pytest.mark.unit
class TestReexecRunner:
    """The interactive self-reexec runner: replace the process image via
    ``os.execv`` so an unsupervised ``mureo configure`` genuinely restarts on
    the new code.

    ``os.execv`` is patched so the suite never actually re-execs itself.
    """

    def test_reexecs_same_command_as_python_m_mureo(self) -> None:
        """The command is rebuilt as ``<python> -m mureo <original args>`` so it
        works for both the console-script and ``-m`` launch styles."""
        import mureo.web.handlers as handlers_mod

        with (
            patch("mureo.web.handlers.time.sleep"),
            patch.object(handlers_mod.sys, "argv", ["mureo", "configure", "--serve"]),
            patch.object(handlers_mod.sys, "executable", "/usr/bin/python3"),
            patch("mureo.web.handlers.os.execv") as mock_execv,
        ):
            handlers_mod._reexec_runner()
        mock_execv.assert_called_once_with(
            "/usr/bin/python3",
            ["/usr/bin/python3", "-m", "mureo", "configure", "--serve"],
        )

    def test_takes_no_wizard_so_it_cannot_signal_stop(self) -> None:
        """Invariant guard (the CRITICAL fix): the runner must NOT set the stop
        event — doing so unblocks the main serve loop and the interpreter
        finalizes, abandoning this daemon thread before ``os.execv`` runs. It
        takes no wizard at all, so there is nothing it *could* stop.
        """
        import inspect

        import mureo.web.handlers as handlers_mod

        assert list(inspect.signature(handlers_mod._reexec_runner).parameters) == []


@pytest.mark.unit
class TestRequestInteractiveReexec:
    """The scheduler that runs ``_reexec_runner`` on a daemon thread AFTER the
    ``/api/restart`` response has flushed."""

    def test_runs_reexec_runner_on_a_background_thread(self) -> None:
        """Spawns a REAL thread but stubs ``_reexec_runner`` itself (so no
        ``os.execv``), rather than patching the global ``threading.Thread`` —
        which would collide with other suites' live HTTP servers."""
        import mureo.web.handlers as handlers_mod

        ran = threading.Event()
        with patch("mureo.web.handlers._reexec_runner", side_effect=lambda: ran.set()):
            handlers_mod._request_interactive_reexec()
            assert ran.wait(timeout=2.0), "reexec runner was not invoked"


@pytest.mark.unit
class TestPostRestart:
    """``POST /api/restart`` — restart the running configure server.

    Managed (launchd/systemd) → exit-to-restart so the supervisor relaunches;
    interactive (plain ``mureo configure``) → self-reexec in place. Both
    schedulers are stubbed so the test process never exits/re-execs.
    """

    ROUTE = "/api/restart"

    def test_managed_schedules_service_restart(self, wizard: ConfigureWizard) -> None:
        with (
            patch("mureo.web.service.is_managed_service", return_value=True),
            patch("mureo.web.handlers._request_service_restart") as mock_service,
            patch("mureo.web.handlers._request_interactive_reexec") as mock_reexec,
        ):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "mode": "managed"}
        mock_service.assert_called_once()
        mock_reexec.assert_not_called()

    def test_interactive_schedules_reexec(self, wizard: ConfigureWizard) -> None:
        with (
            patch("mureo.web.service.is_managed_service", return_value=False),
            patch("mureo.web.handlers._request_service_restart") as mock_service,
            patch("mureo.web.handlers._request_interactive_reexec") as mock_reexec,
        ):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "mode": "interactive"}
        mock_reexec.assert_called_once()
        mock_service.assert_not_called()

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostUpgrade:
    """``POST /api/upgrade`` dispatches to ``run_upgrade_all`` (server-
    derived targets only — the request body is never read for packages)."""

    ROUTE = "/api/upgrade"

    @pytest.fixture(autouse=True)
    def _no_real_restart(self) -> Any:
        """Never let an upgrade test exit the process: stub the
        exit-to-restart scheduler for the whole class."""
        with patch("mureo.web.handlers._request_service_restart") as mock_restart:
            yield mock_restart

    def test_dispatches_to_run_upgrade_all(
        self, wizard: ConfigureWizard, _no_real_restart: Any
    ) -> None:
        fake_result = {
            "status": "ok",
            "returncode": 0,
            "packages": ["mureo", "mureo-agency"],
            "output": "Successfully installed",
        }
        with (
            patch(
                "mureo.web.handlers.run_upgrade_all", return_value=fake_result
            ) as mock_upgrade,
            patch("mureo.web.handlers.request_update_refresh"),
            patch("mureo.web.service.is_managed_service", return_value=False),
        ):
            resp = _post(wizard, self.ROUTE, {})
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
        # Interactive (unmanaged): no auto-restart; envelope gains restarting.
        assert body == {**fake_result, "restarting": False}
        mock_upgrade.assert_called_once()
        _no_real_restart.assert_not_called()

    def test_successful_upgrade_invalidates_update_cache(
        self, wizard: ConfigureWizard
    ) -> None:
        """A successful upgrade drops the cached "update available" result and
        kicks a fresh check, so the About badge / summary stop advertising the
        just-applied update on the next page load."""
        fake_result = {
            "status": "ok",
            "returncode": 0,
            "packages": ["mureo"],
            "output": "Successfully installed",
        }
        with (
            patch("mureo.web.handlers.run_upgrade_all", return_value=fake_result),
            patch("mureo.web.handlers.request_update_refresh") as mock_refresh,
            patch("mureo.web.service.is_managed_service", return_value=False),
        ):
            _post(wizard, self.ROUTE, {})
        mock_refresh.assert_called_once()

    def test_managed_service_upgrade_auto_restarts(
        self, wizard: ConfigureWizard, _no_real_restart: Any
    ) -> None:
        """Under an auto-start supervisor a successful upgrade returns
        ``restarting=True`` and schedules the exit-to-restart, so the
        supervisor relaunches the daemon on the new code with no user action."""
        fake_result = {
            "status": "ok",
            "returncode": 0,
            "packages": ["mureo"],
            "output": "Successfully installed",
        }
        with (
            patch("mureo.web.handlers.run_upgrade_all", return_value=fake_result),
            patch("mureo.web.handlers.request_update_refresh"),
            patch("mureo.web.service.is_managed_service", return_value=True),
        ):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["restarting"] is True
        _no_real_restart.assert_called_once()

    def test_unmanaged_upgrade_does_not_restart(
        self, wizard: ConfigureWizard, _no_real_restart: Any
    ) -> None:
        """A plain interactive ``mureo configure`` (no supervisor) keeps the
        manual prompt: ``restarting=False`` and no restart scheduled."""
        fake_result = {
            "status": "ok",
            "returncode": 0,
            "packages": ["mureo"],
            "output": "Successfully installed",
        }
        with (
            patch("mureo.web.handlers.run_upgrade_all", return_value=fake_result),
            patch("mureo.web.handlers.request_update_refresh"),
            patch("mureo.web.service.is_managed_service", return_value=False),
        ):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["restarting"] is False
        _no_real_restart.assert_not_called()

    def test_error_envelope_surfaces_as_200(self, wizard: ConfigureWizard) -> None:
        fake_result = {
            "status": "error",
            "returncode": 1,
            "packages": ["mureo"],
            "output": "Could not find a version",
        }
        with (
            patch("mureo.web.handlers.run_upgrade_all", return_value=fake_result),
            patch("mureo.web.handlers.request_update_refresh") as mock_refresh,
        ):
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "error"
        # A failed upgrade must NOT touch the update cache.
        mock_refresh.assert_not_called()

    def test_noop_upgrade_skips_cache_invalidation(
        self, wizard: ConfigureWizard
    ) -> None:
        """No mureo dist discovered → ``noop``; the cache is left untouched
        (only a genuine ``ok`` upgrade invalidates it)."""
        fake_result = {
            "status": "noop",
            "returncode": 0,
            "packages": [],
            "output": "",
        }
        with (
            patch("mureo.web.handlers.run_upgrade_all", return_value=fake_result),
            patch("mureo.web.handlers.request_update_refresh") as mock_refresh,
        ):
            resp = _post(wizard, self.ROUTE, {})
        assert json.loads(resp.read().decode("utf-8"))["status"] == "noop"
        mock_refresh.assert_not_called()

    def test_request_body_packages_are_ignored(self, wizard: ConfigureWizard) -> None:
        """A package list smuggled into the body must never reach the
        upgrade action — targets are server-derived only."""
        fake_result = {
            "status": "ok",
            "returncode": 0,
            "packages": ["mureo"],
            "output": "",
        }
        with (
            patch(
                "mureo.web.handlers.run_upgrade_all", return_value=fake_result
            ) as mock_upgrade,
            patch("mureo.web.handlers.request_update_refresh"),
        ):
            _post(wizard, self.ROUTE, {"packages": ["evil-package", "--index-url=x"]})
        # The wrapper takes no package argument at all.
        assert mock_upgrade.call_args.args == ()
        assert mock_upgrade.call_args.kwargs == {}

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403

    def test_rejects_wrong_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf="not-the-real-token")
        assert exc.value.code == 403

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        body = json.dumps({}).encode()
        req = urllib.request.Request(_url(wizard, self.ROUTE), data=body, method="POST")
        req.add_header("Host", "attacker.example.com")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=2.0)
            raise AssertionError("spoofed Host was not rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        except (ConnectionError, urllib.error.URLError) as exc:
            # Windows: the server closes the socket on host rejection
            # before the 403 body is read, surfacing as
            # ConnectionAbortedError (WinError 10053) rather than an
            # HTTPError. The request was still rejected — accept that
            # on win32 only; POSIX must still see a clean 403.
            if sys.platform != "win32":
                raise AssertionError(
                    f"expected HTTP 403, got {type(exc).__name__}: {exc}"
                ) from exc


@pytest.mark.unit
class TestPostCheckUpdates:
    """``POST /api/updates/refresh`` forces a fresh check (#246).

    Route-layer only: ``request_update_refresh`` (cache invalidation + the
    background pip check) is unit-tested in test_web_version_check.py; here we
    pin dispatch, JSON shape, and CSRF gating.
    """

    ROUTE = "/api/updates/refresh"

    def test_dispatches_to_request_update_refresh(
        self, wizard: ConfigureWizard
    ) -> None:
        fake_result = {"status": "checking", "any_update": False, "packages": []}
        with patch(
            "mureo.web.handlers.request_update_refresh", return_value=fake_result
        ) as mock_refresh:
            resp = _post(wizard, self.ROUTE, {})
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
        assert body == fake_result
        mock_refresh.assert_called_once()

    def test_rejects_missing_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, self.ROUTE, {}, csrf=None)
        assert exc.value.code == 403


@pytest.mark.unit
class TestAdvisors:
    """``/api/advisors`` list / add / remove — the Advanced → External
    advisor MCP card. Exercises the full stack against the sandboxed home
    (``wizard`` fixture), so an add/remove writes through to
    ``<home>/.mureo/insight_sources.json``.
    """

    def _path(self, wizard: ConfigureWizard) -> Path:
        return wizard.host_paths.credentials_path.parent / "insight_sources.json"

    def test_list_empty_when_no_file(self, wizard: ConfigureWizard) -> None:
        resp = _get(wizard, "/api/advisors")
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"advisors": []}

    def test_add_persists_and_lists(self, wizard: ConfigureWizard) -> None:
        resp = _post(
            wizard,
            "/api/advisors/add",
            {
                "name": "advisor-1",
                "transport": "stdio",
                "tool": "vector_search",
                "command": "/usr/bin/advisor",
            },
        )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert body["advisors"] == [
            {
                "name": "advisor-1",
                "transport": "stdio",
                "target": "/usr/bin/advisor",
            }
        ]
        # Persisted to the sandboxed home.
        assert self._path(wizard).exists()
        # And surfaced by a fresh GET.
        listed = json.loads(_get(wizard, "/api/advisors").read().decode("utf-8"))
        assert listed["advisors"][0]["name"] == "advisor-1"

    def test_add_http_uses_url_as_target(self, wizard: ConfigureWizard) -> None:
        resp = _post(
            wizard,
            "/api/advisors/add",
            {
                "name": "advisor-http",
                "transport": "http",
                "tool": "vector_search",
                "url": "https://advisor.example.com/mcp",
            },
        )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["advisors"][0] == {
            "name": "advisor-http",
            "transport": "http",
            "target": "https://advisor.example.com/mcp",
        }

    def test_add_invalid_transport_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/advisors/add",
                {"name": "a", "transport": "carrier-pigeon", "tool": "t"},
            )
        assert exc.value.code == 400

    def test_add_stdio_missing_command_returns_400(
        self, wizard: ConfigureWizard
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/advisors/add",
                {"name": "a", "transport": "stdio", "tool": "t"},
            )
        assert exc.value.code == 400

    def test_add_http_missing_url_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/advisors/add",
                {"name": "a", "transport": "http", "tool": "t"},
            )
        assert exc.value.code == 400

    def test_add_duplicate_name_returns_400(self, wizard: ConfigureWizard) -> None:
        _post(
            wizard,
            "/api/advisors/add",
            {
                "name": "dup",
                "transport": "stdio",
                "tool": "t",
                "command": "/c",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/advisors/add",
                {
                    "name": "dup",
                    "transport": "http",
                    "tool": "t",
                    "url": "https://x.example.com/mcp",
                },
            )
        assert exc.value.code == 400

    def test_remove_returns_updated_list(self, wizard: ConfigureWizard) -> None:
        _post(
            wizard,
            "/api/advisors/add",
            {"name": "a", "transport": "stdio", "tool": "t", "command": "/c"},
        )
        _post(
            wizard,
            "/api/advisors/add",
            {
                "name": "b",
                "transport": "http",
                "tool": "t",
                "url": "https://x.example.com/mcp",
            },
        )
        resp = _post(wizard, "/api/advisors/remove", {"name": "a"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert [a["name"] for a in body["advisors"]] == ["b"]

    def test_remove_absent_name_is_ok_noop(self, wizard: ConfigureWizard) -> None:
        resp = _post(wizard, "/api/advisors/remove", {"name": "ghost"})
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"status": "ok", "advisors": []}

    def test_remove_blank_name_returns_400(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/advisors/remove", {"name": "  "})
        assert exc.value.code == 400

    def test_add_requires_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/advisors/add",
                {"name": "a", "transport": "stdio", "tool": "t", "command": "/c"},
                csrf=None,
            )
        assert exc.value.code == 403

    def test_remove_requires_csrf(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/advisors/remove", {"name": "a"}, csrf=None)
        assert exc.value.code == 403


# ---------------------------------------------------------------------------
# Reporting dashboard routes (read-only, STATE.json-sourced):
#   GET /api/reports/clients   (Host-gated only, no CSRF for GET)
#   GET /api/reports/summary   (Host-gated only; ?client=&period= forwarded)
# The reports.py builders are unit-tested in test_web_reports.py; here we
# pin only the route layer (dispatch, gating, query forwarding, JSON shape).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetReportsClients:
    """``GET /api/reports/clients`` — selectable reporting clients."""

    ROUTE = "/api/reports/clients"

    def test_returns_clients_envelope(self, wizard: ConfigureWizard) -> None:
        fake = [{"slug": "default", "name": "default", "active": True}]
        with patch(
            "mureo.web.handlers.list_report_clients", return_value=fake
        ) as mock_clients:
            resp = _get(wizard, self.ROUTE)
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"clients": fake}
        mock_clients.assert_called_once()

    def test_get_does_not_require_csrf(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.list_report_clients", return_value=[]):
            resp = _get(wizard, self.ROUTE)
        assert resp.status == 200

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        req = urllib.request.Request(_url(wizard, self.ROUTE))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestGetReportsSummary:
    """``GET /api/reports/summary`` — read-only STATE.json report summary."""

    ROUTE = "/api/reports/summary"

    def test_returns_summary_payload(self, wizard: ConfigureWizard) -> None:
        fake = {
            "client": "default",
            "period": None,
            "last_synced_at": None,
            "platforms": [],
            "recent_actions": [],
            "reports": None,
        }
        with patch(
            "mureo.web.handlers.build_report_summary", return_value=fake
        ) as mock_summary:
            resp = _get(wizard, self.ROUTE)
        body = json.loads(resp.read().decode("utf-8"))
        assert body == fake
        mock_summary.assert_called_once_with(client=None, period=None)

    def test_forwards_client_and_period_query(self, wizard: ConfigureWizard) -> None:
        with patch(
            "mureo.web.handlers.build_report_summary", return_value={}
        ) as mock_summary:
            resp = _get(wizard, self.ROUTE + "?client=acme&period=LAST_7_DAYS")
        assert resp.status == 200
        mock_summary.assert_called_once_with(client="acme", period="LAST_7_DAYS")

    def test_get_does_not_require_csrf(self, wizard: ConfigureWizard) -> None:
        with patch("mureo.web.handlers.build_report_summary", return_value={}):
            resp = _get(wizard, self.ROUTE)
        assert resp.status == 200

    def test_rejects_spoofed_host_header(self, wizard: ConfigureWizard) -> None:
        req = urllib.request.Request(_url(wizard, self.ROUTE))
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


# ---------------------------------------------------------------------------
# Creative Studio gallery routes (#409, read-only):
#   GET /api/creative/clients  (Host-gated only, no CSRF for GET)
#   GET /api/creative/runs     (?client= forwarded)
#   GET /api/creative/image    (?client=&run=&file= — strict containment in
#                               the builder; the route 404s on refusal)
# The creative_gallery.py builders are unit-tested in
# test_web_creative_gallery.py; here we pin only the route layer.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCreativeClients:
    """``GET /api/creative/clients`` — client picker source."""

    ROUTE = "/api/creative/clients"

    def test_returns_clients_envelope(self, wizard: ConfigureWizard) -> None:
        fake = [{"slug": "default", "name": "default", "active": True}]
        with patch(
            "mureo.web.handlers.list_report_clients", return_value=fake
        ) as mock_clients:
            resp = _get(wizard, self.ROUTE)
        body = json.loads(resp.read().decode("utf-8"))
        assert body == {"clients": fake}
        mock_clients.assert_called_once()


@pytest.mark.unit
class TestGetCreativeRuns:
    """``GET /api/creative/runs`` — run list for one client."""

    ROUTE = "/api/creative/runs"

    def test_forwards_client_and_relays_payload(self, wizard: ConfigureWizard) -> None:
        fake = {"client": "acme", "runs": []}
        with patch(
            "mureo.web.handlers.list_creative_runs", return_value=fake
        ) as mock_runs:
            resp = _get(wizard, self.ROUTE + "?client=acme")
        body = json.loads(resp.read().decode("utf-8"))
        assert body == fake
        mock_runs.assert_called_once_with("acme")

    def test_omitted_client_forwards_none(self, wizard: ConfigureWizard) -> None:
        with patch(
            "mureo.web.handlers.list_creative_runs",
            return_value={"client": "default", "runs": []},
        ) as mock_runs:
            _get(wizard, self.ROUTE)
        mock_runs.assert_called_once_with(None)


@pytest.mark.unit
class TestGetCreativeImage:
    """``GET /api/creative/image`` — PNG bytes with strict containment."""

    ROUTE = "/api/creative/image?client=default&run=r1&file=a.png"

    def test_serves_png_bytes(self, wizard: ConfigureWizard, tmp_path: Path) -> None:
        png = tmp_path / "a.png"
        png.write_bytes(b"\x89PNG gallery bytes")
        with patch(
            "mureo.web.handlers.resolve_gallery_image", return_value=png
        ) as mock_resolve:
            resp = _get(wizard, self.ROUTE)
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "image/png"
        assert resp.read() == b"\x89PNG gallery bytes"
        mock_resolve.assert_called_once_with("default", "r1", "a.png")

    def test_refusal_maps_to_404(self, wizard: ConfigureWizard) -> None:
        with (
            patch("mureo.web.handlers.resolve_gallery_image", return_value=None),
            pytest.raises(urllib.error.HTTPError) as exc,
        ):
            _get(wizard, self.ROUTE)
        assert exc.value.code == 404

    def test_missing_params_map_to_404(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(wizard, "/api/creative/image?run=r1")
        assert exc.value.code == 404

    def test_vanished_file_maps_to_404(
        self, wizard: ConfigureWizard, tmp_path: Path
    ) -> None:
        """A file that disappears between resolution and read (TOCTOU on a
        live run dir) must map to the same uniform 404."""
        ghost = tmp_path / "gone.png"
        with (
            patch("mureo.web.handlers.resolve_gallery_image", return_value=ghost),
            pytest.raises(urllib.error.HTTPError) as exc,
        ):
            _get(wizard, self.ROUTE)
        assert exc.value.code == 404
