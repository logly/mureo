"""Reading ``JOURNAL.jsonl`` back, bounded (#758, phase 4b).

``mureo journal`` grew the only journal reader mureo had, as three private
functions inside a Typer command. ``mureo_history_query`` has to ask the
same file the same questions, and a second reader is a second answer to
"does this record match" — so the three moved into
:mod:`mureo.mcp.journal_read` and the CLI now imports them. What these
tests pin:

- the moved helpers still answer exactly what the CLI's did, and the CLI
  uses THOSE objects rather than copies of them;
- the filters the tool needs (``until`` / ``batch_id`` / ``family`` /
  ``outcome``) are all default-off, so every existing caller is unchanged;
- the tail reader returns the LAST ``max_lines`` lines without reading the
  whole file. The journal grows one line per tool call and nothing rotates
  it yet (#758 phase 6), so an unbounded read is a workspace-sized read.
  The awkward cases are all about where a block boundary lands: a file
  smaller than one block, a line that ends exactly on a boundary, a file
  with no trailing newline, and CRLF.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from mureo.mcp.journal_read import (
    TAIL_BLOCK_BYTES,
    read_records,
    read_records_tail,
    record_date,
    record_matches,
    tail_lines,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "v": 1,
        "ts": "2026-09-16T10:00:00+00:00",
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


def _write(path: Path, *lines: dict[str, Any] | str) -> Path:
    text = "\n".join(
        line if isinstance(line, str) else json.dumps(line) for line in lines
    )
    path.write_text(text + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The helpers the CLI used to own
# ---------------------------------------------------------------------------


class TestTheCliUsesTheSharedReader:
    """Not a copy: the command must call these exact functions, or the two
    readers start disagreeing about what a match is.

    The command imports them inside its callback rather than at module
    scope, because ``mureo.mcp`` pulls the whole MCP server in at package
    import and ``mureo.cli.main`` must not pay for that at startup (#486)
    — so the pin is on the source and on the absence of local copies.
    """

    def test_the_command_keeps_no_reader_of_its_own(self) -> None:
        from mureo.cli import journal_cmd

        for gone in ("_read_records", "_record_date", "_matches"):
            assert not hasattr(journal_cmd, gone)

    def test_the_command_reads_through_this_module(self) -> None:
        import inspect

        from mureo.cli import journal_cmd

        source = inspect.getsource(journal_cmd)
        assert "from mureo.mcp.journal_read import" in source
        for name in (
            "read_records_files",
            "read_records_tail_files",
            "record_matches",
            "JOURNAL_SCAN_LINES",
        ):
            assert name in source
        assert "record_matches(" in source


class TestReadRecords:
    def test_parses_every_object_line(self, tmp_path: Path) -> None:
        log = _write(tmp_path / "j.jsonl", _record(), _record(tool="rollback_apply"))
        records, skipped = read_records(log)
        assert [r["tool"] for r in records] == [
            "google_ads_campaigns_list",
            "rollback_apply",
        ]
        assert skipped == 0

    def test_counts_unparseable_and_non_object_lines(self, tmp_path: Path) -> None:
        log = _write(tmp_path / "j.jsonl", _record(), "{not json", "[1, 2]", "")
        records, skipped = read_records(log)
        assert len(records) == 1
        assert skipped == 2


class TestRecordDate:
    def test_reads_an_offset_timestamp_as_utc(self) -> None:
        assert record_date(_record(ts="2026-09-17T08:30:00+09:00")) == date(2026, 9, 16)

    def test_a_naive_timestamp_is_read_as_utc(self) -> None:
        assert record_date(_record(ts="2026-09-16T23:00:00")) == date(2026, 9, 16)

    def test_an_unusable_timestamp_is_none(self) -> None:
        assert record_date(_record(ts="yesterday")) is None


class TestRecordMatches:
    """The four original filters keep their exact behaviour; the four new
    ones are off unless asked for."""

    def _matches(self, record: dict[str, Any], **kwargs: Any) -> bool:
        defaults: dict[str, Any] = {
            "tool": None,
            "since": None,
            "failures": False,
            "mutations": False,
        }
        defaults.update(kwargs)
        return record_matches(record, **defaults)

    def test_no_filter_matches_everything(self) -> None:
        assert self._matches(_record())

    def test_tool_is_an_exact_match(self) -> None:
        assert not self._matches(_record(), tool="rollback_apply")
        assert self._matches(_record(tool="rollback_apply"), tool="rollback_apply")

    def test_failures_drops_the_successful_calls(self) -> None:
        assert not self._matches(_record(), failures=True)
        assert self._matches(_record(outcome="denied"), failures=True)

    def test_mutations_requires_the_flag_to_be_true(self) -> None:
        assert not self._matches(_record(), mutations=True)
        assert self._matches(_record(mutating=True), mutations=True)

    def test_since_excludes_a_record_with_no_usable_date(self) -> None:
        assert not self._matches(_record(ts="?"), since=date(2026, 1, 1))

    def test_a_record_with_no_usable_date_survives_an_undated_query(self) -> None:
        assert self._matches(_record(ts="?"))

    def test_until_is_inclusive(self) -> None:
        assert self._matches(_record(), until=date(2026, 9, 16))
        assert not self._matches(_record(), until=date(2026, 9, 15))

    def test_until_excludes_a_record_with_no_usable_date(self) -> None:
        assert not self._matches(_record(ts="?"), until=date(2026, 9, 30))

    def test_batch_id_is_an_exact_match(self) -> None:
        assert not self._matches(_record(), batch_id="b-1")
        assert self._matches(_record(batch_id="b-1"), batch_id="b-1")

    def test_family_is_an_exact_match(self) -> None:
        assert not self._matches(_record(), family="meta_ads")
        assert self._matches(_record(), family="google_ads")

    def test_outcome_is_an_exact_match(self) -> None:
        assert not self._matches(_record(), outcome="denied")
        assert self._matches(_record(outcome="denied"), outcome="denied")


# ---------------------------------------------------------------------------
# The tail reader
# ---------------------------------------------------------------------------


class TestTailLines:
    def test_an_empty_file_has_no_lines(self, tmp_path: Path) -> None:
        empty = tmp_path / "j.jsonl"
        empty.write_text("", encoding="utf-8")
        assert tail_lines(empty, 10) == []

    def test_a_file_smaller_than_one_block_is_returned_whole(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "j.jsonl"
        log.write_text("a\nb\nc\n", encoding="utf-8")
        assert len(b"a\nb\nc\n") < TAIL_BLOCK_BYTES
        assert tail_lines(log, 10) == ["a", "b", "c"]

    def test_only_the_last_lines_come_back(self, tmp_path: Path) -> None:
        log = tmp_path / "j.jsonl"
        log.write_text("".join(f"line-{i}\n" for i in range(100)), encoding="utf-8")
        assert tail_lines(log, 3) == ["line-97", "line-98", "line-99"]

    def test_a_file_with_no_trailing_newline_keeps_its_last_line(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "j.jsonl"
        log.write_text("a\nb\nc", encoding="utf-8")
        assert tail_lines(log, 2) == ["b", "c"]

    def test_crlf_line_endings_are_stripped(self, tmp_path: Path) -> None:
        log = tmp_path / "j.jsonl"
        log.write_bytes(b'{"a": 1}\r\n{"a": 2}\r\n')
        assert tail_lines(log, 2) == ['{"a": 1}', '{"a": 2}']

    @pytest.mark.parametrize("block", [1, 2, 3, 4, 8, 16])
    def test_the_answer_does_not_depend_on_where_the_blocks_fall(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, block: int
    ) -> None:
        """A line that ends exactly on a block boundary, and one that
        straddles two, must read the same as a single-block read."""
        import mureo.mcp.journal_read as module

        monkeypatch.setattr(module, "TAIL_BLOCK_BYTES", block)
        log = tmp_path / "j.jsonl"
        log.write_text("aa\nbbb\ncccc\nd\n", encoding="utf-8")

        assert module.tail_lines(log, 3) == ["bbb", "cccc", "d"]
        assert module.tail_lines(log, 99) == ["aa", "bbb", "cccc", "d"]

    def test_a_partial_first_line_is_never_returned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The read starts mid-file, so the oldest line it touches may be
        half a line. Returning it would hand the caller a record that
        never existed."""
        import mureo.mcp.journal_read as module

        monkeypatch.setattr(module, "TAIL_BLOCK_BYTES", 4)
        log = tmp_path / "j.jsonl"
        log.write_text("aaaaaaaaaa\nbb\ncc\n", encoding="utf-8")

        assert module.tail_lines(log, 2) == ["bb", "cc"]

    def test_a_max_of_zero_is_refused(self, tmp_path: Path) -> None:
        log = _write(tmp_path / "j.jsonl", _record())
        with pytest.raises(ValueError, match="at least 1"):
            tail_lines(log, 0)


class TestReadRecordsTail:
    def test_returns_the_newest_records_oldest_first(self, tmp_path: Path) -> None:
        log = _write(
            tmp_path / "j.jsonl",
            *(_record(tool=f"tool-{i}") for i in range(10)),
        )
        tail = read_records_tail(log, 3)
        assert [r["tool"] for r in tail.records] == ["tool-7", "tool-8", "tool-9"]
        assert tail.scanned_lines == 3
        assert tail.skipped_lines == 0

    def test_counts_the_lines_it_could_not_parse(self, tmp_path: Path) -> None:
        log = _write(tmp_path / "j.jsonl", _record(), "{half a line", "42")
        tail = read_records_tail(log, 10)
        assert len(tail.records) == 1
        assert tail.scanned_lines == 3
        assert tail.skipped_lines == 2

    def test_an_empty_file_reads_as_no_records(self, tmp_path: Path) -> None:
        empty = tmp_path / "j.jsonl"
        empty.write_text("", encoding="utf-8")
        tail = read_records_tail(empty, 10)
        assert tail.records == []
        assert tail.scanned_lines == 0
        assert tail.skipped_lines == 0

    def test_the_scan_is_bounded_by_max_lines(self, tmp_path: Path) -> None:
        log = _write(
            tmp_path / "j.jsonl", *(_record(tool=f"t-{i}") for i in range(500))
        )
        tail = read_records_tail(log, 50)
        assert tail.scanned_lines == 50
        assert len(tail.records) == 50
        assert tail.records[0]["tool"] == "t-450"
