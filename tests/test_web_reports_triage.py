"""The server half of the multi-client triage layer (#651).

The triage layer aggregates facts mureo ALREADY computes per client —
totals-withholding conflicts (#636), stale rollups and collection failures
(#638) — and one it does not: how many ``action_log`` observations are past
due. Only the last needs the server, and it needs it for two reasons the
browser cannot work around:

- ``recent_actions`` is the last :data:`_RECENT_ACTIONS_LIMIT` entries, so a
  count taken from it under-reports a long log;
- it carries no ``rollback_of`` / ``evaluation_of``, so a browser-side count
  would keep nagging about observations that were reviewed and closed.

So the count is decided here, over the whole document, through the ONE rule
that already defines "pending" for ``mureo_state_get`` — see
:mod:`mureo.context.observations`.

The other half of the issue is where this may appear at all. The triage
layer is a multi-client surface: with no Agency seam there is no second
client to triage against, and the acceptance criterion is that the summary
is byte-identical to what it was before this feature existed. That is
pinned first below, because "omitted entirely" is the requirement — not
"degraded to one row".
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.models import ActionLogEntry, StateDocument
from mureo.core.runtime_context import default_runtime_context, reset_runtime_context
from mureo.core.state_store import FilesystemStateStore
from mureo.web.reports import build_report_summary

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# The summary's keys, in order, as they were before #651. The triage layer
# adds one MORE key and this list must stay the single-workspace answer.
_LEGACY_SUMMARY_KEYS = [
    "client",
    "period",
    "periods",
    "last_synced_at",
    "platforms",
    "platform_conflicts",
    "recent_actions",
    "reports",
]


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


class _AgencyStore(FilesystemStateStore):
    """A filesystem store that ALSO advertises the Agency client seam.

    Reads the same workspace as the default store, so a test can flip the
    seam on and off over one identical document — which is what makes the
    byte-identical assertion below about the seam and nothing else.
    """

    def list_clients(self) -> list[dict[str, Any]]:
        return [
            {"slug": "acme", "name": "Acme Co", "active": True},
            {"slug": "globex", "name": "Globex", "active": False},
        ]


def _write(workspace: Path, doc: StateDocument) -> None:
    from mureo.context.state import write_state_file

    write_state_file(workspace / "STATE.json", doc)


def _use_workspace(
    monkeypatch: pytest.MonkeyPatch, workspace: Path, *, agency: bool
) -> None:
    """Point the runtime context at ``workspace``, with or without the seam."""
    ctx = default_runtime_context(workspace=workspace)
    if agency:
        ctx = dataclasses.replace(ctx, state_store=_AgencyStore(workspace))
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)


def _due_doc(*entries: ActionLogEntry) -> StateDocument:
    return StateDocument(action_log=list(entries))


def _action(
    *, due: str | None = None, evaluation_of: int | None = None
) -> ActionLogEntry:
    return ActionLogEntry(
        timestamp="2026-08-01T00:00:00+00:00",
        action="budget_update",
        platform="google_ads",
        summary="raised the daily budget",
        observation_due=due,
        evaluation_of=evaluation_of,
    )


# ---------------------------------------------------------------------------
# Requirement 1 — the layer exists only where the Agency seam supplies clients
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_single_workspace_summary_is_unchanged_by_the_triage_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no Agency seam the summary is byte-identical to today's.

    Pinned as the key list AND the serialized body: a new key is exactly
    what "byte-identical" forbids, whatever it is worth, and a
    single-workspace install has no second client to triage against.
    """
    _use_workspace(monkeypatch, tmp_path, agency=False)
    _write(tmp_path, _due_doc(_action(due="2020-01-01")))

    summary = build_report_summary()

    assert list(summary) == _LEGACY_SUMMARY_KEYS
    assert "observations_due" not in json.dumps(summary)


@pytest.mark.unit
def test_the_seam_is_what_adds_the_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The SAME document, read through a store that supplies clients, gains
    the layer — so nothing but the seam decides this."""
    _write(tmp_path, _due_doc(_action(due="2020-01-01")))

    _use_workspace(monkeypatch, tmp_path, agency=False)
    without = build_report_summary()
    _use_workspace(monkeypatch, tmp_path, agency=True)
    with_seam = build_report_summary()

    assert "observations_due" not in without
    assert with_seam["observations_due"] == {"count": 1, "oldest_due": "2020-01-01"}
    assert {k: v for k, v in with_seam.items() if k != "observations_due"} == without


# ---------------------------------------------------------------------------
# What "due" means — the shared pending rule, not a second copy of it
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_only_a_window_that_has_closed_is_due(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A future ``observation_due`` is still under observation, not owed.

    Nagging about an action made yesterday would train an operator to ignore
    the layer, which costs more than the finding is worth.
    """
    _use_workspace(monkeypatch, tmp_path, agency=True)
    _write(tmp_path, _due_doc(_action(due="2099-12-31"), _action(due="2020-06-01")))

    assert build_report_summary()["observations_due"] == {
        "count": 1,
        "oldest_due": "2020-06-01",
    }


@pytest.mark.unit
def test_a_reviewed_observation_is_not_still_due(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``evaluation_of`` closes the entry it names — the same rule
    ``mureo_state_get(action_log="pending")`` applies. Without it the layer
    would ask for a review that was already done, for ever."""
    _use_workspace(monkeypatch, tmp_path, agency=True)
    _write(
        tmp_path,
        _due_doc(
            _action(due="2020-01-01"),
            _action(due="2020-02-02"),
            _action(evaluation_of=0),
        ),
    )

    assert build_report_summary()["observations_due"] == {
        "count": 1,
        "oldest_due": "2020-02-02",
    }


@pytest.mark.unit
def test_a_rolled_back_action_is_not_still_due(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rollback closes the observation too: there is no outcome left to
    review once the change is reversed."""
    _use_workspace(monkeypatch, tmp_path, agency=True)
    reversal = dataclasses.replace(_action(), rollback_of=0)
    _write(tmp_path, _due_doc(_action(due="2020-01-01"), reversal))

    assert build_report_summary()["observations_due"] == {
        "count": 0,
        "oldest_due": None,
    }


@pytest.mark.unit
def test_a_date_mureo_cannot_read_is_not_counted_and_never_relayed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An ``observation_due`` that is not a date cannot be judged past due,
    and unknown is not a verdict (the position ``_platform_freshness`` takes
    on a ``fetched_at`` it cannot parse).

    It is also writer-supplied text. ``recent_actions`` has always relayed it
    verbatim, as it relays every other stored string; what this layer must
    not do is put a *second*, unparsed copy on the wire in a field whose
    whole claim is that mureo judged the date. ``oldest_due`` is therefore
    re-rendered from the date mureo itself parsed, never echoed.
    """
    _use_workspace(monkeypatch, tmp_path, agency=True)
    _write(tmp_path, _due_doc(_action(due="whenever <script>"), _action(due=None)))

    summary = build_report_summary()
    assert summary["observations_due"] == {"count": 0, "oldest_due": None}
    assert "<script>" not in json.dumps(summary["observations_due"])


@pytest.mark.unit
def test_the_count_is_taken_over_the_whole_log_not_the_recent_slice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``recent_actions`` is capped, and a count taken from it would silently
    under-report exactly the operator this layer is for — the one with a long
    history on many clients."""
    _use_workspace(monkeypatch, tmp_path, agency=True)
    _write(tmp_path, _due_doc(*[_action(due="2020-01-01") for _ in range(40)]))

    summary = build_report_summary()
    assert len(summary["recent_actions"]) == 20
    assert summary["observations_due"]["count"] == 40


@pytest.mark.unit
def test_nothing_due_is_still_a_stated_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The wire always answers the question once the seam is there; it is the
    RENDERER that must stay silent (no "0 alerts" banner). A missing key and
    a zero are different facts, and the browser must not have to guess."""
    _use_workspace(monkeypatch, tmp_path, agency=True)
    _write(tmp_path, _due_doc())

    assert build_report_summary()["observations_due"] == {
        "count": 0,
        "oldest_due": None,
    }


@pytest.mark.unit
def test_pending_is_decided_by_one_rule_for_both_surfaces() -> None:
    """``mureo_state_get(action_log="pending")`` and this layer must never
    disagree about what closes an observation. A private copy of the rule is
    how a dashboard ends up asserting something no other surface agrees with
    — the defect #638 and #643 were both about."""
    from mureo.context.observations import closed_observation_indices
    from mureo.mcp import _handlers_mureo_context as handlers

    entries = [{}, {"rollback_of": 0}, {"evaluation_of": 3}]
    assert handlers._closed_indices(entries) == closed_observation_indices(entries)
    assert closed_observation_indices(entries) == {0, 3}


@pytest.mark.unit
def test_the_shared_rule_reads_a_dataclass_entry_and_a_rendered_one_alike() -> None:
    """One rule, two shapes: the MCP handler holds rendered dicts, the report
    builder holds :class:`ActionLogEntry`. A ``bool`` is not an index (it is
    an ``int`` subclass in Python, and that is exactly the coercion that
    would close entry 1 whenever a writer stored ``True``)."""
    from mureo.context.observations import closed_observation_indices

    assert closed_observation_indices([_action(evaluation_of=2)]) == {2}
    assert closed_observation_indices([{"rollback_of": True}]) == set()
