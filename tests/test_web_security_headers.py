"""Security headers attached by ``mureo.web._helpers``.

Every HTML / JSON / static-asset response from the configure-UI must
carry the full SECURITY_HEADERS stack: CSP locked down to 'self'-only
plus 'none' fall-backs, X-Frame-Options DENY, X-Content-Type-Options
nosniff, Referrer-Policy no-referrer, Cache-Control no-store.

These tests exercise the response-writer helpers directly with an
in-memory ``BaseHTTPRequestHandler`` stand-in — no real socket binding.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from mureo.web._helpers import (
    SECURITY_HEADERS,
    send_bytes,
    send_error_json,
    send_json,
)


class _StubHandler:
    """Minimal stand-in for ``BaseHTTPRequestHandler`` that captures
    every header / status / body the helper writes."""

    def __init__(self) -> None:
        self.status: int | None = None
        self.headers_sent: list[tuple[str, str]] = []
        self.ended: bool = False
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.headers_sent.append((name, value))

    def end_headers(self) -> None:
        self.ended = True

    def headers_dict(self) -> dict[str, str]:
        return dict(self.headers_sent)


@pytest.fixture
def handler() -> _StubHandler:
    return _StubHandler()


@pytest.mark.unit
class TestSecurityHeadersConstant:
    """Static contents of the SECURITY_HEADERS tuple."""

    def test_headers_constant_is_tuple_of_pairs(self) -> None:
        assert isinstance(SECURITY_HEADERS, tuple)
        for entry in SECURITY_HEADERS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            assert all(isinstance(x, str) for x in entry)

    def test_includes_csp(self) -> None:
        names = [n for n, _ in SECURITY_HEADERS]
        assert "Content-Security-Policy" in names

    def test_includes_x_frame_options_deny(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert d["X-Frame-Options"] == "DENY"

    def test_includes_x_content_type_options_nosniff(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert d["X-Content-Type-Options"] == "nosniff"

    def test_includes_referrer_policy_no_referrer(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert d["Referrer-Policy"] == "no-referrer"

    def test_includes_cache_control_no_store(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert "no-store" in d["Cache-Control"]

    def test_includes_pragma_no_cache(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert d["Pragma"] == "no-cache"

    def test_csp_uses_default_src_none(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert "default-src 'none'" in d["Content-Security-Policy"]

    def test_csp_uses_frame_ancestors_none(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert "frame-ancestors 'none'" in d["Content-Security-Policy"]

    def test_csp_uses_base_uri_none(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert "base-uri 'none'" in d["Content-Security-Policy"]

    def test_csp_uses_object_src_none(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert "object-src 'none'" in d["Content-Security-Policy"]

    def test_csp_locks_form_action_to_self(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert "form-action 'self'" in d["Content-Security-Policy"]

    def test_csp_locks_script_src_to_self_without_unsafe(self) -> None:
        d = dict(SECURITY_HEADERS)
        csp = d["Content-Security-Policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert "unsafe-eval" not in csp

    def test_csp_locks_style_src_to_self(self) -> None:
        d = dict(SECURITY_HEADERS)
        assert "style-src 'self'" in d["Content-Security-Policy"]

    @pytest.mark.parametrize(
        "required",
        [
            "Content-Security-Policy",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Cache-Control",
            "Pragma",
        ],
    )
    def test_all_required_headers_present(self, required: str) -> None:
        names = {n for n, _ in SECURITY_HEADERS}
        assert required in names


@pytest.mark.unit
class TestSendJsonAttachesSecurityHeaders:
    def test_json_response_includes_full_security_stack(
        self, handler: _StubHandler
    ) -> None:
        send_json(handler, {"ok": True})
        sent = handler.headers_dict()
        for name, value in SECURITY_HEADERS:
            assert sent.get(name) == value, f"missing {name}"

    def test_json_response_has_correct_content_type(
        self, handler: _StubHandler
    ) -> None:
        send_json(handler, {"k": "v"})
        assert handler.headers_dict()["Content-Type"] == (
            "application/json; charset=utf-8"
        )

    def test_json_response_default_status_200(self, handler: _StubHandler) -> None:
        send_json(handler, {})
        assert handler.status == 200

    def test_json_response_honors_custom_status(self, handler: _StubHandler) -> None:
        send_json(handler, {}, status=201)
        assert handler.status == 201

    def test_json_body_is_valid_utf8_json(self, handler: _StubHandler) -> None:
        send_json(handler, {"日本語": "値"})
        body = handler.wfile.getvalue().decode("utf-8")
        assert json.loads(body) == {"日本語": "値"}

    def test_content_length_matches_body(self, handler: _StubHandler) -> None:
        send_json(handler, {"a": 1})
        sent = handler.headers_dict()
        actual = len(handler.wfile.getvalue())
        assert int(sent["Content-Length"]) == actual

    def test_handles_broken_pipe_gracefully(self) -> None:
        h = MagicMock()
        h.wfile = MagicMock()
        h.wfile.write.side_effect = BrokenPipeError
        send_json(h, {"ok": True})  # must not raise

    def test_list_payload_is_serialised(self, handler: _StubHandler) -> None:
        send_json(handler, [1, 2, 3])
        body = handler.wfile.getvalue().decode("utf-8")
        assert json.loads(body) == [1, 2, 3]


@pytest.mark.unit
class TestSendBytesAttachesSecurityHeaders:
    def test_static_response_includes_full_security_stack(
        self, handler: _StubHandler
    ) -> None:
        send_bytes(handler, b"<html></html>", content_type="text/html; charset=utf-8")
        sent = handler.headers_dict()
        for name, value in SECURITY_HEADERS:
            assert sent.get(name) == value, f"missing {name}"

    def test_static_response_uses_provided_content_type(
        self, handler: _StubHandler
    ) -> None:
        send_bytes(handler, b"body { }", content_type="text/css; charset=utf-8")
        assert handler.headers_dict()["Content-Type"] == "text/css; charset=utf-8"

    def test_static_response_writes_exact_bytes(self, handler: _StubHandler) -> None:
        payload = b"\x00\x01\x02binary"
        send_bytes(handler, payload, content_type="application/octet-stream")
        assert handler.wfile.getvalue() == payload

    def test_static_response_default_status_200(self, handler: _StubHandler) -> None:
        send_bytes(handler, b"", content_type="text/plain")
        assert handler.status == 200

    def test_static_response_honors_custom_status(self, handler: _StubHandler) -> None:
        send_bytes(handler, b"", content_type="text/plain", status=304)
        assert handler.status == 304


@pytest.mark.unit
class TestSendErrorJson:
    def test_error_payload_shape(self, handler: _StubHandler) -> None:
        send_error_json(handler, 404, "not_found")
        body = handler.wfile.getvalue().decode("utf-8")
        assert json.loads(body) == {"error": "not_found"}

    def test_error_status_is_propagated(self, handler: _StubHandler) -> None:
        send_error_json(handler, 403, "forbidden")
        assert handler.status == 403

    def test_error_response_includes_security_headers(
        self, handler: _StubHandler
    ) -> None:
        send_error_json(handler, 400, "bad_request")
        sent = handler.headers_dict()
        for name, value in SECURITY_HEADERS:
            assert sent.get(name) == value, f"missing {name}"

    @pytest.mark.parametrize("code", [400, 403, 404, 413, 500])
    def test_error_response_carries_security_headers_for_every_code(
        self, code: int
    ) -> None:
        h = _StubHandler()
        send_error_json(h, code, "x")
        sent = h.headers_dict()
        assert sent["X-Content-Type-Options"] == "nosniff"
        assert sent["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in sent


@pytest.mark.unit
class TestEndHeadersIsCalledOnce:
    def test_send_json_calls_end_headers(self, handler: _StubHandler) -> None:
        send_json(handler, {})
        assert handler.ended is True

    def test_send_bytes_calls_end_headers(self, handler: _StubHandler) -> None:
        send_bytes(handler, b"x", content_type="text/plain")
        assert handler.ended is True


@pytest.mark.unit
class TestNoHeaderInjection:
    """Defense against header injection via the JSON payload."""

    def test_payload_with_newlines_does_not_leak_into_headers(
        self, handler: _StubHandler
    ) -> None:
        attack: dict[str, Any] = {
            "evil": "value\r\nX-Injected: pwned",
        }
        send_json(handler, attack)
        sent_names = [n for n, _ in handler.headers_sent]
        assert "X-Injected" not in sent_names
