"""The Google Ads ``period`` contract, end to end (#716 / #717 / #718).

Three lists used to drift apart with nothing holding them together:

* the ``enum`` the MCP tool schemas offer (three byte-identical copies),
* the whitelist ``mureo.google_ads._gaql_validator`` accepts, and
* the presets ``_get_comparison_date_ranges`` can turn into a
  period-over-period pair.

Every test here pins one edge of that triangle, so a value can no longer be
offered by a schema and then rejected (or silently substituted) downstream.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import TextContent

from mureo.core import clock
from mureo.google_ads import _analysis_constants
from mureo.google_ads._analysis_constants import (
    _PERIOD_DAYS,
    _get_comparison_date_ranges,
)
from mureo.google_ads._gaql_validator import (
    _DEFAULT_MAX_PERIOD_DAYS as _MAX_PERIOD_DAYS,
)
from mureo.google_ads._gaql_validator import (
    DERIVED_DATE_RANGE_DAYS,
    PERIOD_BETWEEN_PATTERN,
    SUPPORTED_PERIOD_CONSTANTS,
    VALID_DATE_RANGE_CONSTANTS,
    GAQLValidationError,
    format_between_clause,
    parse_between_clause,
    resolve_derived_date_range,
    trailing_window,
)
from mureo.google_ads.client import GoogleAdsApiClient
from mureo.mcp._period_param import (
    _PRESENTATION_ORDER,
    COMPARISON_PERIOD_CONSTANTS,
    PERIOD_CONSTANTS,
    _display_rank,
    comparison_period_param,
    period_param,
)
from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_RANGE = "BETWEEN '2026-05-01' AND '2026-05-31'"
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_client() -> GoogleAdsApiClient:
    with patch("mureo.google_ads.client.GoogleAdsClient"):
        return GoogleAdsApiClient(
            credentials=MagicMock(),
            customer_id="1234567890",
            developer_token="test-dev-token",
        )


def _period_schema(tool_name: str) -> dict[str, Any] | None:
    for tool in GOOGLE_ADS_TOOLS:
        if tool.name != tool_name:
            continue
        props = tool.inputSchema.get("properties", {})
        return props.get("period")
    raise AssertionError(f"tool not registered: {tool_name}")


def _tools_with_period() -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for tool in GOOGLE_ADS_TOOLS:
        schema = getattr(tool, "inputSchema", None)
        if not isinstance(schema, dict):
            continue
        period = schema.get("properties", {}).get("period")
        if isinstance(period, dict):
            found.append((tool.name, period))
    return found


def _enum_of(period_schema: dict[str, Any]) -> list[str] | None:
    for branch in period_schema.get("anyOf", ()):
        if "enum" in branch:
            return list(branch["enum"])
    return period_schema.get("enum")


_REQUIRED_STUBS: dict[str, Any] = {
    "campaign_id": "23743184133",
    "ad_group_id": "145680123456",
    "customer_id": "1234567890",
    "conversion_action_id": "987654321",
    "keywords": ["k"],
    "keyword_text": "k",
    "url": "https://example.com/",
    "days": 7,
}


def _args_with_period(tool_name: str, period: Any) -> dict[str, Any]:
    """Minimal schema-satisfying arguments for ``tool_name``, plus ``period``.

    Built from the tool's own ``required`` list so a tool gaining a required
    field does not turn this into a test that passes for the wrong reason.
    """
    for tool in GOOGLE_ADS_TOOLS:
        if tool.name != tool_name:
            continue
        args: dict[str, Any] = {"period": period}
        for field in tool.inputSchema.get("required", ()):
            if field == "period":
                continue
            assert field in _REQUIRED_STUBS, f"no stub for {tool_name}.{field}"
            args[field] = _REQUIRED_STUBS[field]
        return args
    raise AssertionError(f"tool not registered: {tool_name}")


# The 18 tools issue #716 enumerates: 17 in _tools_google_ads_analysis plus
# google_ads_conversions_performance in _tools_google_ads_extensions.
_ENUM_TOOLS = (
    "google_ads_performance_report",
    "google_ads_search_terms_report",
    "google_ads_search_terms_review",
    "google_ads_auction_insights_analyze",
    "google_ads_cpc_detect_trend",
    "google_ads_device_analyze",
    "google_ads_network_performance_report",
    "google_ads_ad_performance_report",
    "google_ads_search_terms_analyze",
    "google_ads_performance_analyze",
    "google_ads_ad_performance_compare",
    "google_ads_budget_efficiency",
    "google_ads_budget_reallocation",
    "google_ads_auction_insights_get",
    "google_ads_rsa_assets_analyze",
    "google_ads_rsa_assets_audit",
    "google_ads_btob_optimizations",
    "google_ads_conversions_performance",
)

# Tools that resolve their own window through _get_comparison_date_ranges and
# therefore cannot honour a calendar constant (#716 caveat / #718).
_COMPARISON_TOOLS = (
    "google_ads_search_terms_review",
    "google_ads_performance_analyze",
    "google_ads_negative_keywords_suggest",
)

# The two keyword tools that pass period straight to _period_to_date_clause
# (#718). They declared it as an unconstrained string; they now carry the same
# schema as every other reporting tool, so the dispatcher rejects a malformed
# window instead of letting it reach the client.
_KEYWORD_REPORT_TOOLS = (
    "google_ads_keywords_audit",
    "google_ads_keywords_cross_adgroup_duplicates",
)


# ---------------------------------------------------------------------------
# #717 — the two lists are one list
# ---------------------------------------------------------------------------


class TestSingleSourceOfTruth:
    def test_every_offered_constant_is_honourable(self) -> None:
        """Nothing is advertised that the GAQL layer cannot resolve.

        ``PERIOD_CONSTANTS`` is derived from ``SUPPORTED_PERIOD_CONSTANTS``, so
        this checks the derivation's INPUT is the union it claims to be — the
        part a transcription error could still get wrong.
        """
        assert (
            VALID_DATE_RANGE_CONSTANTS | set(DERIVED_DATE_RANGE_DAYS)
            == SUPPORTED_PERIOD_CONSTANTS
        )
        assert set(PERIOD_CONSTANTS) == SUPPORTED_PERIOD_CONSTANTS

    def test_offered_constants_have_no_duplicates(self) -> None:
        assert len(PERIOD_CONSTANTS) == len(set(PERIOD_CONSTANTS))

    def test_offered_order_is_shortest_window_first(self) -> None:
        """Derivation must not scramble the published order into set order."""
        assert PERIOD_CONSTANTS[:4] == (
            "TODAY",
            "YESTERDAY",
            "THIS_WEEK_SUN_TODAY",
            "THIS_WEEK_MON_TODAY",
        )
        assert PERIOD_CONSTANTS[-3:] == ("LAST_90_DAYS", "THIS_MONTH", "LAST_MONTH")

    def test_an_unranked_constant_still_ships(self) -> None:
        """Membership comes from the whitelist; the order table is cosmetic. A
        constant Google adds later must not silently vanish from the enum
        because nobody remembered to rank it."""
        ranked = _display_rank("LAST_7_DAYS")
        unranked = _display_rank("LAST_3_DAYS_THAT_DO_NOT_EXIST_YET")
        assert ranked < unranked
        assert unranked[0] == len(_PRESENTATION_ORDER)

    def test_last_90_days_is_offered(self) -> None:
        """#717's headline: LAST_90_DAYS is recommended, so it must work."""
        assert "LAST_90_DAYS" in PERIOD_CONSTANTS

    @pytest.mark.parametrize(
        "constant",
        [
            "LAST_BUSINESS_WEEK",
            "LAST_WEEK_SUN_SAT",
            "LAST_WEEK_MON_SUN",
            "THIS_WEEK_SUN_TODAY",
            "THIS_WEEK_MON_TODAY",
        ],
    )
    def test_previously_unreachable_constants_are_offered(self, constant: str) -> None:
        assert constant in PERIOD_CONSTANTS

    def test_every_offered_constant_reaches_a_date_clause(self) -> None:
        client = _make_client()
        for constant in PERIOD_CONSTANTS:
            clause = client._period_to_date_clause(constant)
            assert clause.startswith(("DURING ", "BETWEEN "))

    def test_comparison_constants_match_the_comparison_resolver(self) -> None:
        """The comparison enum is exactly what _PERIOD_DAYS can honour."""
        assert set(COMPARISON_PERIOD_CONSTANTS) == set(_PERIOD_DAYS)

    def test_comparison_constants_are_a_subset_of_the_full_enum(self) -> None:
        assert set(COMPARISON_PERIOD_CONSTANTS) <= set(PERIOD_CONSTANTS)

    def test_no_tool_carries_its_own_copy_of_the_enum(self) -> None:
        """The three byte-identical enum copies collapsed into one definition.

        Any ``period`` enum on the Google Ads surface must be one of the two
        shared lists — a fourth hand-maintained copy fails here.
        """
        allowed = {
            tuple(PERIOD_CONSTANTS),
            tuple(COMPARISON_PERIOD_CONSTANTS),
        }
        for name, schema in _tools_with_period():
            enum = _enum_of(schema)
            # A budget's period ("DAILY" / "CUSTOM_PERIOD") is an unrelated
            # parameter that happens to share the name; only date-range enums
            # are in scope.
            if enum is None or not set(enum) & set(PERIOD_CONSTANTS):
                continue
            assert tuple(enum) in allowed, f"{name} declares its own period enum"


# ---------------------------------------------------------------------------
# #717 — LAST_90_DAYS is resolved, not rejected
# ---------------------------------------------------------------------------


class TestLast90Days:
    def test_resolves_to_a_between_clause(self, monkeypatch: Any) -> None:
        frozen = datetime(2026, 5, 20, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        clause = _make_client()._period_to_date_clause("LAST_90_DAYS")
        # 90 days ending yesterday: 2026-02-19 .. 2026-05-19 inclusive.
        assert clause == "BETWEEN '2026-02-19' AND '2026-05-19'"

    def test_is_case_insensitive_like_the_constants(self, monkeypatch: Any) -> None:
        frozen = datetime(2026, 5, 20, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        assert (
            _make_client()._period_to_date_clause("last_90_days")
            == "BETWEEN '2026-02-19' AND '2026-05-19'"
        )

    def test_window_excludes_today_and_spans_90_days(self, monkeypatch: Any) -> None:
        frozen = datetime(2026, 5, 20, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        clause = _make_client()._period_to_date_clause("LAST_90_DAYS")
        match = re.fullmatch(PERIOD_BETWEEN_PATTERN, clause)
        assert match is not None
        start, end = (date.fromisoformat(d) for d in match.groups())
        assert end == frozen.date() - timedelta(days=1)
        assert (end - start).days + 1 == 90

    def test_boundary_matches_the_trailing_preset_convention(
        self, monkeypatch: Any
    ) -> None:
        """The derived window uses the same 'ends yesterday' boundary the
        existing trailing presets use, so a 90-day baseline is comparable to
        a 30-day one."""
        frozen = datetime(2026, 5, 20, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        current, _ = _get_comparison_date_ranges("LAST_30_DAYS")
        assert current == "BETWEEN '2026-04-20' AND '2026-05-19'"
        derived = _make_client()._period_to_date_clause("LAST_90_DAYS")
        assert derived.endswith("AND '2026-05-19'")

    def test_derived_clause_is_accepted_by_the_gaql_layer(
        self, monkeypatch: Any
    ) -> None:
        """The derived string is re-validated as a normal BETWEEN clause."""
        frozen = datetime(2026, 5, 20, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        client = _make_client()
        derived = client._period_to_date_clause("LAST_90_DAYS")
        assert client._period_to_date_clause(derived) == derived

    def test_is_not_smuggled_into_the_gaql_whitelist(self) -> None:
        """LAST_90_DAYS has no GAQL constant; it must stay out of DURING."""
        assert "LAST_90_DAYS" not in VALID_DATE_RANGE_CONSTANTS

    def test_comparison_path_honours_it(self, monkeypatch: Any) -> None:
        frozen = datetime(2026, 5, 20, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        current, previous = _get_comparison_date_ranges("LAST_90_DAYS")
        assert current == "BETWEEN '2026-02-19' AND '2026-05-19'"
        assert previous == "BETWEEN '2025-11-21' AND '2026-02-18'"


# ---------------------------------------------------------------------------
# Leap day
# ---------------------------------------------------------------------------


class TestLeapDay:
    """Expected dates were derived by walking the calendar day by day, not by
    repeating the ``timedelta`` arithmetic under test."""

    def test_derived_window_spans_the_leap_day(self, monkeypatch: Any) -> None:
        frozen = datetime(2028, 3, 1, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        assert (
            _make_client()._period_to_date_clause("LAST_90_DAYS")
            == "BETWEEN '2027-12-02' AND '2028-02-29'"
        )

    def test_comparison_windows_span_the_leap_day(self, monkeypatch: Any) -> None:
        frozen = datetime(2028, 3, 1, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        current, previous = _get_comparison_date_ranges("LAST_90_DAYS")
        assert current == "BETWEEN '2027-12-02' AND '2028-02-29'"
        assert previous == "BETWEEN '2027-09-03' AND '2027-12-01'"

    def test_the_leap_day_is_one_of_the_ninety(self, monkeypatch: Any) -> None:
        """A window ending 29 Feb must contain 29 Feb — off-by-one insurance
        that reading the literals above cannot give."""
        frozen = datetime(2028, 3, 1, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        start, end = parse_between_clause(
            _make_client()._period_to_date_clause("LAST_90_DAYS")
        )
        assert start <= date(2028, 2, 29) <= end
        assert (end - start).days + 1 == 90

    def test_previous_window_of_an_explicit_range_absorbs_the_leap_day(self) -> None:
        """March 2028's preceding 31 days end on the leap day, so the previous
        window is one day 'shorter' in calendar months and exactly as long in
        days — which is the contract."""
        current, previous = _get_comparison_date_ranges(
            "BETWEEN '2028-03-01' AND '2028-03-31'"
        )
        assert current == "BETWEEN '2028-03-01' AND '2028-03-31'"
        assert previous == "BETWEEN '2028-01-30' AND '2028-02-29'"

    def test_the_non_leap_year_control(self, monkeypatch: Any) -> None:
        """Same ask one year earlier, when February is 28 days — the two
        results differ, so the leap case above is really exercising it."""
        frozen = datetime(2027, 3, 1, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        assert (
            _make_client()._period_to_date_clause("LAST_90_DAYS")
            == "BETWEEN '2026-12-01' AND '2027-02-28'"
        )


# ---------------------------------------------------------------------------
# #716 — the schemas accept an explicit range
# ---------------------------------------------------------------------------


class TestSchemaAcceptsCustomRange:
    @pytest.mark.parametrize("tool_name", _ENUM_TOOLS)
    def test_between_is_accepted(self, tool_name: str) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        if tool_name not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        _validate_tool_input(tool_name, _args_with_period(tool_name, _SAMPLE_RANGE))

    @pytest.mark.parametrize("tool_name", _ENUM_TOOLS)
    def test_constants_still_accepted(self, tool_name: str) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        if tool_name not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        _validate_tool_input(tool_name, _args_with_period(tool_name, "LAST_30_DAYS"))

    @pytest.mark.parametrize(
        "bad",
        [
            "2026-05-01..2026-05-31",  # the Meta-only spelling (#718)
            "BETWEEN 2026-05-01 AND 2026-05-31",  # unquoted
            "BETWEEN '2026-05-01' AND '2026-05-31' OR 1=1",  # trailing predicate
            "BETWEEN '2026-05-01' AND '2026-05-31'; SELECT",  # statement break
            "LAST_30_DAYS' OR '1'='1",  # quote escape
            "DURING LAST_30_DAYS",  # already-built clause
            "ALL_TIME",  # deliberately not whitelisted
            "between '2026-05-01' and '2026-05-31'",  # lowercase keywords
            "",
        ],
    )
    def test_malformed_periods_are_rejected(self, bad: str) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        tool = "google_ads_performance_report"
        if tool not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(tool, {"period": bad})

    def test_non_string_period_is_rejected(self) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        tool = "google_ads_performance_report"
        if tool not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(tool, {"period": 30})


class TestDispatcherPassesCustomRangeThrough:
    """The real dispatcher path (#660): schema validation runs inside
    ``handle_call_tool`` before any handler, so these assertions are about
    what an MCP caller actually experiences."""

    async def test_between_reaches_the_handler_untouched(
        self, monkeypatch: Any
    ) -> None:
        from mureo.mcp import server

        if "google_ads_performance_report" not in server._TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")

        seen: dict[str, Any] = {}

        async def _record(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            seen["name"] = name
            seen["arguments"] = arguments
            return [TextContent(type="text", text="{}")]

        monkeypatch.setattr(server, "_dispatch_tool", _record)
        await server.handle_call_tool(
            "google_ads_performance_report", {"period": _SAMPLE_RANGE}
        )
        assert seen["arguments"]["period"] == _SAMPLE_RANGE

    async def test_meta_style_range_is_refused_before_the_handler(
        self, monkeypatch: Any
    ) -> None:
        from mureo.mcp import server

        if "google_ads_performance_report" not in server._TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")

        called = False

        async def _record(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            nonlocal called
            called = True
            return [TextContent(type="text", text="{}")]

        monkeypatch.setattr(server, "_dispatch_tool", _record)
        with pytest.raises(ValueError, match="Invalid arguments"):
            await server.handle_call_tool(
                "google_ads_performance_report",
                {"period": "2026-05-01..2026-05-31"},
            )
        assert called is False


# ---------------------------------------------------------------------------
# #716 caveat / #718 — no silent 7-day substitution
# ---------------------------------------------------------------------------


class TestComparisonWindowResolution:
    def test_explicit_range_is_honoured(self) -> None:
        current, previous = _get_comparison_date_ranges(_SAMPLE_RANGE)
        assert current == _SAMPLE_RANGE
        # 31 days immediately before, no overlap.
        assert previous == "BETWEEN '2026-03-31' AND '2026-04-30'"

    def test_previous_window_has_the_same_length(self) -> None:
        current, previous = _get_comparison_date_ranges(_SAMPLE_RANGE)
        spans = []
        for clause in (current, previous):
            match = re.fullmatch(PERIOD_BETWEEN_PATTERN, clause)
            assert match is not None
            start, end = (date.fromisoformat(d) for d in match.groups())
            spans.append((end - start).days)
        assert spans[0] == spans[1]

    def test_single_day_range_is_honoured(self) -> None:
        current, previous = _get_comparison_date_ranges(
            "BETWEEN '2026-05-10' AND '2026-05-10'"
        )
        assert current == "BETWEEN '2026-05-10' AND '2026-05-10'"
        assert previous == "BETWEEN '2026-05-09' AND '2026-05-09'"

    @pytest.mark.parametrize(
        "period",
        [
            "THIS_MONTH",
            "LAST_MONTH",
            "TODAY",
            "YESTERDAY",
            "LAST_BUSINESS_WEEK",
            "UNKNOWN_PERIOD",
            "2026-05-01..2026-05-31",
        ],
    )
    def test_unhonourable_period_raises_instead_of_defaulting_to_7_days(
        self, period: str
    ) -> None:
        """The #134 failure mode: asking for one window and getting another."""
        with pytest.raises(ValueError, match="cannot be compared"):
            _get_comparison_date_ranges(period)

    @pytest.mark.parametrize(
        "period",
        [
            "BETWEEN 2026-05-01 AND 2026-05-31",
            "BETWEEN '2026-05-01' AND '2026-05-31' OR 1=1",
            "BETWEEN '2026-13-01' AND '2026-13-31'",
        ],
    )
    def test_malformed_between_raises(self, period: str) -> None:
        with pytest.raises(ValueError):
            _get_comparison_date_ranges(period)

    def test_reversed_range_raises(self) -> None:
        with pytest.raises(ValueError):
            _get_comparison_date_ranges("BETWEEN '2026-05-31' AND '2026-05-01'")

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError):
            _get_comparison_date_ranges(None)  # type: ignore[arg-type]

    def test_uses_the_server_clock(self, monkeypatch: Any) -> None:
        """No stray datetime.now: the window follows the injected clock."""
        frozen = datetime(2026, 5, 20, 9, 0).astimezone()
        monkeypatch.setattr(clock, "server_now", lambda: frozen)
        current, previous = _get_comparison_date_ranges("LAST_7_DAYS")
        assert current == "BETWEEN '2026-05-13' AND '2026-05-19'"
        assert previous == "BETWEEN '2026-05-06' AND '2026-05-12'"

    def test_module_does_not_bind_date_today(self) -> None:
        assert not hasattr(_analysis_constants, "date_today")


class TestComparisonToolSchemas:
    @pytest.mark.parametrize("tool_name", _COMPARISON_TOOLS)
    def test_offers_only_windows_it_can_honour(self, tool_name: str) -> None:
        schema = _period_schema(tool_name)
        assert schema is not None
        assert _enum_of(schema) == list(COMPARISON_PERIOD_CONSTANTS)

    @pytest.mark.parametrize("tool_name", _COMPARISON_TOOLS)
    def test_rejects_calendar_constants_loudly(self, tool_name: str) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        if tool_name not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(tool_name, _args_with_period(tool_name, "THIS_MONTH"))

    @pytest.mark.parametrize("tool_name", _COMPARISON_TOOLS)
    def test_accepts_an_explicit_range(self, tool_name: str) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        if tool_name not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        _validate_tool_input(tool_name, _args_with_period(tool_name, _SAMPLE_RANGE))


# ---------------------------------------------------------------------------
# #718 — a description and its parser cannot drift apart
# ---------------------------------------------------------------------------


class TestDocumentedFormats:
    def test_no_google_ads_tool_documents_the_meta_range_syntax(self) -> None:
        offenders = [
            tool.name
            for tool in GOOGLE_ADS_TOOLS
            if "YYYY-MM-DD..YYYY-MM-DD" in (tool.description or "")
            or any(
                "YYYY-MM-DD..YYYY-MM-DD" in str(prop)
                for prop in tool.inputSchema.get("properties", {}).values()
            )
        ]
        assert offenders == []

    @pytest.mark.parametrize(
        "tool_name", _ENUM_TOOLS + _COMPARISON_TOOLS + _KEYWORD_REPORT_TOOLS
    )
    def test_documents_the_gaql_range_spelling(self, tool_name: str) -> None:
        schema = _period_schema(tool_name)
        assert schema is not None
        assert "BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'" in schema["description"]

    @pytest.mark.parametrize(
        "rel",
        (
            "skills/_mureo-google-ads/SKILL.md",
            "mureo/_data/skills/_mureo-google-ads/SKILL.md",
        ),
    )
    def test_skill_documents_the_range_and_the_last_90_days_clock(
        self, rel: str
    ) -> None:
        """The skill is what an operator reads before choosing a window, so it
        carries the same two facts the schema does: the explicit range works,
        and LAST_90_DAYS alone follows the server's date. Both trees, because
        the wheel ships the mirror."""
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'" in text
        assert "the 90 days ending yesterday on the server's date" in text

    @pytest.mark.parametrize("tool_name", _KEYWORD_REPORT_TOOLS)
    def test_keyword_report_tools_really_accept_the_documented_range(
        self, tool_name: str
    ) -> None:
        """The capability the description advertises is exercised on the code
        path that tool actually uses — schema first, then the clause builder."""
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        if tool_name not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        _validate_tool_input(tool_name, _args_with_period(tool_name, _SAMPLE_RANGE))
        assert _make_client()._period_to_date_clause(_SAMPLE_RANGE) == _SAMPLE_RANGE

    @pytest.mark.parametrize("tool_name", _KEYWORD_REPORT_TOOLS)
    def test_keyword_report_tools_carry_the_shared_schema(self, tool_name: str) -> None:
        """They declared `period` as an unconstrained string, so a malformed
        window only failed once it reached the client (#718 review)."""
        schema = _period_schema(tool_name)
        assert schema is not None
        assert _enum_of(schema) == list(PERIOD_CONSTANTS)

    @pytest.mark.parametrize("tool_name", _KEYWORD_REPORT_TOOLS)
    def test_keyword_report_tools_reject_a_malformed_window_at_the_dispatcher(
        self, tool_name: str
    ) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        if tool_name not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(
                tool_name, _args_with_period(tool_name, "2026-05-01..2026-05-31")
            )

    @pytest.mark.parametrize(
        "constant", ("LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS")
    )
    def test_keyword_report_tools_really_accept_the_documented_constants(
        self, constant: str
    ) -> None:
        assert _make_client()._period_to_date_clause(constant) == f"DURING {constant}"


class TestPeriodParamBuilder:
    def test_period_param_offers_both_shapes(self) -> None:
        schema = period_param("Window.")
        shapes = schema["anyOf"]
        assert shapes[0]["enum"] == list(PERIOD_CONSTANTS)
        assert shapes[1]["pattern"] == PERIOD_BETWEEN_PATTERN

    def test_comparison_period_param_narrows_the_enum(self) -> None:
        schema = comparison_period_param("Window.")
        assert schema["anyOf"][0]["enum"] == list(COMPARISON_PERIOD_CONSTANTS)

    def test_description_is_preserved_and_extended(self) -> None:
        schema = period_param("Reporting window.")
        assert schema["description"].startswith("Reporting window.")
        assert "BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'" in schema["description"]

    @pytest.mark.parametrize("builder", (period_param, comparison_period_param))
    def test_discloses_the_last_90_days_clock(self, builder: Any) -> None:
        """LAST_90_DAYS is the one offered constant Google does not resolve, so
        it is the one whose boundary follows the server's date rather than the
        account's reporting time zone. Both builders offer it, so both say so.
        """
        description = builder("Window.")["description"]
        assert "LAST_90_DAYS" in description
        assert "server's date" in description
        assert "account's reporting time zone" in description

    def test_returns_a_fresh_mapping_each_call(self) -> None:
        """Schema fragments are shared across 18 tools; a mutable singleton
        would let one tool's edit leak into the others."""
        first = period_param("A.")
        second = period_param("B.")
        assert first is not second
        assert first["anyOf"] is not second["anyOf"]


# ---------------------------------------------------------------------------
# The primitives the three layers share
# ---------------------------------------------------------------------------


class TestGaqlPeriodPrimitives:
    """Tested directly, not only through their callers: a caller that uses the
    parsed endpoints without re-formatting them (the comparison path does) gets
    no second chance to notice a nonsensical range."""

    def test_parse_returns_inclusive_endpoints(self) -> None:
        assert parse_between_clause(_SAMPLE_RANGE) == (
            date(2026, 5, 1),
            date(2026, 5, 31),
        )

    def test_parse_tolerates_case_and_spacing_at_the_boundary(self) -> None:
        assert parse_between_clause(
            "  between   '2026-05-01'   and   '2026-05-31' "
        ) == (date(2026, 5, 1), date(2026, 5, 31))

    def test_parse_rejects_a_reversed_range(self) -> None:
        with pytest.raises(ValueError, match="end date precedes start date"):
            parse_between_clause("BETWEEN '2026-05-31' AND '2026-05-01'")

    def test_parse_rejects_a_well_shaped_impossible_date(self) -> None:
        with pytest.raises(ValueError, match="period.start"):
            parse_between_clause("BETWEEN '2026-13-01' AND '2026-13-31'")

    def test_parse_rejects_unicode_digits(self) -> None:
        """``\\d`` would accept these; the pattern uses ``[0-9]``."""
        with pytest.raises(ValueError, match="Invalid BETWEEN clause"):
            parse_between_clause("BETWEEN '２０２６-０５-０１' AND '2026-05-31'")

    def test_parse_rejects_a_trailing_predicate(self) -> None:
        with pytest.raises(ValueError, match="Invalid BETWEEN clause"):
            parse_between_clause("BETWEEN '2026-05-01' AND '2026-05-31' OR 1=1")

    def test_format_rejects_a_reversed_range(self) -> None:
        with pytest.raises(ValueError, match="precedes"):
            format_between_clause(date(2026, 5, 31), date(2026, 5, 1))

    def test_format_round_trips_the_parser(self) -> None:
        assert format_between_clause(*parse_between_clause(_SAMPLE_RANGE)) == (
            _SAMPLE_RANGE
        )

    def test_trailing_window_ends_the_day_before_today(self) -> None:
        assert trailing_window(7, date(2026, 5, 20)) == (
            date(2026, 5, 13),
            date(2026, 5, 19),
        )

    def test_trailing_window_rejects_a_non_positive_length(self) -> None:
        with pytest.raises(ValueError):
            trailing_window(0, date(2026, 5, 20))

    def test_resolve_derived_passes_through_a_real_constant(self) -> None:
        assert resolve_derived_date_range("LAST_30_DAYS", date(2026, 5, 20)) is None

    def test_resolve_derived_ignores_a_non_string(self) -> None:
        assert resolve_derived_date_range(None, date(2026, 5, 20)) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The span guard: an explicit range is not a way around the ALL_TIME refusal
# ---------------------------------------------------------------------------


def _range_of(days: int, *, start: date = date(2020, 1, 1)) -> str:
    """A well-formed BETWEEN clause covering exactly ``days`` inclusive days."""
    return f"BETWEEN '{start.isoformat()}' AND '{(start + timedelta(days=days - 1)).isoformat()}'"


class TestExplicitRangeSpanGuard:
    """``ALL_TIME`` is kept out of the whitelist because an unbounded window
    bypasses the period-days guard. An unbounded ``BETWEEN`` is the same report
    by another spelling, so it is bounded by the same number."""

    def test_the_bound_is_the_one_the_day_count_validator_uses(self) -> None:
        assert _MAX_PERIOD_DAYS == 730

    def test_accepts_the_longest_permitted_window(self) -> None:
        start, end = parse_between_clause(_range_of(_MAX_PERIOD_DAYS))
        assert (end - start).days + 1 == _MAX_PERIOD_DAYS

    def test_rejects_one_day_past_the_bound(self) -> None:
        with pytest.raises(ValueError, match="731 days, maximum 730"):
            parse_between_clause(_range_of(_MAX_PERIOD_DAYS + 1))

    def test_rejects_a_two_century_window(self) -> None:
        with pytest.raises(ValueError, match="Date range too long"):
            parse_between_clause("BETWEEN '1900-01-01' AND '2100-01-01'")

    def test_clause_builder_rejects_a_two_century_window(self) -> None:
        with pytest.raises(ValueError, match="Date range too long"):
            _make_client()._period_to_date_clause(
                "BETWEEN '1900-01-01' AND '2100-01-01'"
            )

    def test_clause_builder_accepts_the_longest_permitted_window(self) -> None:
        longest = _range_of(_MAX_PERIOD_DAYS)
        assert _make_client()._period_to_date_clause(longest) == longest

    def test_comparison_path_rejects_a_two_century_window(self) -> None:
        with pytest.raises(ValueError, match="Date range too long"):
            _get_comparison_date_ranges("BETWEEN '1900-01-01' AND '2100-01-01'")

    def test_comparison_path_accepts_the_longest_permitted_window(self) -> None:
        """The previous window doubles the reach, and that is deliberate: each
        of the two queries stays inside the bound."""
        current, previous = _get_comparison_date_ranges(_range_of(_MAX_PERIOD_DAYS))
        assert current == _range_of(_MAX_PERIOD_DAYS)
        assert previous == _range_of(
            _MAX_PERIOD_DAYS, start=date(2020, 1, 1) - timedelta(days=_MAX_PERIOD_DAYS)
        )

    def test_full_calendar_range_is_a_clean_validation_error(self) -> None:
        """0001-01-01..9999-12-31 used to reach date arithmetic that raised a
        bare OverflowError down the generic exception path."""
        with pytest.raises(GAQLValidationError, match="Date range too long"):
            _get_comparison_date_ranges("BETWEEN '0001-01-01' AND '9999-12-31'")

    def test_a_window_at_the_start_of_the_calendar_is_a_clean_validation_error(
        self,
    ) -> None:
        """Short enough to pass the span guard, still too early to have an
        equal-length predecessor — the OverflowError remainder."""
        with pytest.raises(GAQLValidationError, match="too early"):
            _get_comparison_date_ranges("BETWEEN '0001-01-01' AND '0001-01-05'")

    @pytest.mark.parametrize(
        "tool_name",
        ("google_ads_performance_report", "google_ads_keywords_audit"),
    )
    def test_schema_defers_the_span_decision_downstream(self, tool_name: str) -> None:
        """The JSON Schema pattern cannot count days, so an over-long window is
        well-formed to it — which is exactly why the parser must guard."""
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        if tool_name not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        _validate_tool_input(
            tool_name,
            _args_with_period(tool_name, "BETWEEN '1900-01-01' AND '2100-01-01'"),
        )

    async def test_dispatcher_refuses_an_unbounded_window(
        self, monkeypatch: Any
    ) -> None:
        """End to end through server.handle_call_tool: the refusal reaches the
        caller as a ValueError, before any row is fetched."""
        from mureo.mcp import _handlers_google_ads as handlers
        from mureo.mcp import server

        if "google_ads_performance_report" not in server._TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")

        client = _make_client()
        searched = False

        async def _explode(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal searched
            searched = True
            raise AssertionError("the query must never be issued")

        monkeypatch.setattr(client, "_search", _explode)
        monkeypatch.setattr(handlers, "_get_client", lambda _args: client)

        with pytest.raises(ValueError, match="Date range too long"):
            await server.handle_call_tool(
                "google_ads_performance_report",
                {"period": "BETWEEN '1900-01-01' AND '2100-01-01'"},
            )
        assert searched is False


# ---------------------------------------------------------------------------
# The published pattern and the parser agree on what "the end" means
# ---------------------------------------------------------------------------


class TestPatternAnchoring:
    def test_pattern_is_anchored_python_side(self) -> None:
        """``jsonschema`` evaluates ``pattern`` with ``re.search``, where ``$``
        also matches before a single trailing newline."""
        assert PERIOD_BETWEEN_PATTERN.startswith(r"\A")
        assert PERIOD_BETWEEN_PATTERN.endswith(r"\Z")

    @pytest.mark.parametrize(
        "bad",
        [
            "BETWEEN '2026-05-01' AND '2026-05-31'\n",
            "BETWEEN '2026-05-01' AND '2026-05-31'\n\n",
            "\nBETWEEN '2026-05-01' AND '2026-05-31'",
        ],
    )
    def test_schema_rejects_a_newline_padded_clause(self, bad: str) -> None:
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        tool = "google_ads_performance_report"
        if tool not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(tool, {"period": bad})

    def test_pattern_still_accepts_the_documented_form(self) -> None:
        assert re.fullmatch(PERIOD_BETWEEN_PATTERN, _SAMPLE_RANGE) is not None
