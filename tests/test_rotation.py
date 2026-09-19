"""Size-bounded append files (#758 phase 6).

``JOURNAL.jsonl`` and ``history/reports/<kind>.jsonl`` are append-only and
grew without a ceiling. :mod:`mureo.core.rotation` is the ceiling: one
name format, one "is it full" question, and one way to enumerate what a
rotation left behind — so a reader can still see the whole record.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from mureo.core import rotation

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

WHEN = datetime(2026, 9, 19, 1, 30, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _forget_the_env_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """The "warned once" flag is process-global; each test starts fresh."""
    monkeypatch.setattr(rotation, "_env_warning_issued", False)


def _write(path: Path, size: int) -> Path:
    path.write_bytes(b"x" * size)
    return path


class TestRotatedName:
    def test_the_stamp_is_utc_and_sorts_lexicographically(self, tmp_path: Path) -> None:
        name = rotation.rotated_name(tmp_path / "JOURNAL.jsonl", WHEN)
        assert name.name == "JOURNAL.20260919T013000Z.jsonl"
        assert name.parent == tmp_path

    def test_a_multi_part_suffix_keeps_only_the_last(self, tmp_path: Path) -> None:
        name = rotation.rotated_name(tmp_path / "daily-check.jsonl", WHEN)
        assert name.name == "daily-check.20260919T013000Z.jsonl"

    def test_a_collision_gets_a_counter(self, tmp_path: Path) -> None:
        first = rotation.rotated_name(tmp_path / "JOURNAL.jsonl", WHEN)
        first.touch()
        second = rotation.rotated_name(tmp_path / "JOURNAL.jsonl", WHEN)
        assert second.name == "JOURNAL.20260919T013000Z-1.jsonl"
        second.touch()
        third = rotation.rotated_name(tmp_path / "JOURNAL.jsonl", WHEN)
        assert third.name == "JOURNAL.20260919T013000Z-2.jsonl"


class TestRotateIfOver:
    def test_below_the_threshold_nothing_moves(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "JOURNAL.jsonl", 99)
        assert rotation.rotate_if_over(path, max_bytes=100, now=WHEN) is None
        assert path.exists()
        assert list(tmp_path.iterdir()) == [path]

    def test_at_the_threshold_it_rotates(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "JOURNAL.jsonl", 100)
        moved = rotation.rotate_if_over(path, max_bytes=100, now=WHEN)
        assert moved == tmp_path / "JOURNAL.20260919T013000Z.jsonl"
        assert not path.exists()
        assert moved.read_bytes() == b"x" * 100

    def test_above_the_threshold_it_rotates(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "JOURNAL.jsonl", 500)
        assert rotation.rotate_if_over(path, max_bytes=100, now=WHEN) is not None
        assert not path.exists()

    def test_a_missing_file_is_never_rotated(self, tmp_path: Path) -> None:
        missing = tmp_path / "JOURNAL.jsonl"
        assert rotation.rotate_if_over(missing, max_bytes=1, now=WHEN) is None
        assert not missing.exists()


class TestSiblingFiles:
    def test_oldest_first_with_the_live_file_last(self, tmp_path: Path) -> None:
        newer = _write(tmp_path / "JOURNAL.20260201T000000Z.jsonl", 1)
        older = _write(tmp_path / "JOURNAL.20260101T000000Z.jsonl", 1)
        live = _write(tmp_path / "JOURNAL.jsonl", 1)
        assert rotation.sibling_files(live) == [older, newer, live]

    def test_a_counter_suffix_sorts_after_its_own_stamp(self, tmp_path: Path) -> None:
        second = _write(tmp_path / "JOURNAL.20260201T000000Z-1.jsonl", 1)
        first = _write(tmp_path / "JOURNAL.20260201T000000Z.jsonl", 1)
        live = tmp_path / "JOURNAL.jsonl"
        assert rotation.sibling_files(live) == [first, second]

    def test_an_absent_live_file_is_left_out(self, tmp_path: Path) -> None:
        rotated = _write(tmp_path / "JOURNAL.20260101T000000Z.jsonl", 1)
        assert rotation.sibling_files(tmp_path / "JOURNAL.jsonl") == [rotated]

    def test_nothing_at_all_is_an_empty_list(self, tmp_path: Path) -> None:
        assert rotation.sibling_files(tmp_path / "JOURNAL.jsonl") == []

    def test_only_names_the_rotation_itself_writes_are_included(
        self, tmp_path: Path
    ) -> None:
        """A backup, a lock and another file's rotation are not this file."""
        for name in (
            "JOURNAL.jsonl.bak",
            "JOURNAL.jsonl.lock",
            "JOURNAL.20260101.jsonl",
            "JOURNAL.20260101T000000Z.json",
            "OTHER.20260101T000000Z.jsonl",
            "JOURNAL.jsonl.20260101T000000Z",
        ):
            _write(tmp_path / name, 1)
        live = _write(tmp_path / "JOURNAL.jsonl", 1)
        assert rotation.sibling_files(live) == [live]


class TestMaxAppendBytes:
    def test_the_default_when_nothing_is_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(rotation.MAX_BYTES_ENV_VAR, raising=False)
        assert rotation.max_append_bytes() == rotation.DEFAULT_MAX_BYTES
        assert rotation.DEFAULT_MAX_BYTES == 32 * 1024 * 1024

    def test_a_positive_override_is_honoured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(rotation.MAX_BYTES_ENV_VAR, "4096")
        assert rotation.max_append_bytes() == 4096

    @pytest.mark.parametrize("value", ["0", "-5", "lots", "", "4096.5"])
    def test_an_unusable_override_falls_back_to_the_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        value: str,
    ) -> None:
        monkeypatch.setenv(rotation.MAX_BYTES_ENV_VAR, value)
        with caplog.at_level(logging.WARNING, logger=rotation.__name__):
            assert rotation.max_append_bytes() == rotation.DEFAULT_MAX_BYTES
        assert len(caplog.records) == 1
        assert rotation.MAX_BYTES_ENV_VAR in caplog.records[0].getMessage()

    def test_the_warning_is_issued_once_per_process(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """This is read on every append; a bad value must not flood the log."""
        monkeypatch.setenv(rotation.MAX_BYTES_ENV_VAR, "nope")
        with caplog.at_level(logging.WARNING, logger=rotation.__name__):
            for _ in range(3):
                assert rotation.max_append_bytes() == rotation.DEFAULT_MAX_BYTES
        assert len(caplog.records) == 1
