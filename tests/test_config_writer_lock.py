"""Regression tests: ~/.claude.json read-modify-write is process/thread safe.

``add_provider_to_claude_settings`` / ``remove_provider_from_claude_settings``
run their file-mode read -> modify -> write inside ``fsutil.file_lock`` so two
concurrent provider edits cannot last-writer-wins away each other's
``mcpServers`` change. The file is shared with Claude Code itself; the lock is
advisory but protects mureo's own concurrent writers.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from mureo.providers.config_writer import (
    add_provider_to_claude_settings,
    remove_provider_from_claude_settings,
)


def _make_spec(spec_id: str) -> Any:
    from mureo.providers.catalog import ProviderSpec

    return ProviderSpec(
        id=spec_id,
        display_name=spec_id,
        install_kind="pipx",
        install_argv=("pipx", "run", "some-mcp"),
        mcp_server_config={"command": "pipx", "args": ["run", spec_id]},
        required_env=(),
        notes="",
        coexists_with_mureo_platform=None,
    )


@pytest.mark.unit
class TestConfigWriterLock:
    def test_concurrent_adds_no_lost_update(self, tmp_path: Path) -> None:
        target = tmp_path / ".claude.json"
        # Seed with the native mureo entry to prove coexistence survives.
        target.write_text(
            json.dumps({"mcpServers": {"mureo": {"command": "mureo"}}}),
            encoding="utf-8",
        )
        n = 10
        barrier = threading.Barrier(n)

        def worker(i: int) -> None:
            barrier.wait()
            add_provider_to_claude_settings(
                _make_spec(f"prov-{i}"), settings_path=target
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        loaded = json.loads(target.read_text(encoding="utf-8"))
        servers = loaded["mcpServers"]
        # Every concurrently-added provider survived...
        for i in range(n):
            assert f"prov-{i}" in servers
        # ...and the pre-existing native entry was preserved.
        assert "mureo" in servers

    def test_concurrent_add_and_remove_consistent(self, tmp_path: Path) -> None:
        target = tmp_path / ".claude.json"
        target.write_text(
            json.dumps(
                {"mcpServers": {"mureo": {"command": "mureo"}, "old": {"command": "x"}}}
            ),
            encoding="utf-8",
        )
        barrier = threading.Barrier(2)

        def adder() -> None:
            barrier.wait()
            add_provider_to_claude_settings(_make_spec("new"), settings_path=target)

        def remover() -> None:
            barrier.wait()
            remove_provider_from_claude_settings("old", settings_path=target)

        t1 = threading.Thread(target=adder)
        t2 = threading.Thread(target=remover)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        servers = json.loads(target.read_text(encoding="utf-8"))["mcpServers"]
        assert "new" in servers  # add survived
        assert "old" not in servers  # remove took effect
        assert "mureo" in servers  # native entry preserved
