"""``mureo install-desktop`` — onboarding for Claude Desktop chat users.

This top-level command exists separately from the ``mureo setup *``
group because it targets non-engineer users. The discoverability of
``install-desktop`` matters more than consistency with the existing
host-specific setup commands.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mureo.desktop_installer import (
    DesktopConfigCorruptError,
    DesktopInstallExistsError,
    DesktopInstallUnsupportedPlatformError,
    format_next_steps,
    install_desktop,
)

install_desktop_app = typer.Typer(
    name="install-desktop",
    help="Wire mureo into Claude Desktop chat (macOS).",
    invoke_without_command=True,
    no_args_is_help=False,
)


@install_desktop_app.callback()  # type: ignore[untyped-decorator, unused-ignore]
def install_desktop_cmd(
    workspace: Path | None = typer.Option(  # noqa: B008
        None,
        "--workspace",
        "-w",
        help="Directory the MCP server will use as its working "
        "directory. STRATEGY.md / STATE.json will live here. "
        "Defaults to ~/mureo.",
    ),
    with_demo: str | None = typer.Option(
        None,
        "--with-demo",
        help="Seed the workspace with a demo scenario "
        "(seasonality-trap | halo-effect | hidden-champion | strategy-drift).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite an existing 'mureo' MCP entry without prompting "
        "(a timestamped backup is always saved first).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would happen without writing anything.",
    ),
) -> None:
    """Wire mureo into Claude Desktop's MCP config.

    Creates the workspace, generates a wrapper shell script, and
    merges a 'mureo' entry into ~/Library/Application
    Support/Claude/claude_desktop_config.json.
    """
    resolved_workspace = workspace if workspace is not None else Path.home() / "mureo"
    try:
        result = install_desktop(
            workspace=resolved_workspace,
            with_demo=with_demo,
            force=force,
            dry_run=dry_run,
        )
    except DesktopInstallUnsupportedPlatformError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except DesktopInstallExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except DesktopConfigCorruptError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.dry_run:
        typer.echo("Dry-run — no changes written.")
        typer.echo(f"  Would create workspace: {result.workspace}")
        typer.echo(f"  Would write wrapper:    {result.wrapper_path}")
        typer.echo(f"  Would update config:    {result.config_path}")
        return

    typer.echo(format_next_steps(result))
