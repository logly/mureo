"""The one Meta Graph error formatter (#866, #605).

``mureo.meta_ads.client``, ``mureo.meta_ads.accounts`` and ``mureo.auth``
each used to render Graph's ``{"error": {...}}`` envelope their own way, with
different fields, different bounds and — in two of them — a fallback to the
raw response body. These pin the single format they now share.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.meta_ads._graph_error import (
    GRAPH_ERROR_CODE_MAX_CHARS,
    GRAPH_ERROR_MESSAGE_MAX_CHARS,
    GRAPH_ERROR_NO_DETAIL,
    format_graph_error,
)

_FALLBACK = "fixed fallback sentence"

#: What ``truncate_text`` appends to a value it cut.
_CUT_MARK = "..."


def _fmt(error: Any) -> str:
    return format_graph_error({"error": error}, fallback=_FALLBACK)


@pytest.mark.unit
def test_all_six_fields_in_order() -> None:
    out = _fmt(
        {
            "fbtrace_id": "TRACE",
            "error_subcode": 463,
            "code": 190,
            "error_user_msg": "Please log in again.",
            "error_user_title": "Session expired",
            "message": "Error validating access token",
        }
    )
    assert out == (
        "Error validating access token | Session expired | Please log in again. "
        "| code=190 | subcode=463 | fbtrace_id=TRACE"
    )


@pytest.mark.unit
def test_message_newlines_collapse_to_one_line() -> None:
    out = _fmt({"message": "first\nsecond\r\nthird"})
    assert "\n" not in out
    assert "\r" not in out
    assert "first" in out
    assert "third" in out


@pytest.mark.unit
@pytest.mark.parametrize("key", ["message", "error_user_title", "error_user_msg"])
def test_text_fields_are_bounded(key: str) -> None:
    out = _fmt({key: "A" * (GRAPH_ERROR_MESSAGE_MAX_CHARS * 3)})
    assert "A" * (GRAPH_ERROR_MESSAGE_MAX_CHARS + 1) not in out
    assert len(out) <= GRAPH_ERROR_MESSAGE_MAX_CHARS + len(_CUT_MARK)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "label"),
    [("code", "code"), ("error_subcode", "subcode"), ("fbtrace_id", "fbtrace_id")],
)
def test_code_fields_are_bounded(key: str, label: str) -> None:
    out = _fmt({key: "F" * (GRAPH_ERROR_CODE_MAX_CHARS * 3)})
    assert out.startswith(f"{label}=")
    assert "F" * (GRAPH_ERROR_CODE_MAX_CHARS + 1) not in out
    assert len(out) <= len(label) + 1 + GRAPH_ERROR_CODE_MAX_CHARS + len(_CUT_MARK)


@pytest.mark.unit
def test_code_zero_is_kept() -> None:
    assert _fmt({"message": "m", "code": 0}) == "m | code=0"


@pytest.mark.unit
def test_empty_string_and_none_are_dropped() -> None:
    assert _fmt({"message": "m", "error_user_title": "", "code": None}) == "m"


@pytest.mark.unit
def test_whitespace_only_text_is_dropped() -> None:
    assert _fmt({"message": "  \n ", "code": 1}) == "code=1"


@pytest.mark.unit
def test_whitespace_only_envelope_returns_the_fallback() -> None:
    assert _fmt({"message": "   "}) == _FALLBACK


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not json",
        [],
        {},
        {"error": "a string, not an object"},
        {"error": {}},
        {"error": {"message": "", "code": None, "type": "OAuthException"}},
    ],
    ids=[
        "none",
        "string",
        "list",
        "no-error",
        "error-not-dict",
        "empty-error",
        "only-unlisted-or-empty",
    ],
)
def test_no_usable_field_returns_the_fallback(payload: Any) -> None:
    assert format_graph_error(payload, fallback=_FALLBACK) == _FALLBACK


@pytest.mark.unit
def test_fallback_is_bounded() -> None:
    out = format_graph_error(None, fallback="x" * 1000)
    assert len(out) <= GRAPH_ERROR_MESSAGE_MAX_CHARS + len(_CUT_MARK)


@pytest.mark.unit
def test_no_detail_sentence() -> None:
    assert GRAPH_ERROR_NO_DETAIL == "no error detail in response body"


@pytest.mark.unit
def test_raw_body_never_appears() -> None:
    """Only the six named fields are read; nothing else of the body is echoed."""
    marker = "RAW-BODY-MARKER-1f3a"
    payload = {
        "error": {"type": marker, "error_data": marker, "is_transient": marker},
        "extra": marker,
    }
    out = format_graph_error(payload, fallback=GRAPH_ERROR_NO_DETAIL)
    assert marker not in out
    assert out == GRAPH_ERROR_NO_DETAIL
