"""Route dispatch / Host-header / CSRF gate for ``mureo.web.handlers``.

These tests boot a real ``ConfigureWizard`` on 127.0.0.1:0 in a daemon
thread and exercise every route via ``urllib.request``. Heavy
dependencies (OAuth bridge, install_basic_setup, install_provider,
remove_provider, env_var writer, legacy_commands) are patched so the
test never makes outbound calls or mutates the real filesystem.
"""

from __future__ import annotations

import json
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403

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
        mock_install.assert_called_once_with("p1")

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
        mock_remove.assert_called_once_with("p1")


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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


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
        with patch(
            "mureo.web.handlers.init_demo", return_value=fake
        ) as mock_init:
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

    def test_error_envelope_surfaces_as_200(
        self, wizard: ConfigureWizard
    ) -> None:
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


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
        with patch(
            "mureo.web.handlers.byod_status", return_value=fake
        ) as mock_status:
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
        with patch(
            "mureo.web.handlers.byod_import", return_value=fake
        ) as mock_imp:
            resp = _post(
                wizard,
                self.ROUTE,
                {"file_path": "/tmp/bundle.xlsx", "replace": False},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        mock_imp.assert_called_once()

    def test_missing_file_path_returns_400(
        self, wizard: ConfigureWizard
    ) -> None:
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostByodRemove:
    """``POST /api/byod/remove`` — drop one platform's BYOD data."""

    ROUTE = "/api/byod/remove"

    def test_dispatches_to_byod_remove(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok", "detail": "google_ads"}
        with patch(
            "mureo.web.handlers.byod_remove", return_value=fake
        ) as mock_rm:
            resp = _post(
                wizard,
                self.ROUTE,
                {"google_ads": True, "meta_ads": False},
            )
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        mock_rm.assert_called_once()

    def test_error_envelope_surfaces_as_200(
        self, wizard: ConfigureWizard
    ) -> None:
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


@pytest.mark.unit
class TestPostByodClear:
    """``POST /api/byod/clear`` — wipe all BYOD data."""

    ROUTE = "/api/byod/clear"

    def test_dispatches_to_byod_clear(self, wizard: ConfigureWizard) -> None:
        fake = MagicMock()
        fake.as_dict.return_value = {"status": "ok"}
        with patch(
            "mureo.web.handlers.byod_clear", return_value=fake
        ) as mock_clear:
            resp = _post(wizard, self.ROUTE, {})
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        mock_clear.assert_called_once()

    def test_noop_envelope_when_nothing_present(
        self, wizard: ConfigureWizard
    ) -> None:
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403


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
        so the per-step ``clear_part`` calls write to the same setup_state.json."""
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403
