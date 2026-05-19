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
import tempfile
from pathlib import Path

import pytest

from mureo.fsutil import secure_chmod, secure_fchmod


@pytest.mark.unit
class TestSecureFchmod:
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
    def test_posix_sets_0600(self, tmp_path: Path) -> None:
        p = tmp_path / "f"
        p.write_text("x")
        p.chmod(0o644)
        secure_chmod(p)
        assert stat.S_IMODE(p.stat().st_mode) == 0o600

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
