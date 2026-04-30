"""``mureo demo`` CLI subcommands: init.

Materializes a self-contained demo directory so users can try mureo
against a realistic synthetic dataset without exporting their own ad
data first. The bundle round-trips through the same ``mureo byod
import`` pipeline that real BYOD users go through, so the demo and
real flows share a single code path downstream.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TCH003 (used at runtime by typer)

import typer

from mureo.demo.installer import DemoInitError, materialize

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
) -> None:
    """Materialize a demo directory at TARGET (default ``./mureo-demo``).

    By default this also imports the demo bundle into ``~/.mureo/byod/``
    so the workflow skills (``/daily-check`` etc.) are immediately
    runnable in Claude Code with no extra steps.
    """
    try:
        results = materialize(target, force=force, skip_import=skip_import)
    except DemoInitError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo("=== mureo demo init ===\n")
    typer.echo(f"  Wrote demo to: {results['bundle'].parent}")
    for label in ("bundle", "strategy", "state", "mcp", "readme"):
        path = results[label]
        if path is None:
            continue  # ``state`` is None when --skip-import is set
        typer.echo(f"    - {path.name}")
    typer.echo("")
    typer.echo("Next steps:")
    if skip_import:
        typer.echo(f"  1. cd {results['bundle'].parent}")
        typer.echo("  2. mureo byod import bundle.xlsx")
        typer.echo("  3. Open this directory in Claude Code")
        typer.echo("  4. Ask: /daily-check  (or /search-term-cleanup)")
    else:
        typer.echo("  Bundle imported into ~/.mureo/byod/.")
        typer.echo(f"  1. cd {results['bundle'].parent}")
        typer.echo("  2. Open this directory in Claude Code")
        typer.echo("  3. Ask: /daily-check  (or /search-term-cleanup)")
