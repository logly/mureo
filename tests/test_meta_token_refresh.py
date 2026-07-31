"""Tests for Meta Ads Long-Lived Token auto-refresh (TDD: RED phase)"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

import httpx
import pytest

import mureo.auth as auth_mod
from mureo.auth import (
    MetaAdsCredentials,
    load_meta_ads_credentials,
    refresh_meta_token_if_needed,
)
from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
)


@pytest.fixture(autouse=True)
def _mock_save_token(request):
    """Prevent tests from writing to real ~/.mureo/credentials.json.

    Tests that explicitly use tmp_path for credential file operations
    can opt out by using @pytest.mark.real_save marker.
    """
    if "real_save" in {m.name for m in request.node.iter_markers()}:
        yield
    else:
        with patch("mureo.auth._save_meta_token"):
            yield


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()


def _make_creds(
    *,
    access_token: str = "old-token",
    app_id: str | None = "app-123",
    app_secret: str | None = "secret-456",
    token_obtained_at: str | None = None,
) -> MetaAdsCredentials:
    return MetaAdsCredentials(
        access_token=access_token,
        app_id=app_id,
        app_secret=app_secret,
        token_obtained_at=token_obtained_at,
    )


def _write_credentials(path: Path, meta_section: dict[str, Any]) -> None:
    data = {"meta_ads": meta_section}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. No refresh when token is fresh (10 days old)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_no_refresh_when_token_is_fresh() -> None:
    """Token obtained 10 days ago should NOT be refreshed."""
    creds = _make_creds(token_obtained_at=_days_ago_iso(10))

    result = await refresh_meta_token_if_needed(creds)

    assert result is creds  # Same object, no refresh occurred


# ---------------------------------------------------------------------------
# 2. Refresh when token is expiring soon (55 days old)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_refresh_when_token_expiring_soon() -> None:
    """Token obtained 55 days ago (>53 threshold) should trigger refresh."""
    creds = _make_creds(token_obtained_at=_days_ago_iso(55))

    mock_response = httpx.Response(
        200,
        json={
            "access_token": "new-refreshed-token",
            "token_type": "bearer",
            "expires_in": 5183944,
        },
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await refresh_meta_token_if_needed(creds)

    assert result.access_token == "new-refreshed-token"
    assert result.token_obtained_at is not None
    assert result.token_obtained_at != creds.token_obtained_at


# ---------------------------------------------------------------------------
# 3. No refresh without app credentials
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_no_refresh_without_app_id() -> None:
    """If app_id is None, skip refresh."""
    creds = _make_creds(
        app_id=None,
        token_obtained_at=_days_ago_iso(55),
    )

    result = await refresh_meta_token_if_needed(creds)

    assert result is creds


@pytest.mark.unit
async def test_no_refresh_without_app_secret() -> None:
    """If app_secret is None, skip refresh."""
    creds = _make_creds(
        app_secret=None,
        token_obtained_at=_days_ago_iso(55),
    )

    result = await refresh_meta_token_if_needed(creds)

    assert result is creds


# ---------------------------------------------------------------------------
# 4. No refresh without token_obtained_at
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_no_refresh_without_obtained_at() -> None:
    """If token_obtained_at is None, skip refresh."""
    creds = _make_creds(token_obtained_at=None)

    result = await refresh_meta_token_if_needed(creds)

    assert result is creds


# ---------------------------------------------------------------------------
# 5. Refresh updates credentials file
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.real_save
async def test_refresh_updates_credentials_file(tmp_path: Path) -> None:
    """After refresh, credentials.json should contain the new token."""
    cred_path = tmp_path / "credentials.json"
    _write_credentials(
        cred_path,
        {
            "access_token": "old-token",
            "app_id": "app-123",
            "app_secret": "secret-456",
            "token_obtained_at": _days_ago_iso(55),
        },
    )

    creds = _make_creds(token_obtained_at=_days_ago_iso(55))

    mock_response = httpx.Response(
        200,
        json={
            "access_token": "new-refreshed-token",
            "token_type": "bearer",
            "expires_in": 5183944,
        },
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await refresh_meta_token_if_needed(creds, path=cred_path)

    # Verify file was updated
    saved_data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert saved_data["meta_ads"]["access_token"] == "new-refreshed-token"
    assert "token_obtained_at" in saved_data["meta_ads"]


# ---------------------------------------------------------------------------
# 6. Refresh failure returns original credentials
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_refresh_failure_returns_original() -> None:
    """If API call fails, return original credentials without crashing."""
    creds = _make_creds(token_obtained_at=_days_ago_iso(55))

    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPError("Network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await refresh_meta_token_if_needed(creds)

    assert result is creds


@pytest.mark.unit
async def test_refresh_failure_on_non_200_returns_original() -> None:
    """If API returns non-200, return original credentials."""
    creds = _make_creds(token_obtained_at=_days_ago_iso(55))

    mock_response = httpx.Response(
        400,
        json={"error": {"message": "Invalid token"}},
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await refresh_meta_token_if_needed(creds)

    assert result is creds


# ---------------------------------------------------------------------------
# 7. Verify correct API call parameters
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_refresh_api_call_parameters() -> None:
    """Verify the correct endpoint and params are used for the refresh call."""
    creds = _make_creds(token_obtained_at=_days_ago_iso(55))

    mock_response = httpx.Response(
        200,
        json={
            "access_token": "new-token",
            "token_type": "bearer",
            "expires_in": 5183944,
        },
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await refresh_meta_token_if_needed(creds)

    mock_client.post.assert_called_once_with(
        "https://graph.facebook.com/v21.0/oauth/access_token",
        data={
            "grant_type": "fb_exchange_token",
            "client_id": "app-123",
            "client_secret": "secret-456",
            "fb_exchange_token": "old-token",
        },
    )


# ---------------------------------------------------------------------------
# 8. Token at exact threshold boundary (53 days)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_refresh_at_exact_threshold() -> None:
    """Token exactly 53 days old should trigger refresh."""
    creds = _make_creds(token_obtained_at=_days_ago_iso(53))

    mock_response = httpx.Response(
        200,
        json={
            "access_token": "refreshed-at-boundary",
            "token_type": "bearer",
            "expires_in": 5183944,
        },
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await refresh_meta_token_if_needed(creds)

    assert result.access_token == "refreshed-at-boundary"


@pytest.mark.unit
async def test_no_refresh_at_52_days() -> None:
    """Token 52 days old should NOT trigger refresh (below 53-day threshold)."""
    creds = _make_creds(token_obtained_at=_days_ago_iso(52))

    result = await refresh_meta_token_if_needed(creds)

    assert result is creds


# ---------------------------------------------------------------------------
# 9. Credentials file preserves other sections
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.real_save
async def test_refresh_preserves_other_credential_sections(
    tmp_path: Path,
) -> None:
    """Refreshing Meta token should not clobber google_ads section."""
    cred_path = tmp_path / "credentials.json"
    full_data = {
        "google_ads": {"developer_token": "keep-me"},
        "meta_ads": {
            "access_token": "old-token",
            "app_id": "app-123",
            "app_secret": "secret-456",
            "token_obtained_at": _days_ago_iso(55),
        },
    }
    cred_path.write_text(json.dumps(full_data), encoding="utf-8")

    creds = _make_creds(token_obtained_at=_days_ago_iso(55))

    mock_response = httpx.Response(
        200,
        json={
            "access_token": "new-token",
            "token_type": "bearer",
            "expires_in": 5183944,
        },
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await refresh_meta_token_if_needed(creds, path=cred_path)

    saved_data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert saved_data["google_ads"]["developer_token"] == "keep-me"
    assert saved_data["meta_ads"]["access_token"] == "new-token"


# ---------------------------------------------------------------------------
# 10. #510 — a ``path=None`` refresh must write where the loader reads
#
# ``load_meta_ads_credentials()`` resolves through ``_resolve_secret_store``
# (the active ``RuntimeContext``'s store), while this refresh used to fall
# back to the legacy ``~/.mureo/credentials.json`` unconditionally. Under a
# runtime that relocates the credentials file the 53-day refresh therefore
# wrote a file nobody reads, so every later process re-refreshed from the
# same aging stored token until it expired. The destination is now resolved
# through ``auth._resolve_write_path`` — i.e.
# ``runtime_credentials_path`` — exactly like the Amazon writer.
#
# Entry-point stubs and the fake stores mirror
# ``tests/test_web_credentials_runtime_alignment.py``.
# ---------------------------------------------------------------------------


class _FakeEP:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    """Stub ``mureo.core.runtime_context.entry_points`` for the
    runtime-context factory group."""

    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "mureo.runtime_context_factory"
        return eps

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)


@pytest.fixture()
def _reset_runtime_ctx() -> Iterator[None]:
    """Each test starts and ends with a clean resolver cache so the
    process-wide singleton cannot bleed between tests."""
    reset_runtime_context()
    yield
    reset_runtime_context()


def _pin_legacy_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the legacy fallback at a tmp file so the real
    ``~/.mureo/credentials.json`` is never touched by these tests."""
    legacy = tmp_path / "legacy" / "credentials.json"
    monkeypatch.setattr(auth_mod, "_resolve_default_path", lambda: legacy)
    return legacy


@contextlib.contextmanager
def _graph_returns(token: str) -> Iterator[None]:
    """Stub the Graph token-exchange call with a 200 returning ``token``."""
    response = httpx.Response(
        200,
        json={"access_token": token, "token_type": "bearer", "expires_in": 5183944},
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        yield


@pytest.mark.unit
@pytest.mark.real_save
@pytest.mark.usefixtures("_reset_runtime_ctx")
async def test_refresh_writes_to_the_store_declared_credentials_write_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store advertising ``credentials_write_path`` steers the
    ``path=None`` refresh; the legacy default stays untouched."""
    legacy = _pin_legacy_default(monkeypatch, tmp_path)
    tenant = tmp_path / "tenant-a" / "credentials.json"

    class _LayeredSecretStore:
        """Filesystem-backed, but not a ``FilesystemSecretStore``."""

        credentials_write_path = tenant

        def load(self, key: str) -> dict[str, Any]:  # pragma: no cover
            return {}

        def save(self, key: str, value: dict[str, Any]) -> None:  # pragma: no cover
            return None

        def delete(self, key: str) -> None:  # pragma: no cover
            return None

    ctx = dataclasses.replace(
        default_runtime_context(), secret_store=_LayeredSecretStore()
    )
    _patch_entry_points(monkeypatch, [_FakeEP("tenant", lambda: ctx)])

    creds = _make_creds(token_obtained_at=_days_ago_iso(55))
    with _graph_returns("new-refreshed-token"):
        await refresh_meta_token_if_needed(creds)

    saved = json.loads(tenant.read_text(encoding="utf-8"))
    assert saved["meta_ads"]["access_token"] == "new-refreshed-token"
    assert not legacy.exists()


@pytest.mark.unit
@pytest.mark.real_save
@pytest.mark.usefixtures("_reset_runtime_ctx")
async def test_refresh_round_trips_through_the_runtime_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh then load with ``path=None`` must see the same token —
    the read and the write agree on one location."""
    legacy = _pin_legacy_default(monkeypatch, tmp_path)
    tenant = tmp_path / "tenant-b" / "credentials.json"
    _write_credentials(
        tenant,
        {
            "access_token": "old-token",
            "app_id": "app-123",
            "app_secret": "secret-456",
            "token_obtained_at": _days_ago_iso(55),
        },
    )
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("tenant", lambda: default_runtime_context(credentials_path=tenant))],
    )

    creds = _make_creds(token_obtained_at=_days_ago_iso(55))
    with _graph_returns("new-refreshed-token"):
        await refresh_meta_token_if_needed(creds)

    reloaded = load_meta_ads_credentials()
    assert reloaded is not None
    assert reloaded.access_token == "new-refreshed-token"
    assert reloaded.app_id == "app-123"  # preserved
    assert not legacy.exists()


@pytest.mark.unit
@pytest.mark.real_save
@pytest.mark.usefixtures("_reset_runtime_ctx")
async def test_refresh_without_override_keeps_the_legacy_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No factory registered → single-backend installs keep writing
    ``~/.mureo/credentials.json`` exactly as before."""
    legacy = _pin_legacy_default(monkeypatch, tmp_path)
    _patch_entry_points(monkeypatch, [])

    creds = _make_creds(token_obtained_at=_days_ago_iso(55))
    with _graph_returns("new-refreshed-token"):
        await refresh_meta_token_if_needed(creds)

    saved = json.loads(legacy.read_text(encoding="utf-8"))
    assert saved["meta_ads"]["access_token"] == "new-refreshed-token"


@pytest.mark.unit
@pytest.mark.real_save
@pytest.mark.usefixtures("_reset_runtime_ctx")
async def test_refresh_explicit_path_wins_over_the_runtime_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The explicit-path branch is unchanged: a caller that names its own
    credentials file must not be redirected."""
    legacy = _pin_legacy_default(monkeypatch, tmp_path)
    tenant = tmp_path / "tenant-c" / "credentials.json"
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("tenant", lambda: default_runtime_context(credentials_path=tenant))],
    )

    cred_path = tmp_path / "explicit" / "credentials.json"
    _write_credentials(cred_path, {"access_token": "old-token"})

    creds = _make_creds(token_obtained_at=_days_ago_iso(55))
    with _graph_returns("new-refreshed-token"):
        await refresh_meta_token_if_needed(creds, path=cred_path)

    saved = json.loads(cred_path.read_text(encoding="utf-8"))
    assert saved["meta_ads"]["access_token"] == "new-refreshed-token"
    assert not tenant.exists()
    assert not legacy.exists()
