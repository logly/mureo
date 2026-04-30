"""``mureo demo`` CLI subcommands: init, list.

Materializes a self-contained demo directory so users can try mureo
against a realistic synthetic dataset without exporting their own ad
data first. The bundle round-trips through the same ``mureo byod
import`` pipeline that real BYOD users go through, so the demo and
real flows share a single code path downstream.

Multiple demo scenarios are registered in :mod:`mureo.demo.scenarios`;
``--scenario <name>`` switches between them.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TCH003 (used at runtime by typer)

import typer

from mureo.demo.installer import DemoInitError, materialize
from mureo.demo.scenarios import DEFAULT_SCENARIO, SCENARIOS

demo_app = typer.Typer(
    name="demo",
    help=(
        "Bootstrap a self-contained demo directory (synthetic XLSX "
        "bundle + STRATEGY.md + .mcp.json) so you can try mureo "
        "without exporting your real ad data first."
    ),
    no_args_is_help=True,
)


@demo_app.command("init")  # type: ignore[untyped-decorator, unused-ignore]
def init(
    target: Path = typer.Argument(  # noqa: B008
        Path("./mureo-demo"),
        help="Directory to create (default: ./mureo-demo).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Overwrite the target even if it contains unrelated files, "
            "and replace any conflicting BYOD data in ~/.mureo/byod/."
        ),
    ),
    skip_import: bool = typer.Option(
        False,
        "--skip-import",
        help=(
            "Write the demo files but do NOT import the bundle into "
            "~/.mureo/byod/. Useful if you want to inspect the bundle "
            "first or already have BYOD data you do not want to disturb."
        ),
    ),
    scenario_name: str = typer.Option(
        DEFAULT_SCENARIO,
        "--scenario",
        help=(
            "Scenario to use. Run `mureo demo list` to see available "
            f"scenarios. Default: {DEFAULT_SCENARIO}."
        ),
    ),
) -> None:
    """Materialize a demo directory at TARGET (default ``./mureo-demo``).

    By default this also imports the demo bundle into ``~/.mureo/byod/``
    so the workflow skills (``/daily-check`` etc.) are immediately
    runnable in Claude Code with no extra steps.
    """
    try:
        results = materialize(
            target,
            force=force,
            skip_import=skip_import,
            scenario_name=scenario_name,
        )
    except ValueError as exc:
        # Unknown scenario name. The registry produces a message that
        # already lists valid keys, so just forward it.
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    except DemoInitError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    # ``bundle`` is always written by materialize(); only ``state`` can
    # be None (under --skip-import). Pull bundle out so the rest of the
    # block doesn't have to relitigate the union.
    bundle = results["bundle"]
    assert bundle is not None
    target_dir = bundle.parent

    scenario = SCENARIOS[scenario_name]
    typer.echo("=== mureo demo init ===\n")
    typer.echo(f"  Scenario: {scenario.title}")
    typer.echo(f"  Wrote demo to: {target_dir}")
    for label in ("bundle", "strategy", "state", "mcp", "readme"):
        path = results[label]
        if path is None:
            continue  # ``state`` is None when --skip-import is set
        typer.echo(f"    - {path.name}")
    typer.echo("")
    typer.echo("Next steps:")
    if skip_import:
        typer.echo(f"  1. cd {target_dir}")
        typer.echo("  2. mureo byod import bundle.xlsx")
        typer.echo("  3. Open this directory in Claude Code")
        typer.echo("  4. Ask: /daily-check  (or /search-term-cleanup)")
    else:
        typer.echo("  Bundle imported into ~/.mureo/byod/.")
        typer.echo(f"  1. cd {target_dir}")
        typer.echo("  2. Open this directory in Claude Code")
        typer.echo("  3. Ask: /daily-check  (or /search-term-cleanup)")


@demo_app.command("list")  # type: ignore[untyped-decorator, unused-ignore]
def list_scenarios() -> None:
    """List the registered demo scenarios.

    Use ``mureo demo init --scenario <name>`` to pick a non-default
    scenario.
    """
    typer.echo("Available demo scenarios:\n")
    for name in sorted(SCENARIOS):
        sc = SCENARIOS[name]
        marker = " (default)" if name == DEFAULT_SCENARIO else ""
        typer.echo(f"  {name}{marker}")
        typer.echo(f"    {sc.title}")
        typer.echo(f"    {sc.blurb}")
        typer.echo("")
