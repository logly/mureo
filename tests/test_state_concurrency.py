"""Concurrency safety for STATE.json read-modify-write mutators (issue #115).

``append_action_log`` / ``upsert_campaign`` each do read -> rebuild ->
``write_state_file``. ``_atomic_write`` makes the file *replace* atomic, but the
surrounding read-modify-write is NOT a critical section: two concurrent
mutating calls (built-in <-> built-in, or built-in <-> plugin dispatch) can
lose an entry under last-writer-wins on the whole ``StateDocument``.

These tests deterministically widen the read->write window (a monkeypatched
slow ``read_state_file``) so the race is exercised every run, then assert no
``action_log`` entry is ever dropped under thread contention — across the
single-mutator path and the mixed ``upsert_campaign`` + ``append_action_log``
path.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import mureo.context.state as state_mod
from mureo.context.models import ActionLogEntry, CampaignSnapshot
from mureo.context.state import append_action_log, read_state_file, upsert_campaign

# Enough contention to surface the race; the injected delay (below) makes it
# deterministic rather than timing-luck dependent.
_THREADS = 8
_PER_THREAD = 10
_READ_DELAY_S = 0.003


@pytest.fixture
def slow_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Widen the read->write window so the RMW race is hit every run.

    The delay sits *inside* whatever critical section the fix introduces, so a
    correct lock serialises the slow read and still drops nothing; the
    unguarded code interleaves and loses entries.
    """
    real_read = state_mod.read_state_file

    def _slow(path: Path) -> object:
        doc = real_read(path)
        time.sleep(_READ_DELAY_S)
        return doc

    monkeypatch.setattr(state_mod, "read_state_file", _slow)


def _entry(tag: str) -> ActionLogEntry:
    return ActionLogEntry(
        timestamp="2026-06-15T00:00:00+00:00",
        action="test",
        platform="google_ads",
        summary=tag,
    )


@pytest.mark.unit
def test_concurrent_append_action_log_drops_no_entries(
    tmp_path: Path, slow_read: None
) -> None:
    path = tmp_path / "STATE.json"

    def worker(thread_id: int) -> None:
        for j in range(_PER_THREAD):
            append_action_log(path, _entry(f"t{thread_id}-{j}"))

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        list(pool.map(worker, range(_THREADS)))

    doc = read_state_file(path)
    summaries = [e.summary for e in doc.action_log]
    assert len(summaries) == _THREADS * _PER_THREAD
    # Every append is unique-tagged: no entry was overwritten/lost.
    assert len(set(summaries)) == _THREADS * _PER_THREAD


@pytest.mark.unit
def test_concurrent_mixed_mutators_preserve_action_log(
    tmp_path: Path, slow_read: None
) -> None:
    """``upsert_campaign`` and ``append_action_log`` share the whole-doc RMW, so
    an unguarded ``upsert_campaign`` can clobber a concurrent log append. The
    lock must cover both mutators."""
    path = tmp_path / "STATE.json"

    def appender(thread_id: int) -> None:
        for j in range(_PER_THREAD):
            append_action_log(path, _entry(f"a{thread_id}-{j}"))

    def upserter(thread_id: int) -> None:
        for j in range(_PER_THREAD):
            upsert_campaign(
                path,
                CampaignSnapshot(
                    campaign_id=f"c{thread_id}-{j}",
                    campaign_name="x",
                    status="ENABLED",
                ),
                platform="google_ads",
                account_id="acct-1",
            )

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        futures = []
        for tid in range(_THREADS):
            target = appender if tid % 2 == 0 else upserter
            futures.append(pool.submit(target, tid))
        for f in futures:
            f.result()

    doc = read_state_file(path)
    appends = _THREADS // 2 * _PER_THREAD
    upserts = _THREADS // 2 * _PER_THREAD
    assert len(doc.action_log) == appends
    assert len(doc.campaigns) == upserts
