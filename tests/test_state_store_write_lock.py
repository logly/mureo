"""Regression tests: ``FilesystemStateStore.write_state`` takes the state lock.

The blind full-document ``write_state`` now writes under the same cross-process
``file_lock`` every STATE.json mutator holds, so it cannot interleave with a
concurrent read-modify-write and resurrect the #115 lost-update race. These
tests pin that the write stays valid under concurrency and that the lock sidecar
is created.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from mureo.context.models import StateDocument
from mureo.context.state import read_state_file
from mureo.core.state_store import FilesystemStateStore


@pytest.mark.unit
class TestWriteStateLock:
    def test_write_state_creates_lock_sidecar(self, tmp_path: Path) -> None:
        store = FilesystemStateStore(workspace=tmp_path)
        store.write_state(StateDocument(version="2", customer_id="cid-1"))
        assert (tmp_path / "STATE.json.lock").exists()
        assert read_state_file(tmp_path / "STATE.json").customer_id == "cid-1"

    def test_concurrent_writes_produce_valid_document(self, tmp_path: Path) -> None:
        """Concurrent blind writes must never leave a torn/partial file: the
        result parses cleanly to one of the written documents."""
        store = FilesystemStateStore(workspace=tmp_path)
        n = 12
        barrier = threading.Barrier(n)

        def worker(i: int) -> None:
            barrier.wait()
            store.write_state(StateDocument(version="2", customer_id=f"cid-{i}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        doc = read_state_file(tmp_path / "STATE.json")
        assert doc.customer_id in {f"cid-{i}" for i in range(n)}
