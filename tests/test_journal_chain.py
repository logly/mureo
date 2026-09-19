"""The journal's hash chain (#758 phase 6).

A journal an editor can quietly rewrite is a record of what the last
person to open it wanted it to say. Every line now carries the hash of
the physical line before it (``prev``) and of itself (``h``), so an edit
or a removal anywhere except the very end is arithmetic, not opinion —
and the limit that "except the very end" names is pinned by a test of its
own, so nobody can read more into the chain than it proves.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core.rotation import MAX_BYTES_ENV_VAR, sibling_files
from mureo.mcp import journal_chain

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _record(index: int) -> dict[str, Any]:
    return {
        "v": 2,
        "ts": "2026-09-19T01:30:00+00:00",
        "tool": f"tool_{index}",
        "outcome": "ok",
        "batch_id": None,
    }


def _append(path: Path, count: int, *, start: int = 0) -> None:
    for index in range(start, start + count):
        journal_chain.chain_append(path, _record(index))


def _lines(path: Path) -> list[bytes]:
    return path.read_bytes().rstrip(b"\n").split(b"\n")


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in _lines(path)]


def _rewrite(path: Path, lines: list[bytes]) -> None:
    path.write_bytes(b"".join(line + b"\n" for line in lines))


class TestChainAppend:
    def test_the_first_line_points_at_nothing(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 1)
        assert _records(log)[0]["prev"] == ""

    def test_the_second_points_at_the_first_physical_line(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 2)
        first, _second = _lines(log)
        assert _records(log)[1]["prev"] == hashlib.sha256(first).hexdigest()

    def test_the_two_keys_come_last_and_in_order(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 1)
        assert list(_records(log)[0])[-2:] == ["prev", "h"]

    def test_the_hash_is_over_the_record_without_it(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 1)
        record = _records(log)[0]
        stored = record.pop("h")
        assert stored == journal_chain.record_hash(record)

    def test_the_callers_record_is_not_mutated(self, tmp_path: Path) -> None:
        record = _record(0)
        journal_chain.chain_append(tmp_path / "JOURNAL.jsonl", record)
        assert record == _record(0)

    def test_the_file_is_created_owner_only(self, tmp_path: Path) -> None:
        if sys.platform == "win32":  # pragma: no cover - POSIX modes only
            pytest.skip("POSIX file modes only")
        log = tmp_path / "ws" / "JOURNAL.jsonl"
        _append(log, 1)
        assert stat.S_IMODE(os.stat(log).st_mode) == 0o600

    def test_concurrent_appends_keep_one_unbroken_chain(self, tmp_path: Path) -> None:
        """The lock is what makes the chain true under two writers."""
        log = tmp_path / "JOURNAL.jsonl"
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(
                pool.map(
                    lambda index: journal_chain.chain_append(log, _record(index)),
                    range(48),
                )
            )
        report = journal_chain.verify_chain([log])
        assert report.records == 48
        assert report.ok, report.first_break


class TestVerifyChain:
    def test_an_untouched_journal_verifies(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 5)
        report = journal_chain.verify_chain([log])
        assert (report.files, report.records, report.unchained) == (1, 5, 0)
        assert report.ok
        assert report.first_break is None

    def test_a_missing_file_is_skipped(self, tmp_path: Path) -> None:
        report = journal_chain.verify_chain([tmp_path / "JOURNAL.jsonl"])
        assert (report.files, report.records, report.ok) == (0, 0, True)

    def test_blank_lines_are_not_records(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 2)
        lines = _lines(log)
        _rewrite(log, [lines[0], b"", lines[1]])
        report = journal_chain.verify_chain([log])
        assert report.records == 2
        assert report.ok

    def test_an_edited_line_is_caught_on_its_own_line(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 3)
        lines = _lines(log)
        lines[1] = lines[1].replace(b'"tool_1"', b'"tool_X"')
        _rewrite(log, lines)
        report = journal_chain.verify_chain([log])
        assert not report.ok
        assert report.first_break == (log, 2, journal_chain.BREAK_HASH_MISMATCH)

    def test_a_deleted_line_is_caught_on_the_one_after_it(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 3)
        lines = _lines(log)
        _rewrite(log, [lines[0], lines[2]])
        report = journal_chain.verify_chain([log])
        assert not report.ok
        assert report.first_break == (log, 2, journal_chain.BREAK_PREV_MISMATCH)

    def test_an_unparseable_line_is_a_break(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 2)
        lines = _lines(log)
        _rewrite(log, [lines[0], b"{half a line", lines[1]])
        report = journal_chain.verify_chain([log])
        assert not report.ok
        assert report.first_break == (log, 2, journal_chain.BREAK_UNPARSEABLE)

    def test_only_the_first_break_is_reported(self, tmp_path: Path) -> None:
        """The scan finishes, so the record counts stay honest."""
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 4)
        lines = _lines(log)
        lines[1] = lines[1].replace(b'"tool_1"', b'"tool_X"')
        lines[3] = lines[3].replace(b'"tool_3"', b'"tool_Y"')
        _rewrite(log, lines)
        report = journal_chain.verify_chain([log])
        assert report.first_break == (log, 2, journal_chain.BREAK_HASH_MISMATCH)
        assert report.records == 4

    def test_version_one_lines_are_unchained_not_broken(self, tmp_path: Path) -> None:
        """A journal written before phase 6 carries no ``prev`` / ``h``.

        Nothing can be proved about those lines, and claiming a break
        would be a false accusation against every pre-upgrade workspace.
        """
        log = tmp_path / "JOURNAL.jsonl"
        legacy = [
            json.dumps({"v": 1, "tool": "old_call"}).encode(),
            json.dumps({"v": 1, "tool": "older_call"}).encode(),
        ]
        _rewrite(log, legacy)
        journal_chain.chain_append(log, _record(0))
        report = journal_chain.verify_chain([log])
        assert report.records == 3
        assert report.unchained == 2
        assert report.ok, report.first_break

    def test_tail_truncation_is_not_detected(self, tmp_path: Path) -> None:
        """The honest limit of a hash chain, pinned so nobody overclaims.

        Each line points BACKWARDS, so dropping the last lines leaves a
        shorter chain that is still internally consistent. Detecting that
        needs an external anchor (a copy of the head hash elsewhere),
        which mureo does not have.
        """
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 3)
        _rewrite(log, _lines(log)[:2])
        report = journal_chain.verify_chain([log])
        assert report.ok
        assert report.records == 2


class TestAcrossRotation:
    def test_the_chain_continues_into_the_next_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MAX_BYTES_ENV_VAR, "400")
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 12)
        files = sibling_files(log)
        assert len(files) > 1, files
        report = journal_chain.verify_chain(files)
        assert report.files == len(files)
        assert report.records == 12
        assert report.ok, report.first_break

    def test_a_gap_between_two_files_is_a_break(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MAX_BYTES_ENV_VAR, "400")
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 12)
        files = sibling_files(log)
        first = files[0]
        _rewrite(first, _lines(first)[:-1])
        report = journal_chain.verify_chain(files)
        assert not report.ok
        assert report.first_break is not None
        assert report.first_break[0] == files[1]
        assert report.first_break[2] == journal_chain.BREAK_PREV_MISMATCH

    def test_a_pruned_file_reads_as_a_break_at_the_oldest_one_left(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Documented in docs/cli.md: an operator who deletes a rotated
        file gets ``prev_mismatch`` at line 1 of the oldest one still
        there. Nothing distinguishes a file they pruned from one somebody
        else removed, and mureo never deletes one itself."""
        monkeypatch.setenv(MAX_BYTES_ENV_VAR, "400")
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 12)
        files = sibling_files(log)
        files[0].unlink()
        remaining = sibling_files(log)

        report = journal_chain.verify_chain(remaining)
        assert report.first_break == (
            remaining[0],
            1,
            journal_chain.BREAK_PREV_MISMATCH,
        )

    def test_the_first_line_of_a_fresh_file_points_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MAX_BYTES_ENV_VAR, "400")
        log = tmp_path / "JOURNAL.jsonl"
        _append(log, 12)
        files = sibling_files(log)
        tail_of_previous = _lines(files[-2])[-1]
        assert (
            _records(files[-1])[0]["prev"]
            == hashlib.sha256(tail_of_previous).hexdigest()
        )


class TestLastLineHash:
    def test_no_file_is_no_hash(self, tmp_path: Path) -> None:
        assert journal_chain.last_line_hash(tmp_path / "nope.jsonl") is None

    def test_an_empty_file_is_no_hash(self, tmp_path: Path) -> None:
        empty = tmp_path / "JOURNAL.jsonl"
        empty.write_bytes(b"")
        assert journal_chain.last_line_hash(empty) is None

    def test_a_line_longer_than_one_read_block_is_read_whole(
        self, tmp_path: Path
    ) -> None:
        """A seek-and-read tail must not hash only the part it landed on."""
        log = tmp_path / "JOURNAL.jsonl"
        huge = b'{"note": "' + b"x" * (journal_chain.TAIL_BLOCK_BYTES * 3) + b'"}'
        _rewrite(log, [b'{"first": 1}', huge])
        assert journal_chain.last_line_hash(log) == hashlib.sha256(huge).hexdigest()

    def test_trailing_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        log = tmp_path / "JOURNAL.jsonl"
        log.write_bytes(b'{"a": 1}\n\n\n')
        assert (
            journal_chain.last_line_hash(log) == hashlib.sha256(b'{"a": 1}').hexdigest()
        )
