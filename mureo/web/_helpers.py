"""Shared helpers for the configure-UI HTTP server.

Stdlib-only utilities for request parsing, response writing, Host
header validation, CSRF comparison, atomic JSON writes, and security
header attachment. Reused by every endpoint in ``handlers.py``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets as _secrets
import tempfile
import urllib.parse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler
    from pathlib import Path

logger = logging.getLogger(__name__)

# Cap form bodies to a small size — the configure UI only ever POSTs
# short JSON payloads (tens of bytes).
MAX_BODY_BYTES = 16 * 1024


def fresh_csrf_token() -> str:
    """Return a URL-safe random CSRF token."""
    return _secrets.token_urlsafe(32)


def compare_csrf(supplied: str, expected: str) -> bool:
    """Constant-time CSRF token comparison."""
    if not supplied or not expected:
        return False
    return _secrets.compare_digest(supplied, expected)


def host_header_ok(host_header: str, port: int) -> bool:
    """Reject requests where the Host header is not loopback.

    Defends against DNS-rebinding: a malicious origin could resolve its
    own domain to ``127.0.0.1`` and trick the browser into POSTing to
    our localhost server. We require the Host header to match the
    loopback names we bound to.
    """
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
    return host_header in allowed


def read_body(handler: BaseHTTPRequestHandler) -> bytes | None:
    """Read up to ``MAX_BODY_BYTES`` from ``handler.rfile``.

    Returns ``None`` if the declared length exceeds the cap. Returns an
    empty bytes object for zero-length bodies.
    """
    length_str = handler.headers.get("Content-Length", "0") or "0"
    try:
        length = int(length_str)
    except ValueError:
        return None
    if length < 0 or length > MAX_BODY_BYTES:
        return None
    if length == 0:
        return b""
    return handler.rfile.read(length)


def parse_json_body(body: bytes) -> dict[str, Any] | None:
    """Parse a request body as a JSON object.

    Returns ``None`` for invalid JSON or non-object payloads. The
    configure UI only ever POSTs JSON objects.
    """
    if not body:
        return None
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def parse_form_body(body: bytes) -> dict[str, str] | None:
    """Parse application/x-www-form-urlencoded body to flat dict."""
    if not body:
        return {}
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parsed = urllib.parse.parse_qs(decoded, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}


SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        (
            "default-src 'none'; "
            "style-src 'self'; "
            "script-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'; "
            "object-src 'none'; "
            "form-action 'self'"
        ),
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store, no-cache, must-revalidate"),
    ("Pragma", "no-cache"),
)


def send_json(
    handler: BaseHTTPRequestHandler,
    payload: dict[str, Any] | list[Any],
    status: int = 200,
) -> None:
    """Write a JSON response with the security-headers stack attached."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    for name, value in SECURITY_HEADERS:
        handler.send_header(name, value)
    handler.end_headers()
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        handler.wfile.write(body)


def send_bytes(
    handler: BaseHTTPRequestHandler,
    body: bytes,
    *,
    content_type: str,
    status: int = 200,
) -> None:
    """Write a binary response (used for static asset serving)."""
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    for name, value in SECURITY_HEADERS:
        handler.send_header(name, value)
    handler.end_headers()
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        handler.wfile.write(body)


def send_error_json(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    """Emit a JSON error envelope rather than the default text body."""
    send_json(handler, {"error": message}, status=status)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` atomically (temp file + rename).

    Sets mode 0o600 on the final file so credential-adjacent JSON does
    not become world-readable. Parent directory is created if absent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def read_json_safe(path: Path) -> dict[str, Any]:
    """Read ``path`` as a JSON object. Return ``{}`` on any error."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed
