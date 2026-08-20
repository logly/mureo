"""The metrics-window vocabulary: strict on write, tolerant on read (#659).

mureo has exactly three windows (``YESTERDAY`` / ``LAST_7_DAYS`` /
``LAST_30_DAYS``). Nothing used to enforce them, so an agent analysing "since
launch" or "the last 8 days" wrote exactly that as a window — the write
succeeded, the agent reported success truthfully, and the card kept reading
stale because the canonical bucket really had not moved. Both statements were
true and nothing named the mismatch.

These tests pin the two halves of the fix, which point in opposite directions
on purpose:

  - **Write** — ``set_platform_metrics`` (and the MCP tool over it) refuses a
    window outside the canonical set, and refuses it WITHOUT remapping: a
    ``LAST_8_DAYS`` figure must never be filed under ``LAST_7_DAYS``, which
    would be exactly the mislabelling #638's staleness rule exists to
    prevent.
  - **Read** — a non-canonical label already on disk stays readable, and is
    REPORTED to the operator rather than quietly dropped or quietly kept.
    Those are real figures, correctly collected, under a name no view
    expects; deleting them loses data mureo did collect.

Plus the property that actually failed in the field: a write that SUCCEEDS is
readable by the default view.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.context.models import PlatformState, StateDocument
from mureo.context.state import read_state_file, set_platform_metrics, write_state_file
from mureo.core.metrics_windows import (
    CANONICAL_METRICS_WINDOWS,
    METRICS_WINDOW_RULE,
    reject_non_canonical_metrics_window,
)
from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
)
from mureo.web.reports import build_report_summary

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def cwd_to_tmp(tmp_path, monkeypatch):
    """Run the MCP-handler tests with cwd = tmp_path so STATE.json lands in
    the sandbox (mirrors tests/test_mcp_tools_mureo_context.py)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _use_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    ctx = default_runtime_context(workspace=workspace)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)


def _import_tools():
    from mureo.mcp import tools_mureo_context

    return tools_mureo_context


def _metrics_schema() -> dict:
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_platform_metrics_set")
    return tool.inputSchema


# ---------------------------------------------------------------------------
# The vocabulary itself
# ---------------------------------------------------------------------------


def test_the_canonical_set_is_the_three_windows_the_dashboard_reads() -> None:
    """One source of truth, shared by the write guard and the read side.

    The dashboard's toggle order and its per-window staleness thresholds are
    derived from this table — a fourth window is a deliberate decision with a
    defined length, not something a caller can create by naming it.
    """
    assert CANONICAL_METRICS_WINDOWS == {
        "YESTERDAY": 1,
        "LAST_7_DAYS": 7,
        "LAST_30_DAYS": 30,
    }

    from mureo.web import reports

    assert reports._PERIOD_LENGTH_DAYS == CANONICAL_METRICS_WINDOWS
    assert tuple(CANONICAL_METRICS_WINDOWS) == reports._PERIOD_ORDER


# ---------------------------------------------------------------------------
# Write — refused, and refused without a guess
# ---------------------------------------------------------------------------


def test_a_window_outside_the_canonical_set_is_not_stored_silently(
    tmp_path: Path,
) -> None:
    """The reported failure: ``SINCE_LAUNCH_17D`` used to be accepted."""
    path = tmp_path / "STATE.json"

    with pytest.raises(ValueError) as excinfo:
        set_platform_metrics(
            path,
            "google_ads",
            "123",
            totals={"spend": 1.0},
            metrics_period="SINCE_LAUNCH_17D",
        )

    message = str(excinfo.value)
    assert "SINCE_LAUNCH_17D" in message
    # The error states the vocabulary, so the caller can fix it here rather
    # than discover it on a dashboard three days later.
    for window in CANONICAL_METRICS_WINDOWS:
        assert window in message
    assert not path.exists()


def test_a_non_canonical_periods_key_is_not_stored_silently(tmp_path: Path) -> None:
    """``periods`` keys are windows too — the toggle is built from them."""
    path = tmp_path / "STATE.json"

    with pytest.raises(ValueError, match="LAST_8_DAYS"):
        set_platform_metrics(
            path,
            "google_ads",
            "123",
            periods={"LAST_8_DAYS": {"spend": 8.0}},
        )
    assert not path.exists()


def test_a_near_miss_window_is_never_rounded_onto_a_canonical_one(
    tmp_path: Path,
) -> None:
    """``LAST_8_DAYS`` must not become ``LAST_7_DAYS``.

    Normalising would file eight days of figures under a seven-day label —
    a number that is not the answer to the question its label asks, which is
    the exact error #638 exists to prevent. Refusing is honest; guessing is
    not.
    """
    path = tmp_path / "STATE.json"
    set_platform_metrics(
        path,
        "google_ads",
        "123",
        periods={"LAST_7_DAYS": {"spend": 7.0}},
    )

    with pytest.raises(ValueError):
        set_platform_metrics(
            path,
            "google_ads",
            "123",
            totals={"spend": 8.0},
            metrics_period="LAST_8_DAYS",
            periods={"LAST_8_DAYS": {"spend": 8.0}},
        )

    doc = read_state_file(path)
    assert doc.platforms is not None
    entry = doc.platforms["google_ads"]
    assert entry.periods is not None
    # No new bucket, and — the point of this test — the existing canonical
    # bucket still holds the seven-day figure, not the eight-day one.
    assert set(entry.periods) == {"LAST_7_DAYS"}
    assert entry.periods["LAST_7_DAYS"]["spend"] == 7.0
    assert entry.totals is None
    assert entry.metrics_period is None


def test_the_canonical_windows_are_all_writable(tmp_path: Path) -> None:
    """The guard refuses a vocabulary, not a spelling."""
    path = tmp_path / "STATE.json"
    for window in CANONICAL_METRICS_WINDOWS:
        set_platform_metrics(
            path,
            "google_ads",
            "123",
            totals={"spend": 1.0},
            metrics_period=window,
            periods={window: {"spend": 1.0}},
        )
    doc = read_state_file(path)
    assert doc.platforms is not None
    assert set(doc.platforms["google_ads"].periods or {}) == set(
        CANONICAL_METRICS_WINDOWS
    )


def test_omitting_the_window_still_preserves_the_stored_one(tmp_path: Path) -> None:
    """``None`` means "leave it alone" — it is not a window to validate."""
    path = tmp_path / "STATE.json"
    set_platform_metrics(
        path, "google_ads", "123", totals={"spend": 1.0}, metrics_period="YESTERDAY"
    )
    doc = set_platform_metrics(path, "google_ads", "123", totals={"spend": 2.0})
    assert doc.platforms is not None
    assert doc.platforms["google_ads"].metrics_period == "YESTERDAY"


# ---------------------------------------------------------------------------
# The acceptance property: a successful write is readable by the default view
# ---------------------------------------------------------------------------


def test_a_successful_write_is_readable_by_the_default_view(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What broke in the field. ``All persistence complete`` was true, and the
    card still read stale, because the write had landed in a window the
    dashboard does not read. Every window a write can now name is a window
    the dashboard renders."""
    _use_workspace(monkeypatch, tmp_path)
    path = tmp_path / "STATE.json"

    for window in CANONICAL_METRICS_WINDOWS:
        set_platform_metrics(
            path,
            "google_ads",
            "123",
            periods={window: {"spend": 12.5, "conversions": 3}},
        )
        summary = build_report_summary(period=window)
        assert window in summary["periods"]
        (row,) = summary["platforms"]
        assert row["totals"] is not None, window
        assert row["totals"]["spend"] == 12.5
        assert row["metrics_period"] == window


# ---------------------------------------------------------------------------
# Read — tolerant, and it says what it found
# ---------------------------------------------------------------------------


def _doc_with_adhoc_windows() -> StateDocument:
    return StateDocument(
        version="2",
        platforms={
            "google_ads": PlatformState(
                account_id="123",
                periods={
                    "YESTERDAY": {"spend": 1.0},
                    "SINCE_LAUNCH_17D": {"spend": 17.0},
                    "LAST_8_DAYS": {"spend": 8.0},
                },
            )
        },
    )


def test_labels_already_on_disk_stay_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Backward compatibility, and the deliberate asymmetry: these are real
    figures under an unexpected name. Making them unreadable would delete
    data mureo did collect."""
    _use_workspace(monkeypatch, tmp_path)
    write_state_file(tmp_path / "STATE.json", _doc_with_adhoc_windows())

    summary = build_report_summary()
    assert summary["periods"] == ["YESTERDAY", "LAST_8_DAYS", "SINCE_LAUNCH_17D"]

    (row,) = build_report_summary(period="SINCE_LAUNCH_17D")["platforms"]
    assert row["totals"] is not None
    assert row["totals"]["spend"] == 17.0


def test_labels_already_on_disk_are_reported_to_the_operator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Neither silent option is right: deleting loses data, keeping quietly
    leaves a toggle nobody can read. The summary names what accumulated so
    an operator can decide."""
    _use_workspace(monkeypatch, tmp_path)
    write_state_file(tmp_path / "STATE.json", _doc_with_adhoc_windows())

    summary = build_report_summary()
    assert summary["non_canonical_periods"] == ["LAST_8_DAYS", "SINCE_LAUNCH_17D"]


def test_a_healthy_document_reports_an_empty_list_not_a_missing_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Always a list, like ``platform_conflicts`` — "nothing accumulated" and
    "this mureo cannot tell you" must not be the same payload."""
    _use_workspace(monkeypatch, tmp_path)
    path = tmp_path / "STATE.json"
    set_platform_metrics(
        path, "google_ads", "123", periods={"YESTERDAY": {"spend": 1.0}}
    )

    summary = build_report_summary()
    assert summary["non_canonical_periods"] == []


def test_a_legacy_single_rollup_window_is_reported_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``metrics_period`` advertises a window just as a ``periods`` key
    does — a pre-``periods`` document must not hide its ad-hoc label."""
    _use_workspace(monkeypatch, tmp_path)
    write_state_file(
        tmp_path / "STATE.json",
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    totals={"spend": 3.0},
                    metrics_period="TO_DATE_1",
                )
            },
        ),
    )

    assert build_report_summary()["non_canonical_periods"] == ["TO_DATE_1"]


# ---------------------------------------------------------------------------
# The MCP surface — the schema states the allow-list
# ---------------------------------------------------------------------------


def test_the_schema_states_the_allowed_windows_rather_than_an_example() -> None:
    """``e.g. LAST_30_DAYS`` is an example, not an allow-list — an agent
    reading it has no way to know the vocabulary is closed."""
    props = _metrics_schema()["properties"]
    assert props["metrics_period"]["enum"] == list(CANONICAL_METRICS_WINDOWS)
    periods = props["periods"]
    assert sorted(periods["properties"]) == sorted(CANONICAL_METRICS_WINDOWS)
    assert periods["additionalProperties"] is False


async def test_the_mcp_tool_refuses_a_non_canonical_window(cwd_to_tmp) -> None:
    """The handler refuses on its own, without the schema.

    This calls the handler DIRECTLY, so the dispatcher's schema validation
    never runs — which is the point: a host that does not validate against
    the declared ``inputSchema`` must still be refused. What a real client
    sees is pinned separately, through ``server.handle_call_tool``, below.
    """
    mod = _import_tools()
    with pytest.raises(ValueError, match="SINCE_LAUNCH_17D"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set",
            {
                "platform": "google_ads",
                "account_id": "123",
                "totals": {"spend": 1.0},
                "metrics_period": "SINCE_LAUNCH_17D",
            },
        )
    assert not (cwd_to_tmp / "STATE.json").exists()


# ---------------------------------------------------------------------------
# The path a real MCP client takes — schema validation runs BEFORE the handler
# ---------------------------------------------------------------------------


async def test_the_real_dispatch_path_refuses_a_non_canonical_window(
    cwd_to_tmp,
) -> None:
    """What an MCP CLIENT actually observes.

    ``handle_call_tool`` schema-validates against the declared ``inputSchema``
    before any handler runs, so the ``enum`` fires first and mureo's own
    message is never reached on this path (same shape as
    ``test_empty_account_id_through_the_real_dispatcher``). Calling
    ``tools_mureo_context.handle_tool`` directly, as the tests above do, skips
    that layer — so it cannot pin what an agent is told, and a test that only
    did that would be green for the wrong reason.
    """
    from mureo.mcp import server as server_mod

    with pytest.raises(ValueError) as excinfo:
        await server_mod.handle_call_tool(
            "mureo_state_platform_metrics_set",
            {
                "platform": "google_ads",
                "account_id": "123",
                "totals": {"spend": 1.0},
                "metrics_period": "SINCE_LAUNCH_17D",
            },
        )

    message = str(excinfo.value)
    assert "metrics_period" in message
    assert "SINCE_LAUNCH_17D" in message
    for window in CANONICAL_METRICS_WINDOWS:
        assert window in message
    assert not (cwd_to_tmp / "STATE.json").exists()


async def test_the_real_dispatch_path_refuses_a_near_miss_periods_key(
    cwd_to_tmp,
) -> None:
    """And refuses it as spelled: the ``LAST_7_DAYS`` bucket keeps the
    seven-day figure rather than acquiring an eight-day one."""
    from mureo.mcp import server as server_mod

    await server_mod.handle_call_tool(
        "mureo_state_platform_metrics_set",
        {
            "platform": "google_ads",
            "account_id": "123",
            "periods": {"LAST_7_DAYS": {"spend": 7.0}},
        },
    )

    with pytest.raises(ValueError) as excinfo:
        await server_mod.handle_call_tool(
            "mureo_state_platform_metrics_set",
            {
                "platform": "google_ads",
                "account_id": "123",
                "periods": {"LAST_8_DAYS": {"spend": 8.0}},
            },
        )
    assert "LAST_8_DAYS" in str(excinfo.value)

    doc = read_state_file(cwd_to_tmp / "STATE.json")
    assert doc.platforms is not None
    entry = doc.platforms["google_ads"]
    assert set(entry.periods or {}) == {"LAST_7_DAYS"}
    assert entry.periods["LAST_7_DAYS"]["spend"] == 7.0


async def test_the_real_dispatch_path_writes_a_window_the_default_view_reads(
    monkeypatch: pytest.MonkeyPatch, cwd_to_tmp
) -> None:
    """The acceptance property, pinned on the path the field failure took:
    a call an MCP client can actually make, whose success the default view
    can read back."""
    _use_workspace(monkeypatch, cwd_to_tmp)
    from mureo.mcp import server as server_mod

    await server_mod.handle_call_tool(
        "mureo_state_platform_metrics_set",
        {
            "platform": "google_ads",
            "account_id": "123",
            "periods": {"YESTERDAY": {"spend": 12.5}},
        },
    )

    summary = build_report_summary(period="YESTERDAY")
    assert "YESTERDAY" in summary["periods"]
    (row,) = summary["platforms"]
    assert row["totals"]["spend"] == 12.5
    assert summary["non_canonical_periods"] == []


def test_the_reason_reaches_the_agent_before_it_calls() -> None:
    """The ``enum`` rejects a bad window before any mureo code runs, so the
    refusal an agent sees is the JSON-Schema one: it carries the allowed
    values and nothing else. The near-miss guidance — do not round onto a
    neighbour, report the other span in your reply instead — therefore has to
    be in the SCHEMA, which the model reads before calling, not only in a
    message it will never receive.

    And it is one text, not two: the same constant the raiser appends, so the
    two paths cannot drift into telling a caller different things.
    """
    props = _metrics_schema()["properties"]
    assert METRICS_WINDOW_RULE in props["metrics_period"]["description"]
    # The near-miss is the case a caller is most likely to assume mureo
    # handled for them — the rule has to say it does not.
    assert "never rounded" in METRICS_WINDOW_RULE

    with pytest.raises(ValueError) as excinfo:
        reject_non_canonical_metrics_window("LAST_8_DAYS", field="metrics_period")
    assert METRICS_WINDOW_RULE in str(excinfo.value)


async def test_the_mcp_tool_still_writes_a_canonical_window(cwd_to_tmp) -> None:
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_platform_metrics_set",
        {
            "platform": "google_ads",
            "account_id": "123",
            "totals": {"spend": 1.0},
            "metrics_period": "YESTERDAY",
            "periods": {"YESTERDAY": {"spend": 1.0}},
        },
    )
    payload = json.loads(result[0].text)
    assert payload["platforms"]["google_ads"]["metrics_period"] == "YESTERDAY"
