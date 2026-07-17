"""Regression: ``_WizardHandler._read_form`` must safely handle a hostile
or malformed ``Content-Length`` header.

Before the fix a negative ``Content-Length`` reached ``rfile.read(-1)``,
which drains the socket to EOF and hangs the keep-alive worker thread; a
non-numeric value raised an uncaught ``ValueError`` that surfaced as a 500.
Both now resolve to a rejection (``None``) without touching the socket,
while the byte cap and the happy path are preserved.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

from mureo.cli.web_auth import _WizardHandler


def _call_read_form(content_length: str | None, body: bytes) -> tuple[Any, io.BytesIO]:
    """Invoke the real ``_read_form`` against a lightweight fake handler."""
    headers: dict[str, str] = {}
    if content_length is not None:
        headers["Content-Length"] = content_length
    rfile = io.BytesIO(body)
    fake = SimpleNamespace(
        headers=headers,
        rfile=rfile,
        _MAX_FORM_BYTES=_WizardHandler._MAX_FORM_BYTES,
    )
    result = _WizardHandler._read_form(fake)  # type: ignore[arg-type]
    return result, rfile


def test_read_form_rejects_negative_content_length() -> None:
    # A negative length must be refused WITHOUT reading the socket, so the
    # keep-alive worker thread cannot hang on rfile.read(-1).
    result, rfile = _call_read_form("-1", b"anything-still-here")
    assert result is None
    assert rfile.tell() == 0, "socket was read despite a negative Content-Length"


def test_read_form_rejects_non_numeric_content_length() -> None:
    result, rfile = _call_read_form("not-a-number", b"payload")
    assert result is None
    assert rfile.tell() == 0


def test_read_form_rejects_oversized_content_length() -> None:
    oversized = str(_WizardHandler._MAX_FORM_BYTES + 1)
    result, _ = _call_read_form(oversized, b"x")
    assert result is None


def test_read_form_missing_header_returns_empty() -> None:
    result, _ = _call_read_form(None, b"")
    assert result == {}


def test_read_form_parses_valid_body() -> None:
    body = b"csrf_token=abc&developer_token=xyz"
    result, _ = _call_read_form(str(len(body)), body)
    assert result == {"csrf_token": "abc", "developer_token": "xyz"}
