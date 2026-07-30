"""Unit tests for ``mureo.core.atomic_json`` (#500).

The fail-closed reader / atomic writer used to be private to
``mureo.providers.config_writer`` while four unrelated writers
(credentials.json, the Amazon tool manifest, insight_sources.json,
~/.claude.json) depended on it. These tests pin the public contract
directly — round trip, ``0o600`` + fsync + same-directory replace, and
fail-closed reads — plus the backwards-compatible aliases the old module
still exposes.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mureo.core.atomic_json import (
    ConfigWriteError,
    atomic_write_json,
    load_existing_json,
)

pytestmark = pytest.mark.unit


class TestLoadExistingJson:
    """Reads are fail-closed: ``{}`` only ever means "file is absent"."""

    def test_absent_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert load_existing_json(tmp_path / "nope.json") == {}

    def test_reads_an_existing_object(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"a": {"b": 1}}), encoding="utf-8")

        assert load_existing_json(path) == {"a": {"b": 1}}

    def test_malformed_json_raises_and_names_the_path(self, tmp_path: Path) -> None:
        """A corrupt file must never read as ``{}`` — that is how a
        single-section write erased every other provider's credentials."""
        path = tmp_path / "credentials.json"
        path.write_text('{"google_ads": {,,,', encoding="utf-8")

        with pytest.raises(ConfigWriteError) as exc_info:
            load_existing_json(path)

        assert str(path) in str(exc_info.value)

    def test_non_object_top_level_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

        with pytest.raises(ConfigWriteError) as exc_info:
            load_existing_json(path)

        assert "list" in str(exc_info.value)


class TestAtomicWriteJson:
    """Writes are atomic, owner-only and leave no debris."""

    def test_round_trip_through_the_loader(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "config.json"
        payload: dict[str, Any] = {"amazon_ads": {"region": "eu"}, "n": [1, 2]}

        atomic_write_json(payload, path)

        assert load_existing_json(path) == payload
        # Parent directories are created on demand.
        assert path.parent.is_dir()

    def test_replaces_from_a_same_directory_tmp_file(self, tmp_path: Path) -> None:
        """``os.replace`` is a rename inside the target's own directory, so
        it is atomic on POSIX (a cross-filesystem move would not be)."""
        path = tmp_path / "config.json"
        captured: dict[str, Any] = {}
        real_replace = os.replace

        def _spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            captured["src"] = os.fspath(src)
            captured["dst"] = os.fspath(dst)
            real_replace(src, dst)

        with patch("mureo.core.atomic_json.os.replace", side_effect=_spy):
            atomic_write_json({"a": 1}, path)

        src = Path(captured["src"])
        assert Path(captured["dst"]) == path
        assert src.parent == path.parent
        assert ".tmp" in src.name
        assert list(path.parent.glob("*.tmp*")) == []

    def test_tmp_file_is_mode_0600_before_the_rename(self, tmp_path: Path) -> None:
        """Permissions are restricted BEFORE the data lands, so the file is
        never world-readable during the write/replace window."""
        if os.name != "posix":
            pytest.skip("file-mode check only meaningful on POSIX")

        path = tmp_path / "credentials.json"
        captured: dict[str, Any] = {}
        real_replace = os.replace

        def _spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            captured["mode"] = stat.S_IMODE(os.stat(src).st_mode)
            real_replace(src, dst)

        with patch("mureo.core.atomic_json.os.replace", side_effect=_spy):
            atomic_write_json({"secret": "x"}, path)

        assert captured["mode"] == 0o600

    def test_data_is_fsynced_before_the_rename(self, tmp_path: Path) -> None:
        """The payload is durably on disk before the directory entry flips,
        so a crash mid-write cannot leave a truncated config."""
        path = tmp_path / "config.json"
        events: list[str] = []
        real_fsync = os.fsync
        real_replace = os.replace

        def _spy_fsync(fd: int) -> None:
            events.append("fsync")
            real_fsync(fd)

        def _spy_replace(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            events.append("replace")
            real_replace(src, dst)

        with (
            patch("mureo.core.atomic_json.os.fsync", side_effect=_spy_fsync),
            patch("mureo.core.atomic_json.os.replace", side_effect=_spy_replace),
        ):
            atomic_write_json({"a": 1}, path)

        # Data fsync, then the rename (the trailing directory fsync that
        # makes the rename itself durable is best-effort, so it is not
        # asserted on).
        assert events[:2] == ["fsync", "replace"]

    def test_failed_replace_leaves_the_original_intact(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"keep": True}), encoding="utf-8")
        pre_bytes = path.read_bytes()

        def _boom(src: Any, dst: Any) -> None:
            raise OSError("simulated atomic replace failure")

        with (
            patch("mureo.core.atomic_json.os.replace", side_effect=_boom),
            pytest.raises(OSError),
        ):
            atomic_write_json({"clobbered": True}, path)

        assert path.read_bytes() == pre_bytes
        assert list(path.parent.glob("*.tmp*")) == []


class TestConfigWriterAliasesAreTheSameObjects:
    """``config_writer`` keeps its old import surface after the move.

    Existing importers — and tests that monkeypatch the private names —
    must keep resolving to the objects that now live in
    :mod:`mureo.core.atomic_json`, not to stale copies.
    """

    def test_private_aliases_resolve_to_the_public_functions(self) -> None:
        from mureo.providers import config_writer

        assert config_writer._load_existing is load_existing_json
        assert config_writer._atomic_write_json is atomic_write_json

    def test_config_write_error_is_the_same_class(self) -> None:
        from mureo.providers import config_writer

        assert config_writer.ConfigWriteError is ConfigWriteError
