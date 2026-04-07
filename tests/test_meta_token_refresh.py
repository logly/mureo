"""Tests for Meta Ads Long-Lived Token auto-refresh (TDD: RED phase)"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import pytest

from mureo.auth import MetaAdsCredentials, refresh_meta_token_if_needed


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
        mock_client.get.return_value = mock_response
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
        mock_client.get.return_value = mock_response
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
        mock_client.get.side_effect = httpx.HTTPError("Network error")
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
        mock_client.get.return_value = mock_response
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
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await refresh_meta_token_if_needed(creds)

    mock_client.get.assert_called_once_with(
        "https://graph.facebook.com/v21.0/oauth/access_token",
        params={
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
        mock_client.get.return_value = mock_response
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
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await refresh_meta_token_if_needed(creds, path=cred_path)

    saved_data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert saved_data["google_ads"]["developer_token"] == "keep-me"
    assert saved_data["meta_ads"]["access_token"] == "new-token"
