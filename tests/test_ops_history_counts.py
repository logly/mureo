"""The ops history aggregate for the client list (#849).

One line per client card — how many changes the last 30 days hold and how
they turned out — counted on the server so the browser never counts. The
counting is a pure function over the items the ops history view already
derives; the window is the one the dashboard feed defaults to.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from mureo.context.ops_history_counts import (
    OPS_HISTORY_WINDOW_DAYS,
    count_ops_history_items,
    ops_history_counts,
)
from mureo.context.state_codec import parse_state

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 14)

_ZERO = {
    "changes": 0,
    "improved": 0,
    "regressed": 0,
    "regressed_open": 0,
    "held": 0,
    "inconclusive": 0,
    "observing": 0,
}


def _item(
    state: str | None, verdict: str | None = None, *, rolled_back: bool = False
) -> dict[str, Any]:
    return {
        "decision": None,
        "actions": [],
        "state": state,
        "verdict": verdict,
        "rolled_back": rolled_back,
    }


class TestCountItems:
    def test_no_items_count_nothing(self) -> None:
        assert count_ops_history_items([]) == _ZERO

    def test_each_outcome_is_counted_once(self) -> None:
        items = [
            _item("evaluated", "improved"),
            _item("evaluated", "improved"),
            _item("evaluated", "regressed"),
            _item("evaluated", "regressed", rolled_back=True),
            _item("evaluated", "held"),
            _item("evaluated", "inconclusive"),
            _item("evaluated", None),
            _item("observing"),
            _item("executed"),
            _item("skipped"),
        ]
        assert count_ops_history_items(items) == {
            "changes": 10,
            "improved": 2,
            "regressed": 2,
            "regressed_open": 1,
            # A held change is its own count, never folded into inconclusive.
            "held": 1,
            "inconclusive": 2,
            "observing": 1,
        }

    def test_a_rolled_back_regression_is_not_open(self) -> None:
        items = [_item("evaluated", "regressed", rolled_back=True)]
        counts = count_ops_history_items(items)
        assert (counts["regressed"], counts["regressed_open"]) == (1, 0)

    @pytest.mark.parametrize("state", ["proposed", "adopted", "rejected", "deferred"])
    def test_a_decision_nothing_carried_out_is_not_a_change(self, state: str) -> None:
        assert count_ops_history_items([_item(state)]) == _ZERO

    def test_the_input_is_not_modified(self) -> None:
        items = [_item("evaluated", "regressed")]
        before = json.dumps(items)
        count_ops_history_items(items)
        assert json.dumps(items) == before


def _document(*, enabled: bool, days: list[str]) -> Any:
    entries = [
        {
            "timestamp": f"{day}T10:00:00+09:00",
            "action": "google_ads_budget_update",
            "platform": "google_ads",
            "campaign_id": "c1",
        }
        for day in days
    ]
    raw = {
        "version": "2",
        "settings": {"ops_history": {"enabled": enabled}},
        "action_log": entries,
    }
    return parse_state(json.dumps(raw))


def _overdue_document(days: list[str]) -> Any:
    """Changes past their observation date with no evaluation yet."""
    entries = [
        {
            "timestamp": f"{day}T10:00:00+09:00",
            "action": "google_ads_budget_update",
            "platform": "google_ads",
            "campaign_id": "c1",
            "observation_due": "2026-10-01",
            "metrics_at_action": {"cpa": 100},
        }
        for day in days
    ]
    decisions = [
        {
            "decision_id": "old",
            "recorded_at": "2026-06-01T10:00:00+09:00",
            "status": "adopted",
            "title": "Old decision",
            "rationale": "Outside every window here.",
        },
        {
            "decision_id": "new",
            "recorded_at": "2026-10-10T10:00:00+09:00",
            "status": "adopted",
            "title": "New decision",
            "rationale": "Inside the window.",
        },
    ]
    raw = {
        "version": "2",
        "settings": {"ops_history": {"enabled": True}},
        "decisions": decisions,
        "action_log": entries,
    }
    return parse_state(json.dumps(raw))


class TestOnlyTheWindowIsDerived:
    """The window is applied BEFORE an item is derived, not after (#849)."""

    def _spy(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
        import mureo.context.ops_history_view as view

        calls: dict[str, list[Any]] = {"actions": [], "decisions": []}
        real_row, real_decision = view._action_row, view._decision_dict

        def row(doc: Any, index: int, *args: Any) -> Any:
            calls["actions"].append(index)
            return real_row(doc, index, *args)

        def decision(records: Any, *args: Any) -> Any:
            calls["decisions"].append(records[0].decision_id)
            return real_decision(records, *args)

        monkeypatch.setattr(view, "_action_row", row)
        monkeypatch.setattr(view, "_decision_dict", decision)
        return calls

    def test_items_outside_the_window_are_never_derived(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doc = _overdue_document(["2026-05-01", "2026-06-01", "2026-10-05"])
        calls = self._spy(monkeypatch)
        counts = ops_history_counts(doc, today=TODAY)
        assert calls["actions"] == [2]
        assert calls["decisions"] == ["new"]
        assert counts["changes"] == 1

    def test_bounded_items_equal_the_unbounded_ones_trimmed(self) -> None:
        from mureo.context.ops_history_query import (
            in_window,
            iso_date,
            ops_history_items,
        )
        from mureo.context.ops_history_view import (
            build_ops_history_items,
            item_timestamp,
        )

        doc = _overdue_document(["2026-05-01", "2026-09-20", "2026-10-05"])
        since, until = date(2026, 9, 15), TODAY

        class _B:
            pass

        bounds = _B()
        bounds.since, bounds.until = since, until  # type: ignore[attr-defined]
        trimmed = [
            item
            for item in build_ops_history_items(doc, today=TODAY)
            if in_window(iso_date(item_timestamp(item)), bounds)  # type: ignore[arg-type]
        ]
        assert ops_history_items(doc, today=TODAY, since=since, until=until) == trimmed


class TestCountsForADocument:
    def test_the_window_is_thirty_days(self) -> None:
        assert OPS_HISTORY_WINDOW_DAYS == 30

    def test_the_window_is_thirty_days_ending_today(self) -> None:
        doc = _document(
            enabled=True,
            days=["2026-09-14", "2026-09-15", "2026-10-14", "2026-10-15"],
        )
        counts = ops_history_counts(doc, today=TODAY)
        # Thirty calendar days, today included: 2026-09-15 (today - 29) is
        # the first day in, 09-14 is out; a change dated after today is out.
        assert counts == {"enabled": True, "window_days": 30, **_ZERO, "changes": 2}

    def test_disabled_counts_nothing(self) -> None:
        doc = _document(enabled=False, days=["2026-10-10"])
        assert ops_history_counts(doc, today=TODAY) == {
            "enabled": False,
            "window_days": 30,
            **_ZERO,
        }

    def test_no_document_is_disabled(self) -> None:
        assert ops_history_counts(None, today=TODAY) == {
            "enabled": False,
            "window_days": 30,
            **_ZERO,
        }

    def test_an_empty_enabled_document_counts_zero(self) -> None:
        doc = _document(enabled=True, days=[])
        assert ops_history_counts(doc, today=TODAY) == {
            "enabled": True,
            "window_days": 30,
            **_ZERO,
        }
