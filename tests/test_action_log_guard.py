"""A whole-document write that shortens ``action_log`` leaves a copy (#758 p6).

``action_log`` is append-only by contract, and every in-repo mutator
respects it. Nothing enforced it on the whole-document writers —
``StateStore.write_state``, a host's import or restore, a repair — so a
caller holding a stale or partial document could shorten the record of
what was done to an ad account and leave nothing behind saying so.

The guard does not refuse the write (a document that cannot be written is
a workspace an operator cannot repair, and the same argument that keeps
``warn_on_duplicate_accounts`` advisory applies here). It makes the write
recoverable: a timestamped copy of what was on disk, and a WARNING naming
both lengths and where the copy is.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context import action_log_guard, platform_guards
from mureo.context.action_log_guard import guard_action_log_shrink
from mureo.context.models import ActionLogEntry, PlatformState, StateDocument
from mureo.context.state import (
    append_action_log,
    read_state_file,
    write_state_file,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _entry(index: int, action: str = "campaign_paused") -> ActionLogEntry:
    return ActionLogEntry(
        timestamp=f"2026-09-{index + 1:02d}T00:00:00+00:00",
        action=action,
        platform="google_ads",
    )


def _doc(count: int, **overrides: Any) -> StateDocument:
    fields: dict[str, Any] = {
        "version": "2",
        "action_log": tuple(_entry(index) for index in range(count)),
    }
    fields.update(overrides)
    return StateDocument(**fields)


def _state(path: Path, count: int) -> Path:
    write_state_file(path, _doc(count))
    return path


def _backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak.*"))


class TestWhatCountsAsShortening:
    def test_a_shorter_log_is_backed_up(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _state(tmp_path / "STATE.json", 3)
        with caplog.at_level(logging.WARNING, logger=action_log_guard.__name__):
            backup = guard_action_log_shrink(path, _doc(2), previous=None)
        assert backup is not None
        assert backup.exists()
        assert len(read_state_file(backup).action_log) == 3
        message = caplog.records[0].getMessage()
        assert "3" in message and "2" in message and str(backup) in message

    def test_a_rewritten_entry_of_the_same_length_is_shortening_too(
        self, tmp_path: Path
    ) -> None:
        """Replacing history is losing it; the length alone would miss it."""
        path = _state(tmp_path / "STATE.json", 2)
        rewritten = StateDocument(
            version="2", action_log=(_entry(0), _entry(1, action="budget_raised"))
        )
        assert guard_action_log_shrink(path, rewritten, previous=None) is not None

    def test_an_appended_entry_is_not(self, tmp_path: Path) -> None:
        path = _state(tmp_path / "STATE.json", 2)
        assert guard_action_log_shrink(path, _doc(3), previous=None) is None
        assert _backups(path) == []

    def test_an_unchanged_log_is_not(self, tmp_path: Path) -> None:
        path = _state(tmp_path / "STATE.json", 2)
        assert guard_action_log_shrink(path, _doc(2), previous=None) is None

    def test_the_rest_of_the_document_is_not_the_guards_business(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path / "STATE.json", 2)
        changed = _doc(2, platforms={"google_ads": PlatformState(account_id="1")})
        assert guard_action_log_shrink(path, changed, previous=None) is None

    def test_a_missing_file_has_nothing_to_guard(self, tmp_path: Path) -> None:
        missing = tmp_path / "STATE.json"
        assert guard_action_log_shrink(missing, _doc(0), previous=None) is None
        assert _backups(missing) == []

    def test_a_document_that_cannot_be_read_is_not_guarded(
        self, tmp_path: Path
    ) -> None:
        """No previous log means no claim that one was shortened."""
        path = tmp_path / "STATE.json"
        path.write_text("{not json at all", encoding="utf-8")
        assert guard_action_log_shrink(path, _doc(0), previous=None) is None
        assert _backups(path) == []

    def test_a_supplied_previous_is_used_instead_of_a_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _state(tmp_path / "STATE.json", 3)

        def _explode(*args: Any, **kwargs: Any) -> StateDocument:
            raise AssertionError("the guard re-read a document it was handed")

        monkeypatch.setattr("mureo.context.state.read_state_file", _explode)
        assert guard_action_log_shrink(path, _doc(1), previous=_doc(3)) is not None


class TestWriteStateFile:
    def test_a_shortening_whole_document_write_is_backed_up(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path / "STATE.json", 3)
        write_state_file(path, _doc(1))
        assert len(read_state_file(path).action_log) == 1
        (backup,) = _backups(path)
        assert len(read_state_file(backup).action_log) == 3

    def test_an_ordinary_write_leaves_no_backup(self, tmp_path: Path) -> None:
        path = _state(tmp_path / "STATE.json", 1)
        write_state_file(path, _doc(2))
        assert _backups(path) == []

    def test_no_backup_means_no_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail closed, like ``apply_state_file_repairs``: a shortening write
        that could not be backed up must not happen at all."""
        path = _state(tmp_path / "STATE.json", 3)
        before = path.read_text(encoding="utf-8")

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise OSError("no room for a backup")

        monkeypatch.setattr(action_log_guard, "backup_file", _boom)
        with pytest.raises(OSError, match="no room"):
            write_state_file(path, _doc(1))
        assert path.read_text(encoding="utf-8") == before


class TestTheOrdinaryMutators:
    def test_append_action_log_pays_no_second_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The locked mutator hands the guard the document it already read."""
        from mureo.context import state as state_mod

        path = _state(tmp_path / "STATE.json", 1)
        reads: list[Path] = []
        original = state_mod.read_state_file

        def _counting(target: Path, *args: Any, **kwargs: Any) -> StateDocument:
            reads.append(target)
            return original(target, *args, **kwargs)

        monkeypatch.setattr(state_mod, "read_state_file", _counting)
        append_action_log(path, _entry(5))

        assert reads == [path]
        assert _backups(path) == []


class TestTheStateStore:
    def test_a_shortened_log_is_backed_up_and_the_write_proceeds(
        self, tmp_path: Path
    ) -> None:
        from mureo.core.state_store import FilesystemStateStore

        path = _state(tmp_path / "STATE.json", 4)
        FilesystemStateStore(workspace=tmp_path).write_state(_doc(1))

        assert len(read_state_file(path).action_log) == 1
        (backup,) = _backups(path)
        assert len(read_state_file(backup).action_log) == 4


class TestAPlatformRepair:
    def test_it_makes_exactly_one_backup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The repair backs up for itself and never shortens the log, so the
        guard must not add a second copy of the same document."""
        from mureo.context.platform_repair import apply_state_file_repairs

        monkeypatch.setattr(
            platform_guards,
            "_provider_entry_points",
            lambda: (SimpleNamespace(name="logly_ads_context"),),
        )
        path = tmp_path / "STATE.json"
        write_state_file(
            path,
            _doc(
                2,
                platforms={
                    "logly_ads": PlatformState(account_id=""),
                    "google_ads": PlatformState(account_id="123"),
                },
            ),
        )

        outcome = apply_state_file_repairs(path)

        assert outcome.changed is True
        assert len(_backups(path)) == 1
        assert len(read_state_file(path).action_log) == 2
