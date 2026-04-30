"""Tests for ``mureo demo init`` — the zero-friction demo bootstrap.

The demo flow materializes a self-contained directory with a synthetic
XLSX bundle, a STRATEGY.md seed, a Claude Code ``.mcp.json`` snippet
and a README. The goal is parity-of-experience with BYOD without the
user having to download their real ad data first.

Coverage:
  - ``materialize`` writes the four expected artifacts
  - refuses an existing non-empty target unless ``force=True``
  - empty target dir is OK
  - the generated bundle parses cleanly through the existing BYOD
    pipeline (both google_ads and meta_ads land)
  - .mcp.json registers a stdio mureo MCP server
  - STRATEGY.md is non-empty and looks like markdown
  - CLI ``mureo demo init`` works end-to-end via the typer runner
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mureo.cli.main import app
from mureo.demo.installer import DemoInitError, materialize

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def byod_root(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` so BYOD writes land in a sandbox.

    Mirrors the pattern used by ``tests/test_byod_bundle.py`` so the
    demo-bundle round-trip test does not touch the real ``~/.mureo``.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    return fake_home


# ---------------------------------------------------------------------------
# materialize() — direct unit tests
# ---------------------------------------------------------------------------


def test_materialize_creates_expected_files(tmp_path: Path) -> None:
    target = tmp_path / "mureo-demo"
    materialize(target)

    assert (target / "bundle.xlsx").is_file()
    assert (target / "STRATEGY.md").is_file()
    assert (target / ".mcp.json").is_file()
    assert (target / "README.md").is_file()


def test_materialize_creates_target_dir_if_missing(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "mureo-demo"
    materialize(target)
    assert target.is_dir()
    assert (target / "bundle.xlsx").is_file()


def test_materialize_refuses_existing_non_empty_dir(tmp_path: Path) -> None:
    target = tmp_path / "mureo-demo"
    target.mkdir()
    (target / "junk").write_text("hi")
    with pytest.raises(DemoInitError):
        materialize(target)


def test_materialize_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "mureo-demo"
    target.mkdir()
    (target / "bundle.xlsx").write_text("stale")
    materialize(target, force=True)
    # The new file should be a real xlsx (zip magic), not the stub text.
    assert (target / "bundle.xlsx").read_bytes()[:2] == b"PK"


def test_materialize_empty_existing_dir_ok(tmp_path: Path) -> None:
    target = tmp_path / "mureo-demo"
    target.mkdir()
    materialize(target)
    assert (target / "bundle.xlsx").is_file()


def test_materialize_refuses_target_that_is_a_file(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.write_text("not a directory")
    with pytest.raises(DemoInitError):
        materialize(target)


def test_materialize_force_preserves_unrelated_files(tmp_path: Path) -> None:
    """``--force`` must not delete anything outside ``_DEMO_FILES``.

    Pins the contract so a future refactor cannot introduce a
    ``shutil.rmtree`` cleanup that wipes user data sitting next to
    where they pointed ``mureo demo init``.
    """
    target = tmp_path / "demo"
    target.mkdir()
    (target / ".env").write_text("SECRET=keep-me", encoding="utf-8")
    sub = target / "src"
    sub.mkdir()
    (sub / "app.py").write_text("print('hi')\n", encoding="utf-8")

    materialize(target, force=True)

    assert (target / ".env").read_text(encoding="utf-8") == "SECRET=keep-me"
    assert (sub / "app.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert (target / "bundle.xlsx").is_file()


def test_materialize_wraps_filesystem_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError mid-write is surfaced as DemoInitError.

    Simulates the symlink-loop / permission-denied / ENOSPC case so
    the CLI prints a clean one-liner instead of a stack trace.
    """
    target = tmp_path / "demo"

    def _boom(path):  # pragma: no cover - injected failure
        raise OSError("simulated disk failure")

    monkeypatch.setattr("mureo.demo.installer.build_bundle", _boom)

    with pytest.raises(DemoInitError) as excinfo:
        materialize(target)
    assert "simulated disk failure" in str(excinfo.value)


def test_mcp_json_registers_mureo_server(tmp_path: Path) -> None:
    target = tmp_path / "mureo-demo"
    materialize(target)
    config = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert "mcpServers" in config
    assert "mureo" in config["mcpServers"]
    server = config["mcpServers"]["mureo"]
    assert server["type"] == "stdio"
    assert isinstance(server["command"], str) and server["command"]


def test_strategy_md_is_seeded_markdown(tmp_path: Path) -> None:
    target = tmp_path / "mureo-demo"
    materialize(target)
    text = (target / "STRATEGY.md").read_text(encoding="utf-8")
    assert text.strip()
    # Looks like markdown with at least one heading.
    assert "#" in text


def test_readme_contains_quickstart_steps(tmp_path: Path) -> None:
    target = tmp_path / "mureo-demo"
    materialize(target)
    text = (target / "README.md").read_text(encoding="utf-8")
    assert "mureo byod import" in text
    assert "bundle.xlsx" in text


def test_bundle_imports_via_byod_pipeline(tmp_path: Path, byod_root) -> None:
    """End-to-end: the demo bundle is consumable by ``import_bundle``.

    Contract: the bundle must round-trip through the same pipeline real
    BYOD users go through, so any divergence between the demo data
    shape and production schemas is caught here.
    """
    from mureo.byod.bundle import import_bundle

    target = tmp_path / "mureo-demo"
    materialize(target)

    results = import_bundle(target / "bundle.xlsx")
    assert "google_ads" in results
    assert "meta_ads" in results
    assert results["google_ads"]["rows"] > 0
    assert results["meta_ads"]["rows"] > 0


# ---------------------------------------------------------------------------
# CLI integration via Typer's CliRunner
# ---------------------------------------------------------------------------


def test_cli_demo_init_creates_artifacts(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    result = runner.invoke(app, ["demo", "init", str(target)])
    assert result.exit_code == 0, result.stdout
    assert (target / "bundle.xlsx").is_file()
    assert (target / ".mcp.json").is_file()


def test_cli_demo_init_refuses_non_empty_without_force(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "junk").write_text("x")
    result = runner.invoke(app, ["demo", "init", str(target)])
    assert result.exit_code != 0


def test_cli_demo_init_force_overrides(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "junk").write_text("x")
    result = runner.invoke(app, ["demo", "init", str(target), "--force"])
    assert result.exit_code == 0, result.stdout
    assert (target / "bundle.xlsx").is_file()
