"""Concurrency safety for credentials.json read-modify-write (M2).

``auth._save_meta_token`` (the background Meta 53-day auto-refresh) and
``auth_setup.save_credentials`` (the CLI / web setup wizard) each do
read -> mutate -> ``_atomic_write_json``. ``_atomic_write_json`` makes only the
file *replace* atomic; the surrounding read-modify-write is not. Run
concurrently they can last-writer-wins away each other's section (e.g. the
wizard re-auth dropping a just-refreshed access_token, or the refresh dropping
a freshly-saved google_ads block). Both paths now hold the same cross-process
``credentials.json.lock`` across the whole cycle.

The test instruments ``config_writer._load_existing`` /
``_atomic_write_json`` to count how many read-modify-write cycles are ever
in-flight at once and widens the window with a sleep. A correct lock keeps the
concurrency at exactly 1; removing the lock lets it climb past 1 and the test
fails. Mirrors ``tests/test_state_concurrency.py``.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

import mureo.providers.config_writer as config_writer
from mureo.auth import GoogleAdsCredentials, _save_meta_token
from mureo.auth_setup import save_credentials

if TYPE_CHECKING:
    from pathlib import Path

# Enough contention to surface an unguarded interleave; the injected delay
# makes it deterministic rather than timing-luck dependent.
_THREADS = 8
_PER_THREAD = 6
_SECTION_DELAY_S = 0.004


class _SectionMonitor:
    """Counts concurrently-active read-modify-write critical sections.

    ``load`` marks a section entered (and sleeps, widening the window);
    ``write`` marks it left. Under a correct lock at most one section is ever
    active, so ``max_active`` stays 1.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self.active = 0
        self.max_active = 0
        self._real_load = config_writer._load_existing
        self._real_write = config_writer._atomic_write_json

    def load(self, settings_path: Path) -> dict[str, Any]:
        data = self._real_load(settings_path)
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(_SECTION_DELAY_S)
        return data

    def write(self, payload: dict[str, Any], settings_path: Path) -> None:
        self._real_write(payload, settings_path)
        with self._guard:
            self.active -= 1


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch) -> _SectionMonitor:
    mon = _SectionMonitor()
    monkeypatch.setattr(config_writer, "_load_existing", mon.load)
    monkeypatch.setattr(config_writer, "_atomic_write_json", mon.write)
    return mon


def _google(tag: str) -> GoogleAdsCredentials:
    return GoogleAdsCredentials(
        developer_token=tag,
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )


@pytest.mark.unit
def test_meta_refresh_and_wizard_save_are_mutually_exclusive(
    tmp_path: Path, monitor: _SectionMonitor
) -> None:
    """A Meta auto-refresh and a wizard save never overlap their RMW, and
    neither section is lost — both end with a value a worker wrote."""
    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps(
            {
                "google_ads": {"developer_token": "SEED"},
                "meta_ads": {
                    "access_token": "SEED",
                    "app_id": "app",
                    "app_secret": "secret",
                },
            }
        ),
        encoding="utf-8",
    )

    def meta_worker(thread_id: int) -> None:
        for j in range(_PER_THREAD):
            _save_meta_token(
                cred_path, f"m-{thread_id}-{j}", "2026-07-18T00:00:00+00:00"
            )

    def google_worker(thread_id: int) -> None:
        for j in range(_PER_THREAD):
            save_credentials(path=cred_path, google=_google(f"g-{thread_id}-{j}"))

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        futures = [
            pool.submit(meta_worker if tid % 2 == 0 else google_worker, tid)
            for tid in range(_THREADS)
        ]
        for f in futures:
            f.result()

    # The read-modify-write cycles were serialised: never two at once.
    assert monitor.max_active == 1

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    # Neither section was clobbered back to (or stuck at) the seed value.
    assert data["meta_ads"]["access_token"].startswith("m-")
    assert data["google_ads"]["developer_token"].startswith("g-")
    # The section each worker type does not touch is preserved, not dropped.
    assert data["meta_ads"]["app_id"] == "app"


@pytest.mark.unit
def test_concurrent_meta_refreshes_never_overlap(
    tmp_path: Path, monitor: _SectionMonitor
) -> None:
    """Two config helpers on the same file contend for the same lock even when
    only ``_save_meta_token`` runs (built-in <-> built-in path)."""
    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps({"meta_ads": {"access_token": "SEED"}}), encoding="utf-8"
    )

    def worker(thread_id: int) -> None:
        for j in range(_PER_THREAD):
            _save_meta_token(
                cred_path, f"t-{thread_id}-{j}", "2026-07-18T00:00:00+00:00"
            )

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        list(pool.map(worker, range(_THREADS)))

    assert monitor.max_active == 1
    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["meta_ads"]["access_token"].startswith("t-")
