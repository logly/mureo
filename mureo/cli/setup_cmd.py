"""Setup commands for different AI agent environments.

``mureo setup claude-code`` — one-command setup for Claude Code users.
``mureo setup cursor`` — MCP-only setup for Cursor users.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import typer

setup_app = typer.Typer(name="setup", help="Set up mureo for AI agent environments")


def _get_data_path(subdir: str) -> Path:
    """Resolve the path to bundled data files.

    Works both in development (source tree) and after pip install
    (package data).
    """
    # Try importlib.resources first (pip install)
    try:
        ref = resources.files("mureo") / "_data" / subdir
        # Materialize to a real path
        with resources.as_file(ref) as p:
            if p.exists():
                return Path(p)
    except (TypeError, FileNotFoundError):
        pass

    # Fallback: source tree layout
    pkg_root = Path(__file__).parent.parent
    data_path = pkg_root / "_data" / subdir
    if data_path.exists():
        return data_path

    raise FileNotFoundError(
        f"Bundled data not found: {subdir}. " f"Ensure mureo is installed correctly."
    )


def install_commands(target_dir: Path | None = None) -> tuple[int, Path]:
    """Copy workflow command .md files to the target directory.

    Args:
        target_dir: Destination directory. Defaults to ~/.claude/commands.

    Returns:
        Tuple of (number of files copied, target directory path).
    """
    dest = target_dir or (Path.home() / ".claude" / "commands")
    dest.mkdir(parents=True, exist_ok=True)

    src = _get_data_path("commands")
    count = 0
    for md_file in sorted(src.glob("*.md")):
        shutil.copy2(md_file, dest / md_file.name)
        count += 1

    return count, dest


def install_skills(target_dir: Path | None = None) -> tuple[int, Path]:
    """Copy skill directories to the target directory.

    Args:
        target_dir: Destination directory. Defaults to ~/.claude/skills.

    Returns:
        Tuple of (number of skills copied, target directory path).
    """
    dest = target_dir or (Path.home() / ".claude" / "skills")
    dest.mkdir(parents=True, exist_ok=True)

    src = _get_data_path("skills")
    count = 0
    for skill_dir in sorted(src.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            dest_skill = dest / skill_dir.name
            if dest_skill.exists():
                shutil.rmtree(dest_skill)
            shutil.copytree(skill_dir, dest_skill)
            count += 1

    return count, dest


@setup_app.command("claude-code")  # type: ignore[untyped-decorator, unused-ignore]
def setup_claude_code(
    skip_auth: bool = typer.Option(
        False,
        "--skip-auth",
        help="Skip authentication (install commands, skills, MCP config, and guard only)",
    ),
) -> None:
    """One-command setup for Claude Code users.

    Runs the full setup flow:
    1. Authentication (Google Ads / Meta Ads) — skipped with --skip-auth
    2. MCP configuration
    3. Credential guard hook
    4. Workflow commands installation
    5. Skills installation
    """
    import asyncio

    typer.echo("=== mureo Setup for Claude Code ===\n")

    # 1. Authentication
    if not skip_auth:
        google = typer.confirm("Configure Google Ads?", default=True)
        meta = typer.confirm("Configure Meta Ads?", default=False)

        if google:
            from mureo.auth_setup import setup_google_ads

            asyncio.run(setup_google_ads())

        if meta:
            from mureo.auth_setup import setup_meta_ads

            asyncio.run(setup_meta_ads())
    else:
        typer.echo("Skipping authentication (--skip-auth).")
        typer.echo("Run /onboard in Claude Code later to configure credentials.\n")

    # 2. MCP configuration
    from mureo.auth_setup import install_mcp_config

    mcp_result = install_mcp_config(scope="global")
    if mcp_result is not None:
        typer.echo(f"MCP configuration added: {mcp_result}")
    else:
        typer.echo("MCP configuration already exists.")

    # 3. Credential guard
    from mureo.auth_setup import install_credential_guard

    guard_result = install_credential_guard()
    if guard_result is not None:
        typer.echo(f"Credential guard installed: {guard_result}")
    else:
        typer.echo("Credential guard already installed.")

    # 4. Workflow commands
    typer.echo("\n--- Installing workflow commands ---")
    try:
        cmd_count, cmd_path = install_commands()
        typer.echo(f"  {cmd_count} commands installed to {cmd_path}")
    except FileNotFoundError as e:
        typer.echo(f"  Warning: {e}", err=True)

    # 5. Skills
    typer.echo("\n--- Installing skills ---")
    try:
        skill_count, skill_path = install_skills()
        typer.echo(f"  {skill_count} skills installed to {skill_path}")
    except FileNotFoundError as e:
        typer.echo(f"  Warning: {e}", err=True)

    # Summary
    typer.echo("\n=== Setup complete ===")
    if skip_auth:
        typer.echo("Next: Open Claude Code and run /onboard to configure credentials.")
    else:
        typer.echo("Next: Open Claude Code and run /onboard to get started.")


@setup_app.command("cursor")  # type: ignore[untyped-decorator, unused-ignore]
def setup_cursor() -> None:
    """Setup for Cursor users (MCP configuration only).

    Cursor supports MCP but does not support slash commands,
    skills, or PreToolUse hooks.
    """
    import asyncio

    typer.echo("=== mureo Setup for Cursor ===\n")

    google = typer.confirm("Configure Google Ads?", default=True)
    meta = typer.confirm("Configure Meta Ads?", default=False)

    if google:
        from mureo.auth_setup import setup_google_ads

        asyncio.run(setup_google_ads())

    if meta:
        from mureo.auth_setup import setup_meta_ads

        asyncio.run(setup_meta_ads())

    if not google and not meta:
        typer.echo("Setup skipped.")
        return

    # MCP config for Cursor (.cursor/mcp.json)
    from mureo.auth_setup import install_mcp_config

    result = install_mcp_config(scope="project")
    if result is not None:
        typer.echo(f"\nMCP config written to {result}")
    else:
        typer.echo("\nMCP config already exists.")

    typer.echo("\nSetup complete. Restart Cursor to activate mureo MCP tools.")
    typer.echo(
        "Note: Cursor does not support workflow commands (/daily-check, etc.) "
        "or skills. Use MCP tools directly."
    )
