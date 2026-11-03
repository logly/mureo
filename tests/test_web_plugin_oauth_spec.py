"""#970 — ``persist_plugin_token``: save the obtained token, then revoke the
token it replaced.

The new token reaches disk before the old one is revoked, so a save that
fails leaves the old token working. The revocation presents the client
credentials the old token was issued to (the stored section's), falling back
to the flow's own pair when the section does not hold both.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.oauth_authcode import AuthCodeResult
from mureo.web.plugin_oauth_spec import PluginOAuthSpec, persist_plugin_token

if TYPE_CHECKING:
    from pathlib import Path

_REVOKE_URL = "https://broker.example.com/oauth/revoke"
_REVOKE = "mureo.web.plugin_oauth_revoke.revoke_token"
_RESULT = AuthCodeResult(refresh_token="RT-new", access_token="AT")
_OLD = {
    "client_id": "CID-old",
    "client_secret": "SECRET-old",
    "refresh_token": "RT-old",
}


def _spec(**overrides: Any) -> PluginOAuthSpec:
    kwargs: dict[str, Any] = {
        "provider": "broker_ads",
        "target_field": "refresh_token",
        "token_url": "https://broker.example.com/oauth/token",
        "client_id": "CID-new",
        "client_secret": "SECRET-new",
        "redirect_uri": "http://127.0.0.1:1/oauth/callback",
        "state": "state-xyz",
        "persist_values": {"client_id": "CID-new", "client_secret": "SECRET-new"},
        "client_id_field": "client_id",
        "client_secret_field": "client_secret",
        "revoke_url": _REVOKE_URL,
    }
    kwargs.update(overrides)
    return PluginOAuthSpec(**kwargs)


def _write(tmp_path: Path, section: dict[str, Any]) -> Path:
    path = tmp_path / ".mureo" / "credentials.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"broker_ads": section}))
    return path


def _stored(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text())["broker_ads"])


def _revoked_with(revoke: MagicMock, client_id: str, client_secret: str) -> None:
    revoke.assert_called_once_with(
        revoke_url=_REVOKE_URL,
        token="RT-old",
        client_id=client_id,
        client_secret=client_secret,
        client_auth="basic",
        headers=None,
    )


@pytest.mark.unit
def test_new_token_is_on_disk_before_the_old_one_is_revoked(tmp_path: Path) -> None:
    path = _write(tmp_path, dict(_OLD))
    on_disk_at_revocation: list[str] = []

    def _revoke(**_kwargs: Any) -> bool:
        on_disk_at_revocation.append(_stored(path)["refresh_token"])
        return True

    with patch(_REVOKE, side_effect=_revoke):
        persist_plugin_token(_spec(), _RESULT, path)
    assert on_disk_at_revocation == ["RT-new"]


@pytest.mark.unit
def test_failed_save_leaves_the_old_token_unrevoked(tmp_path: Path) -> None:
    path = _write(tmp_path, dict(_OLD))
    revoke = MagicMock(return_value=True)
    with (
        patch(_REVOKE, revoke),
        patch(
            "mureo.web.plugin_oauth_spec.FilesystemSecretStore.save",
            side_effect=OSError("disk full"),
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        persist_plugin_token(_spec(), _RESULT, path)
    revoke.assert_not_called()
    assert _stored(path) == _OLD


@pytest.mark.unit
def test_revocation_uses_the_stored_client_credentials(tmp_path: Path) -> None:
    path = _write(tmp_path, dict(_OLD))
    revoke = MagicMock(return_value=True)
    with patch(_REVOKE, revoke):
        persist_plugin_token(_spec(), _RESULT, path)
    _revoked_with(revoke, "CID-old", "SECRET-old")
    assert _stored(path) == {
        "client_id": "CID-new",
        "client_secret": "SECRET-new",
        "refresh_token": "RT-new",
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("section", "overrides"),
    [
        ({"refresh_token": "RT-old"}, {}),
        ({"client_id": "CID-old", "refresh_token": "RT-old"}, {}),
        ({**_OLD, "client_secret": 7}, {}),
        (dict(_OLD), {"client_id_field": None, "client_secret_field": None}),
    ],
    ids=["none-stored", "one-stored", "not-a-string", "no-field-keys"],
)
def test_revocation_falls_back_to_the_flow_client_credentials(
    tmp_path: Path, section: dict[str, Any], overrides: dict[str, Any]
) -> None:
    path = _write(tmp_path, section)
    revoke = MagicMock(return_value=True)
    with patch(_REVOKE, revoke):
        persist_plugin_token(_spec(**overrides), _RESULT, path)
    _revoked_with(revoke, "CID-new", "SECRET-new")
    assert _stored(path)["refresh_token"] == "RT-new"


@pytest.mark.unit
def test_default_spec_client_field_keys_are_none() -> None:
    spec = PluginOAuthSpec(
        provider="p",
        target_field="refresh_token",
        token_url="https://a.test/token",
        client_id="c",
        client_secret="s",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        state="x",
    )
    assert spec.client_id_field is None
    assert spec.client_secret_field is None
