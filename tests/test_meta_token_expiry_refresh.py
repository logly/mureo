"""The Meta refresh clock follows the token's own expiry when it is known (#726).

``_should_refresh`` used to age the token against a fixed 53-day constant —
right for a long-lived *user* token (~60 days from issue), wrong for the
Business Manager system-user token the paste card stores, which carries its
own ``expires_at`` and can have been minted at any point before it was
pasted. A token pasted with 20 days left would sit untouched for another 33
days and die.

With a stored ``token_expires_at`` the threshold becomes *expiry − 7 days*;
without one the 53-day age rule is unchanged.

The exchange itself gains ``set_token_expires_in_60_days=true``, which is
what Meta documents for refreshing an expiring system-user token:
https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens
("To refresh an expiring system user access token, you need: fb_exchange_token
... client_id ... client_secret ... set_token_expires_in_60_days: set to true").
It is sent only on the branch that knows the token expires — the plain
long-lived user-token exchange, which Meta documents without that parameter,
is left exactly as it was.

Marks: unit — httpx is mocked, nothing outbound.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mureo.auth import MetaAdsCredentials, refresh_meta_token_if_needed

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _mock_save_token(request: pytest.FixtureRequest) -> Any:
    if "real_save" in {m.name for m in request.node.iter_markers()}:
        yield
    else:
        with patch("mureo.auth._save_meta_token"):
            yield


def _in_days(days: float) -> str:
    return (datetime.now(tz=timezone.utc) + timedelta(days=days)).isoformat()


def _days_ago_iso(days: float) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()


def _creds(
    *,
    token_obtained_at: str | None = None,
    token_expires_at: str | None = None,
    token_type: str | None = None,
) -> MetaAdsCredentials:
    return MetaAdsCredentials(
        access_token="old-token",
        app_id="app-123",
        app_secret="secret-456",
        token_obtained_at=token_obtained_at or _days_ago_iso(5),
        token_expires_at=token_expires_at,
        token_type=token_type,
    )


def _graph_ok(expires_in: int | None = 5183944) -> httpx.Response:
    payload: dict[str, Any] = {
        "access_token": "new-refreshed-token",
        "token_type": "bearer",
    }
    if expires_in is not None:
        payload["expires_in"] = expires_in
    return httpx.Response(
        200, json=payload, request=httpx.Request("POST", "https://example.com")
    )


def _patched_graph(response: httpx.Response) -> Any:
    patcher = patch("mureo.auth.httpx.AsyncClient")
    mock_client_cls = patcher.start()
    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client
    return patcher, mock_client


async def _assert_no_exchange(credentials: MetaAdsCredentials) -> None:
    """The credentials come back untouched AND no exchange was attempted.

    Asserting only ``result is credentials`` would pass for the wrong reason:
    ``refresh_meta_token_if_needed`` returns the originals when the exchange
    fails too, and it swallows every exception the call can raise (#578/#603),
    so a Graph double that blows up would be caught and look like a pass.
    The load-bearing assertion is therefore that Graph was never posted to;
    the double is a working one so a fired exchange would otherwise succeed.
    """

    patcher, mock_client = _patched_graph(_graph_ok())
    try:
        assert await refresh_meta_token_if_needed(credentials) is credentials
    finally:
        patcher.stop()
    mock_client.post.assert_not_awaited()


# ---------------------------------------------------------------------------
# The expiry-derived threshold
# ---------------------------------------------------------------------------


async def test_refreshes_a_young_token_that_expires_within_the_lead() -> None:
    """A 5-day-old token with 3 days of life left. The 53-day age rule says
    "fresh, leave it"; the stored expiry says "3 days from death". The expiry
    wins."""

    creds = _creds(token_obtained_at=_days_ago_iso(5), token_expires_at=_in_days(3))

    patcher, _client = _patched_graph(_graph_ok())
    try:
        result = await refresh_meta_token_if_needed(creds)
    finally:
        patcher.stop()

    assert result.access_token == "new-refreshed-token"


async def test_leaves_a_token_with_more_than_the_lead_remaining() -> None:
    creds = _creds(token_obtained_at=_days_ago_iso(5), token_expires_at=_in_days(20))

    await _assert_no_exchange(creds)


async def test_already_expired_token_is_still_attempted() -> None:
    """Past the expiry the exchange will very likely fail, but not trying
    guarantees it: the failure is logged and the original credentials come
    back, which is strictly more than silence."""

    creds = _creds(token_obtained_at=_days_ago_iso(70), token_expires_at=_in_days(-2))

    patcher, _client = _patched_graph(_graph_ok())
    try:
        result = await refresh_meta_token_if_needed(creds)
    finally:
        patcher.stop()

    assert result.access_token == "new-refreshed-token"


async def test_old_token_with_a_distant_expiry_is_not_refreshed_on_age() -> None:
    """The 53-day constant is a *fallback* for an unknown expiry, not a second
    trigger. A 60-day-old token that Meta says is good for another month is
    good for another month."""

    creds = _creds(token_obtained_at=_days_ago_iso(60), token_expires_at=_in_days(30))

    await _assert_no_exchange(creds)


@pytest.mark.parametrize("raw", ["", "not-a-date", "60"])
async def test_unparseable_expiry_falls_back_to_the_age_rule(raw: str) -> None:
    fresh = _creds(token_obtained_at=_days_ago_iso(10), token_expires_at=raw)
    await _assert_no_exchange(fresh)

    aged = _creds(token_obtained_at=_days_ago_iso(55), token_expires_at=raw)
    patcher, _client = _patched_graph(_graph_ok())
    try:
        result = await refresh_meta_token_if_needed(aged)
    finally:
        patcher.stop()
    assert result.access_token == "new-refreshed-token"


# ---------------------------------------------------------------------------
# A token Meta called permanent is never exchanged (#740)
# ---------------------------------------------------------------------------


async def test_a_permanent_token_is_never_exchanged() -> None:
    """Graph reports a never-expiring token as ``expires_at: 0``, which used
    to be indistinguishable from "unknown" — so with the app pair stored the
    53-day age clock fired and swapped a permanent token for a 60-day one, a
    strict downgrade that then kept the treadmill going (#740)."""

    creds = MetaAdsCredentials(
        access_token="old-token",
        app_id="app-123",
        app_secret="secret-456",
        token_obtained_at=_days_ago_iso(900),
        token_never_expires=True,
    )

    await _assert_no_exchange(creds)


async def test_a_permanent_token_outranks_a_stored_expiry() -> None:
    """Contradictory records: one says permanent, the other says it died
    last week. The exchange is the irreversible move, so the flag wins."""

    creds = MetaAdsCredentials(
        access_token="old-token",
        app_id="app-123",
        app_secret="secret-456",
        token_obtained_at=_days_ago_iso(70),
        token_expires_at=_in_days(-7),
        token_never_expires=True,
    )

    await _assert_no_exchange(creds)


async def test_a_permanent_system_user_token_is_left_alone() -> None:
    """The kind of token the maintainer's own install holds: Graph's
    debugger says "Expires: Never", the app pair is stored, and the age
    clock is long past."""

    creds = MetaAdsCredentials(
        access_token="old-token",
        app_id="app-123",
        app_secret="secret-456",
        token_obtained_at=_days_ago_iso(120),
        token_type="SYSTEM_USER",
        token_never_expires=True,
    )

    await _assert_no_exchange(creds)


async def test_expiry_alone_does_not_arm_the_refresh_without_the_app_pair() -> None:
    """No app_id/app_secret, no exchange — an operator who pasted a token
    without the app credentials gets the warning path, not a broken call."""

    creds = MetaAdsCredentials(
        access_token="old-token",
        app_id=None,
        app_secret=None,
        token_obtained_at=_days_ago_iso(5),
        token_expires_at=_in_days(1),
    )

    await _assert_no_exchange(creds)


# ---------------------------------------------------------------------------
# The exchange parameters
# ---------------------------------------------------------------------------


async def test_expiring_token_exchange_sets_the_60_day_flag() -> None:
    """``token_type`` is what arms the parameter, not the expiry. The two
    travel together for a pasted system-user token, but the expiry alone
    does not imply the kind — see ``test_meta_token_provenance``."""

    creds = _creds(
        token_obtained_at=_days_ago_iso(5),
        token_expires_at=_in_days(3),
        token_type="SYSTEM_USER",
    )

    patcher, client = _patched_graph(_graph_ok())
    try:
        await refresh_meta_token_if_needed(creds)
    finally:
        patcher.stop()

    sent = client.post.call_args.kwargs["data"]
    assert sent["set_token_expires_in_60_days"] == "true"
    assert sent["grant_type"] == "fb_exchange_token"
    # Still a POST: the app secret and the token never travel in a URL (#605).
    assert client.post.called


async def test_unknown_expiry_exchange_omits_the_60_day_flag() -> None:
    """The documented long-lived *user* token exchange carries no such
    parameter, and mureo does not add one to a call Meta documents without
    it."""

    creds = _creds(
        token_obtained_at=_days_ago_iso(55), token_expires_at=None, token_type=None
    )

    patcher, client = _patched_graph(_graph_ok())
    try:
        await refresh_meta_token_if_needed(creds)
    finally:
        patcher.stop()

    assert "set_token_expires_in_60_days" not in client.post.call_args.kwargs["data"]


# ---------------------------------------------------------------------------
# The new expiry is recorded
# ---------------------------------------------------------------------------


async def test_refreshed_credentials_carry_the_new_expiry() -> None:
    creds = _creds(token_obtained_at=_days_ago_iso(5), token_expires_at=_in_days(3))

    patcher, _client = _patched_graph(_graph_ok(expires_in=60 * 86400))
    try:
        result = await refresh_meta_token_if_needed(creds)
    finally:
        patcher.stop()

    assert result.token_expires_at is not None
    expires = datetime.fromisoformat(result.token_expires_at)
    remaining = expires - datetime.now(tz=timezone.utc)
    assert timedelta(days=59) < remaining < timedelta(days=61)


@pytest.mark.real_save
async def test_new_expiry_is_persisted(tmp_path: Path) -> None:
    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "old-token",
                    "app_id": "app-123",
                    "app_secret": "secret-456",
                    "token_obtained_at": _days_ago_iso(5),
                    "token_expires_at": _in_days(3),
                }
            }
        ),
        encoding="utf-8",
    )
    creds = _creds(token_obtained_at=_days_ago_iso(5), token_expires_at=_in_days(3))

    patcher, _client = _patched_graph(_graph_ok(expires_in=60 * 86400))
    try:
        await refresh_meta_token_if_needed(creds, path=cred_path)
    finally:
        patcher.stop()

    saved = json.loads(cred_path.read_text(encoding="utf-8"))["meta_ads"]
    assert saved["access_token"] == "new-refreshed-token"
    assert saved["token_expires_at"]
    assert saved["token_expires_at"] != _in_days(3)


@pytest.mark.real_save
async def test_a_stale_expiry_is_dropped_when_graph_reports_none(
    tmp_path: Path,
) -> None:
    """A response with no ``expires_in`` says nothing about the new token's
    life. Keeping the OLD token's expiry would describe a token that no
    longer exists — and would keep firing the refresh every call."""

    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "old-token",
                    "app_id": "app-123",
                    "app_secret": "secret-456",
                    "token_obtained_at": _days_ago_iso(5),
                    "token_expires_at": _in_days(3),
                }
            }
        ),
        encoding="utf-8",
    )
    creds = _creds(token_obtained_at=_days_ago_iso(5), token_expires_at=_in_days(3))

    patcher, _client = _patched_graph(_graph_ok(expires_in=None))
    try:
        result = await refresh_meta_token_if_needed(creds, path=cred_path)
    finally:
        patcher.stop()

    assert result.token_expires_at is None
    saved = json.loads(cred_path.read_text(encoding="utf-8"))["meta_ads"]
    assert "token_expires_at" not in saved


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_loader_reads_token_never_expires(tmp_path: Path) -> None:
    from mureo.auth import load_meta_ads_credentials

    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "tok",
                    "token_obtained_at": _days_ago_iso(1),
                    "token_never_expires": True,
                }
            }
        ),
        encoding="utf-8",
    )

    creds = load_meta_ads_credentials(cred_path)

    assert creds is not None
    assert creds.token_never_expires is True


def test_loader_defaults_token_never_expires_to_false(tmp_path: Path) -> None:
    """Every credential written before this field existed, and every one the
    OAuth path writes, has no verdict — and no verdict is not a promise."""

    from mureo.auth import load_meta_ads_credentials

    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps({"meta_ads": {"access_token": "tok"}}), encoding="utf-8"
    )

    creds = load_meta_ads_credentials(cred_path)

    assert creds is not None
    assert creds.token_never_expires is False


def test_loader_coerces_a_hand_edited_flag_to_a_bool(tmp_path: Path) -> None:
    """The file is hand-editable, so the field arrives as whatever JSON the
    operator typed. A truthy value means "permanent"; the stored type never
    leaks into the dataclass."""

    from mureo.auth import load_meta_ads_credentials

    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps({"meta_ads": {"access_token": "tok", "token_never_expires": "yes"}}),
        encoding="utf-8",
    )

    creds = load_meta_ads_credentials(cred_path)

    assert creds is not None
    assert creds.token_never_expires is True


def test_loader_reads_token_expires_at(tmp_path: Path) -> None:
    from mureo.auth import load_meta_ads_credentials

    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "tok",
                    "token_obtained_at": _days_ago_iso(1),
                    "token_expires_at": "2026-11-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    creds = load_meta_ads_credentials(cred_path)

    assert creds is not None
    assert creds.token_expires_at == "2026-11-01T00:00:00+00:00"
