"""The one JSON failure envelope and its reader (#862).

``_failure_result`` writes ``{"status": "refused" | "error", "error": <code>,
"detail": <text>, ...}``; ``failure_of`` reads it back, together with the
``API error:`` text and the ``auth_error`` JSON, and ``is_error_result`` is
nothing but ``failure_of(...) is not None``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.types import TextContent

from mureo.mcp import _helpers
from mureo.mcp._helpers import (
    API_ERROR_PREFIX,
    FAILURE_STATUSES,
    Failure,
    _auth_error_result,
    _failure_result,
    _json_result,
    _no_creds_result,
    failure_of,
    is_error_result,
)

pytestmark = pytest.mark.unit


def _payload(result: list[TextContent]) -> dict[str, Any]:
    return json.loads(result[0].text)


def _text(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


class TestFailureResult:
    def test_default_status_is_error(self) -> None:
        payload = _payload(_failure_result("module_failed", "boom"))
        assert payload == {
            "status": "error",
            "error": "module_failed",
            "detail": "boom",
        }

    def test_refused_flag_sets_status_refused(self) -> None:
        payload = _payload(_failure_result("batch_refused", "no", refused=True))
        assert payload["status"] == "refused"
        assert payload["error"] == "batch_refused"
        assert payload["detail"] == "no"

    def test_extra_fields_ride_beside_the_envelope(self) -> None:
        payload = _payload(
            _failure_result(
                "index_out_of_range", "too big", refused=True, plan=None, index=3
            )
        )
        assert payload["plan"] is None
        assert payload["index"] == 3
        assert payload["status"] == "refused"

    def test_extra_fields_never_override_the_envelope(self) -> None:
        # ``detail`` is a named parameter, so only ``status`` / ``error`` can
        # arrive through ``fields`` at all.
        payload = _payload(
            _failure_result(
                "invalid_arguments",
                "the real detail",
                status="ok",
                error="not a code",
            )
        )
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_arguments"
        assert payload["detail"] == "the real detail"

    def test_code_and_detail_cannot_be_shadowed_by_fields(self) -> None:
        # Positional-only: a field named ``code`` / ``detail`` is just a field.
        payload = _payload(_failure_result("x", "y", code="shadow"))
        assert payload["error"] == "x"
        assert payload["detail"] == "y"

    def test_statuses_are_the_two_failure_words(self) -> None:
        assert frozenset({"refused", "error"}) == FAILURE_STATUSES


class TestFailureOf:
    def test_api_error_text_keeps_its_full_text(self) -> None:
        text = f"{API_ERROR_PREFIX} PERMISSION_DENIED"
        assert failure_of(_text(text)) == Failure("error", "api_error", text)

    def test_auth_envelope(self) -> None:
        result = _auth_error_result("token_invalid", "expired")
        assert failure_of(result) == Failure("auth_error", "token_invalid", "expired")

    def test_no_credentials_envelope(self) -> None:
        failure = failure_of(_no_creds_result("set GOOGLE_ADS_CLIENT_ID"))
        assert failure == Failure(
            "auth_error", "no_credentials", "set GOOGLE_ADS_CLIENT_ID"
        )

    def test_auth_envelope_non_string_fields_are_coerced(self) -> None:
        result = _json_result({"status": "auth_error", "auth_cause": 7, "detail": 1})
        assert failure_of(result) == Failure("auth_error", "7", "1")

    def test_refused_envelope(self) -> None:
        result = _failure_result(
            "tracking_preflight_failed", "not created", refused=True
        )
        assert failure_of(result) == Failure(
            "refused", "tracking_preflight_failed", "not created"
        )

    def test_error_envelope(self) -> None:
        result = _failure_result("module_failed", "boom", platform="x")
        assert failure_of(result) == Failure("error", "module_failed", "boom")

    def test_missing_detail_reads_as_empty(self) -> None:
        result = _json_result({"status": "error", "error": "module_failed"})
        assert failure_of(result) == Failure("error", "module_failed", "")

    @pytest.mark.parametrize(
        "body",
        [
            {"status": "ok"},
            {"status": "open", "batch_id": "b"},
            {"status": "capability_not_available", "platform": "x"},
            {"status": "applied", "dispatched_tool": "t"},
            {"campaigns": []},
            [1, 2],
        ],
    )
    def test_success_payloads_are_not_failures(self, body: Any) -> None:
        assert failure_of(_json_result(body)) is None

    def test_a_large_success_body_is_not_parsed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [{"id": str(i), "status": "ENABLED"} for i in range(5000)]
        result = _json_result({"campaigns": rows})

        def _no_parse(text: str) -> Any:
            raise AssertionError("failure_of parsed a success body")

        monkeypatch.setattr(_helpers.json, "loads", _no_parse)
        assert failure_of(result) is None

    def test_plain_text_is_not_a_failure(self) -> None:
        assert failure_of(_text("Error: data")) is None
        assert failure_of(_text("plan")) is None

    def test_malformed_json_is_not_a_failure(self) -> None:
        assert failure_of(_text('{"status": "error", "error": ')) is None

    def test_a_non_string_code_is_not_a_failure(self) -> None:
        for code in (None, 3, ["x"], {"a": 1}):
            body = {"status": "error", "error": code, "detail": "d"}
            assert failure_of(_json_result(body)) is None

    def test_an_unhashable_status_is_not_a_failure(self) -> None:
        body = {"status": ["error"], "error": "c", "detail": "d"}
        assert failure_of(_json_result(body)) is None

    def test_json_nested_past_the_recursion_limit_is_not_a_failure(self) -> None:
        deep = '{"status": ' + "[" * 100_000 + "]" * 100_000 + "}"
        assert failure_of(_text(deep)) is None

    def test_a_refused_status_without_a_code_is_not_a_failure(self) -> None:
        assert failure_of(_json_result({"status": "refused"})) is None

    @pytest.mark.parametrize("result", [None, []])
    def test_empty_results_are_not_failures(self, result: Any) -> None:
        assert failure_of(result) is None

    def test_a_non_text_item_is_not_a_failure(self) -> None:
        assert failure_of([{"ok": True}]) is None


class TestIsErrorResultParity:
    @pytest.mark.parametrize(
        "result",
        [
            None,
            [],
            _text("API error: x"),
            _text("ok"),
            _text("{not json"),
            _no_creds_result("nope"),
            _failure_result("batch_refused", "open already", refused=True),
            _failure_result("module_failed", "boom"),
            _json_result({"status": "ok"}),
            _json_result({"status": "error", "error": 1}),
            _json_result({"id": "1"}),
        ],
    )
    def test_is_error_result_is_failure_of_not_none(self, result: Any) -> None:
        assert is_error_result(result) is (failure_of(result) is not None)

    def test_the_new_envelope_counts_as_an_error(self) -> None:
        assert is_error_result(_failure_result("rollback_refused", "x", refused=True))
