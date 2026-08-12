"""An auth failure must be machine-distinguishable from data (#580).

Before this suite, a platform whose credentials were missing or whose token
had expired answered an MCP read with a *successful* tool result whose text
happened to be a sentence about credentials. Nothing downstream could tell
"this platform spent nothing" from "this platform could not be read", so
``/daily-check`` shipped a report that looked complete with error prose
sitting where the numbers belonged.

The fix gives every platform ONE payload shape for that outcome — the same
``status`` vocabulary ``blind_spots`` and ``DeliveryCollapseReport`` already
use — produced in the two central places every platform routes through:
``_no_creds_result`` and ``api_error_handler``.

Marks: unit — pure in-process, no network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.types import TextContent

from mureo.core.auth_failure import (
    AUTH_CAUSE_NO_CREDENTIALS,
    AUTH_CAUSE_TOKEN_INVALID,
    AUTH_ERROR_STATUS,
    PlatformAuthError,
    auth_failure_payload,
    classify_auth_exception,
)
from mureo.mcp._helpers import (
    API_ERROR_PREFIX,
    _json_result,
    _no_creds_result,
    api_error_handler,
    is_auth_error_result,
    is_error_result,
)

pytestmark = pytest.mark.unit


def _payload(result: list[Any]) -> dict[str, Any]:
    parsed = json.loads(result[0].text)
    assert isinstance(parsed, dict)
    return parsed


# ---------------------------------------------------------------------------
# The vocabulary itself
# ---------------------------------------------------------------------------


class TestAuthFailurePayload:
    def test_carries_status_cause_and_human_detail(self) -> None:
        payload = auth_failure_payload(AUTH_CAUSE_TOKEN_INVALID, "token expired")
        assert payload == {
            "status": AUTH_ERROR_STATUS,
            "auth_cause": AUTH_CAUSE_TOKEN_INVALID,
            "detail": "token expired",
        }

    def test_rejects_a_cause_outside_the_vocabulary(self) -> None:
        """An unknown cause would reach a skill that has no branch for it."""
        with pytest.raises(ValueError, match="auth cause"):
            auth_failure_payload("probably_fine", "detail")


# ---------------------------------------------------------------------------
# Classifying the exception behind an error
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeHttpStatusError(Exception):
    """Shaped like ``httpx.HTTPStatusError`` (Search Console's raise path)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.response = _FakeResponse(status_code)


class _FakeErrorCode:
    def __init__(self, oneof: str) -> None:
        self._oneof = oneof

    def WhichOneof(self, name: str) -> str:  # noqa: N802 - protobuf API name
        assert name == "error_code"
        return self._oneof


class _FakeGoogleAdsFailure:
    def __init__(self, oneof: str) -> None:
        self.errors = [type("E", (), {"error_code": _FakeErrorCode(oneof)})()]


class _FakeGoogleAdsError(Exception):
    """Shaped like ``GoogleAdsException`` (Google Ads' read path)."""

    def __init__(self, oneof: str) -> None:
        super().__init__("google ads failed")
        self.failure = _FakeGoogleAdsFailure(oneof)


class TestClassifyAuthException:
    def test_platform_auth_error_reports_its_own_cause(self) -> None:
        exc = PlatformAuthError("nope", cause=AUTH_CAUSE_NO_CREDENTIALS)
        assert classify_auth_exception(exc) == AUTH_CAUSE_NO_CREDENTIALS

    def test_platform_auth_error_defaults_to_token_invalid(self) -> None:
        assert classify_auth_exception(PlatformAuthError("nope")) == (
            AUTH_CAUSE_TOKEN_INVALID
        )

    @pytest.mark.parametrize("status", [401, 403])
    def test_rejected_credential_http_statuses(self, status: int) -> None:
        assert classify_auth_exception(_FakeHttpStatusError(status)) == (
            AUTH_CAUSE_TOKEN_INVALID
        )

    @pytest.mark.parametrize("status", [400, 404, 429, 500])
    def test_other_http_statuses_are_not_auth_failures(self, status: int) -> None:
        """Mislabelling a 500 as an auth failure would send the operator to
        re-authorize an account whose credentials are fine."""
        assert classify_auth_exception(_FakeHttpStatusError(status)) is None

    @pytest.mark.parametrize("oneof", ["authentication_error", "authorization_error"])
    def test_google_ads_auth_error_codes(self, oneof: str) -> None:
        assert classify_auth_exception(_FakeGoogleAdsError(oneof)) == (
            AUTH_CAUSE_TOKEN_INVALID
        )

    def test_google_ads_non_auth_error_codes(self) -> None:
        assert classify_auth_exception(_FakeGoogleAdsError("mutate_error")) is None

    def test_walks_the_exception_chain(self) -> None:
        """Clients re-raise ``RuntimeError(...) from exc``; the cause must not
        be lost behind the wrapper."""
        try:
            try:
                raise PlatformAuthError("token expired")
            except PlatformAuthError as inner:
                raise RuntimeError("An error occurred") from inner
        except RuntimeError as outer:
            assert classify_auth_exception(outer) == AUTH_CAUSE_TOKEN_INVALID

    def test_ordinary_failures_are_not_auth_failures(self) -> None:
        assert classify_auth_exception(RuntimeError("quota exceeded")) is None
        assert classify_auth_exception(None) is None


# ---------------------------------------------------------------------------
# The MCP result envelope
# ---------------------------------------------------------------------------


class TestNoCredsResult:
    def test_is_a_structured_auth_error_not_prose(self) -> None:
        result = _no_creds_result("Credentials not found. Set META_ADS_ACCESS_TOKEN.")
        payload = _payload(result)
        assert payload["status"] == AUTH_ERROR_STATUS
        assert payload["auth_cause"] == AUTH_CAUSE_NO_CREDENTIALS

    def test_keeps_the_operator_facing_sentence(self) -> None:
        msg = "Credentials not found. Set META_ADS_ACCESS_TOKEN."
        assert _payload(_no_creds_result(msg))["detail"] == msg


class TestIsAuthErrorResult:
    def test_true_for_the_auth_envelope(self) -> None:
        assert is_auth_error_result(_no_creds_result("nope")) is True

    def test_false_for_an_ordinary_api_error(self) -> None:
        api_error = [TextContent(type="text", text="API error: x")]
        assert is_auth_error_result(api_error) is False

    def test_false_for_ordinary_json_data(self) -> None:
        assert is_auth_error_result(_json_result({"campaigns": []})) is False

    def test_false_for_a_json_string_that_is_not_an_object(self) -> None:
        assert is_auth_error_result([TextContent(type="text", text="[1, 2]")]) is False

    def test_false_for_empty_and_none(self) -> None:
        assert is_auth_error_result(None) is False
        assert is_auth_error_result([]) is False


class TestIsErrorResult:
    """The mutation gate must keep recognising BOTH envelopes.

    ``is_error_result`` is what stops a mutation that never reached the
    platform from being written to ``action_log``. An auth failure is exactly
    such a mutation, so the new envelope must not fall out of that gate.
    """

    def test_still_true_for_the_api_error_envelope(self) -> None:
        assert is_error_result([TextContent(type="text", text="API error: x")]) is True

    def test_true_for_the_auth_error_envelope(self) -> None:
        assert is_error_result(_no_creds_result("nope")) is True

    def test_false_for_a_successful_result(self) -> None:
        assert is_error_result(_json_result({"id": "1"})) is False


# ---------------------------------------------------------------------------
# api_error_handler routing
# ---------------------------------------------------------------------------


class TestApiErrorHandlerRouting:
    async def test_auth_failure_becomes_the_auth_envelope(self) -> None:
        @api_error_handler
        async def handler() -> list[TextContent]:
            raise PlatformAuthError("Meta API request failed (status=190)")

        payload = _payload(await handler())
        assert payload["status"] == AUTH_ERROR_STATUS
        assert payload["auth_cause"] == AUTH_CAUSE_TOKEN_INVALID
        assert "status=190" in payload["detail"]

    async def test_other_failures_stay_on_the_api_error_envelope(self) -> None:
        @api_error_handler
        async def handler() -> list[TextContent]:
            raise RuntimeError("quota exceeded")

        result = await handler()
        assert result[0].text == f"{API_ERROR_PREFIX} quota exceeded"

    async def test_value_error_still_propagates(self) -> None:
        @api_error_handler
        async def handler() -> list[TextContent]:
            raise ValueError("Required parameter customer_id is not specified")

        with pytest.raises(ValueError, match="customer_id"):
            await handler()
