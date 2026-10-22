"""The failure contract of every POST route in ``ConfigureHandler._POST_ROUTES``.

#864: a refused request is HTTP 400 with ``{"error": <snake_case code>,
"detail"?: ...}``; an action that was attempted and failed is HTTP 500 with
the same body. ``detail`` is a code or an exception class name, never a
sentence or a path. The routes are read from the route table when this module
is collected, so a new route is covered without editing this file — and the
bookkeeping test fails until the new route is given an input it must refuse
or is declared inputless.

Only the static table is covered. Routes dispatched by regex — ``/api/oauth/*``,
the plugin OAuth start (``/api/credentials/plugins/<p>/oauth/start``) and
``/api/ext/*`` — are outside ``_POST_ROUTES`` and not tested here.

What is blocked for every contract request: ``subprocess.run``,
``subprocess.Popen``, ``os.execv``, ``webbrowser.open``, httpx
(``Client.send`` / ``AsyncClient.send``, the HTTP client behind the web
layer's platform calls) and ``urllib.request.urlopen`` when called off the
test's main thread — that is, by the server; the test client's own requests
run on the main thread and pass. Each raises
``AssertionError("contract test reached <name>")`` and is recorded, and the
test fails if anything was. What is redirected: the autouse
``_isolate_credential_writes`` sends credential writes to a temp HOME, and
the cases chdir into ``tmp_path`` because STATE.json / STRATEGY.md resolve
from the working directory. Nothing else is redirected.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import urllib.request
import webbrowser
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mureo.byod.bundle import BundleImportError
from mureo.byod.installer import BYODImportError
from mureo.demo.installer import DemoInitError
from mureo.providers.installer import InstallResult
from mureo.web import version_check
from mureo.web.action_result import ActionResult
from mureo.web.handlers import ConfigureHandler
from tests.web_support import get, post, post_refused

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from mureo.web.server import ConfigureWizard

_ROUTES: tuple[str, ...] = tuple(ConfigureHandler._POST_ROUTES)

_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]*$")

#: ``detail``: a code or an exception class name — no space, no path.
_DETAIL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

#: One input per route that the route must refuse: the refusal stage 2 of
#: #864 fixed where the route had one, otherwise the handler's own check.
_INVALID_INPUTS: dict[str, dict[str, Any]] = {
    "/api/locale": {"locale": "fr"},
    "/api/host": {"host": "vscode"},
    "/api/providers/install": {"provider_id": "no-such-provider"},
    "/api/providers/confirm": {"provider_id": "no-such-provider"},
    "/api/providers/native-toggle": {"platform": "no_such_platform"},
    "/api/providers/remove": {"provider_id": "no-such-provider"},
    "/api/advisors/add": {},
    "/api/advisors/remove": {},
    "/api/credentials/env-var": {"name": "NOT_AN_ALLOWED_VAR", "value": "x"},
    "/api/credentials/remove": {"section": "no_such_section"},
    "/api/credentials/meta/token": {},
    "/api/credentials/plugins/save": {},
    # The three Amazon routes refuse on state, not body: the temp HOME
    # holds no credentials and the AMAZON_ADS_* fallback is unset.
    "/api/amazon/refresh-manifest": {},
    "/api/amazon/oauth/authorize-url": {},
    "/api/amazon/oauth/exchange": {},
    "/api/demo/init": {"target": "demo\x01dir"},
    "/api/byod/import": {"file_path": "relative.xlsx"},
    "/api/byod/remove": {},
    "/api/reports/clients/archive": {},
    "/api/strategy/currency": {"currency": 5},
    "/api/strategy/guardrails": {"set": "not-an-object"},
    "/api/settings/ops_history": {"enabled": "yes"},
}

#: Routes with nothing to refuse: the body is ignored, or its only field
#: (``host``, ``title``, ``kind``) falls back to a default instead of being
#: rejected. CSRF still applies; only the shape test skips them.
_NO_INVALID_INPUT: frozenset[str] = frozenset(
    {
        "/api/setup/basic",
        "/api/setup/basic/clear",
        "/api/upgrade",
        "/api/restart",
        "/api/updates/refresh",
        "/api/setup/mcp/remove",
        "/api/setup/hook/remove",
        "/api/setup/hook/install",
        "/api/setup/skills/remove",
        "/api/setup/skills/install",
        "/api/providers/hosted-status",
        "/api/byod/clear",
        "/api/shutdown",
        "/api/pick/directory",
        "/api/pick/file",
    }
)

#: Routes whose action must never run from this module, even if a future
#: change made them validate input: they stop or re-exec the server, run the
#: package upgrade, or open a native file dialog. They may never be given an
#: invalid input (the shape test dispatches every route it has an input
#: for); the CSRF test still covers them, because CSRF refuses before
#: dispatch. The failure table below dispatches the upgrade and the pickers
#: with the step that would act (discovery, the dialog process) patched.
_NEVER_DISPATCH: frozenset[str] = frozenset(
    {
        "/api/shutdown",
        "/api/restart",
        "/api/upgrade",
        "/api/pick/directory",
        "/api/pick/file",
    }
)

_AMAZON_ENV = (
    "AMAZON_ADS_CLIENT_ID",
    "AMAZON_ADS_CLIENT_SECRET",
    "AMAZON_ADS_ACCESS_TOKEN",
    "AMAZON_ADS_REFRESH_TOKEN",
    "AMAZON_ADS_REGION",
)


def _tripwire(reached: list[str], name: str) -> Callable[..., Any]:
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        reached.append(name)
        raise AssertionError(f"contract test reached {name}")

    return _raise


def _server_side_only(
    reached: list[str], name: str, real: Callable[..., Any]
) -> Callable[..., Any]:
    """Trip ``name`` off the main thread only, so the test client still works."""
    tripped = _tripwire(reached, name)

    def _guard(*args: Any, **kwargs: Any) -> Any:
        if threading.current_thread() is threading.main_thread():
            return real(*args, **kwargs)
        return tripped(*args, **kwargs)

    return _guard


@pytest.fixture
def tripwires(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[list[str]]:
    """Block every install / spawn / exec / browser / outbound call and record it.

    The handler runs on the server thread and may swallow the raised error
    into a 500 or an ``error`` envelope, so the record is what the test
    asserts on, after the request.
    """
    reached: list[str] = []
    monkeypatch.chdir(tmp_path)
    for name in _AMAZON_ENV:
        monkeypatch.delenv(name, raising=False)
    for target, attr, name in (
        (subprocess, "run", "subprocess.run"),
        (subprocess, "Popen", "subprocess.Popen"),
        (os, "execv", "os.execv"),
        (webbrowser, "open", "webbrowser.open"),
        (httpx.Client, "send", "httpx.Client.send"),
        (httpx.AsyncClient, "send", "httpx.AsyncClient.send"),
    ):
        monkeypatch.setattr(target, attr, _tripwire(reached, name))
    urlopen = _server_side_only(
        reached, "urllib.request.urlopen", urllib.request.urlopen
    )
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    yield reached
    assert reached == [], f"a contract request reached {reached}"


@pytest.mark.unit
class TestRouteTable:
    """The bookkeeping above stays in step with the route table."""

    def test_every_route_has_an_input_or_is_declared_inputless(self) -> None:
        missing = [
            path
            for path in _ROUTES
            if path not in _INVALID_INPUTS and path not in _NO_INVALID_INPUT
        ]
        assert missing == [], f"give each an input it must refuse: {missing}"

    def test_no_route_is_in_both_lists(self) -> None:
        assert set(_INVALID_INPUTS) & _NO_INVALID_INPUT == set()

    def test_every_listed_path_is_a_route(self) -> None:
        listed = set(_INVALID_INPUTS) | _NO_INVALID_INPUT | _NEVER_DISPATCH
        assert listed - set(_ROUTES) == set()

    def test_never_dispatched_routes_have_no_input(self) -> None:
        assert _NEVER_DISPATCH & set(_INVALID_INPUTS) == set()


@pytest.mark.unit
@pytest.mark.parametrize("path", _ROUTES)
def test_missing_csrf_is_refused(
    tripwires: list[str], wizard: ConfigureWizard, path: str
) -> None:
    status, body = post(wizard, path, _INVALID_INPUTS.get(path, {}), csrf=None)
    assert (status, body) == (403, {"error": "csrf_invalid"})


def _assert_contract_body(body: dict[str, Any]) -> None:
    error = body.get("error")
    assert isinstance(error, str) and _ERROR_CODE.fullmatch(error), body
    detail = body.get("detail")
    assert detail is None or (
        isinstance(detail, str) and _DETAIL.fullmatch(detail)
    ), body
    assert "status" not in body, body


@pytest.mark.unit
@pytest.mark.parametrize("path", [path for path in _ROUTES if path in _INVALID_INPUTS])
def test_refusal_has_the_contract_shape(
    tripwires: list[str], wizard: ConfigureWizard, path: str
) -> None:
    status, body = post(wizard, path, _INVALID_INPUTS[path])

    assert status == 400, (status, body)
    _assert_contract_body(body)


#: Routes whose action is attempted and fails: (route, body, the name the
#: failure is patched onto, the exception it raises or the value it returns,
#: the expected 500 body). The failure is raised inside the action wrapper,
#: so the case covers the wrapper's ``ActionResult.failed`` and the
#: route's ``send_result`` together.
_FAILURES: tuple[tuple[str, dict[str, Any], str, Any, dict[str, str]], ...] = (
    (
        "/api/setup/mcp/remove",
        {},
        "mureo.web.setup_actions.remove_mcp_config",
        OSError("disk"),
        {"error": "internal_error", "detail": "OSError"},
    ),
    (
        "/api/setup/hook/remove",
        {},
        "mureo.web.setup_actions.remove_credential_guard",
        PermissionError("denied"),
        {"error": "internal_error", "detail": "PermissionError"},
    ),
    (
        "/api/setup/hook/install",
        {},
        "mureo.web.setup_actions.auth_setup.install_credential_guard",
        OSError("disk"),
        {"error": "internal_error", "detail": "OSError"},
    ),
    (
        "/api/setup/skills/remove",
        {},
        "mureo.web.setup_actions.remove_skills",
        OSError("disk"),
        {"error": "internal_error", "detail": "OSError"},
    ),
    (
        "/api/setup/skills/install",
        {},
        "mureo.web.setup_actions.install_skills",
        FileNotFoundError("bundle"),
        {"error": "internal_error", "detail": "FileNotFoundError"},
    ),
    (
        "/api/providers/install",
        {"provider_id": "google-ads-official"},
        "mureo.providers.installer.run_install",
        InstallResult(returncode=2, stdout="", stderr="", argv=[]),
        {"error": "install_failed", "detail": "install_returncode_2"},
    ),
    (
        "/api/byod/clear",
        {},
        "mureo.web.byod_actions.clear_all",
        OSError("disk"),
        {"error": "internal_error", "detail": "OSError"},
    ),
    (
        "/api/byod/remove",
        {"google_ads": True},
        "mureo.web.byod_actions.remove_platform",
        BYODImportError("broken"),
        {"error": "byod_remove_failed", "detail": "BYODImportError"},
    ),
    (
        "/api/demo/init",
        {"scenario_name": "seasonality-trap", "target": "demo-dir"},
        "mureo.web.demo_actions.materialize",
        DemoInitError("directory is not empty"),
        {"error": "demo_init_failed", "detail": "DemoInitError"},
    ),
    (
        "/api/upgrade",
        {},
        "mureo.web.upgrade_action.discover_all_mureo_packages",
        OSError("metadata"),
        {"error": "internal_error", "detail": "OSError"},
    ),
    (
        "/api/pick/directory",
        {},
        "mureo.web.native_picker._invoke",
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        {"error": "picker_failed", "detail": "failed"},
    ),
    (
        "/api/pick/file",
        {"kind": "xlsx"},
        "mureo.web.native_picker._invoke",
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        {"error": "picker_failed", "detail": "failed"},
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "payload", "target", "outcome", "expected"),
    [pytest.param(*case, id=case[0]) for case in _FAILURES],
)
def test_failed_action_is_a_500_with_its_code(
    tripwires: list[str],
    wizard: ConfigureWizard,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, Any],
    target: str,
    outcome: Any,
    expected: dict[str, str],
) -> None:
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(target, _fail)
    status, body = post_refused(wizard, path, payload)

    assert (status, body) == (500, expected)
    _assert_contract_body(body)


class _BrokenRegistry:
    """A scenario registry that cannot be read."""

    def __iter__(self) -> Iterator[str]:
        raise KeyError("registry")


@pytest.mark.unit
def test_failed_scenario_listing_is_a_500_with_its_code(
    tripwires: list[str], wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /api/demo/scenarios`` answers a registry failure like a POST."""
    monkeypatch.setattr("mureo.web.demo_actions.SCENARIOS", _BrokenRegistry())
    status, body = get(wizard, "/api/demo/scenarios")

    assert (status, body) == (500, {"error": "internal_error", "detail": "KeyError"})
    _assert_contract_body(body)


@pytest.mark.unit
def test_failed_update_check_is_a_500_with_its_code(
    tripwires: list[str], wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /api/updates`` answers a cached failed check like a POST."""
    failed = ActionResult.failed("update_check_failed")
    monkeypatch.setattr(version_check, "_cached_result", failed)
    monkeypatch.setattr(version_check, "_cached_at_monotonic", time.monotonic())
    status, body = get(wizard, "/api/updates")

    assert (status, body) == (500, {"error": "update_check_failed"})
    _assert_contract_body(body)


@pytest.mark.unit
def test_failed_bundle_import_is_a_500_with_its_code(
    tripwires: list[str],
    wizard: ConfigureWizard,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The import needs a real ``.xlsx`` on disk to get past validation."""

    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise BundleImportError("no recognized tabs in /private/secret.xlsx")

    monkeypatch.setattr("mureo.web.byod_actions.import_bundle", _fail)
    bundle = tmp_path / "bundle.xlsx"
    bundle.write_bytes(b"PK\x03\x04stub")
    status, body = post_refused(wizard, "/api/byod/import", {"file_path": str(bundle)})

    assert (status, body) == (
        500,
        {"error": "bundle_import_failed", "detail": "BundleImportError"},
    )
