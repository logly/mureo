"""Setup commands for different AI agent environments.

``mureo setup claude-code`` — one-command setup for Claude Code users.
``mureo setup cursor`` — MCP-only setup for Cursor users.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import typer

from mureo.cli._tty import confirm_or_default, is_tty

setup_app = typer.Typer(name="setup", help="Set up mureo for AI agent environments")


def _should_skip_auth(skip_auth_flag: bool) -> tuple[bool, str | None]:
    """Decide whether to skip OAuth, accounting for missing TTYs.

    When an AI agent (Claude Code Bash tool, Codex, etc.) runs this
    command there is no TTY, so the interactive ``input()`` calls in
    ``setup_google_ads`` / ``setup_meta_ads`` would hang. We auto-skip
    in that case and return a banner message for the caller to echo so
    the operator understands what happened.
    """
    if skip_auth_flag:
        return True, "Skipping authentication (--skip-auth)."
    if not is_tty():
        return True, (
            "No TTY detected (running under an AI agent or subprocess). "
            "Skipping OAuth setup.\n"
            "Run `mureo auth setup` in a real terminal to complete "
            "authentication."
        )
    return False, None


def _warn_unused_ads_flags(
    should_skip: bool, google_ads: bool | None, meta_ads: bool | None
) -> None:
    """If the user passed --google-ads / --meta-ads but we're skipping
    auth, they expected something to run. Be explicit rather than silent.
    """
    if should_skip and (google_ads is not None or meta_ads is not None):
        typer.echo(
            "Note: --google-ads / --meta-ads ignored because "
            "authentication is skipped. Run `mureo auth setup` in a "
            "terminal to apply them.",
            err=True,
        )


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
    google_ads: bool | None = typer.Option(
        None,
        "--google-ads/--no-google-ads",
        help="Configure Google Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
    meta_ads: bool | None = typer.Option(
        None,
        "--meta-ads/--no-meta-ads",
        help="Configure Meta Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
) -> None:
    """One-command setup for Claude Code users.

    Runs the full setup flow:
    1. Authentication (Google Ads / Meta Ads) — skipped with --skip-auth
       or auto-skipped when no TTY is attached (e.g. run from an AI agent)
    2. MCP configuration
    3. Credential guard hook
    4. Workflow commands installation
    5. Skills installation
    """
    import asyncio

    typer.echo("=== mureo Setup for Claude Code ===\n")

    # 1. Authentication
    should_skip, banner = _should_skip_auth(skip_auth)
    _warn_unused_ads_flags(should_skip, google_ads, meta_ads)
    if should_skip:
        if banner is not None:
            typer.echo(banner)
        typer.echo("Run /onboard in Claude Code later to configure credentials.\n")
    else:
        google = confirm_or_default(
            "Configure Google Ads?", default=True, override=google_ads
        )
        meta = confirm_or_default(
            "Configure Meta Ads?", default=True, override=meta_ads
        )

        if google:
            from mureo.auth_setup import setup_google_ads

            asyncio.run(setup_google_ads())

        if meta:
            from mureo.auth_setup import setup_meta_ads

            asyncio.run(setup_meta_ads())

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
def setup_cursor(
    skip_auth: bool = typer.Option(
        False, "--skip-auth", help="Skip authentication (MCP config only)."
    ),
    google_ads: bool | None = typer.Option(
        None,
        "--google-ads/--no-google-ads",
        help="Configure Google Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
    meta_ads: bool | None = typer.Option(
        None,
        "--meta-ads/--no-meta-ads",
        help="Configure Meta Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
) -> None:
    """Setup for Cursor users (MCP configuration only).

    Cursor supports MCP but does not support slash commands,
    skills, or PreToolUse hooks.
    """
    import asyncio

    typer.echo("=== mureo Setup for Cursor ===\n")

    should_skip, banner = _should_skip_auth(skip_auth)
    _warn_unused_ads_flags(should_skip, google_ads, meta_ads)
    if should_skip:
        if banner is not None:
            typer.echo(banner)
        google = meta = False
    else:
        google = confirm_or_default(
            "Configure Google Ads?", default=True, override=google_ads
        )
        meta = confirm_or_default(
            "Configure Meta Ads?", default=True, override=meta_ads
        )

        if google:
            from mureo.auth_setup import setup_google_ads

            asyncio.run(setup_google_ads())

        if meta:
            from mureo.auth_setup import setup_meta_ads

            asyncio.run(setup_meta_ads())

    if not google and not meta and not should_skip:
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


@setup_app.command("codex")  # type: ignore[untyped-decorator, unused-ignore]
def setup_codex(
    skip_auth: bool = typer.Option(
        False,
        "--skip-auth",
        help="Skip authentication (install MCP config, guard, command skills, and shared skills only)",
    ),
    google_ads: bool | None = typer.Option(
        None,
        "--google-ads/--no-google-ads",
        help="Configure Google Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
    meta_ads: bool | None = typer.Option(
        None,
        "--meta-ads/--no-meta-ads",
        help="Configure Meta Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
) -> None:
    """One-command setup for OpenAI Codex CLI users.

    Runs the full setup flow (MCP + credential guard + workflow command
    skills + shared skills) in ``~/.codex/``. Mirrors the Claude Code
    setup layer-for-layer, except that workflow commands are installed
    as Codex skills (invoked with ``$<command>`` or via ``/skills``)
    because Codex CLI 0.117.0+ no longer surfaces ``~/.codex/prompts/``.
    """
    import asyncio

    from mureo.cli.setup_codex import (
        install_codex_command_skills,
        install_codex_credential_guard,
        install_codex_mcp_config,
        install_codex_skills,
    )

    typer.echo("=== mureo Setup for Codex CLI ===\n")

    should_skip, banner = _should_skip_auth(skip_auth)
    _warn_unused_ads_flags(should_skip, google_ads, meta_ads)
    if should_skip:
        if banner is not None:
            typer.echo(banner)
        typer.echo("Run `$onboard` in Codex later to configure credentials.\n")
    else:
        google = confirm_or_default(
            "Configure Google Ads?", default=True, override=google_ads
        )
        meta = confirm_or_default(
            "Configure Meta Ads?", default=True, override=meta_ads
        )

        if google:
            from mureo.auth_setup import setup_google_ads

            asyncio.run(setup_google_ads())

        if meta:
            from mureo.auth_setup import setup_meta_ads

            asyncio.run(setup_meta_ads())

    mcp_result = install_codex_mcp_config()
    if mcp_result is not None:
        typer.echo(f"MCP configuration added: {mcp_result}")
    else:
        typer.echo("MCP configuration already exists.")

    guard_result = install_codex_credential_guard()
    if guard_result is not None:
        typer.echo(f"Credential guard installed: {guard_result}")
    else:
        typer.echo("Credential guard already installed.")

    typer.echo("\n--- Installing workflow commands as Codex skills ---")
    try:
        cmd_count, cmd_path = install_codex_command_skills()
        typer.echo(
            f"  {cmd_count} workflow skills installed to {cmd_path}. "
            "Invoke with $<command-name> or via Codex's /skills picker."
        )
    except FileNotFoundError as e:
        typer.echo(f"  Warning: {e}", err=True)

    typer.echo("\n--- Installing skills ---")
    try:
        skill_count, skill_path = install_codex_skills()
        typer.echo(f"  {skill_count} skills installed to {skill_path}")
    except FileNotFoundError as e:
        typer.echo(f"  Warning: {e}", err=True)

    typer.echo("\n=== Setup complete ===")
    if skip_auth:
        typer.echo(
            "Next: Open Codex and run `$onboard` (or pick it from /skills) "
            "to configure credentials."
        )
    else:
        typer.echo(
            "Next: Open Codex and run `$onboard` (or pick it from /skills) "
            "to get started."
        )


@setup_app.command("gemini")  # type: ignore[untyped-decorator, unused-ignore]
def setup_gemini(
    skip_auth: bool = typer.Option(
        False, "--skip-auth", help="Skip authentication (extension manifest only)."
    ),
    google_ads: bool | None = typer.Option(
        None,
        "--google-ads/--no-google-ads",
        help="Configure Google Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
    meta_ads: bool | None = typer.Option(
        None,
        "--meta-ads/--no-meta-ads",
        help="Configure Meta Ads auth (default: prompt in TTY, yes in non-TTY).",
    ),
) -> None:
    """Setup for Gemini CLI users (extension manifest only).

    Registers mureo as a Gemini CLI extension at
    ``~/.gemini/extensions/mureo/`` with MCP server config and
    ``contextFileName: CONTEXT.md``. Gemini CLI does not support the
    PreToolUse hook surface or the ``.md`` command format mureo bundles,
    so neither is installed here.
    """
    import asyncio

    from mureo.cli.setup_gemini import install_gemini_extension

    typer.echo("=== mureo Setup for Gemini CLI ===\n")

    should_skip, banner = _should_skip_auth(skip_auth)
    _warn_unused_ads_flags(should_skip, google_ads, meta_ads)
    if should_skip:
        if banner is not None:
            typer.echo(banner)
    else:
        google = confirm_or_default(
            "Configure Google Ads?", default=True, override=google_ads
        )
        meta = confirm_or_default(
            "Configure Meta Ads?", default=True, override=meta_ads
        )

        if google:
            from mureo.auth_setup import setup_google_ads

            asyncio.run(setup_google_ads())

        if meta:
            from mureo.auth_setup import setup_meta_ads

            asyncio.run(setup_meta_ads())

    manifest = install_gemini_extension()
    typer.echo(f"\nGemini extension manifest written to {manifest}")

    typer.echo("\nSetup complete. Restart Gemini CLI to activate mureo.")
    typer.echo(
        "Note: Gemini CLI does not support PreToolUse hooks or the .md "
        "command format mureo bundles. Only MCP tools and the CONTEXT.md "
        "context file are enabled."
    )
