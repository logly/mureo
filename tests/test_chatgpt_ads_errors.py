"""Reading an Advertiser API error body into one bounded line.

The published reference defines no error-body schema, so every shape the
reader accepts is pinned here, along with the feature-gate rule that keeps a
bare 404 an ordinary API error.
"""

from __future__ import annotations

import json

import pytest

from mureo.chatgpt_ads._errors import (
    MAY_HAVE_BEEN_APPLIED,
    NO_ERROR_DETAIL,
    ChatGPTAdsAPIError,
    error_from_response,
)
from mureo.core.auth_failure import PlatformAuthError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("body", "text", "code"),
    [
        (
            {"error": {"message": "Bad id", "code": "invalid_id", "type": "x"}},
            "Bad id",
            "invalid_id",
        ),
        ({"error": "plain error text"}, "plain error text", None),
        ({"message": "top-level message"}, "top-level message", None),
        ({"detail": "detail text"}, "detail text", None),
        ({"code": "some_code"}, None, "some_code"),
        ({"error": {"message": "m", "code": 42}}, "m", "42"),
    ],
)
def test_every_accepted_body_shape(
    body: dict[str, object], text: str | None, code: str | None
) -> None:
    error = error_from_response(400, json.dumps(body))
    assert isinstance(error, ChatGPTAdsAPIError)
    assert error.status == 400
    assert error.code == code
    if text is not None:
        assert text in str(error)


def test_a_plain_text_body_is_never_quoted() -> None:
    """An intermediary's error page can echo the request headers."""
    error = error_from_response(
        502, "Bad gateway\nAuthorization: Bearer leaked-value from proxy"
    )
    assert str(error) == f"HTTP 502: {NO_ERROR_DETAIL}"
    assert "leaked-value" not in str(error)


def test_json_message_text_is_quoted_on_one_line() -> None:
    body = json.dumps({"error": {"message": "Bad\nid\r\n  given"}})
    error = error_from_response(400, body)
    assert "Bad id given" in str(error)
    assert "\n" not in str(error)


def test_non_printable_characters_are_dropped() -> None:
    message = "a\x1b[31mred\x07 ‮bidi\x85 \x00end"
    error = error_from_response(400, json.dumps({"error": {"message": message}}))
    text = str(error)
    for char in ("\x1b", "\x07", "‮", "\x85", "\x00"):
        assert char not in text
    assert "red" in text and "bidi" in text and "end" in text


def test_secret_shaped_text_is_scrubbed() -> None:
    body = json.dumps({"error": {"message": "failed: password=hunter2xyz"}})
    assert "hunter2xyz" not in str(error_from_response(400, body))


@pytest.mark.parametrize(
    "code",
    [
        "bad\ncode",
        # An explicit id: pytest puts the test id into an environment
        # variable, and Windows refuses one longer than 32,767 characters.
        pytest.param("x" * 100_000, id="100k_chars"),
        "has space",
        "",
        "a" * 65,
        "tab\tcode",
    ],
)
def test_a_code_outside_the_pattern_is_treated_as_absent(code: str) -> None:
    body = json.dumps({"error": {"message": "m", "code": code}})
    error = error_from_response(400, body)
    assert isinstance(error, ChatGPTAdsAPIError)
    assert error.code is None
    assert str(error) == "HTTP 400: m"


def test_a_malformed_gate_code_does_not_open_the_gate() -> None:
    body = json.dumps({"error": {"code": "feature_disabled\nx"}})
    assert isinstance(error_from_response(403, body), PlatformAuthError)


def test_a_code_inside_the_pattern_is_kept() -> None:
    body = json.dumps({"error": {"message": "m", "code": "a.b-c_9"}})
    assert error_from_response(400, body).code == "a.b-c_9"  # type: ignore[union-attr]


def test_a_body_nested_past_the_recursion_limit_is_unreadable() -> None:
    error = error_from_response(500, "[" * 100_000)
    assert isinstance(error, ChatGPTAdsAPIError)
    assert str(error) == f"HTTP 500: {NO_ERROR_DETAIL}"


def test_long_text_is_cut_at_200_characters() -> None:
    error = error_from_response(400, json.dumps({"error": {"message": "x" * 500}}))
    assert "x" * 200 in str(error)
    assert "x" * 201 not in str(error)


@pytest.mark.parametrize("body", ["", "   ", "{}", "[]", "null", '{"error": {}}'])
def test_an_unreadable_body_reports_the_status_alone(body: str) -> None:
    error = error_from_response(500, body)
    assert isinstance(error, ChatGPTAdsAPIError)
    assert "500" in str(error)


def test_401_is_an_auth_failure() -> None:
    assert isinstance(error_from_response(401, "{}"), PlatformAuthError)


def test_403_without_a_gate_signal_is_an_auth_failure() -> None:
    body = json.dumps({"error": {"message": "Forbidden"}})
    assert isinstance(error_from_response(403, body), PlatformAuthError)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (403, {"error": {"message": "Denied", "code": "product_feed_api_disabled"}}),
        (403, {"error": {"message": "Conversion bidding is not enabled"}}),
        (404, {"error": {"message": "x", "code": "hotel_insights_not_enabled"}}),
        (404, {"message": "Segments are not enabled for this account"}),
        (403, {"detail": "This feature is not enabled for the ad account"}),
    ],
)
def test_feature_gates(status: int, body: dict[str, object]) -> None:
    error = error_from_response(status, json.dumps(body))
    assert isinstance(error, ChatGPTAdsAPIError)
    assert error.is_feature_gate


def test_a_bare_404_is_not_a_feature_gate() -> None:
    error = error_from_response(404, json.dumps({"error": {"message": "Not found"}}))
    assert isinstance(error, ChatGPTAdsAPIError)
    assert not error.is_feature_gate


def test_a_gate_signal_on_another_status_is_not_a_gate() -> None:
    body = json.dumps({"error": {"code": "x_disabled"}})
    error = error_from_response(400, body)
    assert isinstance(error, ChatGPTAdsAPIError)
    assert not error.is_feature_gate


def test_a_note_ends_the_message_and_keeps_the_classification() -> None:
    body = json.dumps({"error": {"message": "boom", "code": "server_error"}})
    error = error_from_response(503, body, note=MAY_HAVE_BEEN_APPLIED)
    assert isinstance(error, ChatGPTAdsAPIError)
    assert str(error) == f"{error_from_response(503, body)} {MAY_HAVE_BEEN_APPLIED}"
    assert (error.status, error.code) == (503, "server_error")
