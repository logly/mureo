"""The ``YYYY-MM-DD..YYYY-MM-DD`` spelling of a Google Ads ``period`` (#866).

Google Ads took an explicit range only in GAQL spelling
(``BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'``) while Meta Ads took
``YYYY-MM-DD..YYYY-MM-DD``. Google now accepts the Meta form as well, so one
spelling works on both platforms; the GAQL one keeps working. These tests pin
the new spelling on every layer the GAQL one already crosses: the validator,
the clause builder, the comparison resolver, the published schema and the
dispatcher. The schema-to-validator pin itself lives beside the GAQL one in
``tests/test_google_ads_period_contract.py``.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.google_ads._analysis_constants import _get_comparison_date_ranges
from mureo.google_ads._gaql_validator import (
    _DEFAULT_MAX_PERIOD_DAYS as _MAX_PERIOD_DAYS,
)
from mureo.google_ads._gaql_validator import (
    PERIOD_RANGE_PATTERN,
    GAQLValidationError,
    is_explicit_period_range,
    parse_period_range,
)
from mureo.google_ads.client import GoogleAdsApiClient
from mureo.mcp._period_param import CUSTOM_RANGE_HINT
from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS

pytestmark = pytest.mark.unit

_DOTTED = "2026-05-01..2026-05-31"
_GAQL = "BETWEEN '2026-05-01' AND '2026-05-31'"

_PERIOD_TOOLS = (
    "google_ads_performance_report",
    "google_ads_keywords_audit",
    "google_ads_conversions_performance",
)
_COMPARISON_TOOLS = (
    "google_ads_search_terms_review",
    "google_ads_performance_analyze",
    "google_ads_negative_keywords_suggest",
)
_REQUIRED_STUBS: dict[str, Any] = {
    "campaign_id": "23743184133",
    "customer_id": "1234567890",
}


def _make_client() -> GoogleAdsApiClient:
    with patch("mureo.google_ads.client.GoogleAdsClient"):
        return GoogleAdsApiClient(
            credentials=MagicMock(),
            customer_id="1234567890",
            developer_token="test-dev-token",
        )


def _args(tool_name: str, period: str) -> dict[str, Any]:
    for tool in GOOGLE_ADS_TOOLS:
        if tool.name == tool_name:
            required = tool.inputSchema.get("required", ())
            stubs = {f: _REQUIRED_STUBS[f] for f in required if f != "period"}
            return {**stubs, "period": period}
    raise AssertionError(f"tool not registered: {tool_name}")


def _validate(tool_name: str, arguments: dict[str, Any]) -> None:
    from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

    if tool_name not in _TOOL_VALIDATORS:
        pytest.skip("google_ads tools disabled in this environment")
    _validate_tool_input(tool_name, arguments)


class TestParsePeriodRange:
    def test_dotted_range_returns_inclusive_endpoints(self) -> None:
        assert parse_period_range(_DOTTED) == (date(2026, 5, 1), date(2026, 5, 31))

    def test_gaql_spelling_still_parses(self) -> None:
        assert parse_period_range(_GAQL) == (date(2026, 5, 1), date(2026, 5, 31))

    def test_single_day_range(self) -> None:
        assert parse_period_range("2026-05-10..2026-05-10") == (
            date(2026, 5, 10),
            date(2026, 5, 10),
        )

    def test_reversed_range_is_refused_like_the_gaql_path(self) -> None:
        with pytest.raises(GAQLValidationError, match="end date precedes start date"):
            parse_period_range("2026-05-31..2026-05-01")

    def test_impossible_date_names_the_endpoint(self) -> None:
        with pytest.raises(GAQLValidationError, match="period.start"):
            parse_period_range("2026-13-01..2026-05-31")

    def test_span_guard_applies(self) -> None:
        with pytest.raises(GAQLValidationError, match="Date range too long"):
            parse_period_range("1900-01-01..2100-01-01")

    @pytest.mark.parametrize(
        "bad",
        [
            "2026-1-1..2026-01-31",  # unpadded
            "2026-05-01..",  # missing end
            "..2026-05-31",  # missing start
            "2026-05-01..2026-05-14..2026-05-21",  # three parts
            "2026-05-01...2026-05-31",  # three dots
            "2026-05-01 .. 2026-05-31",  # whitespace around the separator
            "2026/05/01..2026/05/31",  # slashes
            "２０２６-０５-０１..2026-05-31",  # full-width digits
            "'2026-05-01'..'2026-05-31'",  # GAQL quoting on the dotted form
            "BETWEEN '2026-05-01'..'2026-05-31'",  # GAQL keyword with dots
            "2026-05-01..2026-05-31 OR 1=1",  # trailing predicate
            "",
        ],
    )
    def test_malformed_values_are_refused(self, bad: str) -> None:
        with pytest.raises(GAQLValidationError):
            parse_period_range(bad)

    def test_non_string_is_refused(self) -> None:
        with pytest.raises(GAQLValidationError, match="Invalid period"):
            parse_period_range(None)  # type: ignore[arg-type]


def test_is_explicit_period_range() -> None:
    """Both spellings (padded, any case, malformed too) route to the range
    parser; a constant and a non-string do not — callers refuse a non-string
    themselves before asking."""
    assert is_explicit_period_range(_DOTTED)
    assert is_explicit_period_range(_GAQL)
    assert is_explicit_period_range("  between '2026-05-01' and '2026-05-31' ")
    assert is_explicit_period_range("2026-1-1..")
    assert not is_explicit_period_range("LAST_30_DAYS")
    assert not is_explicit_period_range(None)  # type: ignore[arg-type]


class TestPattern:
    def test_is_anchored_python_side(self) -> None:
        assert PERIOD_RANGE_PATTERN.startswith(r"\A")
        assert PERIOD_RANGE_PATTERN.endswith(r"\Z")

    def test_accepts_the_documented_form(self) -> None:
        assert re.fullmatch(PERIOD_RANGE_PATTERN, _DOTTED) is not None

    @pytest.mark.parametrize("bad", [f"{_DOTTED}\n", f"\n{_DOTTED}", "2026-1-1.."])
    def test_rejects_what_the_parser_would_not_take(self, bad: str) -> None:
        assert re.search(PERIOD_RANGE_PATTERN, bad) is None


class TestClauseBuilder:
    def test_dotted_range_becomes_the_gaql_clause(self) -> None:
        clause = _make_client()._period_to_date_clause("2026-01-01..2026-01-31")
        assert clause == "BETWEEN '2026-01-01' AND '2026-01-31'"

    def test_both_spellings_build_the_same_clause(self) -> None:
        client = _make_client()
        assert client._period_to_date_clause(_DOTTED) == (
            client._period_to_date_clause(_GAQL)
        )

    def test_malformed_dotted_range_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Invalid period range"):
            _make_client()._period_to_date_clause("2026-1-1..2026-01-31")

    def test_span_guard_applies(self) -> None:
        with pytest.raises(ValueError, match="Date range too long"):
            _make_client()._period_to_date_clause("1900-01-01..2100-01-01")


class TestComparisonPath:
    def test_dotted_range_is_honoured_like_the_gaql_one(self) -> None:
        assert _get_comparison_date_ranges(_DOTTED) == (
            _get_comparison_date_ranges(_GAQL)
        )

    def test_reversed_dotted_range_is_refused(self) -> None:
        with pytest.raises(ValueError, match="end date precedes start date"):
            _get_comparison_date_ranges("2026-05-31..2026-05-01")


class TestSchema:
    @pytest.mark.parametrize("tool_name", _PERIOD_TOOLS + _COMPARISON_TOOLS)
    def test_dotted_range_is_accepted(self, tool_name: str) -> None:
        _validate(tool_name, _args(tool_name, _DOTTED))

    @pytest.mark.parametrize(
        "bad", ["2026-1-1..2026-01-31", f"{_DOTTED}\n", "2026-05-01...2026-05-31"]
    )
    def test_malformed_dotted_range_is_refused(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate("google_ads_performance_report", {"period": bad})

    def test_hint_documents_both_spellings(self) -> None:
        assert "YYYY-MM-DD..YYYY-MM-DD" in CUSTOM_RANGE_HINT
        assert "BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'" in CUSTOM_RANGE_HINT


class TestDispatcher:
    @pytest.mark.parametrize("period", [_DOTTED, _GAQL])
    async def test_range_reaches_the_client_as_a_between_clause(
        self, period: str, monkeypatch: Any
    ) -> None:
        """End to end through ``server.handle_call_tool``: either spelling
        reaches the GAQL query as the same re-emitted ``BETWEEN`` clause."""
        from mureo.mcp import _handlers_google_ads as handlers
        from mureo.mcp import server

        if "google_ads_performance_report" not in server._TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")

        client = _make_client()
        queries: list[str] = []

        async def _record(query: str, *_args: Any, **_kwargs: Any) -> list[Any]:
            queries.append(query)
            return []

        monkeypatch.setattr(client, "_search", _record)
        monkeypatch.setattr(handlers, "_get_client", AsyncMock(return_value=client))

        await server.handle_call_tool(
            "google_ads_performance_report", {"period": period}
        )
        assert len(queries) == 1
        assert f"WHERE segments.date {_GAQL}" in queries[0]


def test_bound_is_shared_with_the_gaql_spelling() -> None:
    """The longest permitted dotted window is exactly the GAQL one's bound."""
    start, end = parse_period_range(f"2020-01-01..{date(2021, 12, 30).isoformat()}")
    assert (end - start).days + 1 == _MAX_PERIOD_DAYS
