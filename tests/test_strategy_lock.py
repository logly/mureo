"""Regression tests: STRATEGY.md read-modify-write is process/thread safe.

``add_strategy_entry`` / ``remove_strategy_entry`` run their read -> modify ->
write cycle inside ``fsutil.file_lock`` (the same cross-process lock STATE.json
mutations use, issue #115). Without it two concurrent callers could
last-writer-wins away each other's change (a lost update). These tests lock in
that every concurrent add/remove is preserved.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from mureo.context.models import StrategyEntry
from mureo.context.strategy import (
    add_strategy_entry,
    read_strategy_file,
    remove_strategy_entry,
)


def _custom_entry(title: str) -> StrategyEntry:
    return StrategyEntry(context_type="custom", title=title, content=f"body {title}")


@pytest.mark.unit
class TestStrategyLock:
    def test_sequential_adds_are_all_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        add_strategy_entry(path, _custom_entry("a"))
        add_strategy_entry(path, _custom_entry("b"))

        titles = {e.title for e in read_strategy_file(path)}
        assert titles == {"a", "b"}

    def test_concurrent_adds_no_lost_update(self, tmp_path: Path) -> None:
        """N threads each append a distinct entry; the lock must serialise the
        read-modify-write so every entry survives (no lost update)."""
        path = tmp_path / "STRATEGY.md"
        n = 12
        barrier = threading.Barrier(n)

        def worker(i: int) -> None:
            # Release all threads at once to maximise read-modify-write overlap.
            barrier.wait()
            add_strategy_entry(path, _custom_entry(f"t{i}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        titles = sorted(e.title for e in read_strategy_file(path))
        assert titles == sorted(f"t{i}" for i in range(n))

    def test_concurrent_add_and_remove_are_consistent(self, tmp_path: Path) -> None:
        """A concurrent add of a new type and a remove of a different type must
        not clobber each other's write."""
        path = tmp_path / "STRATEGY.md"
        # Seed with a persona entry that the remover targets.
        add_strategy_entry(
            path, StrategyEntry(context_type="persona", title="Persona", content="p")
        )
        barrier = threading.Barrier(2)

        def adder() -> None:
            barrier.wait()
            add_strategy_entry(path, _custom_entry("kept"))

        def remover() -> None:
            barrier.wait()
            remove_strategy_entry(path, "persona")

        t1 = threading.Thread(target=adder)
        t2 = threading.Thread(target=remover)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        entries = read_strategy_file(path)
        types = {e.context_type for e in entries}
        titles = {e.title for e in entries}
        # The added entry survived regardless of interleaving...
        assert "kept" in titles
        # ...and the persona removal took effect.
        assert "persona" not in types

    def test_lock_sidecar_is_created(self, tmp_path: Path) -> None:
        path = tmp_path / "STRATEGY.md"
        add_strategy_entry(path, _custom_entry("a"))
        assert (tmp_path / "STRATEGY.md.lock").exists()
