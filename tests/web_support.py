"""HTTP helpers shared by the configure web server tests (#864).

The ``wizard`` fixture (``tests/conftest.py``) serves a real
``ConfigureWizard`` on 127.0.0.1; these functions are how a test talks to
it. They live in a module rather than in a fixture because module-level
helpers in the test files call them too, and a fixture cannot be reached
from there.

``post`` / ``get`` return ``(status, body)`` for every outcome, 2xx and
4xx/5xx alike, so a test asserts on the status it expects instead of on
which exception ``urllib`` raised. ``body`` is the decoded JSON object; a
response that is not one fails the test where it is read. ``post_ok`` /
``get_ok`` / ``post_refused`` are the same calls with the status asserted.
``get_text`` reads an HTML page; ``get_raw`` hands back the open response
for the tests that read headers or bytes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from http.client import HTTPResponse

    from mureo.web.server import ConfigureWizard

#: ``csrf`` default: send the wizard's own session token.
USE_SESSION_CSRF = "use_session"

#: Client-side deadline for one request. The slowest route under test
#: (the Amazon manifest refresh with its stubbed MCP session) needs more
#: than the 2 s most modules used; a passing request never waits for it.
REQUEST_TIMEOUT_SECONDS = 5.0


def route_url(wiz: ConfigureWizard, path: str) -> str:
    """Absolute loopback URL for ``path`` on the running wizard."""
    return f"http://127.0.0.1:{wiz.port}{path}"


def post(
    wiz: ConfigureWizard,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    csrf: str | None = USE_SESSION_CSRF,
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """POST ``payload`` as JSON and return ``(status, body)``.

    ``csrf`` is the ``X-CSRF-Token`` header: the session token by default,
    the given string otherwise, and no header at all for ``None``.
    ``raw_body`` replaces the JSON encoding of ``payload`` (for the
    invalid-JSON and oversized-body gates). ``headers`` are added last, so
    a key given there wins (a spoofed ``Host``).
    """
    data = raw_body if raw_body is not None else json.dumps(payload or {}).encode()
    request = urllib.request.Request(route_url(wiz, path), data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    if csrf == USE_SESSION_CSRF:
        request.add_header("X-CSRF-Token", wiz.session.csrf_token)
    elif csrf is not None:
        request.add_header("X-CSRF-Token", csrf)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    return _send(request)


def post_ok(
    wiz: ConfigureWizard,
    path: str,
    payload: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """``post`` that must answer 200; returns the body."""
    status, body = post(wiz, path, payload, **kwargs)
    assert status == 200, (status, body)
    return body


def post_refused(
    wiz: ConfigureWizard,
    path: str,
    payload: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[int, dict[str, Any]]:
    """``post`` that must answer an HTTP error; returns ``(status, body)``."""
    status, body = post(wiz, path, payload, **kwargs)
    assert status >= 400, f"expected an HTTP error, got {status}: {body}"
    return status, body


def get(
    wiz: ConfigureWizard, path: str, *, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    """GET a JSON route and return ``(status, body)``."""
    return _send(_get_request(wiz, path, headers))


def get_ok(
    wiz: ConfigureWizard, path: str, *, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """``get`` that must answer 200; returns the body."""
    status, body = get(wiz, path, headers=headers)
    assert status == 200, (status, body)
    return body


def get_text(wiz: ConfigureWizard, path: str) -> tuple[int, str]:
    """GET a page and return ``(status, decoded text)`` for any outcome."""
    request = _get_request(wiz, path, None)
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read().decode("utf-8")


def get_raw(wiz: ConfigureWizard, path: str) -> HTTPResponse:
    """GET ``path`` and return the open response, raising ``HTTPError`` on a
    4xx/5xx as ``urlopen`` does — for tests that read headers or raw bytes."""
    response: HTTPResponse = urllib.request.urlopen(
        route_url(wiz, path), timeout=REQUEST_TIMEOUT_SECONDS
    )
    return response


def _get_request(
    wiz: ConfigureWizard, path: str, headers: dict[str, str] | None
) -> urllib.request.Request:
    request = urllib.request.Request(route_url(wiz, path))
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    return request


def _send(request: urllib.request.Request) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return response.status, _json_object(response.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, _json_object(exc.read())


def _json_object(raw: bytes) -> dict[str, Any]:
    body = json.loads(raw.decode("utf-8"))
    if not isinstance(body, dict):
        raise AssertionError(f"expected a JSON object, got {type(body).__name__}")
    return body
