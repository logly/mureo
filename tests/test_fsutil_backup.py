"""Tests for ``mureo.fsutil.backup_file`` (issue #276 before-state backup).

A write path keeps a copy of the prior good file before an in-place
overwrite so a botched round-trip is recoverable. ``timestamped`` keeps a
history (STRATEGY.md); the rolling form keeps a single ``.bak``
(credentials.json).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mureo.fsutil import backup_file


@pytest.mark.unit
def test_backup_absent_file_returns_none(tmp_path: Path) -> None:
    """Nothing to back up on a first write — returns None, creates nothing."""
    target = tmp_path / "credentials.json"
    assert backup_file(target) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
def test_rolling_backup_copies_prior_content(tmp_path: Path) -> None:
    target = tmp_path / "credentials.json"
    target.write_text('{"google_ads": {"developer_token": "DT"}}', encoding="utf-8")

    backup = backup_file(target)

    assert backup == tmp_path / "credentials.json.bak"
    assert backup is not None and backup.exists()
    assert "DT" in backup.read_text(encoding="utf-8")


@pytest.mark.unit
def test_rolling_backup_overwrites_single_bak(tmp_path: Path) -> None:
    """The non-timestamped form keeps exactly one rolling ``.bak``."""
    target = tmp_path / "credentials.json"
    target.write_text("v1", encoding="utf-8")
    backup_file(target)
    target.write_text("v2", encoding="utf-8")
    backup_file(target)

    baks = list(tmp_path.glob("credentials.json.bak*"))
    assert len(baks) == 1
    assert baks[0].read_text(encoding="utf-8") == "v2"


@pytest.mark.unit
def test_timestamped_backup_keeps_history(tmp_path: Path) -> None:
    target = tmp_path / "STRATEGY.md"
    target.write_text("# Strategy\n\n## Persona\nv1\n", encoding="utf-8")
    first = backup_file(target, timestamped=True)
    target.write_text("# Strategy\n\n## Persona\nv2\n", encoding="utf-8")
    second = backup_file(target, timestamped=True)

    assert first is not None and second is not None
    assert first != second
    history = sorted(tmp_path.glob("STRATEGY.md.bak.*"))
    assert len(history) == 2


@pytest.mark.unit
def test_timestamped_backup_disambiguates_same_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical ``time.time_ns()`` (low-res clocks) must not clobber history."""
    monkeypatch.setattr("mureo.fsutil.time.time_ns", lambda: 4242)

    target = tmp_path / "STRATEGY.md"
    target.write_text("v1", encoding="utf-8")
    first = backup_file(target, timestamped=True)
    target.write_text("v2", encoding="utf-8")
    second = backup_file(target, timestamped=True)

    assert first is not None and second is not None and first != second
    history = sorted(tmp_path.glob("STRATEGY.md.bak.*"))
    assert len(history) == 2
    assert {p.read_text(encoding="utf-8") for p in history} == {"v1", "v2"}
