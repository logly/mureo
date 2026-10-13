"""Every ``## Guardrails`` field, read and written from ``mureo configure`` (#843).

The currency card (#786) proved the shape: a surgical read-modify-write of
the operator's STRATEGY.md under its lock. This extends it to every field
of :class:`~mureo.policy.strategy_gate.Guardrails`, so the layers pinned
here are the same ones, generalised:

- the read side reports what the GATE would read — the parsed value, the
  raw text, and whether the text was usable at all;
- the validator refuses an unknown key, a wrong type or an out-of-range
  number before anything is written, and never turns a blank into ``0``;
- the writer changes exactly the bullets it was asked to and leaves every
  other line of the document as it was;
- the two routes, on a real server, behind the configure UI's CSRF gate,
  with labels resolved in the caller's language.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from mureo.policy.guardrail_fields import GUARDRAIL_FIELDS
from mureo.policy.strategy_gate import guardrails_from_strategy_text
from mureo.web.guardrail_values import (
    StrategyGuardrailsError,
    content_with_bullets,
    parse_changes,
)
from mureo.web.strategy_guardrails import (
    read_guardrails,
    resolve_lang,
    write_guardrails,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path

    from mureo.web.server import ConfigureWizard


_DOC = (
    "# Strategy\n\n"
    "## Persona\n30s, busy\n\n"
    "## Guardrails\n"
    "- currency: EUR\n"
    "- max_total_daily_budget: 900\n"
    "Free prose the operator wrote.\n"
    "- blocked_operations: google_ads_keywords_remove\n\n"
    "## USP\ncheapest\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _by_key(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["key"]: row for row in state["fields"]}


def _diff_lines(before: str, after: str) -> list[tuple[str, str]]:
    """Line pairs that differ, for documents of the same line count."""
    old, new = before.splitlines(), after.splitlines()
    assert len(old) == len(new), (old, new)
    return [(a, b) for a, b in zip(old, new, strict=True) if a != b]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadGuardrails:
    def test_a_missing_file_lists_every_field_as_undeclared(
        self, tmp_path: Path
    ) -> None:
        state = read_guardrails(tmp_path / "STRATEGY.md")
        assert state["exists"] is False
        assert state["guardrails_present"] is False
        assert [row["key"] for row in state["fields"]] == [
            f.key for f in GUARDRAIL_FIELDS
        ]
        for row in state["fields"]:
            assert row["value"] is None
            assert row["raw"] is None
            assert row["recognised"] is True

    def test_each_row_carries_its_description(self, tmp_path: Path) -> None:
        row = _by_key(read_guardrails(tmp_path / "STRATEGY.md"))[
            "max_daily_budget_increase_pct"
        ]
        assert set(row) == {
            "key",
            "kind",
            "unit",
            "min",
            "max",
            "label",
            "desc",
            "value",
            "raw",
            "recognised",
        }
        assert row["kind"] == "percent"
        assert row["unit"] == "%"
        assert row["min"] == 0
        assert row["max"] is None
        assert row["label"] == "Max daily budget increase per change (%)"
        assert row["desc"]

    def test_labels_follow_the_requested_language(self, tmp_path: Path) -> None:
        row = _by_key(read_guardrails(tmp_path / "STRATEGY.md", lang="ja"))[
            "max_daily_budget_increase_pct"
        ]
        assert row["label"] == "1 回の変更で許す日予算の増加率(%)"

    def test_declared_values_are_parsed_as_the_gate_parses_them(
        self, tmp_path: Path
    ) -> None:
        path = _write(
            tmp_path / "STRATEGY.md",
            "# Strategy\n\n## Guardrails\n"
            "- currency: eur\n"
            "- max_daily_budget_per_campaign: 1,500\n"
            "- exclusion_impact_window_days: 14\n"
            "- block_learning_resets: yes\n"
            "- blocked_operations: b_tool, a_tool\n"
            "- exclusion_impact_metrics: Impressions, cost\n",
        )
        rows = _by_key(read_guardrails(path))
        assert rows["currency"]["value"] == "EUR"
        assert rows["currency"]["raw"] == "eur"
        assert rows["max_daily_budget_per_campaign"]["value"] == 1500.0
        assert rows["max_daily_budget_per_campaign"]["raw"] == "1,500"
        assert rows["exclusion_impact_window_days"]["value"] == 14
        assert rows["block_learning_resets"]["value"] is True
        assert rows["blocked_operations"]["value"] == ["b_tool", "a_tool"]
        assert rows["exclusion_impact_metrics"]["value"] == [
            "impressions",
            "cost",
        ]
        for key in rows:
            assert rows[key]["recognised"] is True, key
        assert rows["max_total_daily_budget"]["value"] is None

    def test_a_false_bool_is_declared_not_missing(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "STRATEGY.md",
            "# Strategy\n\n## Guardrails\n- block_learning_resets: off\n",
        )
        row = _by_key(read_guardrails(path))["block_learning_resets"]
        assert row["value"] is False
        assert row["raw"] == "off"
        assert row["recognised"] is True

    @pytest.mark.parametrize(
        ("line", "key"),
        [
            ("- max_total_daily_budget: lots", "max_total_daily_budget"),
            ("- exclusion_impact_window_days: 7.5", "exclusion_impact_window_days"),
            ("- currency: XYZ", "currency"),
            ("- block_learning_resets: maybe", "block_learning_resets"),
            ("- exclusion_impact_metrics: reach", "exclusion_impact_metrics"),
        ],
    )
    def test_an_unusable_line_is_reported_as_ignored(
        self, tmp_path: Path, line: str, key: str
    ) -> None:
        path = _write(
            tmp_path / "STRATEGY.md", f"# Strategy\n\n## Guardrails\n{line}\n"
        )
        row = _by_key(read_guardrails(path))[key]
        assert row["recognised"] is False
        assert row["raw"] == line.split(": ", 1)[1]

    def test_the_last_occurrence_wins_like_the_gate(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "STRATEGY.md",
            "# Strategy\n\n## Guardrails\n"
            "- max_total_daily_budget: 100\n"
            "- max_total_daily_budget: 200\n",
        )
        assert _by_key(read_guardrails(path))["max_total_daily_budget"]["value"] == 200


# ---------------------------------------------------------------------------
# Validating
# ---------------------------------------------------------------------------


def _refusal(payload: dict[str, Any]) -> StrategyGuardrailsError:
    with pytest.raises(StrategyGuardrailsError) as excinfo:
        parse_changes(payload)
    return excinfo.value


@pytest.mark.unit
class TestParseChanges:
    def test_numbers_and_numeric_strings_are_normalised(self) -> None:
        changes = parse_changes(
            {
                "set": {
                    "max_total_daily_budget": "1500",
                    "max_daily_budget_increase_pct": 20,
                    "max_cpc_bid_per_ad_group": " 1.25 ",
                    "exclusion_impact_window_days": "14",
                }
            }
        )
        assert changes == {
            "max_total_daily_budget": "1500",
            "max_daily_budget_increase_pct": "20",
            "max_cpc_bid_per_ad_group": "1.25",
            "exclusion_impact_window_days": "14",
        }

    def test_zero_is_a_value_that_can_be_set(self) -> None:
        assert parse_changes({"set": {"max_total_daily_budget": 0}}) == {
            "max_total_daily_budget": "0"
        }

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_a_blank_clears_and_is_never_zero(self, blank: Any) -> None:
        assert parse_changes({"set": {"max_total_daily_budget": blank}}) == {
            "max_total_daily_budget": None
        }

    def test_clear_lists_keys_to_remove(self) -> None:
        assert parse_changes({"clear": ["currency", "block_learning_resets"]}) == {
            "currency": None,
            "block_learning_resets": None,
        }

    def test_bools(self) -> None:
        assert parse_changes(
            {
                "set": {
                    "block_learning_resets": True,
                    "block_learning_resets_during_incident": "false",
                    "block_exclusions_without_impact_data": "on",
                }
            }
        ) == {
            "block_learning_resets": "true",
            "block_learning_resets_during_incident": "false",
            "block_exclusions_without_impact_data": "true",
        }

    def test_lists_are_split_trimmed_and_deduplicated(self) -> None:
        assert parse_changes(
            {
                "set": {
                    "blocked_operations": " b_tool, a_tool,,b_tool ",
                    "exclusion_impact_metrics": "Cost, impressions",
                }
            }
        ) == {
            "blocked_operations": "b_tool, a_tool",
            "exclusion_impact_metrics": "cost, impressions",
        }

    def test_currency_is_upper_cased(self) -> None:
        assert parse_changes({"set": {"currency": "eur"}}) == {"currency": "EUR"}

    @pytest.mark.parametrize(
        ("payload", "code", "field"),
        [
            ({"set": {"no_such_rule": 1}}, "unknown_field", "no_such_rule"),
            ({"clear": ["no_such_rule"]}, "unknown_field", "no_such_rule"),
            ({"set": {"max_total_daily_budget": "lots"}}, "invalid_value", None),
            ({"set": {"max_total_daily_budget": True}}, "invalid_value", None),
            ({"set": {"max_total_daily_budget": "nan"}}, "invalid_value", None),
            ({"set": {"max_total_daily_budget": "inf"}}, "invalid_value", None),
            ({"set": {"max_total_daily_budget": -1}}, "out_of_range", None),
            (
                {"set": {"max_delivery_share_removed_pct": 101}},
                "out_of_range",
                None,
            ),
            (
                {"set": {"exclusion_impact_window_days": "7.5"}},
                "invalid_value",
                None,
            ),
            ({"set": {"exclusion_impact_window_days": 0}}, "out_of_range", None),
            ({"set": {"exclusion_impact_window_days": 366}}, "out_of_range", None),
            ({"set": {"block_learning_resets": "maybe"}}, "invalid_value", None),
            ({"set": {"block_learning_resets": 1}}, "invalid_value", None),
            ({"set": {"currency": "XYZ"}}, "invalid_value", None),
            ({"set": {"exclusion_impact_metrics": "reach"}}, "invalid_value", None),
            ({"set": {"blocked_operations": ["a_tool"]}}, "invalid_value", None),
            (
                {"set": {"blocked_operations": "a_tool\n## Persona"}},
                "invalid_value",
                None,
            ),
        ],
    )
    def test_refusals(
        self, payload: dict[str, Any], code: str, field: str | None
    ) -> None:
        error = _refusal(payload)
        assert error.code == code
        expected_field = field or next(iter(payload["set"]))
        assert error.field == expected_field

    @pytest.mark.parametrize(
        "payload",
        [
            {"set": ["max_total_daily_budget"]},
            {"clear": "max_total_daily_budget"},
            {"clear": [5]},
        ],
    )
    def test_a_malformed_body_is_refused(self, payload: dict[str, Any]) -> None:
        assert _refusal(payload).code == "invalid_payload"

    def test_the_same_key_in_set_and_clear_is_refused(self) -> None:
        error = _refusal(
            {"set": {"max_total_daily_budget": 5}, "clear": ["max_total_daily_budget"]}
        )
        assert error.code == "conflicting_fields"
        assert error.field == "max_total_daily_budget"


# ---------------------------------------------------------------------------
# The line surgery
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContentWithBullets:
    def test_an_existing_bullet_is_replaced_where_it_stands(self) -> None:
        content = "- a_rule: 1\n- max_total_daily_budget: 900\nprose"
        assert content_with_bullets(content, {"max_total_daily_budget": "50"}) == (
            "- a_rule: 1\n- max_total_daily_budget: 50\nprose"
        )

    def test_the_key_is_matched_case_insensitively_like_the_gate(self) -> None:
        content = "- Max_Total_Daily_Budget: 900"
        assert content_with_bullets(content, {"max_total_daily_budget": "50"}) == (
            "- max_total_daily_budget: 50"
        )

    def test_a_new_bullet_goes_after_the_last_bullet(self) -> None:
        content = "- a_rule: 1\n- b_rule: 2\nprose after"
        assert content_with_bullets(content, {"max_total_daily_budget": "5"}) == (
            "- a_rule: 1\n- b_rule: 2\n- max_total_daily_budget: 5\nprose after"
        )

    def test_a_new_currency_goes_first_like_the_currency_card(self) -> None:
        content = "- max_total_daily_budget: 900"
        assert content_with_bullets(content, {"currency": "EUR"}) == (
            "- currency: EUR\n- max_total_daily_budget: 900"
        )

    def test_duplicates_collapse_to_one_line(self) -> None:
        content = "- max_total_daily_budget: 1\n- x: 2\n- max_total_daily_budget: 3"
        assert content_with_bullets(content, {"max_total_daily_budget": "9"}) == (
            "- max_total_daily_budget: 9\n- x: 2"
        )

    def test_clearing_drops_every_occurrence(self) -> None:
        content = "- max_total_daily_budget: 1\n- x: 2\n- max_total_daily_budget: 3"
        assert content_with_bullets(content, {"max_total_daily_budget": None}) == (
            "- x: 2"
        )

    def test_an_empty_section_gets_its_first_bullet(self) -> None:
        assert content_with_bullets("", {"max_total_daily_budget": "5"}) == (
            "- max_total_daily_budget: 5"
        )

    def test_nothing_to_do_returns_the_input(self) -> None:
        content = "- x: 2"
        assert content_with_bullets(content, {"max_total_daily_budget": None}) is (
            content
        )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteGuardrails:
    def test_setting_one_value_changes_exactly_one_line(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "STRATEGY.md", _DOC)
        state = write_guardrails(path, {"max_total_daily_budget": "1200"})
        after = path.read_text(encoding="utf-8")
        assert _diff_lines(_DOC, after) == [
            ("- max_total_daily_budget: 900", "- max_total_daily_budget: 1200")
        ]
        assert _by_key(state)["max_total_daily_budget"]["value"] == 1200.0

    def test_adding_a_value_inserts_exactly_one_line(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "STRATEGY.md", _DOC)
        write_guardrails(path, {"block_learning_resets": "true"})
        old = _DOC.splitlines()
        new = path.read_text(encoding="utf-8").splitlines()
        assert len(new) == len(old) + 1
        inserted = new.index("- block_learning_resets: true")
        assert new[:inserted] + new[inserted + 1 :] == old

    def test_clearing_removes_the_line_and_nothing_else(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "STRATEGY.md", _DOC)
        state = write_guardrails(path, {"max_total_daily_budget": None})
        old = _DOC.splitlines()
        new = path.read_text(encoding="utf-8").splitlines()
        assert new == [line for line in old if "max_total_daily_budget" not in line]
        assert _by_key(state)["max_total_daily_budget"]["value"] is None

    def test_no_section_creates_one_at_the_end(self, tmp_path: Path) -> None:
        before = "# Strategy\n\n## Persona\n30s\n"
        path = _write(tmp_path / "STRATEGY.md", before)
        write_guardrails(path, {"max_total_daily_budget": "5"})
        assert path.read_text(encoding="utf-8") == (
            before + "\n## Guardrails\n- max_total_daily_budget: 5\n"
        )

    def test_no_file_creates_one(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        state = write_guardrails(path, {"max_total_daily_budget": "5"})
        assert path.read_text(encoding="utf-8") == (
            "# Strategy\n\n## Guardrails\n- max_total_daily_budget: 5\n"
        )
        assert state["exists"] is True

    def test_a_no_op_does_not_touch_the_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "STRATEGY.md", _DOC)
        mtime = path.stat().st_mtime_ns
        write_guardrails(path, {"max_total_daily_budget": "900"})
        write_guardrails(path, {"exclusion_impact_window_days": None})
        assert path.read_text(encoding="utf-8") == _DOC
        assert path.stat().st_mtime_ns == mtime
        assert list(tmp_path.glob("STRATEGY.md.bak*")) == []

    def test_clearing_does_not_create_a_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        state = write_guardrails(path, {"max_total_daily_budget": None})
        assert not path.exists()
        assert state["exists"] is False

    def test_a_change_is_backed_up_first(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "STRATEGY.md", _DOC)
        write_guardrails(path, {"max_total_daily_budget": "1"})
        backups = list(tmp_path.glob("STRATEGY.md.bak.*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == _DOC

    def test_the_gate_reads_back_every_kind(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        changes = parse_changes(
            {
                "set": {
                    "currency": "usd",
                    "max_daily_budget_per_campaign": "250",
                    "max_daily_budget_increase_pct": "20",
                    "max_total_daily_budget": "900",
                    "max_lifetime_budget_per_campaign": "9000",
                    "max_bid_amount_per_ad_set": "3",
                    "max_cpc_bid_per_ad_group": "1.5",
                    "blocked_operations": "google_ads_keywords_remove",
                    "block_learning_resets": True,
                    "block_learning_resets_during_incident": True,
                    "max_delivery_share_removed_pct": "10",
                    "max_cumulative_delivery_share_removed_pct": "25",
                    "exclusion_impact_window_days": "14",
                    "exclusion_impact_metrics": "impressions, cost",
                    "block_exclusions_without_impact_data": True,
                }
            }
        )
        assert set(changes) == {f.key for f in GUARDRAIL_FIELDS}
        write_guardrails(path, changes)
        gate = guardrails_from_strategy_text(path.read_text(encoding="utf-8"))
        assert gate.currency == "USD"
        assert gate.max_daily_budget_per_campaign == 250
        assert gate.max_daily_budget_increase_pct == 20
        assert gate.max_total_daily_budget == 900
        assert gate.max_lifetime_budget_per_campaign == 9000
        assert gate.max_bid_amount_per_ad_set == 3
        assert gate.max_cpc_bid_per_ad_group == 1.5
        assert gate.blocked_operations == frozenset({"google_ads_keywords_remove"})
        assert gate.block_learning_resets is True
        assert gate.block_learning_resets_during_incident is True
        assert gate.max_delivery_share_removed_pct == 10
        assert gate.max_cumulative_delivery_share_removed_pct == 25
        assert gate.exclusion_impact_window_days == 14
        assert gate.exclusion_impact_metrics == ("impressions", "cost")
        assert gate.block_exclusions_without_impact_data is True

    def test_concurrent_writers_do_not_lose_each_other(self, tmp_path: Path) -> None:
        """Both writers go through the STRATEGY.md lock, so neither change
        is a lost update — the read-modify-write is serialised."""
        path = _write(tmp_path / "STRATEGY.md", _DOC)
        keys = [f.key for f in GUARDRAIL_FIELDS if f.kind == "money"]
        barrier = threading.Barrier(len(keys))
        errors: list[BaseException] = []

        def worker(key: str) -> None:
            try:
                barrier.wait(timeout=5)
                write_guardrails(path, {key: "7"})
            except BaseException as exc:  # noqa: BLE001 — surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert errors == []
        gate = guardrails_from_strategy_text(path.read_text(encoding="utf-8"))
        for key in keys:
            assert getattr(gate, key) == 7, key
        # The prose and the other sections came through every rewrite.
        text = path.read_text(encoding="utf-8")
        assert "Free prose the operator wrote." in text
        assert "## USP\ncheapest" in text


# ---------------------------------------------------------------------------
# Language resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveLang:
    @pytest.mark.parametrize(
        ("header", "query", "expected"),
        [
            (None, None, "en"),
            ("ja", None, "ja"),
            ("ja-JP,ja;q=0.9,en;q=0.8", None, "ja"),
            ("fr-FR, en;q=0.5", None, "en"),
            ("en;q=0.2, ja;q=0.9", None, "ja"),
            ("fr", "ja", "ja"),
            (None, "ja", "ja"),
            (None, "de", "en"),
            ("ja", "en", "ja"),
            ("ja;q=0", None, "en"),
        ],
    )
    def test_header_then_query_then_english(
        self, header: str | None, query: str | None, expected: str
    ) -> None:
        assert resolve_lang(header, query) == expected


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    from mureo.core.runtime_context import (
        default_runtime_context,
        reset_runtime_context,
    )

    reset_runtime_context()
    ctx = default_runtime_context(workspace=tmp_path)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    yield tmp_path
    reset_runtime_context()


@pytest.fixture
def wizard(tmp_path: Path) -> Iterator[ConfigureWizard]:
    from mureo.web.server import ConfigureWizard

    home = tmp_path / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".mureo").mkdir()
    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


_ROUTE = "/api/strategy/guardrails"


def _url(wiz: ConfigureWizard, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


def _get(
    wiz: ConfigureWizard, path: str, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    req = urllib.request.Request(_url(wiz, path))
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=2.0) as res:
        body: dict[str, Any] = json.loads(res.read().decode("utf-8"))
    return body


def _post(
    wiz: ConfigureWizard, payload: dict[str, Any], *, csrf: bool = True
) -> HTTPResponse:
    req = urllib.request.Request(
        _url(wiz, _ROUTE), data=json.dumps(payload).encode(), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    if csrf:
        req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    return urllib.request.urlopen(req, timeout=2.0)


def _post_json(wiz: ConfigureWizard, payload: dict[str, Any]) -> dict[str, Any]:
    with _post(wiz, payload) as res:
        body: dict[str, Any] = json.loads(res.read().decode("utf-8"))
    return body


@pytest.mark.unit
class TestStrategyGuardrailsRoutes:
    def test_get_lists_every_field_for_the_active_workspace(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = _get(wizard, _ROUTE)
        assert body["status"] == "ok"
        assert body["client"] is None
        assert body["path"] == str(workspace / "STRATEGY.md")
        assert body["exists"] is False
        assert [row["key"] for row in body["fields"]] == [
            f.key for f in GUARDRAIL_FIELDS
        ]

    def test_get_resolves_labels_from_accept_language(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = _get(wizard, _ROUTE, {"Accept-Language": "ja-JP,ja;q=0.9"})
        row = _by_key(body)["max_cumulative_delivery_share_removed_pct"]
        assert row["label"] == "除外で削ってよい配信量の累計上限(%)"

    def test_get_falls_back_to_the_lang_query(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = _get(wizard, f"{_ROUTE}?lang=ja")
        row = _by_key(body)["max_daily_budget_increase_pct"]
        assert row["label"] == "1 回の変更で許す日予算の増加率(%)"

    def test_post_writes_and_answers_with_the_re_read_state(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        path = _write(workspace / "STRATEGY.md", _DOC)
        body = _post_json(
            wizard,
            {
                "set": {"max_total_daily_budget": "1200"},
                "clear": ["blocked_operations"],
            },
        )
        assert body["status"] == "ok"
        rows = _by_key(body)
        assert rows["max_total_daily_budget"]["value"] == 1200.0
        assert rows["blocked_operations"]["value"] is None
        text = path.read_text(encoding="utf-8")
        assert "- max_total_daily_budget: 1200" in text
        assert "blocked_operations" not in text
        assert _get(wizard, _ROUTE) == body

    @pytest.mark.parametrize(
        ("payload", "code"),
        [
            ({"set": {"no_such_rule": 1}}, "unknown_field"),
            ({"set": {"max_total_daily_budget": "lots"}}, "invalid_value"),
            ({"set": {"max_total_daily_budget": -5}}, "out_of_range"),
            ({"set": "max_total_daily_budget"}, "invalid_payload"),
        ],
    )
    def test_post_refusals_write_nothing(
        self,
        wizard: ConfigureWizard,
        workspace: Path,
        payload: dict[str, Any],
        code: str,
    ) -> None:
        path = _write(workspace / "STRATEGY.md", _DOC)
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(wizard, payload)
        assert excinfo.value.code == 400
        assert json.loads(excinfo.value.read())["error"] == code
        assert path.read_text(encoding="utf-8") == _DOC

    def test_post_names_the_field_it_refused(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(wizard, {"set": {"exclusion_impact_window_days": 0}})
        body = json.loads(excinfo.value.read())
        assert body == {
            "error": "out_of_range",
            "field": "exclusion_impact_window_days",
        }

    def test_post_a_blank_clears_rather_than_writing_zero(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        path = _write(workspace / "STRATEGY.md", _DOC)
        _post_json(wizard, {"set": {"max_total_daily_budget": ""}})
        text = path.read_text(encoding="utf-8")
        assert "max_total_daily_budget" not in text
        assert ": 0" not in text

    def test_post_needs_the_csrf_header(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(wizard, {"set": {"max_total_daily_budget": 5}}, csrf=False)
        assert excinfo.value.code == 403
        assert not (workspace / "STRATEGY.md").exists()

    def test_the_currency_route_sees_what_this_route_wrote(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        _post_json(wizard, {"set": {"currency": "eur"}})
        assert _get(wizard, "/api/strategy/currency")["currency"] == "EUR"

    def test_a_client_slug_is_echoed_and_ignored_on_a_single_workspace(
        self, wizard: ConfigureWizard, workspace: Path
    ) -> None:
        body = _post_json(
            wizard, {"client": "acme", "set": {"max_total_daily_budget": 5}}
        )
        assert body["client"] == "acme"
        assert body["path"] == str(workspace / "STRATEGY.md")
        assert _get(wizard, f"{_ROUTE}?client=acme")["client"] == "acme"
