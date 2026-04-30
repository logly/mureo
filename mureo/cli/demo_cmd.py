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
        help="Overwrite the target even if it already contains unrelated files.",
    ),
) -> None:
    """Materialize a demo directory at TARGET (default ``./mureo-demo``).

    After this completes, follow the printed next steps to import the
    bundle and open the directory in Claude Code.
    """
    try:
        results = materialize(target, force=force)
    except DemoInitError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo("=== mureo demo init ===\n")
    typer.echo(f"  Wrote demo to: {results['bundle'].parent}")
    for label in ("bundle", "strategy", "mcp", "readme"):
        typer.echo(f"    - {results[label].name}")
    typer.echo("")
    typer.echo("Next steps:")
    typer.echo(f"  1. cd {results['bundle'].parent}")
    typer.echo("  2. mureo byod import bundle.xlsx")
    typer.echo("  3. Open this directory in Claude Code")
    typer.echo("  4. Ask: /daily-check  (or /search-term-cleanup)")
