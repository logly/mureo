"""Single-instance probe for ``mureo.web.instance``.

``probe_mureo_instance`` GETs ``http://<host>:<port>/api/ping`` and
returns ``True`` only when the JSON body carries
``app == "mureo-configure"``. Every failure mode — connection refused,
timeout, non-JSON body, wrong/missing ``app`` field — returns ``False``
and NEVER raises, so a second launch can safely probe a possibly-dead or
foreign port. These tests mock :mod:`urllib.request` entirely; nothing
hits the network.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

from mureo.web.instance import probe_mureo_instance


class _FakeResponse:
    """Minimal context-manager stand-in for ``urlopen``'s return value."""

    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._buf.read()


def _urlopen_returning(payload: Any) -> Any:
    """Build a ``urlopen`` replacement that yields ``payload`` as JSON."""
    body = json.dumps(payload).encode("utf-8")

    def fake_urlopen(req: Any, timeout: float = 0.0) -> _FakeResponse:
        return _FakeResponse(body)

    return fake_urlopen


def _urlopen_raising(exc: Exception) -> Any:
    """Build a ``urlopen`` replacement that raises ``exc``."""

    def fake_urlopen(req: Any, timeout: float = 0.0) -> _FakeResponse:
        raise exc

    return fake_urlopen


@pytest.mark.unit
class TestProbeMureoInstance:
    def test_returns_true_for_mureo_signature(self) -> None:
        """A body with ``app == 'mureo-configure'`` is recognised as ours."""
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            _urlopen_returning({"app": "mureo-configure", "version": "1.2.3"}),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is True

    def test_returns_false_for_foreign_json(self) -> None:
        """A valid JSON body from a foreign service is not ours."""
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            _urlopen_returning({"app": "something-else"}),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is False

    def test_returns_false_when_app_field_missing(self) -> None:
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            _urlopen_returning({"version": "1.2.3"}),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is False

    def test_returns_false_for_non_object_json(self) -> None:
        """A JSON array / scalar must not crash the ``.get`` lookup."""
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            _urlopen_returning([1, 2, 3]),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is False

    def test_returns_false_on_invalid_json(self) -> None:
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            lambda req, timeout=0.0: _FakeResponse(b"not json at all"),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is False

    def test_returns_false_on_connection_refused(self) -> None:
        """A dead port (URLError) returns False, never raises."""
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            _urlopen_raising(urllib.error.URLError("connection refused")),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is False

    def test_returns_false_on_timeout(self) -> None:
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            _urlopen_raising(TimeoutError("timed out")),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is False

    def test_returns_false_on_os_error(self) -> None:
        with patch(
            "mureo.web.instance.urllib.request.urlopen",
            _urlopen_raising(OSError("socket boom")),
        ):
            assert probe_mureo_instance("127.0.0.1", 7613) is False

    def test_probes_the_ping_endpoint_on_given_host_port(self) -> None:
        """The probe must target ``/api/ping`` at the requested host:port."""
        captured: dict[str, str] = {}

        def fake_urlopen(req: Any, timeout: float = 0.0) -> _FakeResponse:
            captured["url"] = req.full_url if hasattr(req, "full_url") else str(req)
            return _FakeResponse(json.dumps({"app": "mureo-configure"}).encode())

        with patch("mureo.web.instance.urllib.request.urlopen", fake_urlopen):
            probe_mureo_instance("127.0.0.1", 9999)
        assert captured["url"] == "http://127.0.0.1:9999/api/ping"
