"""``read_data_file``: a local text file read the way ``read_image_file`` reads.

The same path rules and error types as the image read, one open, the type and
size judged on the open descriptor, and a read that stops one byte past the
cap, so the bytes returned are the bytes a caller parses. No image probing.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from mureo import _image_validation
from mureo._image_validation import read_data_file

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_EXTS = frozenset({"txt", "csv"})


def _read(path: Path, *, max_size_bytes: int = 1024) -> tuple[Path, bytes]:
    return read_data_file(
        str(path),
        max_size_bytes=max_size_bytes,
        max_size_label=f"{max_size_bytes}B",
        allowed_extensions=_EXTS,
    )


@pytest.mark.parametrize("name", ["list.txt", "list.csv", "LIST.TXT"])
def test_returns_the_path_and_the_bytes(tmp_path: Path, name: str) -> None:
    data = b"a@example.com\nb@example.com\n"
    path = tmp_path / name
    path.write_bytes(data)
    found, content = _read(path)
    assert found == path
    assert content == data


def test_the_content_is_not_probed(tmp_path: Path) -> None:
    """A PNG signature in a .txt file is just bytes here."""
    path = tmp_path / "list.txt"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert _read(path)[1] == b"\x89PNG\r\n\x1a\n"


def test_the_size_cap_is_inclusive(tmp_path: Path) -> None:
    path = tmp_path / "list.txt"
    path.write_bytes(b"x" * 10)
    assert _read(path, max_size_bytes=10)[1] == b"x" * 10
    with pytest.raises(ValueError, match="File size exceeds the limit"):
        _read(path, max_size_bytes=9)


def test_the_read_itself_is_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "growing.txt"
    path.write_bytes(b"x" * 100)
    real_fstat = os.fstat
    real_stat = _image_validation.Path.stat

    def small(st: os.stat_result) -> os.stat_result:
        fields = list(st)
        fields[6] = 1  # st_size
        return os.stat_result(fields)

    monkeypatch.setattr(_image_validation.os, "fstat", lambda fd: small(real_fstat(fd)))
    monkeypatch.setattr(
        _image_validation.Path,
        "stat",
        lambda self, **kw: small(real_stat(self, **kw)),
    )
    with pytest.raises(ValueError, match="File size exceeds the limit"):
        _read(path, max_size_bytes=50)


def test_the_path_rules_of_the_image_read(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _read(tmp_path / "missing.txt")
    with pytest.raises(ValueError, match="must not contain"):
        _read(tmp_path / ".." / "x.txt")
    other = tmp_path / "list.json"
    other.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported data format"):
        _read(other)
    folder = tmp_path / "folder.txt"
    folder.mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        _read(folder)


def test_the_open_descriptor_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available on this platform")
    real = tmp_path / "real.txt"
    real.write_bytes(b"a@example.com\n")
    fifo = tmp_path / "pipe.txt"
    os.mkfifo(fifo)
    real_open = os.open

    def swapped_open(path: object, flags: int, *args: object) -> int:
        return real_open(fifo if str(path).endswith("real.txt") else path, flags)

    monkeypatch.setattr(_image_validation.os, "open", swapped_open)
    with pytest.raises(ValueError, match="not a regular file"):
        _read(real)


def test_no_content_appears_in_a_size_error(tmp_path: Path) -> None:
    path = tmp_path / "list.txt"
    path.write_bytes(b"SENTINEL-CONTENT@example.com\n" * 4)
    with pytest.raises(ValueError) as info:
        _read(path, max_size_bytes=10)
    assert "SENTINEL-CONTENT" not in str(info.value)
