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
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from mureo.web.server import ConfigureWizard
from tests.web_support import post

if TYPE_CHECKING:
    from pathlib import Path

_PROBE = "mureo.web.handlers.validate_meta_access_token"

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
        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            return _VALID

        with patch(_PROBE, side_effect=_fake) as probe:
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "validate_only": True},
            )
        assert status == 200, body
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
        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            return _VALID

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": "act_1"},
            )
        assert status == 200, body
        assert body["status"] == "ok"
        data = json.loads(wizard.host_paths.credentials_path.read_text())
        meta = data["meta_ads"]
        assert meta["access_token"] == "sys-tok"
        assert meta["account_id"] == "act_1"
        # Never-expiring system-user token: no refresh-clock fields.
        assert "app_id" not in meta
        assert "app_secret" not in meta

    def test_save_without_account_id_persists_token_and_omits_the_key(
        self, wizard: ConfigureWizard
    ) -> None:
        """The ad account is OPTIONAL: the card's placeholder option posts
        ``account_id: null``. The token is still saved, and the ``meta_ads``
        block carries NO ``account_id`` key (``_merge_meta_section`` only
        writes one when resolved or previously saved) — and still no
        refresh-clock fields."""

        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            return _VALID

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok"},
            )
        assert status == 200
        assert body["status"] == "ok"
        data = json.loads(wizard.host_paths.credentials_path.read_text())
        meta = data["meta_ads"]
        assert meta["access_token"] == "sys-tok"
        assert "account_id" not in meta
        assert "app_id" not in meta
        assert "app_secret" not in meta

    @pytest.mark.parametrize("account_id", [None, ""])
    def test_blank_account_id_is_treated_as_absent(
        self, wizard: ConfigureWizard, account_id: str | None
    ) -> None:
        """``accountSelect.value || null`` posts ``null``; a stricter client
        could post ``""``. Both mean "no account" — neither is cross-checked
        against the probe list nor persisted."""

        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            return _VALID

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": account_id},
            )
        assert status == 200
        assert body["status"] == "ok"
        meta = json.loads(wizard.host_paths.credentials_path.read_text())["meta_ads"]
        assert "account_id" not in meta

    def test_save_without_account_id_keeps_a_prior_selection(
        self, wizard: ConfigureWizard
    ) -> None:
        """Re-saving a token with the placeholder selected must not wipe an
        account_id the operator already stored — ``_merge_meta_section``
        carries the prior value forward when none is submitted."""

        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            return _VALID

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": "act_1"},
            )
            assert status == 200, body
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok-2"},
            )
            assert status == 200, body
        meta = json.loads(wizard.host_paths.credentials_path.read_text())["meta_ads"]
        assert meta["access_token"] == "sys-tok-2"
        assert meta["account_id"] == "act_1"

    def test_save_with_missing_scopes_warns_but_saves(
        self, wizard: ConfigureWizard
    ) -> None:
        probe_result = {
            "scopes": ["ads_read"],
            "missing_scopes": ["ads_management", "business_management"],
            "accounts": [{"id": "act_1", "name": "One"}],
        }

        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            return probe_result

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": "act_1"},
            )
        assert status == 200, body
        assert body["status"] == "ok"
        assert body["missing_scopes"] == ["ads_management", "business_management"]
        # Saved despite the warning.
        data = json.loads(wizard.host_paths.credentials_path.read_text())
        assert data["meta_ads"]["access_token"] == "sys-tok"

    def test_invalid_token_returns_structured_error(
        self, wizard: ConfigureWizard
    ) -> None:
        from mureo.meta_ads.accounts import MetaTokenInvalidError

        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            raise MetaTokenInvalidError("Invalid OAuth access token. | subcode=463")

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "bad-tok"},
            )
        assert status == 400
        assert body["error"] == "token_invalid"
        assert "Invalid OAuth access token." in body["detail"]

    def test_missing_access_token_rejected(self, wizard: ConfigureWizard) -> None:
        status, body = post(
            wizard, "/api/credentials/meta/token", {"account_id": "act_1"}
        )
        assert status == 400
        assert body["error"] == "access_token_required"

    def test_missing_csrf_rejected(self, wizard: ConfigureWizard) -> None:
        status, body = post(
            wizard,
            "/api/credentials/meta/token",
            {"access_token": "sys-tok"},
            csrf=None,
        )
        assert status == 403
        assert body["error"] == "csrf_invalid"

    def test_spoofed_host_rejected(self, wizard: ConfigureWizard) -> None:
        """The route is Host-gated like every sibling POST route."""
        status, body = post(
            wizard,
            "/api/credentials/meta/token",
            {"access_token": "sys-tok"},
            headers={"Host": "attacker.example.com"},
        )
        assert status == 403
        assert body["error"] == "host_not_allowed"

    def test_account_fetch_failure_returns_distinct_code(
        self, wizard: ConfigureWizard
    ) -> None:
        """A valid token whose /me/adaccounts listing fails is reported as
        ``account_fetch_failed``, NOT mislabeled ``token_invalid``."""
        from mureo.meta_ads.accounts import MetaAccountFetchError

        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            raise MetaAccountFetchError("Meta ad-account listing failed: boom")

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok"},
            )
        assert status == 400
        assert body["error"] == "account_fetch_failed"
        assert "listing failed" in body["detail"]

    def test_save_rejects_inaccessible_account(self, wizard: ConfigureWizard) -> None:
        """A submitted account_id absent from the probe's account list is
        rejected (server-side trust boundary) instead of saved silently."""
        probe_result = {
            "scopes": ["ads_management"],
            "missing_scopes": [],
            "accounts": [{"id": "act_1", "name": "One"}],
        }

        async def _fake(token: str, **kwargs: Any) -> dict[str, Any]:
            return probe_result

        with patch(_PROBE, side_effect=_fake):
            status, body = post(
                wizard,
                "/api/credentials/meta/token",
                {"access_token": "sys-tok", "account_id": "act_999"},
            )
        assert status == 400
        assert body["error"] == "account_not_accessible"
        assert body["account_id"] == "act_999"
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
