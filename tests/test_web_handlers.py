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
