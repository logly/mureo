"""Tests for the Meta minor-unit conversion helpers (mureo.policy.currency_units).

Meta's write tools carry ``daily_budget`` / ``lifetime_budget`` /
``bid_amount`` in the account currency's MINOR units, while the STRATEGY.md
``## Guardrails`` caps are written in currency units (#783). This module owns
the conversion: which tools and which keys carry minor units, the divisor the
operator's declared ``currency`` implies, and the amount formatting the deny
messages use so a fractional figure is not printed as a whole one.
"""

from __future__ import annotations

import logging
import math

import pytest

from mureo.policy.currency_units import (
    META_MINOR_UNIT_KEYS,
    META_TOOL_PREFIX,
    _amount,
    minor_unit_divisor,
    parse_currency_code,
    to_currency_units,
)

pytestmark = pytest.mark.unit


class TestMetaMinorUnitKeys:
    def test_names_exactly_the_three_meta_minor_unit_arguments(self) -> None:
        """The three Meta write-tool arguments documented as minor units."""
        assert set(META_MINOR_UNIT_KEYS) == {
            "daily_budget",
            "lifetime_budget",
            "bid_amount",
        }

    def test_tool_prefix_is_the_native_meta_namespace(self) -> None:
        assert META_TOOL_PREFIX == "meta_ads_"


class TestMinorUnitDivisor:
    def test_meta_tool_with_offset_100_currency_divides_by_100(self) -> None:
        assert minor_unit_divisor("meta_ads_campaigns_update", "EUR") == 100

    def test_meta_tool_with_zero_decimal_currency_does_not_divide(self) -> None:
        assert minor_unit_divisor("meta_ads_ad_sets_update", "JPY") == 1

    def test_google_tool_is_never_converted(self) -> None:
        """Google amounts are micros or currency units — never minor units."""
        assert minor_unit_divisor("google_ads_campaigns_update", "EUR") == 1

    def test_no_declared_currency_leaves_meta_amounts_alone(self) -> None:
        assert minor_unit_divisor("meta_ads_ad_sets_update", None) == 1

    def test_unknown_code_propagates(self) -> None:
        """The parser validated the code, so this is a programming error."""
        with pytest.raises(ValueError):
            minor_unit_divisor("meta_ads_ad_sets_update", "XYZ")


class TestToCurrencyUnits:
    def test_divides_minor_units(self) -> None:
        assert to_currency_units(25000.0, 100) == 250.0

    def test_keeps_fractions(self) -> None:
        assert to_currency_units(25050.0, 100) == 250.5

    def test_divisor_one_is_identity(self) -> None:
        assert to_currency_units(25000.0, 1) == 25000.0

    def test_saturated_infinity_stays_infinity(self) -> None:
        """An oversized int saturated to inf must still fail closed."""
        assert to_currency_units(math.inf, 100) == math.inf
        assert to_currency_units(-math.inf, 100) == -math.inf

    def test_nan_stays_nan(self) -> None:
        assert math.isnan(to_currency_units(math.nan, 100))


class TestParseCurrencyCode:
    def test_upper_cases_and_strips(self) -> None:
        assert parse_currency_code(" eur ") == "EUR"

    def test_unknown_code_is_dropped_with_one_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_currency_code("XYZ") is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "XYZ" in warnings[0].getMessage()

    def test_absent_is_none_without_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_currency_code(None) is None
            assert parse_currency_code("   ") is None
        assert not caplog.records


class TestAmount:
    def test_integral_values_render_exactly_as_before(self) -> None:
        assert _amount(250.0) == "250"
        assert _amount(1234.0) == "1,234"

    def test_integer_caps_render_without_decimals(self) -> None:
        """A cap may be a bare ``int`` (constructed, not parsed)."""
        assert _amount(50000) == "50,000"

    def test_fractional_values_keep_their_cents(self) -> None:
        assert _amount(250.01) == "250.01"
        assert _amount(250.5) == "250.50"
        assert _amount(1234.56) == "1,234.56"
