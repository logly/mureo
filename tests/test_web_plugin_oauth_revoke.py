"""#970 — best-effort token revocation and the plugin Disconnect action.

``revoke_plugin_token`` wraps :func:`mureo.oauth_authcode.revoke_token` so a
failed revocation is one WARNING naming the provider and never an exception.
``disconnect_plugin_provider`` removes a plugin provider's whole credential
section, revoking its stored OAuth token first when the provider declares a
``revoke_url``. Neither may write the token or the client secret to a log.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mureo.core.providers import AccountCredentialField, AccountOAuthConfig
from mureo.core.providers.registry import ProviderEntry, default_registry
from mureo.web.plugin_credentials import UnknownProviderError
from mureo.web.plugin_oauth_revoke import (
    disconnect_plugin_provider,
    revoke_plugin_token,
)

if TYPE_CHECKING:
    from pathlib import Path

_REVOKE_URL = "https://broker.example.com/oauth/revoke"
_LOGGER = "mureo.web.plugin_oauth_revoke"
_FIELDS = (
    AccountCredentialField(key="client_id", display_name="Client ID"),
    AccountCredentialField(key="client_secret", display_name="Secret", secret=True),
    AccountCredentialField(key="refresh_token", display_name="Refresh", secret=True),
)


def _oauth(revoke_url: str | None) -> AccountOAuthConfig:
    return AccountOAuthConfig(
        authorize_url="https://broker.example.com/oauth/authorize",
        token_url="https://broker.example.com/oauth/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
        token_auth_style="body",
        token_headers=(("X-Example", "abc"),),
        revoke_url=revoke_url,
    )


def _entry(name: str, oauth: AccountOAuthConfig | None) -> ProviderEntry:
    class _Provider:
        account_credential_fields = _FIELDS

    _Provider.name = name  # type: ignore[attr-defined]
    if oauth is not None:
        _Provider.account_oauth = oauth  # type: ignore[attr-defined]
    return ProviderEntry(
        name=name,
        display_name=name,
        capabilities=frozenset(),
        provider_class=_Provider,
        source_distribution=None,
    )


@pytest.fixture
def _providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {
            "broker_ads": _entry("broker_ads", _oauth(_REVOKE_URL)),
            "plain_oauth": _entry("plain_oauth", _oauth(None)),
            "manual_ads": _entry("manual_ads", None),
        },
    )


_FULL = {"client_id": "CID", "client_secret": "SECRET", "refresh_token": "RT-old"}


def _write(tmp_path: Path, root: dict[str, Any]) -> Path:
    path = tmp_path / ".mureo" / "credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(root))
    return path


def _root(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text()))


def _revoke_records(caplog: pytest.LogCaptureFixture) -> list[Any]:
    return [r for r in caplog.records if r.name == _LOGGER and r.levelname == "WARNING"]


# ---------------------------------------------------------------------------
# revoke_plugin_token
# ---------------------------------------------------------------------------


def _call_revoke() -> bool:
    return revoke_plugin_token(
        "broker_ads",
        revoke_url=_REVOKE_URL,
        token="RT-old",
        client_id="CID",
        client_secret="SECRET",
    )


@pytest.mark.unit
def test_revoke_plugin_token_success_logs_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(f"{_LOGGER}.revoke_token", return_value=True) as revoke:
        assert _call_revoke() is True
    assert revoke.call_args.kwargs == {
        "revoke_url": _REVOKE_URL,
        "token": "RT-old",
        "client_id": "CID",
        "client_secret": "SECRET",
        "client_auth": "basic",
        "headers": None,
    }
    assert _revoke_records(caplog) == []


@pytest.mark.unit
def test_revoke_plugin_token_refused_logs_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(f"{_LOGGER}.revoke_token", return_value=False):
        assert _call_revoke() is False
    records = _revoke_records(caplog)
    assert len(records) == 1
    assert "broker_ads" in records[0].getMessage()


@pytest.mark.unit
def test_revoke_plugin_token_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    with patch(
        f"{_LOGGER}.revoke_token",
        side_effect=ValueError("bad RT-old SECRET"),
    ):
        assert _call_revoke() is False
    records = _revoke_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "broker_ads" in message
    assert "ValueError" in message
    assert "RT-old" not in caplog.text
    assert "SECRET" not in caplog.text


@pytest.mark.unit
def test_revoke_plugin_token_transport_failure_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Through the real ``revoke_token``: a request that cannot be made is a
    single WARNING across every logger, not one per layer."""
    with (
        caplog.at_level("WARNING"),
        patch(
            "mureo.oauth_authcode._post_form",
            side_effect=httpx.ConnectError("down RT-old SECRET"),
        ),
    ):
        assert _call_revoke() is False
    records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(records) == 1
    assert records[0].name == _LOGGER
    assert "broker_ads" in records[0].getMessage()
    assert "ConnectError" in records[0].getMessage()
    assert "RT-old" not in caplog.text
    assert "SECRET" not in caplog.text


# ---------------------------------------------------------------------------
# disconnect_plugin_provider
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_unknown_provider_raises(tmp_path: Path) -> None:
    with pytest.raises(UnknownProviderError, match="nobody_ads"):
        disconnect_plugin_provider("nobody_ads", credentials_path=tmp_path / "c.json")


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_revokes_stored_token_then_removes_section(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, {"broker_ads": dict(_FULL), "other": {"k": "v"}})
    with patch(f"{_LOGGER}.revoke_token", return_value=True) as revoke:
        assert disconnect_plugin_provider("broker_ads", credentials_path=path) is True
    revoke.assert_called_once_with(
        revoke_url=_REVOKE_URL,
        token="RT-old",
        client_id="CID",
        client_secret="SECRET",
        client_auth="body",
        headers={"X-Example": "abc"},
    )
    assert _root(path) == {"other": {"k": "v"}}


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_backs_up_credentials_before_removing(tmp_path: Path) -> None:
    root = {"broker_ads": dict(_FULL), "other": {"k": "v"}}
    path = _write(tmp_path, root)
    with patch(f"{_LOGGER}.revoke_token", return_value=True):
        assert disconnect_plugin_provider("broker_ads", credentials_path=path) is True
    backup = path.with_name(path.name + ".bak")
    assert json.loads(backup.read_text()) == root
    assert _root(path) == {"other": {"k": "v"}}


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
@pytest.mark.parametrize(
    "revoke",
    [MagicMock(return_value=False), MagicMock(side_effect=OSError("down"))],
    ids=["refused", "raised"],
)
def test_disconnect_failed_revocation_still_removes_section(
    tmp_path: Path, revoke: Any, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path, {"broker_ads": dict(_FULL)})
    with patch(f"{_LOGGER}.revoke_token", revoke):
        assert disconnect_plugin_provider("broker_ads", credentials_path=path) is True
    assert "broker_ads" not in _root(path)
    records = _revoke_records(caplog)
    assert len(records) == 1
    assert "broker_ads" in records[0].getMessage()
    assert "RT-old" not in caplog.text
    assert "SECRET" not in caplog.text


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_without_revoke_url_does_not_revoke(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path, {"plain_oauth": dict(_FULL)})
    with patch(f"{_LOGGER}.revoke_token") as revoke:
        assert disconnect_plugin_provider("plain_oauth", credentials_path=path) is True
    revoke.assert_not_called()
    assert "plain_oauth" not in _root(path)
    assert _revoke_records(caplog) == []


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_token_without_client_credentials_skips_revocation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path, {"broker_ads": {"refresh_token": "RT-old"}})
    with patch(f"{_LOGGER}.revoke_token") as revoke:
        assert disconnect_plugin_provider("broker_ads", credentials_path=path) is True
    revoke.assert_not_called()
    assert "broker_ads" not in _root(path)
    records = _revoke_records(caplog)
    assert len(records) == 1
    assert "broker_ads" in records[0].getMessage()
    assert "RT-old" not in caplog.text


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_without_stored_token_does_not_revoke(tmp_path: Path) -> None:
    section = {"client_id": "CID", "client_secret": "SECRET"}
    path = _write(tmp_path, {"broker_ads": section})
    with patch(f"{_LOGGER}.revoke_token") as revoke:
        assert disconnect_plugin_provider("broker_ads", credentials_path=path) is True
    revoke.assert_not_called()
    assert "broker_ads" not in _root(path)


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_nothing_stored_writes_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path, {"other": {"k": "v"}})
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with patch(f"{_LOGGER}.revoke_token") as revoke:
        assert disconnect_plugin_provider("broker_ads", credentials_path=path) is False
    revoke.assert_not_called()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert not path.with_name(path.name + ".bak").exists()


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_without_credentials_file_creates_none(tmp_path: Path) -> None:
    path = tmp_path / ".mureo" / "credentials.json"
    assert disconnect_plugin_provider("broker_ads", credentials_path=path) is False
    assert not path.exists()


@pytest.mark.unit
@pytest.mark.usefixtures("_providers")
def test_disconnect_manual_provider_removes_section(tmp_path: Path) -> None:
    path = _write(tmp_path, {"manual_ads": {"client_id": "CID"}})
    with patch(f"{_LOGGER}.revoke_token") as revoke:
        assert disconnect_plugin_provider("manual_ads", credentials_path=path) is True
    revoke.assert_not_called()
    assert "manual_ads" not in _root(path)
