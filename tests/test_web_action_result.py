"""``mureo.web.action_result``: the one result type and its HTTP mapping (#864)."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from mureo.web.action_result import (
    ACTION_STATUSES,
    BASIC_CLEAR_FAILED,
    BASIC_SETUP_FAILED,
    ERROR_STATUS,
    FAILED_HTTP_STATUS,
    REFUSED_HTTP_STATUS,
    SUCCESS_HTTP_STATUS,
    ActionResult,
    every_step_failed,
    refuse_error_status,
    returncode_detail,
    send_result,
    send_steps,
)


@pytest.mark.unit
class TestConstructors:
    def test_refused_is_a_400_error(self) -> None:
        result = ActionResult.refused("unknown_provider")
        assert (result.status, result.code, result.http_status, result.detail) == (
            ERROR_STATUS,
            "unknown_provider",
            REFUSED_HTTP_STATUS,
            None,
        )
        assert REFUSED_HTTP_STATUS == 400

    def test_failed_is_a_500_error_with_its_detail(self) -> None:
        result = ActionResult.failed("internal_error", "OSError")
        assert (result.status, result.code, result.http_status, result.detail) == (
            ERROR_STATUS,
            "internal_error",
            FAILED_HTTP_STATUS,
            "OSError",
        )
        assert FAILED_HTTP_STATUS == 500

    @pytest.mark.parametrize("status", sorted(ACTION_STATUSES))
    def test_every_action_status_is_a_200_result(self, status: str) -> None:
        result = ActionResult(status=status)
        assert (result.code, result.http_status) == (None, SUCCESS_HTTP_STATUS)

    def test_error_is_not_an_action_status(self) -> None:
        assert ERROR_STATUS not in ACTION_STATUSES


@pytest.mark.unit
class TestPostInitRefusals:
    def test_unknown_status(self) -> None:
        with pytest.raises(ValueError, match="unknown action status"):
            ActionResult(status="done")

    @pytest.mark.parametrize(
        "code", [None, "", "Not a code", "unknown-provider", "9_lives", "Caps"]
    )
    def test_error_without_a_snake_case_code(self, code: str | None) -> None:
        with pytest.raises(ValueError, match="snake_case code"):
            ActionResult(status=ERROR_STATUS, code=code, http_status=400)

    @pytest.mark.parametrize("http_status", [200, 404, 409, 502])
    def test_error_with_another_http_status(self, http_status: int) -> None:
        with pytest.raises(ValueError, match="400 or 500"):
            ActionResult(status=ERROR_STATUS, code="x", http_status=http_status)

    def test_success_with_a_code(self) -> None:
        with pytest.raises(ValueError, match="errors only"):
            ActionResult(status="ok", code="internal_error")

    def test_success_with_an_error_http_status(self) -> None:
        with pytest.raises(ValueError, match="errors only"):
            ActionResult(status="noop", http_status=500)

    def test_refused_with_a_sentence_code(self) -> None:
        with pytest.raises(ValueError, match="snake_case code"):
            ActionResult.refused("target contains control characters")

    @pytest.mark.parametrize(
        "detail",
        [
            "",
            "a sentence with spaces",
            "/private/tmp/x.xlsx",
            "install_returncode_-9",
            "9_lives",
            "Meta token validation failed: boom",
        ],
    )
    def test_error_with_a_detail_that_is_not_a_code(self, detail: str) -> None:
        """A failure's detail is a code or an exception class name."""
        with pytest.raises(ValueError, match="code or class name"):
            ActionResult.failed("internal_error", detail)

    @pytest.mark.parametrize(
        "detail", ["OSError", "install_returncode_2", "_Private", "not_installed"]
    )
    def test_error_with_a_code_or_class_name_detail(self, detail: str) -> None:
        assert ActionResult.refused("x", detail).detail == detail


@pytest.mark.unit
class TestReturncodeDetail:
    def test_exit_status(self) -> None:
        assert returncode_detail("install", 2) == "install_returncode_2"

    def test_killed_by_a_signal(self) -> None:
        assert returncode_detail("upgrade", -9) == "upgrade_signal_9"

    @pytest.mark.parametrize("returncode", [-15, -1, 1, 255, 3221225477])
    def test_is_always_a_valid_failure_detail(self, returncode: int) -> None:
        detail = returncode_detail("install", returncode)
        assert ActionResult.failed("install_failed", detail).detail == detail


@pytest.mark.unit
class TestRefuseErrorStatus:
    def test_error_raises(self) -> None:
        with pytest.raises(ValueError, match="a failure is an ActionResult"):
            refuse_error_status(object(), ERROR_STATUS)

    @pytest.mark.parametrize("status", ["ok", "noop", "cancelled", "checking", None])
    def test_anything_else_passes(self, status: str | None) -> None:
        refuse_error_status(object(), status)


@pytest.mark.unit
class TestAsDict:
    def test_success_body(self) -> None:
        assert ActionResult(status="noop", detail="not_installed").as_dict() == {
            "status": "noop",
            "detail": "not_installed",
        }

    def test_error_step_carries_the_contract_keys(self) -> None:
        assert ActionResult.failed("internal_error", "OSError").as_dict() == {
            "status": "error",
            "error": "internal_error",
            "detail": "OSError",
        }


@pytest.mark.unit
class TestSendResult:
    def _send(self, result: object) -> tuple[MagicMock, MagicMock]:
        handler = MagicMock()
        with (
            patch("mureo.web.action_result.send_error_json") as error_writer,
            patch("mureo.web.action_result.send_json") as json_writer,
        ):
            send_result(handler, result)  # type: ignore[arg-type]
        return error_writer, json_writer

    def test_refused_goes_to_the_error_writer_as_400(self) -> None:
        error_writer, json_writer = self._send(ActionResult.refused("unknown_provider"))
        error_writer.assert_called_once()
        _handler, status, code = error_writer.call_args.args
        assert (status, code, error_writer.call_args.kwargs) == (
            400,
            "unknown_provider",
            {"detail": None},
        )
        json_writer.assert_not_called()

    def test_failed_goes_to_the_error_writer_as_500(self) -> None:
        error_writer, json_writer = self._send(
            ActionResult.failed("install_failed", "install_returncode_2")
        )
        _handler, status, code = error_writer.call_args.args
        assert (status, code, error_writer.call_args.kwargs) == (
            500,
            "install_failed",
            {"detail": "install_returncode_2"},
        )
        json_writer.assert_not_called()

    def test_success_is_its_body_at_200(self) -> None:
        error_writer, json_writer = self._send(ActionResult(status="ok"))
        error_writer.assert_not_called()
        _handler, body = json_writer.call_args.args
        assert (body, json_writer.call_args.kwargs) == ({"status": "ok"}, {})

    def test_a_richer_success_body_is_sent_as_is(self) -> None:
        success = MagicMock()
        success.as_dict.return_value = {"status": "ok", "platforms": []}
        error_writer, json_writer = self._send(success)
        error_writer.assert_not_called()
        assert json_writer.call_args.args[1] == {"status": "ok", "platforms": []}

    def test_a_mapping_is_sent_as_a_200_body(self) -> None:
        body = MappingProxyType({"status": "checking", "packages": []})
        error_writer, json_writer = self._send(body)
        error_writer.assert_not_called()
        assert json_writer.call_args.args[1] == {"status": "checking", "packages": []}

    @pytest.mark.parametrize("as_mapping", [True, False])
    def test_a_success_body_with_the_error_status_raises(
        self, as_mapping: bool
    ) -> None:
        """A 200 body never carries ``status: "error"``; nothing is sent."""
        body = {"status": "error", "detail": "OSError"}
        result: object = body
        if not as_mapping:
            result = MagicMock()
            result.as_dict.return_value = body
        with (
            patch("mureo.web.action_result.send_error_json") as error_writer,
            patch("mureo.web.action_result.send_json") as json_writer,
            pytest.raises(ValueError, match="a failure is an ActionResult"),
        ):
            send_result(MagicMock(), result)  # type: ignore[arg-type]
        error_writer.assert_not_called()
        json_writer.assert_not_called()


_OK = {"status": "ok"}
_NOOP = {"status": "noop", "detail": "not_installed"}
_SKIPPED = {"status": "skipped", "detail": "multi_account_auth"}
_FAILED = {"status": "error", "error": "internal_error", "detail": "OSError"}

#: The same envelopes as PARITY_CASES in tests/js/step_failures.test.js: the
#: server decides "every step failed" and the page lists the failed steps by
#: one flattening rule — a nested value is a step only if it has a status.
_PARITY_CASES: list[tuple[dict[str, object], bool]] = [
    ({"mureo_mcp": _SKIPPED, "auth_hook": _FAILED, "skills": _FAILED}, True),
    ({"skills": _FAILED, "providers": {"p1": _OK}}, False),
    ({"skills": _FAILED, "providers": {"p1": {"note": "no status"}}}, True),
    ({"skills": _OK, "providers": {"p1": _FAILED, "p2": "not a step"}}, False),
]


@pytest.mark.unit
class TestEveryStepFailed:
    """#891: a multi-step envelope fails as a whole only when nothing worked."""

    def test_all_succeeded(self) -> None:
        assert not every_step_failed({"a": _OK, "b": _NOOP, "c": _OK})

    def test_some_failed(self) -> None:
        assert not every_step_failed({"a": _FAILED, "b": _OK, "c": _FAILED})

    def test_all_failed(self) -> None:
        assert every_step_failed({"a": _FAILED, "b": _FAILED})

    def test_skipped_and_failed_only_is_all_failed(self) -> None:
        assert every_step_failed({"a": _SKIPPED, "b": _FAILED, "c": _FAILED})

    def test_skipped_only_is_not_a_failure(self) -> None:
        assert not every_step_failed({"a": _SKIPPED})

    @pytest.mark.parametrize("status", ["noop", "manual_required"])
    def test_a_non_error_status_next_to_failures_is_not_all_failed(
        self, status: str
    ) -> None:
        assert not every_step_failed({"a": {"status": status}, "b": _FAILED})

    def test_nested_providers_count_one_step_each(self) -> None:
        envelope = {
            "mureo_mcp": _FAILED,
            "auth_hook": _FAILED,
            "skills": _FAILED,
            "providers": {"google-ads-official": _OK},
        }
        assert not every_step_failed(envelope)

    def test_nested_providers_that_failed_too(self) -> None:
        envelope = {
            "mureo_mcp": _FAILED,
            "auth_hook": _FAILED,
            "skills": _FAILED,
            "providers": {"google-ads-official": _FAILED},
        }
        assert every_step_failed(envelope)

    def test_a_nested_failure_next_to_top_level_success(self) -> None:
        envelope = {"skills": _OK, "providers": {"p1": _FAILED}}
        assert not every_step_failed(envelope)

    def test_an_empty_providers_map_is_no_step(self) -> None:
        assert every_step_failed({"skills": _FAILED, "providers": {}})

    @pytest.mark.parametrize("envelope", [{}, {"providers": {}}])
    def test_no_step_is_not_a_failure(self, envelope: dict[str, object]) -> None:
        assert not every_step_failed(envelope)

    @pytest.mark.parametrize(("envelope", "expected"), _PARITY_CASES)
    def test_reads_an_envelope_as_the_page_does(
        self, envelope: dict[str, object], expected: bool
    ) -> None:
        assert every_step_failed(envelope) is expected


@pytest.mark.unit
class TestSendSteps:
    def _send(self, envelope: object) -> tuple[MagicMock, MagicMock]:
        handler = MagicMock()
        with (
            patch("mureo.web.action_result.send_error_json") as error_writer,
            patch("mureo.web.action_result.send_json") as json_writer,
        ):
            send_steps(handler, envelope, BASIC_SETUP_FAILED)  # type: ignore[arg-type]
        return error_writer, json_writer

    def test_the_failure_codes(self) -> None:
        assert (BASIC_SETUP_FAILED, BASIC_CLEAR_FAILED) == (
            "basic_setup_failed",
            "basic_clear_failed",
        )

    def test_every_step_failed_is_a_500_with_the_steps(self) -> None:
        envelope = {"mureo_mcp": _SKIPPED, "auth_hook": _FAILED, "skills": _FAILED}
        error_writer, json_writer = self._send(envelope)
        _handler, status, code = error_writer.call_args.args
        assert (status, code, error_writer.call_args.kwargs) == (
            500,
            "basic_setup_failed",
            {"extra": {"steps": envelope}},
        )
        json_writer.assert_not_called()

    def test_some_failed_is_the_envelope_at_200(self) -> None:
        envelope = {"mureo_mcp": _OK, "auth_hook": _FAILED, "skills": _OK}
        error_writer, json_writer = self._send(MappingProxyType(envelope))
        error_writer.assert_not_called()
        _handler, body = json_writer.call_args.args
        assert (type(body), body, json_writer.call_args.kwargs) == (dict, envelope, {})

    def test_all_succeeded_is_the_envelope_at_200(self) -> None:
        envelope = {"mureo_mcp": _OK, "auth_hook": _NOOP, "skills": _OK}
        error_writer, json_writer = self._send(envelope)
        error_writer.assert_not_called()
        assert json_writer.call_args.args[1] == envelope

    def test_logs_the_failed_steps_and_their_codes_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        envelope = {
            "auth_hook": {
                "status": "error",
                "error": "internal_error",
                "detail": "SecretDetail",
            },
            "providers": {"p1": {"status": "error", "error": "unknown_provider"}},
        }
        with caplog.at_level("WARNING", logger="mureo.web.action_result"):
            self._send(envelope)
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "basic_setup_failed" in message
        assert "auth_hook=internal_error" in message
        assert "p1=unknown_provider" in message
        assert "SecretDetail" not in message

    def test_a_partial_failure_logs_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING", logger="mureo.web.action_result"):
            self._send({"a": _OK, "b": _FAILED})
        assert caplog.records == []
