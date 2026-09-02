"""The root conftest keeps credential writes off the real machine (#739).

``tests/conftest.py::_isolate_credential_writes`` is the only thing standing
between a ``path``-less ``refresh_meta_token_if_needed`` /
``save_amazon_access_token`` in a test and the contributor's own
``~/.mureo/credentials.json`` — or, when a ``mureo.runtime_context_factory``
distribution is installed next to mureo, the host plugin's shared credential
store, which the resolver prefers over the default path entirely.

An isolation fixture that quietly stops working is worse than none, because
the suite still passes while writing stub tokens into a real file. So the
fixture gets its own pins: the home directory really moved, the factory group
really looks empty, the resolver really returns its default, and a full
``path``-less refresh really lands inside the temp home. The last test proves
the fixture does not overreach — a test that installs its own fake factory
still gets it.

Marks: unit — httpx is mocked, nothing touches the network.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mureo.auth import MetaAdsCredentials, refresh_meta_token_if_needed
from mureo.core import runtime_context
from mureo.core.runtime_context import (
    RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
    default_runtime_context,
    runtime_credentials_path,
)

# Every lookup below goes through the MODULE attribute, never a name imported
# into this module: the fixture (and the runtime-context tests) monkeypatch
# ``mureo.core.runtime_context.entry_points``, and a from-import would bind the
# original and pass vacuously.

pytestmark = pytest.mark.unit

#: The contributor's actual home, captured at IMPORT time. Collection runs
#: before any function-scoped fixture, so this is the value ``Path.home()``
#: would return if the fixture were not there — which is exactly what the
#: first test asserts it is no longer.
_REAL_HOME = Path(os.path.expanduser("~"))


def _aged_creds() -> MetaAdsCredentials:
    """A credential old enough that the 53-day age rule fires."""
    obtained = datetime.now(tz=timezone.utc) - timedelta(days=55)
    return MetaAdsCredentials(
        access_token="stale-token",
        app_id="app-1",
        app_secret="secret-1",
        token_obtained_at=obtained.isoformat(),
    )


class _Graph:
    """Patch ``mureo.auth.httpx.AsyncClient`` with a 200 exchange."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._patcher = patch("mureo.auth.httpx.AsyncClient")

    def __enter__(self) -> _Graph:
        cls = self._patcher.start()
        client = AsyncMock()
        client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": self._token,
                    "token_type": "bearer",
                    "expires_in": 5183944,
                },
                request=httpx.Request("POST", "https://graph.facebook.com/"),
            )
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = client
        return self

    def __exit__(self, *exc: object) -> None:
        self._patcher.stop()


class _FakeEP:
    """Stands in for an ``importlib.metadata`` entry point."""

    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


# ---------------------------------------------------------------------------
# The fixture's three moving parts
# ---------------------------------------------------------------------------


def test_the_home_directory_is_not_the_real_one() -> None:
    """``Path.home()`` follows ``HOME`` / ``USERPROFILE``, and both point at a
    temp dir for the duration of every test."""

    assert Path.home() != _REAL_HOME
    assert Path.home() == Path(os.environ["HOME"])


def test_no_runtime_context_factory_is_visible() -> None:
    """Whatever is installed in the interpreter, the resolver's group reads
    empty — the plugin relocation cannot engage."""

    visible = runtime_context.entry_points(
        group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP
    )
    assert list(visible) == []


def test_other_entry_point_groups_still_resolve() -> None:
    """Only the factory group is hidden; the wrapper delegates every other
    group untouched, so a test that enumerates providers or console scripts
    sees exactly what ``importlib.metadata`` would return."""

    from importlib.metadata import entry_points as real_entry_points

    seen = runtime_context.entry_points(group="console_scripts")
    assert sorted(ep.name for ep in seen) == sorted(
        ep.name for ep in real_entry_points(group="console_scripts")
    )


def test_the_resolver_returns_the_caller_default(tmp_path: Path) -> None:
    """With no factory visible, ``runtime_credentials_path`` hands back the
    default it was given rather than a store's location."""

    sentinel = tmp_path / "sentinel" / "credentials.json"
    assert runtime_credentials_path(sentinel) == sentinel


# ---------------------------------------------------------------------------
# The write that used to escape
# ---------------------------------------------------------------------------


async def test_a_path_less_refresh_writes_inside_the_temp_home() -> None:
    """The #739 reproduction, with the fixture in place: a mocked 200 makes
    the refresh succeed, the save runs for real, and it lands under the temp
    home instead of the contributor's own credentials file."""

    with _Graph("refreshed-in-temp-home"):
        await refresh_meta_token_if_needed(_aged_creds())

    written = Path.home() / ".mureo" / "credentials.json"
    assert written.exists()
    # Inside the fixture's temp home, and not the contributor's own file. Not
    # "outside the real home": on Windows the runner's temp directory lives
    # under %USERPROFILE%\AppData\Local\Temp, so every temp home is inside
    # the real one and that stricter check fails for the wrong reason.
    temp_home = Path(os.environ["HOME"]).resolve()
    assert written.resolve().is_relative_to(temp_home)
    assert written.resolve() != (_REAL_HOME / ".mureo" / "credentials.json").resolve()

    section = json.loads(written.read_text(encoding="utf-8"))["meta_ads"]
    assert section["access_token"] == "refreshed-in-temp-home"


# ---------------------------------------------------------------------------
# ...without disarming the tests that need a factory
# ---------------------------------------------------------------------------


async def test_a_test_installed_factory_still_steers_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture hides *installed* factories, not the fake ones the
    runtime-context tests inject: those patch the same module attribute later
    in the stack, so their stub wins for the length of the test."""

    tenant = tmp_path / "tenant" / "credentials.json"

    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP
        return [
            _FakeEP(
                "tenant",
                lambda: default_runtime_context(credentials_path=tenant),
            )
        ]

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)

    with _Graph("refreshed-for-the-tenant"):
        await refresh_meta_token_if_needed(_aged_creds())

    section = json.loads(tenant.read_text(encoding="utf-8"))["meta_ads"]
    assert section["access_token"] == "refreshed-for-the-tenant"
    assert not (Path.home() / ".mureo" / "credentials.json").exists()
