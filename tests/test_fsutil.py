"""Cross-platform secure-permission helpers (TDD).

`os.fchmod` is Unix-only — calling it on Windows raises
`AttributeError`, which previously crashed every credential / config
write path. These helpers apply 0600 on POSIX and degrade to a
best-effort no-op on Windows (or any platform where the perm op is
unavailable), never raising.
"""

from __future__ import annotations

import os
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mureo.fsutil import file_lock, secure_chmod, secure_fchmod

# POSIX file-mode assertions: on Windows chmod cannot set 0o600 — the
# helpers are best-effort there (the never-raise contract is verified
# by the Windows-path tests below). Skip the mode assertions on win32.
_posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX file-mode semantics; Windows secure_* is best-effort",
)


@pytest.mark.unit
class TestSecureFchmod:
    @_posix_only
    def test_posix_sets_0600(self, tmp_path: Path) -> None:
        p = tmp_path / "f"
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT, 0o666)
        try:
            secure_fchmod(fd)
        finally:
            os.close(fd)
        assert stat.S_IMODE(p.stat().st_mode) == 0o600

    def test_no_fchmod_attr_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate Windows: os has no `fchmod`.
        monkeypatch.delattr(os, "fchmod", raising=False)
        p = tmp_path / "f"
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT, 0o666)
        try:
            secure_fchmod(fd)  # must not raise
        finally:
            os.close(fd)

    def test_oserror_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_fd: int, _mode: int) -> None:
            raise OSError("unsupported")

        monkeypatch.setattr(os, "fchmod", _boom, raising=False)
        secure_fchmod(123)  # must not raise


@pytest.mark.unit
class TestSecureChmod:
    @_posix_only
    def test_posix_sets_0600(self, tmp_path: Path) -> None:
        p = tmp_path / "f"
        p.write_text("x")
        p.chmod(0o644)
        secure_chmod(p)
        assert stat.S_IMODE(p.stat().st_mode) == 0o600

    @_posix_only
    def test_accepts_str_path(self, tmp_path: Path) -> None:
        p = tmp_path / "f"
        p.write_text("x")
        secure_chmod(str(p))
        assert stat.S_IMODE(p.stat().st_mode) == 0o600

    def test_error_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_p: object, _mode: int) -> None:
            raise NotImplementedError  # e.g. some Windows filesystems

        monkeypatch.setattr(os, "chmod", _boom)
        secure_chmod("/nonexistent/whatever")  # must not raise

    def test_missing_path_does_not_raise(self, tmp_path: Path) -> None:
        secure_chmod(tmp_path / "does-not-exist")  # OSError swallowed


@pytest.mark.unit
class TestFileLock:
    def test_serialises_concurrent_critical_sections(self, tmp_path: Path) -> None:
        """Two threads running a deliberately non-atomic read-modify-write of a
        shared file never lose an update when the section is held under the
        lock — the mutual-exclusion contract the STATE.json mutators rely on."""
        lock = tmp_path / "counter.lock"
        counter = tmp_path / "counter.txt"
        counter.write_text("0", encoding="utf-8")

        def bump(_: int) -> None:
            with file_lock(lock):
                value = int(counter.read_text(encoding="utf-8"))
                time.sleep(0.002)  # widen the window an unguarded RMW would lose
                counter.write_text(str(value + 1), encoding="utf-8")

        rounds = 40
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(bump, range(rounds)))

        assert int(counter.read_text(encoding="utf-8")) == rounds

    def test_released_after_context_exit(self, tmp_path: Path) -> None:
        """Sequential acquisitions of the same lock do not deadlock — the lock
        is released on context exit."""
        lock = tmp_path / "x.lock"
        for _ in range(3):
            with file_lock(lock):
                pass

    def test_creates_sidecar_file(self, tmp_path: Path) -> None:
        lock = tmp_path / "s.lock"
        assert not lock.exists()
        with file_lock(lock):
            assert lock.exists()

    def test_windows_path_calls_msvcrt_blocking_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Windows branch must call ``msvcrt.locking`` with the real
        blocking/unlock constants. Exercised on POSIX by faking ``msvcrt`` and
        disabling ``fcntl`` — the only coverage of that branch, guarding
        against constant typos (e.g. the non-existent ``LK_LCK``)."""
        calls: list[tuple[int, int]] = []

        class _FakeMsvcrt:
            LK_LOCK = 1
            LK_UNLCK = 0

            def locking(self, _fd: int, mode: int, nbytes: int) -> None:
                calls.append((mode, nbytes))

        fake = _FakeMsvcrt()
        monkeypatch.setattr("mureo.fsutil._fcntl", None)
        monkeypatch.setattr("mureo.fsutil._msvcrt", fake)

        with file_lock(tmp_path / "w.lock"):
            pass

        assert (fake.LK_LOCK, 1) in calls  # acquire used the blocking lock
        assert (fake.LK_UNLCK, 1) in calls  # release used the unlock
