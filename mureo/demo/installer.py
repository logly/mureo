"""Materialize the ``mureo demo init`` artifacts on disk.

The installer writes the demo files for a chosen :class:`Scenario`
into a target directory and (by default) imports the bundle into
``~/.mureo/byod/`` so the workflow skills are immediately usable.

Artifacts written:

  bundle.xlsx     — synthetic Google Ads + Meta Ads bundle, content
                    sourced from the resolved scenario
                    (see :mod:`mureo.demo.scenarios`)
  STRATEGY.md     — scenario-specific STRATEGY.md text
  STATE.json      — v2 STATE.json with per-platform campaigns and a
                    seeded ``action_log``; omitted under
                    ``--skip-import`` (its IDs would point at empty
                    BYOD storage)
  .mcp.json       — Claude Code MCP server registration for the
                    ``mureo`` stdio server
  README.md       — quickstart instructions
"""

from __future__ import annotations

import json
from pathlib import Path

from mureo.byod.bundle import BundleImportError, import_bundle
from mureo.byod.runtime import byod_platform_info
from mureo.demo.builder import build_bundle
from mureo.demo.scenarios import Scenario, get_scenario

# Marker used to recognize a prior ``mureo demo init`` run. The
# ``import_bundle`` flow records ``source_filename`` in the manifest
# entry; we set it to the same name (``bundle.xlsx``) the demo writes,
# so a re-run can distinguish "user has real BYOD data" from "user has
# the demo's BYOD data and is just running demo init again".
_DEMO_BUNDLE_FILENAME: str = "bundle.xlsx"
_DEMO_PLATFORMS: tuple[str, ...] = ("google_ads", "meta_ads")


class DemoInitError(RuntimeError):
    """Raised when ``materialize`` cannot safely write the demo artifacts."""


# Files the installer writes. Used by the empty-dir guard so re-running
# on a partial install (e.g. when the previous run was interrupted)
# does not wedge the user behind a "directory not empty" error.
_DEMO_FILES: tuple[str, ...] = (
    "bundle.xlsx",
    "STRATEGY.md",
    "STATE.json",
    ".mcp.json",
    "README.md",
)


def materialize(
    target_dir: Path | str,
    *,
    force: bool = False,
    skip_import: bool = False,
    scenario_name: str | None = None,
) -> dict[str, Path | None]:
    """Write the demo artifacts into ``target_dir``.

    Default behavior is the full one-step demo: write the five demo
    files into ``target_dir`` *and* import the bundle into
    ``~/.mureo/byod/`` so ``/daily-check`` works immediately when the
    user opens the directory in Claude Code.

    Args:
        target_dir: Destination directory. Created (with parents) if
            absent. Existing **empty** directories are reused without
            complaint.
        force: When True, overwrite the target even if it contains
            unrelated files, AND replace any existing BYOD platform
            data conflicting with the demo bundle. When False
            (default) the call refuses on either conflict so the user
            never silently loses real data.
        skip_import: When True, write the demo files but do NOT touch
            ``~/.mureo/byod/``. The user can run ``mureo byod import
            bundle.xlsx`` themselves later. Useful when the user wants
            to inspect the bundle first or already has BYOD data they
            don't want to disturb.
        scenario_name: Optional registered scenario key (see
            :mod:`mureo.demo.scenarios`). ``None`` selects the default
            scenario. Resolved via :func:`get_scenario`, which raises
            :class:`ValueError` for unknown names — let the CLI wrap
            that into a user-friendly error.

    Returns:
        Mapping of artifact name → absolute path of the written file.
        ``state`` is ``None`` when ``skip_import=True``.

    Raises:
        DemoInitError: if ``target_dir`` exists as a non-directory; or
            the target is non-empty (with unrelated files) and
            ``force`` is False; or BYOD already has demo-conflicting
            platforms and ``force`` is False; or any filesystem /
            adapter error surfaces during the write.
        ValueError: when ``scenario_name`` is not a registered key.
    """
    scenario = get_scenario(scenario_name)
    target = Path(target_dir).expanduser().resolve()

    if target.exists() and not target.is_dir():
        raise DemoInitError(
            f"{target}: exists and is not a directory. "
            "Pick a different path or remove the file first."
        )

    if target.exists() and not force:
        existing = [p for p in target.iterdir() if p.name not in _DEMO_FILES]
        if existing:
            sample = ", ".join(sorted(p.name for p in existing[:5]))
            raise DemoInitError(
                f"{target}: directory is not empty (contains {sample}). "
                "Re-run with --force to overwrite, or pick a different "
                "target path."
            )

    if not skip_import and not force:
        # Refuse to clobber the user's real BYOD data, but treat a prior
        # ``mureo demo init`` run as a benign idempotent re-run rather
        # than a conflict — the user shouldn't need ``--force`` just to
        # repeat the demo bootstrap.
        conflicts: list[str] = []
        for p in _DEMO_PLATFORMS:
            info = byod_platform_info(p)
            if info is None:
                continue
            if info.get("source_filename") == _DEMO_BUNDLE_FILENAME:
                continue  # prior demo run, safe to re-import
            conflicts.append(p)
        if conflicts:
            raise DemoInitError(
                f"BYOD already has data for {', '.join(conflicts)}. "
                "Re-run with --force to replace it, or with "
                "--skip-import to leave BYOD untouched."
            )

    state_path: Path | None = None
    try:
        target.mkdir(parents=True, exist_ok=True)

        bundle_path = target / "bundle.xlsx"
        build_bundle(bundle_path, scenario)

        strategy_path = target / "STRATEGY.md"
        strategy_path.write_text(scenario.strategy_md, encoding="utf-8")

        # STATE.json is paired with imported BYOD data. When the user
        # opts out of the import, shipping STATE.json would lie — its
        # campaign_ids would point at CSV rows that don't exist yet.
        # The skip_import README documents the manual flow instead.
        if not skip_import:
            state_path = target / "STATE.json"
            state_path.write_text(_state_json(scenario), encoding="utf-8")

        mcp_path = target / ".mcp.json"
        mcp_path.write_text(_mcp_json(), encoding="utf-8")

        readme_path = target / "README.md"
        readme_path.write_text(
            _readme_md(scenario=scenario, skip_import=skip_import), encoding="utf-8"
        )
    except OSError as exc:
        # Surface filesystem failures (broken symlinks, permission errors,
        # ENOSPC, symlink loops resolving to non-existent paths) as a
        # clean DemoInitError so the CLI prints a one-line message
        # instead of a stack trace.
        raise DemoInitError(f"{target}: {exc}") from exc

    if not skip_import:
        # Pass replace=True whenever any prior platform data exists
        # (real or demo). The demo-platform conflict was already
        # filtered above; --force is required for real-data conflicts.
        # In both cases, replace=True satisfies import_bundle's own
        # per-platform conflict guard.
        needs_replace = force or any(
            byod_platform_info(p) is not None for p in _DEMO_PLATFORMS
        )
        try:
            import_bundle(bundle_path, replace=needs_replace)
        except BundleImportError as exc:
            raise DemoInitError(f"BYOD import failed: {exc}") from exc

    return {
        "bundle": bundle_path,
        "strategy": strategy_path,
        "state": state_path,
        "mcp": mcp_path,
        "readme": readme_path,
    }


# ---------------------------------------------------------------------------
# Static artifact bodies
# ---------------------------------------------------------------------------


def _state_json(scenario: Scenario) -> str:
    """Render the scenario's ``state_doc`` as STATE.json text.

    The scenario module is the single source of truth for STATE.json
    content so that adding a new scenario is purely additive — no
    branches in the installer.
    """
    return json.dumps(scenario.state_doc, indent=2, ensure_ascii=False) + "\n"


def _mcp_json() -> str:
    """Claude Code MCP registration pointing at the local mureo server.

    ``python -m mureo.mcp`` matches the entry point used by
    ``mureo/cli/setup_codex.py`` so the demo and the real install path
    stay in sync if one changes.
    """
    config = {
        "mcpServers": {
            "mureo": {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "mureo.mcp"],
            }
        }
    }
    return json.dumps(config, indent=2) + "\n"


def _readme_md(*, scenario: Scenario, skip_import: bool) -> str:
    """Render the demo README, scenario-aware.

    The active scenario's title appears in the header so the user
    knows which story they're playing through. The two body branches
    (skip_import vs default) preserve the prior installer's UX:
    skip_import documents the manual ``mureo byod import`` step,
    default celebrates the one-shot flow.
    """
    period = f"{scenario.days} days ending {scenario.end_date.isoformat()}"

    if skip_import:
        return f"""# mureo demo — {scenario.title}

This directory was generated by `mureo demo init --scenario {scenario.name} --skip-import`.
The synthetic data has NOT been imported into mureo's BYOD store yet.

> {scenario.blurb}

## Quickstart (Claude Code)

1. Import the demo bundle into mureo's BYOD store:

       mureo byod import bundle.xlsx

2. Open this directory in Claude Code. The bundled `.mcp.json`
   registers the `mureo` MCP server automatically.

3. In Claude Code, try one of:

       /daily-check
       /search-term-cleanup
       /budget-rebalance
       /weekly-report

The bundle is deliberately seeded so the workflow skills surface
actionable findings tied to the scenario's story arc.

## Files

- `bundle.xlsx`  — Google Ads + Meta Ads synthetic data, {period}
- `STRATEGY.md`  — scenario-specific strategy used by `_mureo-strategy` skills
- `.mcp.json`    — Claude Code MCP server registration
- `README.md`    — this file

(STATE.json is intentionally not shipped under `--skip-import` because
its campaign_ids would point at BYOD CSVs that don't exist yet. Run
`mureo byod import bundle.xlsx` first, then re-run `mureo demo init`
without the flag to get STATE.json.)

## Other scenarios

Run `mureo demo list` to see available scenarios; pick a different
story with `mureo demo init --scenario <name>`.

## Cleaning up

To remove the imported demo data afterwards:

    mureo byod clear
"""
    return f"""# mureo demo — {scenario.title}

This directory was generated by `mureo demo init --scenario {scenario.name}`.
The synthetic bundle has already been imported into mureo's BYOD
store and a matching `STATE.json` has been written, so the workflow
skills are ready to run with no extra setup.

> {scenario.blurb}

## Quickstart (Claude Code)

1. Open this directory in Claude Code. The bundled `.mcp.json`
   registers the `mureo` MCP server automatically.

2. In Claude Code, try one of:

       /daily-check
       /search-term-cleanup
       /budget-rebalance
       /weekly-report

The bundle is deliberately seeded so the workflow skills surface
actionable findings tied to the scenario's story arc.

## Files

- `bundle.xlsx`  — Google Ads + Meta Ads synthetic data, {period}
- `STRATEGY.md`  — scenario-specific strategy used by `_mureo-strategy` skills
- `STATE.json`   — campaign snapshots + action_log used by `/daily-check` etc.
- `.mcp.json`    — Claude Code MCP server registration
- `README.md`    — this file

## Cleaning up

To remove the imported demo data and restore an empty BYOD store:

    mureo byod clear
"""
