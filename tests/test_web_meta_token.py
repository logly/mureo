"""HTTP + persistence tests for the manual Meta system-user token route (#458).

``POST /api/credentials/meta/token`` lets the configure UI (a) probe a
pasted Business-Manager system-user token (``validate_only: true``) and
(b) persist it. A system-user token never expires, so it is saved WITHOUT
``app_id`` / ``app_secret`` — that keeps it out of the 53-day auto-refresh
path (``mureo.auth._should_refresh`` returns False when either is absent).

The route is CSRF + Host gated identically to its sibling POST routes.
These tests boot a real ``ConfigureWizard`` on 127.0.0.1:0 (mirroring
``tests/test_web_handlers.py``) and patch the network probe so nothing
outbound happens.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path

_PROBE = "mureo.web.handlers.validate_meta_access_token"


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


def _url(wiz: ConfigureWizard, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


def _post(
    wiz: ConfigureWizard,
    path: str,
    payload: dict[str, Any] | None,
    *,
    csrf: str | None = "use_session",
) -> HTTPResponse:
    body = json.dumps(payload or {}).encode()
    req = urllib.request.Request(_url(wiz, path), data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if csrf == "use_session":
        req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    elif csrf is not None:
        req.add_header("X-CSRF-Token", csrf)
    return urllib.request.urlopen(req, timeout=2.0)


def _body(resp: HTTPResponse) -> dict[str, Any]:
    return json.loads(resp.read().decode())


_VALID = {
    "scopes": ["ads_management", "ads_read"],
    "missing_scopes": [],
    "accounts": [{"id": "act_1", "name": "One"}],
}


@pytest.mark.unit
class TestMetaTokenRoute:
    def test_validate_only_returns_probe_without_saving(
        self, wizard: ConfigureWizard
    ) -> None:
        async def _fake(token: str) -> dict[str, Any]:
            return _VALID

        with patch(_PROBE, side_effect=_fake) as probe:
            resp = _post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "validate_only": True},
            )
        body = _body(resp)
        assert probe.called
        assert body["scopes"] == ["ads_management", "ads_read"]
        assert body["accounts"] == [{"id": "act_1", "name": "One"}]
        assert body["missing_scopes"] == []
        # Nothing persisted on a validate-only probe.
        cred_path = wizard.host_paths.credentials_path
        if cred_path.exists():
            data = json.loads(cred_path.read_text())
            assert "meta_ads" not in data

    def test_save_success_persists_token(self, wizard: ConfigureWizard) -> None:
        async def _fake(token: str) -> dict[str, Any]:
            return _VALID

        with patch(_PROBE, side_effect=_fake):
            resp = _post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": "act_1"},
            )
        body = _body(resp)
        assert body["status"] == "ok"
        data = json.loads(wizard.host_paths.credentials_path.read_text())
        meta = data["meta_ads"]
        assert meta["access_token"] == "sys-tok"
        assert meta["account_id"] == "act_1"
        # Never-expiring system-user token: no refresh-clock fields.
        assert "app_id" not in meta
        assert "app_secret" not in meta

    def test_save_with_missing_scopes_warns_but_saves(
        self, wizard: ConfigureWizard
    ) -> None:
        probe_result = {
            "scopes": ["ads_read"],
            "missing_scopes": ["ads_management", "business_management"],
            "accounts": [{"id": "act_1", "name": "One"}],
        }

        async def _fake(token: str) -> dict[str, Any]:
            return probe_result

        with patch(_PROBE, side_effect=_fake):
            resp = _post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": "act_1"},
            )
        body = _body(resp)
        assert body["status"] == "ok"
        assert body["missing_scopes"] == ["ads_management", "business_management"]
        # Saved despite the warning.
        data = json.loads(wizard.host_paths.credentials_path.read_text())
        assert data["meta_ads"]["access_token"] == "sys-tok"

    def test_invalid_token_returns_structured_error(
        self, wizard: ConfigureWizard
    ) -> None:
        from mureo.meta_ads.accounts import MetaTokenInvalidError

        async def _fake(token: str) -> dict[str, Any]:
            raise MetaTokenInvalidError("Invalid OAuth access token. | subcode=463")

        with (
            patch(_PROBE, side_effect=_fake),
            pytest.raises(urllib.error.HTTPError) as exc,
        ):
            _post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "bad-tok"},
            )
        assert exc.value.code == 400
        err = json.loads(exc.value.read().decode())
        assert err["error"] == "token_invalid"
        assert "Invalid OAuth access token." in err["detail"]

    def test_missing_access_token_rejected(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(wizard, "/api/credentials/meta/token", {"account_id": "act_1"})
        assert exc.value.code == 400
        err = json.loads(exc.value.read().decode())
        assert err["error"] == "access_token_required"

    def test_missing_csrf_rejected(self, wizard: ConfigureWizard) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok"},
                csrf=None,
            )
        assert exc.value.code == 403
        err = json.loads(exc.value.read().decode())
        assert err["error"] == "csrf_invalid"

    def test_spoofed_host_rejected(self, wizard: ConfigureWizard) -> None:
        """The route is Host-gated like every sibling POST route."""
        body = json.dumps({"access_token": "sys-tok"}).encode()
        req = urllib.request.Request(
            _url(wizard, "/api/credentials/meta/token"),
            data=body,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("X-CSRF-Token", wizard.session.csrf_token)
        req.add_header("Host", "attacker.example.com")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc.value.code == 403
        err = json.loads(exc.value.read().decode())
        assert err["error"] == "host_not_allowed"

    def test_account_fetch_failure_returns_distinct_code(
        self, wizard: ConfigureWizard
    ) -> None:
        """A valid token whose /me/adaccounts listing fails is reported as
        ``account_fetch_failed``, NOT mislabeled ``token_invalid``."""
        from mureo.meta_ads.accounts import MetaAccountFetchError

        async def _fake(token: str) -> dict[str, Any]:
            raise MetaAccountFetchError("Meta ad-account listing failed: boom")

        with (
            patch(_PROBE, side_effect=_fake),
            pytest.raises(urllib.error.HTTPError) as exc,
        ):
            _post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok"},
            )
        assert exc.value.code == 400
        err = json.loads(exc.value.read().decode())
        assert err["error"] == "account_fetch_failed"
        assert "listing failed" in err["detail"]

    def test_save_rejects_inaccessible_account(self, wizard: ConfigureWizard) -> None:
        """A submitted account_id absent from the probe's account list is
        rejected (server-side trust boundary) instead of saved silently."""
        probe_result = {
            "scopes": ["ads_management"],
            "missing_scopes": [],
            "accounts": [{"id": "act_1", "name": "One"}],
        }

        async def _fake(token: str) -> dict[str, Any]:
            return probe_result

        with (
            patch(_PROBE, side_effect=_fake),
            pytest.raises(urllib.error.HTTPError) as exc,
        ):
            _post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": "act_999"},
            )
        assert exc.value.code == 400
        err = json.loads(exc.value.read().decode())
        assert err["error"] == "account_not_accessible"
        assert err["account_id"] == "act_999"
        # Nothing persisted on rejection.
        cred_path = wizard.host_paths.credentials_path
        if cred_path.exists():
            data = json.loads(cred_path.read_text())
            assert "meta_ads" not in data


@pytest.mark.unit
class TestSavedShapeSkipsRefresh:
    def test_saved_meta_block_has_no_refresh_fields(self, tmp_path: Path) -> None:
        """A pasted system-user token saved via save_credentials with no
        app_id/app_secret writes a meta_ads block lacking those keys."""
        from mureo.auth import MetaAdsCredentials
        from mureo.auth_setup import save_credentials

        cred_path = tmp_path / "credentials.json"
        save_credentials(
            path=cred_path,
            meta=MetaAdsCredentials(access_token="sys-tok"),
            account_id="act_9",
        )
        data = json.loads(cred_path.read_text())
        meta = data["meta_ads"]
        assert meta["access_token"] == "sys-tok"
        assert meta["account_id"] == "act_9"
        assert "app_id" not in meta
        assert "app_secret" not in meta

    def test_should_refresh_false_for_that_shape(self) -> None:
        """The refresh clock never arms without app_id/app_secret."""
        from mureo.auth import MetaAdsCredentials, _should_refresh

        creds = MetaAdsCredentials(
            access_token="sys-tok",
            token_obtained_at="2020-01-01T00:00:00+00:00",  # ancient on purpose
            account_id="act_9",
        )
        assert _should_refresh(creds) is False

    def test_repr_hides_token_and_secret(self) -> None:
        """access_token / app_secret must not leak via repr (#458)."""
        from mureo.auth import MetaAdsCredentials

        creds = MetaAdsCredentials(
            access_token="SECRET-TOKEN-XYZ",
            app_id="123",
            app_secret="SECRET-APP-SECRET",
            account_id="act_9",
        )
        text = repr(creds)
        assert "SECRET-TOKEN-XYZ" not in text
        assert "SECRET-APP-SECRET" not in text
        # Non-sensitive fields still appear.
        assert "act_9" in text
        assert "123" in text
