"""#198 — the OAuth account-picker step is skippable for multi-account
backends.

A multi-account ``RuntimeContext`` backend (e.g. the agency plugin)
advertises ``multi_account_auth`` on its ``SecretStore``. When set, the
operator-wide OAuth wizard persists only the operator-shared credentials
(Google ``developer_token`` + OAuth, or the Meta app creds/token) and
skips the per-account picker — ``customer_id`` / ``account_id`` are
per-client values supplied out-of-band.

Default (standalone OSS): capability absent → ``False`` → picker shown
exactly as today.

The capability is threaded explicitly into ``WebAuthWizard``
(default ``False``) rather than read from the process-global context in
the request handler, so these tests — and every existing web_auth test —
are isolated from whatever ``mureo.runtime_context_factory`` happens to
be installed in the dev/CI venv. The production resolution + home gate
lives in ``ConfigureHandler`` and is covered separately.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.cli.web_auth import WebAuthWizard
from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
    runtime_multi_account_auth,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class _FakeEP:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _patch_eps(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "mureo.runtime_context_factory"
        return eps

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 30x as an HTTPError so the test can read the Location
    (mirrors ``tests/test_web_auth.py``)."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


# ---------------------------------------------------------------------------
# runtime_multi_account_auth helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runtime_multi_account_auth_false_when_no_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_eps(monkeypatch, [])
    assert runtime_multi_account_auth() is False


@pytest.mark.unit
def test_runtime_multi_account_auth_true_when_store_advertises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Store:
        multi_account_auth = True

        def load(self, key: str) -> dict[str, Any]:
            return {}

        def save(self, key: str, value: dict[str, Any]) -> None:
            return None

        def delete(self, key: str) -> None:
            return None

    ctx = dataclasses.replace(default_runtime_context(), secret_store=_Store())
    _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
    assert runtime_multi_account_auth() is True


@pytest.mark.unit
def test_runtime_multi_account_auth_false_when_store_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory present but its store doesn't advertise the flag (the
    built-in FilesystemSecretStore) → False."""
    _patch_eps(monkeypatch, [_FakeEP("x", default_runtime_context)])
    assert runtime_multi_account_auth() is False


@pytest.mark.unit
def test_runtime_multi_account_auth_non_true_value_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truthy-but-not-True declaration (mis-typed store) is rejected —
    the flag must be exactly ``True`` to skip the picker."""

    class _Store:
        multi_account_auth = "yes"

        def load(self, key: str) -> dict[str, Any]:
            return {}

        def save(self, key: str, value: dict[str, Any]) -> None:
            return None

        def delete(self, key: str) -> None:
            return None

    ctx = dataclasses.replace(default_runtime_context(), secret_store=_Store())
    _patch_eps(monkeypatch, [_FakeEP("x", lambda: ctx)])
    assert runtime_multi_account_auth() is False


# ---------------------------------------------------------------------------
# WebAuthWizard threading
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_web_auth_wizard_default_multi_account_false() -> None:
    assert WebAuthWizard().multi_account_auth is False


@pytest.mark.unit
def test_web_auth_wizard_accepts_multi_account_flag() -> None:
    assert WebAuthWizard(multi_account_auth=True).multi_account_auth is True


@pytest.mark.unit
def test_oauth_bridge_threads_multi_account_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OAuthBridge.start`` must pass ``multi_account_auth`` through to
    the spawned ``WebAuthWizard``."""
    from mureo.web.oauth_bridge import OAuthBridge

    captured: dict[str, Any] = {}

    class _FakeWizard:
        # Polled by OAuthBridge._watch_handoff on its daemon thread;
        # defined so that watcher does not raise before bridge.cancel().
        completed = False

        def __init__(
            self, *, credentials_path: Any = None, multi_account_auth: bool = False
        ) -> None:
            captured["multi_account_auth"] = multi_account_auth

        def serve(self) -> None:
            return None

        def wait_until_ready(self, timeout: float = 5.0) -> None:
            return None

        def home_url(self) -> str:
            return "http://127.0.0.1:0/"

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr("mureo.cli.web_auth.WebAuthWizard", _FakeWizard)
    bridge = OAuthBridge()
    try:
        bridge.start(
            provider="google",
            configure_wizard=MagicMock(),
            multi_account_auth=True,
        )
        assert captured["multi_account_auth"] is True
    finally:
        bridge.cancel("google")


# ---------------------------------------------------------------------------
# Callback skip behavior (Google + Meta)
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_wizard(tmp_path: Path) -> Iterator[Any]:
    creds_path = tmp_path / ".mureo" / "credentials.json"
    wiz = WebAuthWizard(credentials_path=creds_path, multi_account_auth=True)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=2.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _url(wiz: Any, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


@pytest.mark.unit
def test_google_callback_skips_picker_when_multi_account(multi_wizard: Any) -> None:
    """With ``multi_account_auth``, the Google callback persists the
    shared credentials (no ``customer_id``) and redirects straight to
    /done — the account probe + picker are skipped entirely."""
    from mureo.auth_setup import OAuthResult

    sess = multi_wizard.session
    sess.google_flow = MagicMock()
    sess.google_developer_token = "DT-123"
    sess.google_client_id = "CID-abc"
    sess.google_client_secret = "SECRET-xyz"
    sess.google_oauth_state = "state-xyz"

    async def _must_not_probe(_creds: Any) -> list[dict[str, Any]]:
        raise AssertionError("account probe must be skipped for multi-account")

    with (
        patch(
            "mureo.cli.web_auth.exchange_google_code",
            return_value=OAuthResult(
                refresh_token="REFRESH_TOKEN", access_token="ACCESS_TOKEN"
            ),
        ),
        patch(
            "mureo.cli.web_auth.list_accessible_accounts", side_effect=_must_not_probe
        ),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(multi_wizard, "/google-ads/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 302
        assert exc.value.headers.get("Location", "") == "/done"

    saved = json.loads(multi_wizard.credentials_path.read_text())
    # No real account is recorded: ``save_credentials`` always emits the
    # ``customer_id`` key for Google, so the multi-account marker is the
    # null value (identical to the existing empty-accounts fallback) —
    # the agency backend supplies the per-client customer_id out of band.
    assert saved["google_ads"]["customer_id"] is None
    assert saved["google_ads"]["developer_token"] == "DT-123"
    assert saved["google_ads"]["refresh_token"] == "REFRESH_TOKEN"


@pytest.mark.unit
def test_meta_callback_skips_picker_when_multi_account(multi_wizard: Any) -> None:
    """With ``multi_account_auth``, the Meta callback persists the shared
    app credentials/token (no ``account_id``) and redirects to /done."""
    from mureo.auth_setup import MetaOAuthResult

    sess = multi_wizard.session
    sess.meta_app_id = "APP-1"
    sess.meta_app_secret = "APP-SECRET"
    sess.meta_oauth_state = "state-xyz"

    async def _must_not_probe(_token: str) -> list[dict[str, Any]]:
        raise AssertionError("account probe must be skipped for multi-account")

    with (
        patch(
            "mureo.cli.web_auth.exchange_meta_code",
            return_value=MetaOAuthResult(access_token="META_TOKEN", expires_in=0),
        ),
        patch("mureo.cli.web_auth.list_meta_ad_accounts", side_effect=_must_not_probe),
    ):
        opener = urllib.request.build_opener(_NoRedirect())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(
                _url(multi_wizard, "/meta-ads/callback?code=AC&state=state-xyz"),
                timeout=2.0,
            )
        assert exc.value.code == 302
        assert exc.value.headers.get("Location", "") == "/done"

    saved = json.loads(multi_wizard.credentials_path.read_text())
    assert "account_id" not in saved.get("meta_ads", {})
    assert saved["meta_ads"]["access_token"] == "META_TOKEN"
