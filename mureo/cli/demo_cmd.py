"""``mureo demo`` CLI subcommands: init / reset / uninstall / status.

Lets a new user try mureo without any real ad-account credentials.
The actual install/copy logic lives in :mod:`mureo.demo.installer`.
"""

from __future__ import annotations

import typer

from mureo.demo.installer import (
    demo_data_dir,
    demo_is_installed,
    install_demo,
    uninstall_demo,
)

demo_app = typer.Typer(
    name="demo",
    help="Try mureo with synthetic data — no credentials required.",
    no_args_is_help=True,
)


_NEXT_STEPS_BLOCK = """
Next:
  Add this to your Claude Code MCP config
  (~/.claude/settings.json or your project .mcp.json):

  {
    "mcpServers": {
      "mureo-demo": {
        "command": "python",
        "args": ["-m", "mureo.mcp", "--demo"]
      }
    }
  }

  Then ask Claude Code: "Run /daily-check on mureo-demo"
"""


def _print_install_summary(dst: object) -> None:
    typer.echo(f"  Created {dst}/")
    typer.echo(
        "  Generated Google Ads dataset "
        "(3 campaigns, 5 ad groups, 12 ads, 30 keywords)"
    )
    typer.echo("  Generated Meta Ads dataset (3 campaigns, 5 ad sets, 8 ads)")
    typer.echo("  Generated Search Console dataset (50 queries, 14 days)")
    typer.echo("  Wrote STRATEGY.md (B2B SaaS, Conservative mode)")
    typer.echo("  Wrote expected_output.md")


@demo_app.command("init")  # type: ignore[untyped-decorator, unused-ignore]
def init(
    force: bool = typer.Option(
        False, "--force", help="Overwrite existing demo data without prompting."
    ),
) -> None:
    """Install synthetic demo data into ~/.mureo/demo/."""
    try:
        dst = install_demo(force=force)
    except FileExistsError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from None
    typer.echo("=== mureo demo init ===\n")
    _print_install_summary(dst)
    typer.echo(_NEXT_STEPS_BLOCK)


@demo_app.command("reset")  # type: ignore[untyped-decorator, unused-ignore]
def reset() -> None:
    """Re-extract the demo dataset (equivalent to: mureo demo init --force)."""
    dst = install_demo(force=True)
    typer.echo("=== mureo demo reset ===\n")
    _print_install_summary(dst)


@demo_app.command("uninstall")  # type: ignore[untyped-decorator, unused-ignore]
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Remove ~/.mureo/demo/ entirely."""
    target = demo_data_dir()
    if not demo_is_installed():
        typer.echo(f"No demo data to remove ({target} does not exist).")
        return
    if not yes:
        confirm = typer.confirm(f"Remove {target} and all demo data?", default=False)
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(code=1)
    removed = uninstall_demo()
    if removed:
        typer.echo(f"Removed {target}")
    else:
        typer.echo(f"Nothing removed ({target} did not exist)")


@demo_app.command("status")  # type: ignore[untyped-decorator, unused-ignore]
def status() -> None:
    """Show whether demo data is currently installed."""
    target = demo_data_dir()
    if demo_is_installed():
        typer.echo(f"Demo data is installed at {target}")
    else:
        typer.echo(f"Demo data is NOT installed (would live at {target})")
