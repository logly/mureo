"""``set_token_expires_in_60_days`` is for system-user tokens only (#726).

Meta documents the parameter under "Refresh Access Token" for an expiring
**system user** access token
(https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens).
The long-lived *user* token exchange
(https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived)
is documented with the same ``grant_type=fb_exchange_token`` and no such
parameter.

The first cut of #726 used "we know when this token expires" as a proxy for
"this is a system-user token". That proxy is wrong, and it decays into the
wrong answer on its own: a browser-OAuth credential is stored with no
expiry, but the *first* refresh response carries ``expires_in``, which mureo
writes back as ``token_expires_at`` — so from the second refresh onward the
proxy says "system user" about a plain user token.

The provenance is now explicit: ``token_type`` is Graph's own
``debug_token`` verdict, recorded only where mureo actually asked, and only
``SYSTEM_USER`` arms the parameter. Anything else — including an inspection
that failed — leaves it off, which costs nothing: the exchange succeeds
either way and Meta returns a 60-day token.

Marks: unit — httpx is mocked, nothing touches the network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mureo.auth import (
    MetaAdsCredentials,
    load_meta_ads_credentials,
    refresh_meta_token_if_needed,
)

# ``asyncio_mode = "auto"`` in pyproject.toml runs the async tests; the
# two loader tests below are deliberately synchronous.
pytestmark = pytest.mark.unit

_FLAG = "set_token_expires_in_60_days"

# What Graph returns for a 60-day token: 5183944 seconds ≈ 59.99 days.
_EXPIRES_IN = 5183944


def _days_ago(days: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()


def _in_days(days: int) -> str:
    return (datetime.now(tz=timezone.utc) + timedelta(days=days)).isoformat()


def _graph_ok(token: str = "new-token") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": token,
            "token_type": "bearer",
            "expires_in": _EXPIRES_IN,
        },
        request=httpx.Request("POST", "https://graph.facebook.com/"),
    )


class _Graph:
    """Patch ``mureo.auth.httpx.AsyncClient`` and record every POST body."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self._patcher = patch("mureo.auth.httpx.AsyncClient")

    def __enter__(self) -> _Graph:
        cls = self._patcher.start()
        client = AsyncMock()

        async def _post(url: str, data: dict[str, Any] | None = None) -> httpx.Response:
            self.bodies.append(dict(data or {}))
            return _graph_ok(f"refreshed-{len(self.bodies)}")

        client.post = AsyncMock(side_effect=_post)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = client
        return self

    def __exit__(self, *exc: object) -> None:
        self._patcher.stop()

    @property
    def last_body(self) -> dict[str, Any]:
        assert self.bodies, "no exchange was attempted"
        return self.bodies[-1]


# ---------------------------------------------------------------------------
# The regression: two refresh cycles of a browser-OAuth credential
# ---------------------------------------------------------------------------


async def test_two_refresh_cycles_of_a_user_token_never_send_the_flag(
    tmp_path: Path,
) -> None:
    """The whole reported defect, start to finish.

    ``mureo auth setup``'s OAuth flow stores no ``token_expires_at``. Cycle
    one refreshes on the 53-day age rule and, because Graph answered with an
    ``expires_in``, writes an expiry to disk. Cycle two must still recognise
    this as a user token — under the old expiry-as-proxy rule it did not.
    """

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "user-token-from-oauth",
                    "app_id": "app-1",
                    "app_secret": "secret-1",
                    "token_obtained_at": _days_ago(55),
                }
            }
        ),
        encoding="utf-8",
    )

    with _Graph() as graph:
        # --- cycle 1: refreshed on age; no expiry stored yet.
        first = load_meta_ads_credentials(path)
        assert first.token_expires_at is None
        await refresh_meta_token_if_needed(first, path=path)
        assert _FLAG not in graph.last_body

        # The exchange response wrote an expiry back — this is the step that
        # used to flip the proxy.
        stored = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert stored["token_expires_at"], "expires_in should have been recorded"

        # --- cycle 2: bring the expiry inside the refresh lead and go again.
        stored["token_expires_at"] = _in_days(3)
        path.write_text(json.dumps({"meta_ads": stored}), encoding="utf-8")

        second = load_meta_ads_credentials(path)
        assert second.token_expires_at is not None
        await refresh_meta_token_if_needed(second, path=path)

    assert len(graph.bodies) == 2, "both cycles should have exchanged"
    assert (
        _FLAG not in graph.last_body
    ), "a plain user token must never be refreshed with the system-user flag"


async def test_a_pasted_system_user_token_does_send_the_flag(tmp_path: Path) -> None:
    """The other half of the pair: provenance recorded, parameter armed."""

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "pasted-system-user-token",
                    "app_id": "app-1",
                    "app_secret": "secret-1",
                    "token_obtained_at": _days_ago(5),
                    "token_expires_at": _in_days(3),
                    "token_type": "SYSTEM_USER",
                }
            }
        ),
        encoding="utf-8",
    )

    creds = load_meta_ads_credentials(path)
    assert creds.token_type == "SYSTEM_USER"

    with _Graph() as graph:
        await refresh_meta_token_if_needed(creds, path=path)

    assert graph.last_body[_FLAG] == "true"


# ---------------------------------------------------------------------------
# Provenance is what decides, not the expiry
# ---------------------------------------------------------------------------


async def test_known_expiry_alone_does_not_arm_the_flag() -> None:
    """An expiry with no provenance is exactly the state cycle two lands in."""

    creds = MetaAdsCredentials(
        access_token="tok",
        app_id="app-1",
        app_secret="secret-1",
        token_obtained_at=_days_ago(5),
        token_expires_at=_in_days(3),
        token_type=None,
    )

    with _Graph() as graph:
        await refresh_meta_token_if_needed(creds)

    assert _FLAG not in graph.last_body


@pytest.mark.parametrize("token_type", ["USER", "PAGE", "APP", "", "SYSTEM  USER"])
async def test_only_system_user_arms_the_flag(token_type: str) -> None:
    creds = MetaAdsCredentials(
        access_token="tok",
        app_id="app-1",
        app_secret="secret-1",
        token_obtained_at=_days_ago(5),
        token_expires_at=_in_days(3),
        token_type=token_type,
    )

    with _Graph() as graph:
        await refresh_meta_token_if_needed(creds)

    assert _FLAG not in graph.last_body


@pytest.mark.parametrize("token_type", ["SYSTEM_USER", "system_user", " System_User "])
async def test_graph_casing_and_padding_are_tolerated(token_type: str) -> None:
    """Graph's documented spelling is upper-case, but a value that round-trips
    through JSON and a UI should not decide a security-relevant branch on
    whitespace."""

    creds = MetaAdsCredentials(
        access_token="tok",
        app_id="app-1",
        app_secret="secret-1",
        token_obtained_at=_days_ago(5),
        token_expires_at=_in_days(3),
        token_type=token_type,
    )

    with _Graph() as graph:
        await refresh_meta_token_if_needed(creds)

    assert graph.last_body[_FLAG] == "true"


async def test_a_failed_inspection_leaves_the_flag_off() -> None:
    """``token_inspect_failed`` means mureo never learned the type. Guessing
    "probably system user, the card asks for one" is the guess that put the
    parameter on a user token in the first place — and omitting it costs
    nothing, since the exchange returns a 60-day token either way."""

    creds = MetaAdsCredentials(
        access_token="tok",
        app_id="app-1",
        app_secret="secret-1",
        # Old enough for the 53-day age rule, so the exchange really fires.
        token_obtained_at=_days_ago(55),
        token_expires_at=None,
        token_type=None,
    )

    with _Graph() as graph:
        await refresh_meta_token_if_needed(creds)

    assert _FLAG not in graph.last_body


# ---------------------------------------------------------------------------
# The field survives the round trip
# ---------------------------------------------------------------------------


async def test_refresh_preserves_the_provenance(tmp_path: Path) -> None:
    """Refreshing a system-user token yields another system-user token, so
    the type must survive — otherwise the flag arms exactly once and the
    install silently reverts to the user-token exchange."""

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "old",
                    "app_id": "app-1",
                    "app_secret": "secret-1",
                    "token_obtained_at": _days_ago(5),
                    "token_expires_at": _in_days(3),
                    "token_type": "SYSTEM_USER",
                }
            }
        ),
        encoding="utf-8",
    )

    with _Graph():
        refreshed = await refresh_meta_token_if_needed(
            load_meta_ads_credentials(path), path=path
        )

    assert refreshed.token_type == "SYSTEM_USER"
    stored = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
    assert stored["token_type"] == "SYSTEM_USER"


def test_loader_reads_token_type(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps({"meta_ads": {"access_token": "t", "token_type": "SYSTEM_USER"}}),
        encoding="utf-8",
    )

    assert load_meta_ads_credentials(path).token_type == "SYSTEM_USER"


def test_loader_defaults_to_no_provenance(tmp_path: Path) -> None:
    """Every credential written before this change — and every one written by
    the OAuth path — has no ``token_type``."""

    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"meta_ads": {"access_token": "t"}}), encoding="utf-8")

    assert load_meta_ads_credentials(path).token_type is None
