"""GAQL validator tests.

Pure validation functions for GAQL query construction.
No DB/API required — all synchronous, deterministic.
"""

from __future__ import annotations

import pytest

from mureo.google_ads._gaql_validator import (
    VALID_DATE_RANGE_CONSTANTS,
    GAQLValidationError,
    build_in_clause,
    escape_string_literal,
    validate_date,
    validate_date_range_constant,
    validate_id,
    validate_id_list,
    validate_period_days,
)


@pytest.mark.unit
class TestValidateId:
    def test_valid_digits(self) -> None:
        assert validate_id("1234567890", "campaign_id") == "1234567890"

    def test_empty_rejected(self) -> None:
        with pytest.raises(GAQLValidationError, match="campaign_id"):
            validate_id("", "campaign_id")

    def test_injection_attempt_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_id("123 OR 1=1", "campaign_id")

    def test_quote_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_id("123'", "campaign_id")

    def test_dash_rejected(self) -> None:
        # customer_id with dashes must be normalized by caller first
        with pytest.raises(GAQLValidationError):
            validate_id("123-456-7890", "customer_id")

    def test_leading_space_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_id(" 123", "id")

    def test_error_is_valueerror(self) -> None:
        with pytest.raises(ValueError):
            validate_id("bad", "id")

    def test_length_cap(self) -> None:
        # 20 digits is the practical Google Ads ID max — one more is rejected.
        assert validate_id("1" * 20, "id") == "1" * 20
        with pytest.raises(GAQLValidationError):
            validate_id("1" * 21, "id")


@pytest.mark.unit
class TestValidateIdList:
    def test_valid_list(self) -> None:
        assert validate_id_list(["1", "2", "3"], "campaign_id") == ["1", "2", "3"]

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(GAQLValidationError, match="empty"):
            validate_id_list([], "campaign_id")

    def test_one_bad_id_rejects_all(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_id_list(["1", "2 OR 1=1", "3"], "campaign_id")

    def test_preserves_order(self) -> None:
        assert validate_id_list(["9", "1", "5"], "id") == ["9", "1", "5"]


@pytest.mark.unit
class TestValidateDate:
    def test_valid_date(self) -> None:
        assert validate_date("2025-04-01", "start_date") == "2025-04-01"

    def test_wrong_format_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_date("2025/04/01", "start_date")

    def test_injection_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_date("2025-04-01' OR '1'='1", "start_date")


@pytest.mark.unit
class TestValidateDateRangeConstant:
    def test_last_7_days(self) -> None:
        assert validate_date_range_constant("LAST_7_DAYS") == "LAST_7_DAYS"

    def test_lowercase_normalized(self) -> None:
        assert validate_date_range_constant("last_30_days") == "LAST_30_DAYS"

    def test_unknown_constant_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_date_range_constant("LAST_999_DAYS")

    def test_injection_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_date_range_constant("LAST_7_DAYS; DROP TABLE")

    def test_known_constants_include_common_ones(self) -> None:
        assert "LAST_7_DAYS" in VALID_DATE_RANGE_CONSTANTS
        assert "LAST_30_DAYS" in VALID_DATE_RANGE_CONSTANTS
        assert "THIS_MONTH" in VALID_DATE_RANGE_CONSTANTS

    def test_all_time_rejected(self) -> None:
        # ALL_TIME bypasses the period-days guard — callers must use BETWEEN.
        with pytest.raises(GAQLValidationError):
            validate_date_range_constant("ALL_TIME")


@pytest.mark.unit
class TestEscapeStringLiteral:
    def test_simple_string_unchanged(self) -> None:
        assert escape_string_literal("hello") == "hello"

    def test_single_quote_escaped(self) -> None:
        assert escape_string_literal("O'Brien") == "O\\'Brien"

    def test_backslash_escaped_first(self) -> None:
        assert escape_string_literal("a\\b") == "a\\\\b"

    def test_combined(self) -> None:
        # Backslash must be escaped before quotes so escape sequences aren't
        # double-processed
        assert escape_string_literal("a\\'b") == "a\\\\\\'b"

    def test_injection_attempt(self) -> None:
        raw = "foo' OR name='bar"
        escaped = escape_string_literal(raw)
        assert "'" not in escaped.replace("\\'", "")


@pytest.mark.unit
class TestValidatePeriodDays:
    def test_valid_int(self) -> None:
        assert validate_period_days(30) == 30

    def test_min_value(self) -> None:
        assert validate_period_days(1) == 1

    def test_zero_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_period_days(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_period_days(-1)

    def test_too_large_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            validate_period_days(10_000)

    def test_custom_max(self) -> None:
        assert validate_period_days(400, max_days=500) == 400
        with pytest.raises(GAQLValidationError):
            validate_period_days(600, max_days=500)


@pytest.mark.unit
class TestBuildInClause:
    def test_single_value(self) -> None:
        assert build_in_clause(["123"], "campaign_id") == "(123)"

    def test_multiple_values(self) -> None:
        assert build_in_clause(["1", "2", "3"], "id") == "(1, 2, 3)"

    def test_empty_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            build_in_clause([], "id")

    def test_injection_in_any_value_rejected(self) -> None:
        with pytest.raises(GAQLValidationError):
            build_in_clause(["1", "2); DROP TABLE campaign; --"], "id")
