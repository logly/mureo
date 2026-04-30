"""Materialize the ``mureo demo init`` artifacts on disk.

The installer is intentionally narrow: it writes four files into a
target directory and otherwise stays out of the user's way. It does
**not** import the bundle into ``~/.mureo/byod/`` — that step remains
the user's explicit ``mureo byod import`` invocation, so the demo
flow cannot silently overwrite real BYOD data the user already has.

Artifacts written:

  bundle.xlsx     — synthetic Google Ads + Meta Ads bundle
                    (see :mod:`mureo.demo.scenario` /
                    :mod:`mureo.demo.builder`)
  STRATEGY.md     — minimal seed strategy for the FlowDesk B2B SaaS
                    scenario, suitable for ``mureo-strategy`` skills
  .mcp.json       — Claude Code MCP server registration for the
                    ``mureo`` stdio server
  README.md       — quickstart instructions
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mureo.byod.bundle import BundleImportError, import_bundle
from mureo.byod.runtime import byod_platform_info
from mureo.demo import scenario
from mureo.demo.builder import build_bundle

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

    Returns:
        Mapping of artifact name → absolute path of the written file.

    Raises:
        DemoInitError: if ``target_dir`` exists as a non-directory; or
            the target is non-empty (with unrelated files) and
            ``force`` is False; or BYOD already has demo-conflicting
            platforms and ``force`` is False; or any filesystem /
            adapter error surfaces during the write.
    """
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
        build_bundle(bundle_path)

        strategy_path = target / "STRATEGY.md"
        strategy_path.write_text(_strategy_md(), encoding="utf-8")

        # STATE.json is paired with imported BYOD data. When the user
        # opts out of the import, shipping STATE.json would lie — its
        # campaign_ids would point at CSV rows that don't exist yet.
        # The skip_import README documents the manual flow instead.
        if not skip_import:
            state_path = target / "STATE.json"
            state_path.write_text(_state_json(), encoding="utf-8")

        mcp_path = target / ".mcp.json"
        mcp_path.write_text(_mcp_json(), encoding="utf-8")

        readme_path = target / "README.md"
        readme_path.write_text(_readme_md(skip_import=skip_import), encoding="utf-8")
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


def _state_json() -> str:
    """Initial v2 STATE.json for the demo scenario.

    Schema follows ``docs/strategy-context.md`` — version "2",
    per-platform campaigns, empty action_log. ``last_synced_at`` uses
    a fixed ISO 8601 timestamp tied to the demo period so re-runs of
    ``mureo demo init`` produce identical STATE.json bytes.
    """
    last_synced = datetime.combine(
        scenario.DEMO_END_DATE, datetime.min.time(), tzinfo=timezone.utc
    ).isoformat(timespec="seconds")
    doc = {
        "version": "2",
        "last_synced_at": last_synced,
        "platforms": {
            "google_ads": {
                "account_id": "demo-flowdesk-google-ads",
                "campaigns": scenario.google_ads_state_campaigns(),
            },
            "meta_ads": {
                "account_id": "demo-flowdesk-meta-ads",
                "campaigns": scenario.meta_ads_state_campaigns(),
            },
        },
        "action_log": [],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


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


def _strategy_md() -> str:
    return """# STRATEGY — FlowDesk (demo)

> Synthetic mid-market B2B SaaS scenario shipped with `mureo demo init`.
> Replace with your real strategy when you switch to a live account.

## Business
- **Brand:** FlowDesk
- **Product:** Project management & team collaboration SaaS
- **ICP:** 50–500 person companies, ops / PM leaders
- **Plan range:** ~JPY 1,200 / seat / month

## Marketing goals (this quarter)
- Hit 320 paid signups / month at <= JPY 12,000 CPA
- Keep brand-search CTR >= 15%
- Hold blended Google + Meta ROAS >= 2.5x

## Channel mix
- **Google Ads:** Brand (Exact + Phrase), Generic (High intent + Low intent)
- **Meta Ads:** Awareness video at the top of funnel, Lead-form conversion at the bottom

## Constraints
- No competitor-name bidding
- Brand terms should not appear in Phrase or Broad campaigns
- Demo bundle covers the 30 days ending 2026-04-29
"""


def _readme_md(*, skip_import: bool) -> str:
    if skip_import:
        return """# mureo demo

This directory was generated by `mureo demo init --skip-import`. The
synthetic data has NOT been imported into mureo's BYOD store yet.

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

The bundle deliberately contains realistic problems (brand
cannibalization in the Phrase campaign, an over-funded low-intent
generic campaign, a fatiguing Meta video creative) so the skills
surface actionable findings instead of "everything is fine."

## Files

- `bundle.xlsx`  — Google Ads + Meta Ads synthetic data, 30 days
- `STRATEGY.md`  — seed strategy used by `mureo-strategy` skills
- `STATE.json`   — campaign snapshots used by `/daily-check` etc.
- `.mcp.json`    — Claude Code MCP server registration
- `README.md`    — this file

## Cleaning up

To remove the imported demo data afterwards:

    mureo byod clear
"""
    return """# mureo demo

This directory was generated by `mureo demo init`. The synthetic
bundle has already been imported into mureo's BYOD store and a
matching `STATE.json` has been written, so the workflow skills are
ready to run with no extra setup.

## Quickstart (Claude Code)

1. Open this directory in Claude Code. The bundled `.mcp.json`
   registers the `mureo` MCP server automatically.

2. In Claude Code, try one of:

       /daily-check
       /search-term-cleanup
       /budget-rebalance
       /weekly-report

The bundle deliberately contains realistic problems (brand
cannibalization in the Phrase campaign, an over-funded low-intent
generic campaign, a fatiguing Meta video creative) so the skills
surface actionable findings instead of "everything is fine."

## Files

- `bundle.xlsx`  — Google Ads + Meta Ads synthetic data, 30 days
- `STRATEGY.md`  — seed strategy used by `mureo-strategy` skills
- `STATE.json`   — campaign snapshots used by `/daily-check` etc.
- `.mcp.json`    — Claude Code MCP server registration
- `README.md`    — this file

## Cleaning up

To remove the imported demo data and restore an empty BYOD store:

    mureo byod clear
"""
