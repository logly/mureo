"""Unit tests for the Creative Studio output workspace helpers."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import TYPE_CHECKING

import pytest

from mureo.creative_studio.workspace import (
    create_run_dir,
    sha256_of,
    write_bytes,
    write_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_create_run_dir_is_unique_and_nested(tmp_path: Path) -> None:
    dirs = {create_run_dir(base=tmp_path) for _ in range(8)}
    assert len(dirs) == 8  # run ids never collide
    for run_dir in dirs:
        assert run_dir.is_dir()
        assert run_dir.parent == tmp_path
        # run_id = UTC timestamp + 6 hex chars
        assert run_dir.name.endswith(tuple("0123456789abcdef"))


@pytest.mark.unit
def test_create_run_dir_defaults_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = create_run_dir()
    assert run_dir.parent == tmp_path / "creative_studio"


@pytest.mark.unit
def test_write_manifest_round_trip(tmp_path: Path) -> None:
    run_dir = create_run_dir(base=tmp_path)
    data = {"run_id": run_dir.name, "files": [], "note": "日本語のメモ"}
    path = write_manifest(run_dir, data)
    assert path.name == "manifest.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == data
    # ensure_ascii=False keeps UTF-8 characters raw on disk.
    assert "日本語のメモ" in path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello world")
    assert sha256_of(p) == hashlib.sha256(b"hello world").hexdigest()


@pytest.mark.unit
def test_write_bytes_creates_file(tmp_path: Path) -> None:
    run_dir = create_run_dir(base=tmp_path)
    path = write_bytes(run_dir / "a.png", b"payload")
    assert path.read_bytes() == b"payload"


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_permissions(tmp_path: Path) -> None:
    run_dir = create_run_dir(base=tmp_path)
    assert (run_dir.stat().st_mode & 0o777) == 0o755
    manifest = write_manifest(run_dir, {"a": 1})
    assert (manifest.stat().st_mode & 0o777) == 0o644
    img = write_bytes(run_dir / "b.png", b"x")
    assert (img.stat().st_mode & 0o777) == 0o644
