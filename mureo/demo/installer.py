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
from pathlib import Path

from mureo.demo.builder import build_bundle


class DemoInitError(RuntimeError):
    """Raised when ``materialize`` cannot safely write the demo artifacts."""


# Files the installer writes. Used by the empty-dir guard so re-running
# on a partial install (e.g. when the previous run was interrupted)
# does not wedge the user behind a "directory not empty" error.
_DEMO_FILES: tuple[str, ...] = (
    "bundle.xlsx",
    "STRATEGY.md",
    ".mcp.json",
    "README.md",
)


def materialize(target_dir: Path | str, *, force: bool = False) -> dict[str, Path]:
    """Write the demo artifacts into ``target_dir``.

    Args:
        target_dir: Destination directory. Created (with parents) if
            absent. Existing **empty** directories are reused without
            complaint.
        force: When True, overwrite any existing demo artifacts in the
            target without checking for unrelated files. When False
            (default) the call refuses if the target already contains
            files other than the four artifacts this installer
            manages, so the user is never surprised by losing
            unrelated data.

    Returns:
        Mapping of artifact name → absolute path of the written file.

    Raises:
        DemoInitError: if ``target_dir`` exists as a non-directory, or
            if the target is non-empty and ``force`` is False (with
            existing-but-unrelated files present).
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

    try:
        target.mkdir(parents=True, exist_ok=True)

        bundle_path = target / "bundle.xlsx"
        build_bundle(bundle_path)

        strategy_path = target / "STRATEGY.md"
        strategy_path.write_text(_strategy_md(), encoding="utf-8")

        mcp_path = target / ".mcp.json"
        mcp_path.write_text(_mcp_json(), encoding="utf-8")

        readme_path = target / "README.md"
        readme_path.write_text(_readme_md(), encoding="utf-8")
    except OSError as exc:
        # Surface filesystem failures (broken symlinks, permission errors,
        # ENOSPC, symlink loops resolving to non-existent paths) as a
        # clean DemoInitError so the CLI prints a one-line message
        # instead of a stack trace. The pre-checks above only cover the
        # "target exists and isn't usable" case; this catches the
        # mid-write surprises.
        raise DemoInitError(f"{target}: {exc}") from exc

    return {
        "bundle": bundle_path,
        "strategy": strategy_path,
        "mcp": mcp_path,
        "readme": readme_path,
    }


# ---------------------------------------------------------------------------
# Static artifact bodies
# ---------------------------------------------------------------------------


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


def _readme_md() -> str:
    return """# mureo demo

This directory was generated by `mureo demo init`. It contains a
self-contained, synthetic-data demo of mureo so you can try the
skills against a realistic dataset without exporting your own data
first.

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

The bundle deliberately contains a few realistic problems
(brand-cannibalization in the Phrase campaign, an over-funded
low-intent generic campaign, a fatiguing Meta video creative) so the
skills surface actionable findings instead of "everything is fine."

## Files

- `bundle.xlsx`  — Google Ads + Meta Ads synthetic data, 30 days
- `STRATEGY.md`  — seed strategy used by `mureo-strategy` skills
- `.mcp.json`    — Claude Code MCP server registration
- `README.md`    — this file

## Cleaning up

To remove the imported demo data afterwards:

    mureo byod clear
"""
