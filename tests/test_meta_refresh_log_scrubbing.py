"""A failed Meta token refresh must not write Graph's raw body to the log (#605).

``_call_refresh_api`` used to interpolate the whole ``resp.text`` into the
``ValueError`` it raised, and ``refresh_meta_token_if_needed`` logged that with
``exc_info=True``. Before #581 nothing installed a handler so the line went
nowhere; since #581 it lands in ``~/.mureo/logs/configure.log``.

Dropping the line is not the fix — this refresh fails on *every* Meta call and
the log line is the only record (#578). So these tests pin both halves: the
raw body stays out, and the status code plus a curated, bounded slice of
Graph's JSON error envelope stays in.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mureo.auth import MetaAdsCredentials, refresh_meta_token_if_needed

#: A marker planted in parts of the body that must never be logged. Long
#: enough that no curated field could contain it by accident.
_BODY_MARKER = "GRAPH-RAW-BODY-MARKER-8f3a1c"


def _make_creds() -> MetaAdsCredentials:
    obtained = datetime.now(tz=timezone.utc) - timedelta(days=55)
    return MetaAdsCredentials(
        access_token="old-token",
        app_id="app-123",
        app_secret="secret-456",
        token_obtained_at=obtained.isoformat(),
    )


def _response(**kwargs: object) -> httpx.Response:
    return httpx.Response(
        400,
        request=httpx.Request("POST", "https://graph.facebook.com/"),
        **kwargs,  # type: ignore[arg-type]
    )


async def _refresh_with(response_or_error: object) -> None:
    """Drive one refresh attempt against a canned Graph response/transport error."""
    with patch("mureo.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        if isinstance(response_or_error, BaseException):
            mock_client.post.side_effect = response_or_error
        else:
            mock_client.post.return_value = response_or_error
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        creds = _make_creds()
        assert await refresh_meta_token_if_needed(creds) is creds


def _refresh_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "refresh Meta Ads token" in r.getMessage()]


# ---------------------------------------------------------------------------
# The raw body stays out
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_the_log_line_omits_the_raw_response_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Everything Graph returned outside the curated fields is dropped."""
    body = {
        "error": {
            "message": "Error validating application.",
            "code": 190,
            "error_subcode": 460,
            "fbtrace_id": _BODY_MARKER,
        },
        "unexpected_extra": _BODY_MARKER,
    }
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(json=body))

    records = _refresh_records(caplog)
    assert len(records) == 1
    assert _BODY_MARKER not in caplog.text


@pytest.mark.unit
async def test_the_log_line_carries_no_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``exc_info`` is gone — a traceback re-prints ``str(exc)`` and follows
    ``__cause__``, which is how the body got into the file in the first place."""
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(json={"error": {"message": "nope"}}))

    (record,) = _refresh_records(caplog)
    assert record.exc_info is None
    assert record.exc_text is None


@pytest.mark.unit
async def test_a_non_json_body_contributes_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An HTML error page (a proxy, a Graph outage) is not the envelope — drop it."""
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(text=f"<html>{_BODY_MARKER}</html>"))

    assert _BODY_MARKER not in caplog.text
    assert len(_refresh_records(caplog)) == 1


@pytest.mark.unit
async def test_a_json_body_without_an_error_envelope_contributes_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Valid JSON that is not ``{"error": {...}}`` is still uncurated content."""
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(json={"whatever": _BODY_MARKER}))

    assert _BODY_MARKER not in caplog.text
    assert len(_refresh_records(caplog)) == 1


@pytest.mark.unit
async def test_a_long_graph_message_is_truncated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Graph's ``message`` is unbounded free text — bound what reaches the file."""
    body = {"error": {"message": "x" * 5000, "code": 190}}
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(json=body))

    (record,) = _refresh_records(caplog)
    assert "x" * 5000 not in record.getMessage()
    assert len(record.getMessage()) < 500
    assert "code=190" in record.getMessage()


@pytest.mark.unit
async def test_a_multiline_graph_message_cannot_forge_log_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Newlines in Graph-authored text would otherwise fake extra log records."""
    body = {"error": {"message": "first\nWARNING second\r\nthird"}}
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(json=body))

    (record,) = _refresh_records(caplog)
    assert "\n" not in record.getMessage()
    assert "\r" not in record.getMessage()


@pytest.mark.unit
async def test_a_transport_failure_logs_only_the_exception_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """httpx's own exception text can embed the request URL — name the type only."""
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(httpx.ConnectError(f"connecting to {_BODY_MARKER}"))

    (record,) = _refresh_records(caplog)
    assert _BODY_MARKER not in caplog.text
    assert "ConnectError" in record.getMessage()
    assert record.exc_info is None


# ---------------------------------------------------------------------------
# The failure stays diagnosable (#578)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_the_log_line_keeps_the_status_and_the_curated_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Status plus ``error.message`` / ``error.code`` / ``error_subcode``."""
    body = {
        "error": {
            "message": "Error validating application.",
            "code": 190,
            "error_subcode": 460,
        }
    }
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(json=body))

    (record,) = _refresh_records(caplog)
    message = record.getMessage()
    assert "400" in message
    assert "Error validating application." in message
    assert "code=190" in message
    assert "subcode=460" in message


@pytest.mark.unit
async def test_a_body_with_no_usable_field_still_reports_the_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The status code alone is the minimum a silent refresh must leave behind."""
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(_response(json={"error": {}}))

    (record,) = _refresh_records(caplog)
    assert "400" in record.getMessage()


@pytest.mark.unit
async def test_a_response_missing_the_token_is_named_as_such(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 200 with no ``access_token`` is a distinct failure, not a generic one."""
    ok = httpx.Response(
        200,
        json={"token_type": "bearer", "junk": _BODY_MARKER},
        request=httpx.Request("POST", "https://graph.facebook.com/"),
    )
    with caplog.at_level(logging.WARNING, logger="mureo.auth"):
        await _refresh_with(ok)

    (record,) = _refresh_records(caplog)
    assert "access_token" in record.getMessage()
    assert _BODY_MARKER not in caplog.text
