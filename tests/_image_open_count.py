"""Count how often a local image file is opened (#1011).

Not a test module (no ``test_`` prefix). Shared by the tests that hold an
upload to one read of the file it sends.

Three ways of opening a path are counted: ``os.open`` (the descriptor
``read_image_file`` opens), ``Path.open`` (which ``Path.read_bytes`` and
``Path.read_text`` go through) and the builtin ``open``. Counting opens of
the one path under test keeps the assertion independent of how many other
files the interpreter happens to touch.
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from typing import Any

import pytest

from mureo import _image_validation

#: What one bounded read through ``read_image_file`` looks like.
OPENED_ONCE = {"os.open": 1, "Path.open": 0, "open": 0}


def _count_opens(monkeypatch: pytest.MonkeyPatch, target: Path) -> dict[str, int]:
    counts = {"os.open": 0, "Path.open": 0, "open": 0}
    real_os_open = os.open
    real_path_open = Path.open
    real_open = builtins.open

    def counting_os_open(path: Any, flags: int, *args: Any) -> int:
        if str(path) == str(target):
            counts["os.open"] += 1
        return real_os_open(path, flags, *args)

    def counting_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if str(self) == str(target):
            counts["Path.open"] += 1
        return real_path_open(self, *args, **kwargs)

    def counting_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if str(file) == str(target):
            counts["open"] += 1
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(_image_validation.os, "open", counting_os_open)
    monkeypatch.setattr(Path, "open", counting_path_open)
    monkeypatch.setattr(builtins, "open", counting_open)
    return counts
