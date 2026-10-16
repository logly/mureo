"""The external approval in the ops history view (#854).

An action row carries its entry's ``approval``; a decision carries the
newest approval stated on its chain. Absent, both are ``None``.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from mureo.context.ops_history_view import build_ops_history_items
from mureo.context.state_codec import parse_state

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 17)


def _approval(reference: str) -> dict[str, str]:
    return {
        "reference": reference,
        "approved_by": "Jane Operator",
        "approved_at": "2026-10-16T09:30:00+09:00",
    }


def _decision(decision_id: str, day: str, **extra: Any) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "recorded_at": f"{day}T10:00:00+09:00",
        "status": "adopted",
        "title": f"Decision {decision_id}",
        "rationale": "Because.",
        **extra,
    }


def _action(**extra: Any) -> dict[str, Any]:
    return {
        "timestamp": "2026-10-16T10:00:00+09:00",
        "action": "google_ads_campaigns_update_status",
        "platform": "google_ads",
        "campaign_id": "c1",
        **extra,
    }


def _items(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    doc = parse_state(json.dumps({"version": "2", **document}))
    items = build_ops_history_items(doc, today=TODAY)
    keyed: dict[str, dict[str, Any]] = {}
    for item in items:
        decision = item["decision"]
        keyed[decision["decision_id"] if decision else "none"] = item
    return keyed


class TestActionRow:
    def test_an_entry_with_one_shows_it(self) -> None:
        items = _items(
            {"action_log": [_action(approval=_approval("REQ-1"))], "decisions": []}
        )
        assert items["none"]["actions"][0]["approval"] == _approval("REQ-1")

    def test_an_entry_without_one_shows_none(self) -> None:
        items = _items({"action_log": [_action()], "decisions": []})
        assert items["none"]["actions"][0]["approval"] is None


class TestDecision:
    def test_a_call_without_an_entry_shows_it_on_the_decision(self) -> None:
        record = _decision(
            "D",
            "2026-10-16",
            applied_params={"budget_id": "b1", "amount": 12000},
            journal_call_id="call-1",
            journal_tool="google_ads_budget_update",
            approval=_approval("REQ-2"),
        )
        items = _items({"decisions": [record]})
        assert items["D"]["actions"] == []
        assert items["D"]["decision"]["approval"] == _approval("REQ-2")

    def test_the_newest_on_the_chain_wins(self) -> None:
        records = [
            _decision("P", "2026-10-10", status="proposed"),
            _decision(
                "P2", "2026-10-12", supersedes="P", approval=_approval("REQ-old")
            ),
            _decision(
                "P3", "2026-10-14", supersedes="P2", approval=_approval("REQ-new")
            ),
            _decision("P4", "2026-10-15", supersedes="P3"),
        ]
        items = _items({"decisions": records})
        assert items["P"]["decision"]["approval"] == _approval("REQ-new")

    def test_a_decision_without_one_shows_none(self) -> None:
        items = _items({"decisions": [_decision("E", "2026-10-16")]})
        assert items["E"]["decision"]["approval"] is None

    def test_the_view_is_a_copy(self) -> None:
        record = _decision("C", "2026-10-16", approval=_approval("REQ-3"))
        doc = parse_state(json.dumps({"version": "2", "decisions": [record]}))
        items = build_ops_history_items(doc, today=TODAY)
        items[0]["decision"]["approval"]["reference"] = "changed"
        assert doc.decisions[0].approval is not None
        assert doc.decisions[0].approval.reference == "REQ-3"
