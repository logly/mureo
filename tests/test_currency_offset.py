"""Currency-offset handling for Meta budget conversions.

Meta expresses budgets in the currency's minor unit with a per-currency
offset (https://developers.facebook.com/docs/marketing-api/currencies):
offset 100 for e.g. USD ("1500" = 15.00 USD) and offset 1 for
zero-decimal currencies (JPY, KRW, TWD, ... — "5000" = ¥5,000). A blanket
÷100 / ×10_000 silently scales JPY budgets by 100x, so every conversion
must be currency-aware.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.core.providers.models import ZERO_DECIMAL_CURRENCIES, minor_units_per_unit

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Core helper
# ---------------------------------------------------------------------------


class TestMinorUnitsPerUnit:
    def test_offset_100_for_decimal_currencies(self) -> None:
        assert minor_units_per_unit("USD") == 100
        assert minor_units_per_unit("EUR") == 100

    def test_offset_1_for_zero_decimal_currencies(self) -> None:
        for code in ("JPY", "KRW", "TWD", "VND", "IDR", "HUF", "CLP"):
            assert minor_units_per_unit(code) == 1, code

    def test_case_and_whitespace_insensitive(self) -> None:
        assert minor_units_per_unit(" jpy ") == 1

    def test_unknown_currency_fails_fast(self) -> None:
        # Guessing an offset for an unrecognized code could send a
        # 100x-too-large budget to the live API — refuse instead.
        with pytest.raises(ValueError, match="currency"):
            minor_units_per_unit("XXX")

    def test_typo_of_zero_decimal_code_fails_fast(self) -> None:
        """ "JPN" must not silently fall back to offset 100."""
        with pytest.raises(ValueError, match="JPN"):
            minor_units_per_unit("JPN")

    def test_zero_decimal_set_matches_meta_docs(self) -> None:
        assert ZERO_DECIMAL_CURRENCIES == frozenset(
            {
                "CLP",
                "COP",
                "CRC",
                "HUF",
                "IDR",
                "ISK",
                "JPY",
                "KRW",
                "PYG",
                "TWD",
                "VND",
            }
        )


# ---------------------------------------------------------------------------
# mureo.meta_ads.mappers (exported read mappers)
# ---------------------------------------------------------------------------


class TestMetaAdsMappersCurrency:
    def _raw_campaign(self) -> dict[str, Any]:
        return {
            "id": "1",
            "name": "C",
            "status": "ACTIVE",
            "daily_budget": "5000",
            "lifetime_budget": "90000",
        }

    def test_map_campaign_jpy_budget_is_not_divided(self) -> None:
        from mureo.meta_ads.mappers import map_campaign

        out = map_campaign(self._raw_campaign(), currency="JPY")
        assert out["daily_budget"] == 5000.0
        assert out["lifetime_budget"] == 90000.0

    def test_map_campaign_usd_budget_divided_by_100(self) -> None:
        from mureo.meta_ads.mappers import map_campaign

        out = map_campaign(self._raw_campaign(), currency="USD")
        assert out["daily_budget"] == 50.0
        assert out["lifetime_budget"] == 900.0

    def test_map_ad_set_jpy_bid_amount(self) -> None:
        from mureo.meta_ads.mappers import map_ad_set

        raw: dict[str, Any] = {
            "id": "2",
            "name": "AS",
            "status": "ACTIVE",
            "daily_budget": "3000",
            "bid_amount": "120",
        }
        out = map_ad_set(raw, currency="JPY")
        assert out["daily_budget"] == 3000.0
        assert out["bid_amount"] == 120.0


# ---------------------------------------------------------------------------
# mureo.adapters.meta_ads (provider adapter boundary)
# ---------------------------------------------------------------------------


class TestAdapterMapperCurrency:
    def test_to_campaign_jpy_minor_units_to_micros(self) -> None:
        """JPY "5000" means ¥5,000 → 5_000_000_000 micros (not 50_000_000)."""
        from mureo.adapters.meta_ads.mappers import to_campaign

        raw: dict[str, Any] = {
            "id": "c1",
            "name": "JP",
            "status": "ACTIVE",
            "daily_budget": "5000",
        }
        out = to_campaign(raw, account_id="act_1", currency="JPY")
        assert out.daily_budget_micros == 5_000_000_000

    def test_to_campaign_usd_cents_to_micros(self) -> None:
        from mureo.adapters.meta_ads.mappers import to_campaign

        raw: dict[str, Any] = {
            "id": "c1",
            "name": "US",
            "status": "ACTIVE",
            "daily_budget": "1500",
        }
        out = to_campaign(raw, account_id="act_1", currency="USD")
        assert out.daily_budget_micros == 15_000_000


class TestAdapterWriteCurrency:
    def _adapter(self, currency: str) -> Any:
        from unittest.mock import MagicMock

        from mureo.adapters.meta_ads.adapter import MetaAdsAdapter
        from mureo.meta_ads.client import MetaAdsApiClient

        mock_client = MagicMock(spec=MetaAdsApiClient)
        mock_client._ad_account_id = "act_1"
        return MetaAdsAdapter(client=mock_client, currency=currency)

    def test_micros_to_minor_units_jpy(self) -> None:
        """¥5,000/day (5e9 micros) must reach Meta as 5000 — not 500,000."""
        from mureo.adapters.meta_ads.adapter import _micros_to_minor_units

        assert _micros_to_minor_units(5_000_000_000, "JPY") == 5000

    def test_micros_to_minor_units_usd(self) -> None:
        from mureo.adapters.meta_ads.adapter import _micros_to_minor_units

        assert _micros_to_minor_units(15_000_000, "USD") == 1500

    def test_micros_to_minor_units_rejects_negative(self) -> None:
        from mureo.adapters.meta_ads.adapter import _micros_to_minor_units

        with pytest.raises(ValueError, match="non-negative"):
            _micros_to_minor_units(-1, "USD")

    def test_micros_to_minor_units_unknown_currency_fails_fast(self) -> None:
        from mureo.adapters.meta_ads.adapter import _micros_to_minor_units

        with pytest.raises(ValueError, match="currency"):
            _micros_to_minor_units(5_000_000_000, "JPN")

    def test_adapter_requires_currency(self) -> None:
        from unittest.mock import MagicMock

        from mureo.adapters.meta_ads.adapter import MetaAdsAdapter
        from mureo.meta_ads.client import MetaAdsApiClient

        mock_client = MagicMock(spec=MetaAdsApiClient)
        with pytest.raises(TypeError):
            MetaAdsAdapter(client=mock_client)  # type: ignore[call-arg]

    def test_adapter_rejects_blank_currency(self) -> None:
        with pytest.raises(ValueError, match="currency"):
            self._adapter("  ")
