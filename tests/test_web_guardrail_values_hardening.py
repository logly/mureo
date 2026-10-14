"""The Guardrails editor against values a typo or a hostile request can carry (#843).

What a hand-edited STRATEGY.md or a crafted POST body can hold that the
ordinary path never produces: a non-finite number (``nan``, ``inf``,
``1e999``), an integer too large for a float, a numeric string whose
separators could be read two ways, a number past any plausible cap, and a
Unicode line separator inside a prose line. Each one is either read as
"not declared" or refused with a fixed code; none of them crashes a route
or reaches the JSON encoder as ``NaN``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.policy.guardrail_fields import GuardrailField
from mureo.policy.strategy_gate import Guardrails, parse_guardrails
from mureo.web import guardrail_values, strategy_guardrails
from mureo.web.guardrail_values import (
    StrategyGuardrailsError,
    content_with_bullets,
    describe_fields,
    parse_changes,
)
from mureo.web.strategy_guardrails import read_guardrails

pytestmark = pytest.mark.unit


def _labels(item: GuardrailField) -> tuple[str, str]:
    return item.key, item.key


def _rows(content: str) -> dict[str, dict[str, Any]]:
    return {row["key"]: row for row in describe_fields(content, _labels)}


def _refusal(payload: dict[str, Any]) -> StrategyGuardrailsError:
    with pytest.raises(StrategyGuardrailsError) as excinfo:
        parse_changes(payload)
    return excinfo.value


# ---------------------------------------------------------------------------
# Non-finite values in the file
# ---------------------------------------------------------------------------


_NON_FINITE_DOC = (
    "# Strategy\n\n## Guardrails\n"
    "- max_total_daily_budget: nan\n"
    "- max_daily_budget_per_campaign: inf\n"
    "- max_daily_budget_increase_pct: 1e999\n"
    "- exclusion_impact_window_days: 1e999\n"
    "- max_delivery_share_removed_pct: -inf\n"
)

_NON_FINITE_KEYS = (
    "max_total_daily_budget",
    "max_daily_budget_per_campaign",
    "max_daily_budget_increase_pct",
    "exclusion_impact_window_days",
    "max_delivery_share_removed_pct",
)


class TestNonFiniteInTheFile:
    def test_each_reads_as_an_ignored_line(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(_NON_FINITE_DOC, encoding="utf-8")
        rows = {row["key"]: row for row in read_guardrails(path)["fields"]}
        for key in _NON_FINITE_KEYS:
            assert rows[key]["value"] is None, key
            assert rows[key]["recognised"] is False, key
            assert rows[key]["raw"] is not None, key

    def test_the_state_serialises_without_nan(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text(_NON_FINITE_DOC, encoding="utf-8")
        # allow_nan=False raises on NaN / Infinity instead of emitting them.
        text = json.dumps(read_guardrails(path), allow_nan=False)
        assert "NaN" not in text
        assert "Infinity" not in text

    def test_a_non_finite_parse_is_never_shown_as_a_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Belt and braces: even if the gate handed back ``nan``, the card
        would report the line as ignored rather than serialise it."""

        def fake_parse(content: str) -> Guardrails:
            return Guardrails(
                max_total_daily_budget=float("nan"),
                max_daily_budget_per_campaign=float("inf"),
            )

        monkeypatch.setattr(guardrail_values, "parse_guardrails", fake_parse)
        rows = _rows("- max_total_daily_budget: 1\n- max_daily_budget_per_campaign: 2")
        for key in ("max_total_daily_budget", "max_daily_budget_per_campaign"):
            assert rows[key]["value"] is None, key
            assert rows[key]["recognised"] is False, key
        json.dumps(list(rows.values()), allow_nan=False)

    def test_any_fault_while_describing_is_a_read_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "STRATEGY.md"
        path.write_text("# Strategy\n\n## Guardrails\n- x: 1\n", encoding="utf-8")

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise OverflowError("cannot convert float infinity to integer")

        monkeypatch.setattr(strategy_guardrails, "describe_fields", boom)
        with pytest.raises(StrategyGuardrailsError) as excinfo:
            read_guardrails(path)
        assert excinfo.value.code == "read_failed"
        assert "infinity" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Numbers in the request
# ---------------------------------------------------------------------------


class TestRequestNumbers:
    @pytest.mark.parametrize(
        "key", ["max_total_daily_budget", "exclusion_impact_window_days"]
    )
    def test_an_integer_too_large_for_a_float_is_refused(self, key: str) -> None:
        error = _refusal({"set": {key: 10**400}})
        assert (error.code, error.field) == ("invalid_value", key)

    def test_a_huge_numeric_string_is_refused(self) -> None:
        error = _refusal({"set": {"max_total_daily_budget": "1" + "0" * 400}})
        assert error.code == "invalid_value"

    @pytest.mark.parametrize(
        "raw",
        [
            "1,5",
            "1_0",
            "１０",
            "1,00",
            "12,34,567",
            "1.000,5",
            "١٠",
            "1e",
            "1 000",
        ],
    )
    def test_an_ambiguous_numeric_string_is_refused(self, raw: str) -> None:
        payload = {"set": {"max_total_daily_budget": raw}}
        error = _refusal(payload)
        assert (error.code, error.field) == ("invalid_value", "max_total_daily_budget")

    @pytest.mark.parametrize(
        ("raw", "written"),
        [
            ("1,000", "1000"),
            ("1,000,000.25", "1000000.25"),
            ("1000.5", "1000.5"),
            ("1e3", "1000"),
            ("1.5E2", "150"),
            (" 42 ", "42"),
        ],
    )
    def test_plain_and_grouped_numbers_are_accepted(
        self, raw: str, written: str
    ) -> None:
        changes = parse_changes({"set": {"max_total_daily_budget": raw}})
        assert changes == {"max_total_daily_budget": written}

    def test_money_has_a_ceiling(self) -> None:
        ok = parse_changes({"set": {"max_total_daily_budget": 10**12}})
        assert ok == {"max_total_daily_budget": "1000000000000"}
        error = _refusal({"set": {"max_total_daily_budget": 10**12 + 1}})
        assert (error.code, error.field) == ("out_of_range", "max_total_daily_budget")

    def test_the_increase_percentage_has_a_ceiling(self) -> None:
        key = "max_daily_budget_increase_pct"
        assert parse_changes({"set": {key: 1_000_000}}) == {key: "1000000"}
        error = _refusal({"set": {key: 1_000_001}})
        assert (error.code, error.field) == ("out_of_range", key)


# ---------------------------------------------------------------------------
# Line separators other than a newline
# ---------------------------------------------------------------------------


class TestLineSeparators:
    @pytest.mark.parametrize("separator", ["\x85", " ", " ", "\x0c"])
    def test_a_prose_line_survives_a_rewrite_byte_for_byte(
        self, separator: str
    ) -> None:
        prose = f"Policy note: keep calm{separator}ok"
        content = f"- max_total_daily_budget: 900\n{prose}\n- x: 1"
        after = content_with_bullets(content, {"max_total_daily_budget": "1200"})
        assert after == f"- max_total_daily_budget: 1200\n{prose}\n- x: 1"

    @pytest.mark.parametrize("separator", ["\x85", " ", "\x0c"])
    def test_the_card_reads_a_line_as_the_gate_does(self, separator: str) -> None:
        content = (
            f"Policy note: keep calm{separator}- max_total_daily_budget: 5\n"
            "- max_daily_budget_per_campaign: 100"
        )
        rows = _rows(content)
        gate = parse_guardrails(content)
        assert rows["max_total_daily_budget"]["raw"] is None
        assert gate.max_total_daily_budget is None
        assert rows["max_daily_budget_per_campaign"]["value"] == 100
        assert gate.max_daily_budget_per_campaign == 100

    def test_a_new_bullet_lands_after_the_last_real_bullet(self) -> None:
        content = "- x: 1\nnote - y: 2"
        after = content_with_bullets(content, {"max_total_daily_budget": "5"})
        assert after == "- x: 1\n- max_total_daily_budget: 5\nnote - y: 2"


# ---------------------------------------------------------------------------
# The label catalog
# ---------------------------------------------------------------------------


class _BrokenJson:
    @staticmethod
    def loads(_text: str) -> Any:
        raise ValueError("not json")


class TestLabelCatalog:
    def test_a_failed_load_is_retried_rather_than_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(strategy_guardrails, "_catalog_cache", None)
        monkeypatch.setattr(strategy_guardrails, "json", _BrokenJson)
        assert strategy_guardrails._i18n_catalog() == {}
        monkeypatch.setattr(strategy_guardrails, "json", json)
        catalog = strategy_guardrails._i18n_catalog()
        assert "en" in catalog
        assert strategy_guardrails._i18n_catalog() is catalog
