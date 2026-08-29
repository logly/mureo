"""The paste route records — and reports — when the Meta token dies (#726).

``POST /api/credentials/meta/token`` was built on "a system-user token never
expires" (#458) and therefore stored no clock at all. Business Manager mints
60-day system-user tokens, so that assumption cost every affected install a
silent outage every couple of months.

The route now inspects the token with Graph ``debug_token`` during
validation, persists ``token_obtained_at`` plus the reported expiry as
``token_expires_at``, echoes the expiry back so the card can show it, and —
when the operator supplies ``app_id`` / ``app_secret`` — keeps them so the
auto-extension path is armed. It still refuses nothing on this basis: an
inspection Graph declines to answer is a warning in the response, never a
rejected save.

Boots a real ``ConfigureWizard`` like ``tests/test_web_meta_token.py`` and
patches the network probe, so nothing outbound happens.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path

pytestmark = pytest.mark.unit

_PROBE = "mureo.web.handlers.validate_meta_access_token"

_EXPIRES_AT = "2026-11-01T00:00:00+00:00"
_DATA_ACCESS_EXPIRES_AT = "2026-12-30T00:00:00+00:00"
_ISSUED_AT = "2026-09-02T00:00:00+00:00"

_TOKEN_INFO = {
    "type": "SYSTEM_USER",
    "expires_at": _EXPIRES_AT,
    "data_access_expires_at": _DATA_ACCESS_EXPIRES_AT,
    "issued_at": _ISSUED_AT,
}


def _probe_result(
    *,
    token_info: dict[str, Any] | None = None,
    token_inspect_error: str | None = None,
) -> dict[str, Any]:
    return {
        "scopes": ["ads_management", "ads_read"],
        "missing_scopes": [],
        "accounts": [{"id": "act_1", "name": "One"}],
        "token_info": token_info,
        "token_inspect_error": token_inspect_error,
    }


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


def _post(
    wiz: ConfigureWizard, payload: dict[str, Any]
) -> HTTPResponse:  # pragma: no cover - trivial
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{wiz.port}/api/credentials/meta/token",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    return urllib.request.urlopen(req, timeout=2.0)


def _save(
    wiz: ConfigureWizard,
    payload: dict[str, Any],
    probe: dict[str, Any],
) -> dict[str, Any]:
    async def _fake(token: str) -> dict[str, Any]:
        return probe

    with patch(_PROBE, side_effect=_fake):
        resp = _post(wiz, payload)
    return json.loads(resp.read().decode())


def _stored(wiz: ConfigureWizard) -> dict[str, Any]:
    return json.loads(wiz.host_paths.credentials_path.read_text())["meta_ads"]


# ---------------------------------------------------------------------------
# validate_only echoes the inspection
# ---------------------------------------------------------------------------


def test_validate_only_reports_the_expiry(wizard: ConfigureWizard) -> None:
    body = _save(
        wizard,
        {"access_token": "sys-tok", "validate_only": True},
        _probe_result(token_info=_TOKEN_INFO),
    )

    assert body["token_expires_at"] == _EXPIRES_AT
    assert body["token_type"] == "SYSTEM_USER"
    assert body["data_access_expires_at"] == _DATA_ACCESS_EXPIRES_AT
    # Read-only probe: nothing on disk.
    assert not wizard.host_paths.credentials_path.exists()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_save_persists_obtained_at_and_expires_at(wizard: ConfigureWizard) -> None:
    body = _save(
        wizard,
        {"access_token": "sys-tok", "account_id": "act_1"},
        _probe_result(token_info=_TOKEN_INFO),
    )

    assert body["status"] == "ok"
    assert body["token_expires_at"] == _EXPIRES_AT
    meta = _stored(wizard)
    assert meta["token_expires_at"] == _EXPIRES_AT
    assert meta["token_obtained_at"]


def test_save_persists_the_token_type_graph_reported(
    wizard: ConfigureWizard,
) -> None:
    """The refresh path picks its exchange from this field, so the paste
    route is the one place that can establish it (#726)."""

    body = _save(
        wizard,
        {"access_token": "sys-tok"},
        _probe_result(token_info=_TOKEN_INFO),
    )

    assert body["token_type"] == "SYSTEM_USER"
    assert _stored(wizard)["token_type"] == "SYSTEM_USER"


def test_a_user_token_is_recorded_as_a_user_token(wizard: ConfigureWizard) -> None:
    """Graph's verdict is stored verbatim, not normalised to what the card
    asked for. Pasting a plain user token into the system-user field must
    not arm the system-user exchange."""

    info = dict(_TOKEN_INFO, type="USER")
    _save(wizard, {"access_token": "user-tok"}, _probe_result(token_info=info))

    assert _stored(wizard)["token_type"] == "USER"


def test_a_failed_inspection_records_no_token_type(wizard: ConfigureWizard) -> None:
    """No verdict is not "probably a system user". The absent key reads as
    "not established", which keeps the exchange on the documented user-token
    form."""

    _save(
        wizard,
        {"access_token": "sys-tok"},
        _probe_result(token_inspect_error="Graph said no"),
    )

    assert "token_type" not in _stored(wizard)


def test_save_without_a_known_expiry_records_no_expiry_key(
    wizard: ConfigureWizard,
) -> None:
    """A token Graph reports without ``expires_at`` — or one it declined to
    inspect — must not acquire an invented date. The obtained-at stamp is
    still written, so the 53-day fallback clock applies."""

    body = _save(
        wizard,
        {"access_token": "sys-tok"},
        _probe_result(token_inspect_error="Graph said no"),
    )

    assert body["token_expires_at"] is None
    meta = _stored(wizard)
    assert "token_expires_at" not in meta
    assert meta["token_obtained_at"]


def test_failed_inspection_still_saves_and_warns(wizard: ConfigureWizard) -> None:
    body = _save(
        wizard,
        {"access_token": "sys-tok"},
        _probe_result(token_inspect_error="Graph said no"),
    )

    assert body["status"] == "ok"
    assert "token_inspect_failed" in body["warnings"]
    assert _stored(wizard)["access_token"] == "sys-tok"


def test_known_expiry_without_app_credentials_warns_it_cannot_extend(
    wizard: ConfigureWizard,
) -> None:
    body = _save(
        wizard,
        {"access_token": "sys-tok"},
        _probe_result(token_info=_TOKEN_INFO),
    )

    assert body["auto_refresh"] is False
    assert "auto_refresh_unavailable" in body["warnings"]


# ---------------------------------------------------------------------------
# app_id / app_secret arm the auto-extension
# ---------------------------------------------------------------------------


def test_app_credentials_are_saved_and_arm_auto_refresh(
    wizard: ConfigureWizard,
) -> None:
    body = _save(
        wizard,
        {
            "access_token": "sys-tok",
            "app_id": "app-123",
            "app_secret": "secret-456",
        },
        _probe_result(token_info=_TOKEN_INFO),
    )

    assert body["auto_refresh"] is True
    assert "auto_refresh_unavailable" not in body["warnings"]
    meta = _stored(wizard)
    assert meta["app_id"] == "app-123"
    assert meta["app_secret"] == "secret-456"


def test_a_later_paste_keeps_previously_saved_app_credentials(
    wizard: ConfigureWizard,
) -> None:
    """#458 dropped ``app_id``/``app_secret`` unconditionally, so re-pasting a
    token disarmed the refresh the operator had already configured. The paste
    route no longer throws away what it was not asked to change."""

    _save(
        wizard,
        {
            "access_token": "sys-tok",
            "app_id": "app-123",
            "app_secret": "secret-456",
        },
        _probe_result(token_info=_TOKEN_INFO),
    )
    body = _save(
        wizard,
        {"access_token": "sys-tok-2"},
        _probe_result(token_info=_TOKEN_INFO),
    )

    meta = _stored(wizard)
    assert meta["access_token"] == "sys-tok-2"
    assert meta["app_id"] == "app-123"
    assert meta["app_secret"] == "secret-456"
    assert body["auto_refresh"] is True


def test_blank_app_fields_are_treated_as_absent(wizard: ConfigureWizard) -> None:
    """The card posts empty strings when the optional fields are untouched."""

    _save(
        wizard,
        {"access_token": "sys-tok", "app_id": "", "app_secret": "  "},
        _probe_result(token_info=_TOKEN_INFO),
    )

    meta = _stored(wizard)
    assert "app_id" not in meta
    assert "app_secret" not in meta


# ---------------------------------------------------------------------------
# Nothing secret comes back
# ---------------------------------------------------------------------------


def test_response_never_echoes_the_secrets(wizard: ConfigureWizard) -> None:
    body = _save(
        wizard,
        {
            "access_token": "sys-tok",
            "app_id": "app-123",
            "app_secret": "secret-456",
        },
        _probe_result(token_info=_TOKEN_INFO),
    )

    rendered = json.dumps(body)
    assert "sys-tok" not in rendered
    assert "secret-456" not in rendered
