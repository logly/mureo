"""``mureo journal`` — read back the dispatcher journal (#758).

The reader is deliberately forgiving: an append-only log written by a
best-effort writer can end in a half-line after a crash, and one broken
line must never cost the operator the other 10 000. Malformed lines are
skipped and counted, never fatal.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mureo.cli.main import app
from mureo.mcp import journal

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = CliRunner()


def _entry(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "v": 1,
        "ts": "2026-09-16T10:00:00+00:00",
        "session": "s" * 32,
        "client": "Claude Code/1.4.2",
        "mureo": "0.18.0",
        "workspace_id": "default",
        "tool": "google_ads_campaigns_list",
        "family": "google_ads",
        "mutating": False,
        "args": {"customer_id": "123"},
        "outcome": "ok",
        "duration_ms": 42,
        "batch_id": None,
    }
    record.update(overrides)
    return record


def _write(path: Path, *records: dict[str, Any] | str) -> Path:
    lines = [
        record if isinstance(record, str) else json.dumps(record) for record in records
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(*args: str) -> Any:
    # ``FORCE_COLOR`` in the ambient environment (GitHub Actions sets it)
    # makes rich emit ANSI even into CliRunner's in-memory stream, which
    # splits ``--last`` in typer's usage error. Drop it for the invocation
    # so the output is the plain text the assertions read.
    return runner.invoke(app, ["journal", *args], env={"FORCE_COLOR": None})


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    missing = tmp_path / "JOURNAL.jsonl"
    result = _run("--path", str(missing))
    assert result.exit_code == 0, result.output
    assert f"no journal at {missing}" in result.output


def test_default_path_comes_from_the_journal_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _write(tmp_path / "JOURNAL.jsonl", _entry(tool="rollback_plan_get"))
    monkeypatch.setattr(journal, "journal_path", lambda: log)
    result = _run()
    assert result.exit_code == 0, result.output
    assert "rollback_plan_get" in result.output


def test_table_lists_the_columns(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(outcome="denied", reason="read-only mode is active", batch_id="batch-1"),
    )
    result = _run("--path", str(log))
    assert result.exit_code == 0, result.output
    row = next(
        ln for ln in result.output.splitlines() if "google_ads_campaigns_list" in ln
    )
    for cell in ("2026-09-16", "denied", "google_ads", "42", "batch-1", "read-only"):
        assert cell in row


def test_an_ok_row_shows_the_rationale_in_the_last_column(tmp_path: Path) -> None:
    """One column, two readings: a failure explains itself, a success says
    why the agent made the change."""
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(tool="rollback_apply", rationale="the budget change overshot"),
    )
    result = _run("--path", str(log))
    assert result.exit_code == 0, result.output
    assert "reason/rationale" in result.output
    row = next(ln for ln in result.output.splitlines() if "rollback_apply" in ln)
    assert "the budget change overshot" in row


def test_a_failed_row_shows_the_failure_not_the_rationale(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(
            tool="rollback_apply",
            outcome="denied",
            reason="read-only mode is active",
            rationale="the budget change overshot",
        ),
    )
    result = _run("--path", str(log))
    row = next(ln for ln in result.output.splitlines() if "rollback_apply" in ln)
    assert "read-only mode is active" in row
    assert "overshot" not in row


def test_the_table_cell_is_one_line_of_plain_text(tmp_path: Path) -> None:
    """A journal is read in a terminal and the text in it came from a model.

    A newline would break the column alignment into nonsense and an ANSI
    escape would recolour the operator's terminal, so both are flattened
    before the cell is cut to width. ``--json`` keeps the raw text.
    """
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(
            tool="rollback_apply",
            rationale="line one\n\x1b[31mline two\x1b[0m\tand   three",
        ),
    )
    result = _run("--path", str(log))
    assert "\x1b[31m" not in result.output
    assert "line one line two and three" in result.output


def test_json_keeps_the_rationale_verbatim(tmp_path: Path) -> None:
    log = _write(tmp_path / "JOURNAL.jsonl", _entry(rationale="z" * 300))
    result = _run("--path", str(log), "--json")
    assert _json_lines(result.output)[0]["rationale"] == "z" * 300


def test_long_reasons_are_truncated_in_the_table(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl", _entry(outcome="exception", reason="z" * 300)
    )
    result = _run("--path", str(log))
    assert "z" * 300 not in result.output
    assert "z" * 60 in result.output


def test_json_prints_the_raw_records(tmp_path: Path) -> None:
    log = _write(tmp_path / "JOURNAL.jsonl", _entry(), _entry(tool="rollback_apply"))
    result = _run("--path", str(log), "--json")
    assert result.exit_code == 0, result.output
    records = _json_lines(result.output)
    assert [record["tool"] for record in records] == [
        "google_ads_campaigns_list",
        "rollback_apply",
    ]
    assert records[0]["args"] == {"customer_id": "123"}


def test_tool_filter_is_exact(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(tool="google_ads_campaigns_list"),
        _entry(tool="google_ads_campaigns_list_extra"),
    )
    result = _run("--path", str(log), "--tool", "google_ads_campaigns_list", "--json")
    records = _json_lines(result.output)
    assert [record["tool"] for record in records] == ["google_ads_campaigns_list"]


def test_since_filters_on_the_utc_date(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(ts="2026-09-14T23:00:00+00:00", tool="old_call"),
        _entry(ts="2026-09-15T00:00:00+00:00", tool="boundary_call"),
        _entry(ts="2026-09-16T10:00:00+00:00", tool="new_call"),
    )
    result = _run("--path", str(log), "--since", "2026-09-15", "--json")
    records = _json_lines(result.output)
    assert [record["tool"] for record in records] == ["boundary_call", "new_call"]


def test_failures_keeps_every_non_ok_outcome(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(tool="fine"),
        _entry(tool="broke", outcome="exception", reason="boom"),
        _entry(tool="blocked", outcome="denied", reason="nope"),
    )
    result = _run("--path", str(log), "--failures", "--json")
    records = _json_lines(result.output)
    assert [record["tool"] for record in records] == ["broke", "blocked"]


def test_mutations_keeps_only_mutating_calls(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(tool="read"),
        _entry(tool="write", mutating=True),
    )
    result = _run("--path", str(log), "--mutations", "--json")
    records = _json_lines(result.output)
    assert [record["tool"] for record in records] == ["write"]


def test_last_keeps_the_tail_after_filtering(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        *[_entry(tool=f"t{index}", mutating=index % 2 == 0) for index in range(10)],
    )
    result = _run("--path", str(log), "--mutations", "--last", "2", "--json")
    records = _json_lines(result.output)
    assert [record["tool"] for record in records] == ["t6", "t8"]


def test_last_one_returns_exactly_one_row(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        *[_entry(tool=f"t{index}") for index in range(4)],
    )
    result = _run("--path", str(log), "--last", "1", "--json")
    assert [record["tool"] for record in _json_lines(result.output)] == ["t3"]


@pytest.mark.parametrize("value", ["0", "-3"])
def test_a_non_positive_last_is_rejected_at_the_boundary(
    tmp_path: Path, value: str
) -> None:
    """``--last 0`` used to mean "no limit", which reads as "show nothing".

    A count below 1 has no sensible reading, and guessing one silently is
    how an operator ends up trusting a view that answered a different
    question. Typer refuses it with the usage error (exit 2) instead.
    """
    log = _write(tmp_path / "JOURNAL.jsonl", _entry())
    result = _run("--path", str(log), "--last", value)
    assert result.exit_code == 2
    # Under a colour-capable terminal (CI) typer renders the usage error
    # through rich, which splits ``--last`` across ANSI escapes; compare
    # the plain text.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--last" in plain
    assert "Invalid value" in plain


def test_malformed_lines_are_skipped_and_counted(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "JOURNAL.jsonl",
        _entry(tool="good"),
        "{not json at all",
        "[1, 2, 3]",
        _entry(tool="also_good"),
    )
    result = _run("--path", str(log), "--json")
    assert result.exit_code == 0, result.output
    records = _json_lines(result.output)
    assert [record["tool"] for record in records] == ["good", "also_good"]
    assert "skipped 2 malformed line(s)" in result.output


def test_a_clean_file_says_nothing_about_malformed_lines(tmp_path: Path) -> None:
    log = _write(tmp_path / "JOURNAL.jsonl", _entry())
    result = _run("--path", str(log))
    assert "malformed" not in result.output
