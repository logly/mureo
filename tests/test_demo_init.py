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


@pytest.fixture(autouse=True)
def byod_root(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` so BYOD writes land in a sandbox.

    Autouse because ``materialize()`` now auto-imports the bundle into
    ``~/.mureo/byod/`` by default — every test in this module needs a
    sandboxed home or it would clobber the developer's real BYOD data.
    Mirrors the pattern in ``tests/test_byod_bundle.py``.
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

    def _boom(path, scenario):  # pragma: no cover - injected failure
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
    """Default README describes the 1-step quickstart (no manual import)."""
    target = tmp_path / "mureo-demo"
    materialize(target)
    text = (target / "README.md").read_text(encoding="utf-8")
    assert "/daily-check" in text
    assert "Claude Code" in text
    # The default flow auto-imports, so the manual import command must
    # NOT appear in the default README — that copy is reserved for the
    # --skip-import variant only.
    assert "mureo byod import" not in text


def test_readme_skip_import_variant_documents_manual_import(tmp_path: Path) -> None:
    """``--skip-import`` README still documents the manual import step."""
    target = tmp_path / "mureo-demo"
    materialize(target, skip_import=True)
    text = (target / "README.md").read_text(encoding="utf-8")
    assert "mureo byod import" in text
    assert "bundle.xlsx" in text


def test_materialize_writes_state_json(tmp_path: Path) -> None:
    """STATE.json (v2 platforms shape) is written alongside the bundle.

    /daily-check and the other workflow skills require STATE.json — if
    the demo only shipped bundle.xlsx the user would have to run
    /onboard manually before any skill could read campaign metadata.
    """
    target = tmp_path / "demo"
    materialize(target)

    state_path = target / "STATE.json"
    assert state_path.is_file()

    doc = json.loads(state_path.read_text(encoding="utf-8"))
    assert doc["version"] == "2"
    assert "platforms" in doc
    assert "google_ads" in doc["platforms"]
    assert "meta_ads" in doc["platforms"]

    gads = doc["platforms"]["google_ads"]["campaigns"]
    meta = doc["platforms"]["meta_ads"]["campaigns"]
    assert gads, "google_ads campaigns must not be empty"
    assert meta, "meta_ads campaigns must not be empty"
    for camp in list(gads) + list(meta):
        assert camp["campaign_id"].startswith("camp_")
        assert camp["campaign_name"]
        assert camp["status"]


def test_materialize_auto_imports_bundle(tmp_path: Path) -> None:
    """``materialize`` populates ``~/.mureo/byod/`` so /daily-check works.

    Replaces the v1 round-trip test — the round-trip is now exercised
    by materialize itself rather than by a separate import_bundle call.
    """
    from mureo.byod.runtime import byod_active_platforms

    target = tmp_path / "demo"
    materialize(target)

    active = byod_active_platforms()
    assert "google_ads" in active
    assert "meta_ads" in active


def test_materialize_skip_import_leaves_byod_untouched(tmp_path: Path) -> None:
    """``--skip-import`` writes the demo files but does NOT touch BYOD.

    STATE.json is intentionally NOT written because its campaign_ids
    would refer to BYOD CSV rows that don't exist yet — shipping it
    would mislead any skill the user runs before doing the manual
    ``mureo byod import``.
    """
    from mureo.byod.runtime import byod_active_platforms

    target = tmp_path / "demo"
    materialize(target, skip_import=True)

    assert (target / "bundle.xlsx").is_file()
    assert not (
        target / "STATE.json"
    ).exists(), "skip_import must not ship STATE.json — see installer.py docstring"
    assert byod_active_platforms() == []


def test_materialize_idempotent_re_run(tmp_path: Path) -> None:
    """Re-running ``mureo demo init`` against an existing demo is a no-op-ish.

    Pins the contract that prior-demo BYOD data is not treated as a
    conflict — the user shouldn't need ``--force`` just to refresh
    the demo. Real (non-demo) BYOD data still requires --force; that
    is covered by ``test_materialize_refuses_existing_byod_without_force``.
    """
    from mureo.byod.runtime import byod_active_platforms

    target = tmp_path / "demo"
    materialize(target)
    materialize(target)  # must succeed without --force

    active = byod_active_platforms()
    assert "google_ads" in active
    assert "meta_ads" in active


def test_materialize_refuses_existing_byod_without_force(tmp_path: Path) -> None:
    """Real (non-demo) BYOD data conflicts → refuse without ``--force``.

    Pins the safety contract: when the user already has BYOD data
    from a real ``mureo byod import <their-bundle>.xlsx``, a demo
    init without ``--force`` must refuse rather than silently
    replace their data. (Prior-demo conflicts are intentionally
    benign — covered by ``test_materialize_idempotent_re_run``.)
    """
    from mureo.byod.runtime import write_manifest

    # Fake a manifest entry that looks like a real (non-demo) import
    # — ``source_filename`` is the discriminator that distinguishes
    # demo bundles from user-supplied ones.
    write_manifest(
        {
            "schema_version": 1,
            "imported_on": "2026-04-29T00:00:00+09:00",
            "platforms": {
                "google_ads": {
                    "files": ["campaigns.csv"],
                    "date_range": {"start": "", "end": ""},
                    "rows": 0,
                    "campaigns": 0,
                    "ad_groups": 0,
                    "source_format": "real_user_bundle_v1",
                    "imported_at": "2026-04-29T00:00:00+09:00",
                    "source_file_sha256": "deadbeef",
                    "source_filename": "real-account-export.xlsx",
                }
            },
        }
    )

    with pytest.raises(DemoInitError) as excinfo:
        materialize(tmp_path / "demo")
    msg = str(excinfo.value).lower()
    assert "byod" in msg or "already" in msg


def test_materialize_force_replaces_existing_byod(tmp_path: Path) -> None:
    """``--force`` clears the BYOD conflict and re-imports cleanly."""
    from mureo.byod.runtime import byod_active_platforms

    materialize(tmp_path / "first")
    materialize(tmp_path / "second", force=True)

    active = byod_active_platforms()
    assert "google_ads" in active
    assert "meta_ads" in active


def test_state_campaign_ids_match_byod_csv(tmp_path: Path) -> None:
    """STATE.json campaign_ids must equal the BYOD adapter's synthesized ids.

    /daily-check, /search-term-cleanup, /budget-rebalance all join
    STATE.json campaign metadata with BYOD performance data on
    ``campaign_id``. If the IDs diverge by even one character the
    skills can't correlate the two — which is exactly the bug the
    demo flow needs to avoid.
    """
    import csv as _csv
    from pathlib import Path as _Path

    target = tmp_path / "demo"
    materialize(target)

    state = json.loads((target / "STATE.json").read_text(encoding="utf-8"))
    byod_root = _Path.home() / ".mureo" / "byod"

    # The Google Ads adapter writes the CSV column as ``name`` (not
    # ``campaign_name``); see ``mureo/byod/adapters/google_ads.py:221``.
    # The Meta Ads adapter mirrors that convention.
    for platform in ("google_ads", "meta_ads"):
        state_ids = {
            c["campaign_name"]: c["campaign_id"]
            for c in state["platforms"][platform]["campaigns"]
        }
        csv_path = byod_root / platform / "campaigns.csv"
        with csv_path.open(encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        csv_ids = {row["name"]: row["campaign_id"] for row in rows}

        for name, sid in state_ids.items():
            assert csv_ids.get(name) == sid, (
                f"{platform}: campaign_id mismatch for {name!r}: "
                f"STATE.json={sid!r} vs BYOD csv={csv_ids.get(name)!r}"
            )


def test_cli_demo_init_skip_import_flag(tmp_path: Path) -> None:
    """``mureo demo init --skip-import`` works end-to-end via Typer."""
    from mureo.byod.runtime import byod_active_platforms

    target = tmp_path / "demo"
    result = runner.invoke(app, ["demo", "init", str(target), "--skip-import"])
    assert result.exit_code == 0, result.stdout
    assert (target / "bundle.xlsx").is_file()
    assert byod_active_platforms() == []


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
