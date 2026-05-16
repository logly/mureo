"""`mureo providers` subcommand group.

Three commands:
- ``list`` — show every catalog entry and its installation status.
- ``add <id>`` / ``add --all`` — install the official MCP and register it in
  ``~/.claude/settings.json``. Honors ``--dry-run``.
- ``remove <id>`` — delete the ``mcpServers.<id>`` entry. Does not uninstall
  the underlying pipx/npm package (documented in ``--help``).

The catalog is source-baked in ``mureo.providers.catalog`` — no user input
flows into subprocess argv.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from mureo.providers.catalog import CATALOG, ProviderSpec, get_provider
from mureo.providers.coexistence import coexistence_warning
from mureo.providers.config_writer import (
    add_provider_to_claude_settings,
    is_hosted_provider_connected,
    is_provider_installed,
    remove_provider_from_claude_settings,
)
from mureo.providers.installer import run_install
from mureo.providers.mureo_env import (
    add_provider_and_disable_in_mureo,
    set_mureo_disable_env,
    unset_mureo_disable_env,
)

providers_app = typer.Typer(
    name="providers",
    help=(
        "Install / list / remove official MCP providers (Google Ads, Meta "
        "Ads, GA4) for Claude Code. `remove` only edits "
        "~/.claude/settings.json — it does not uninstall the underlying "
        "pipx/npm package (and is a no-op for hosted-HTTP providers like "
        "Meta Ads, which have no local install)."
    ),
    no_args_is_help=True,
)


def _render_list() -> None:
    """Print the catalog as a Rich table to stdout.

    Uses a wide explicit console width and ``no_wrap`` columns so the full
    provider id and status text are always present verbatim in the output —
    both for human readability and so callers (tests, scripts) can grep for
    exact substrings without worrying about Rich's terminal-width truncation.
    """
    console = Console(width=200)
    table = Table(title="Official MCP providers (Phase 1: Claude Code)")
    table.add_column("id", no_wrap=True)
    table.add_column("display name", no_wrap=True)
    table.add_column("install via", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("required env", no_wrap=True)

    for spec in CATALOG:
        installed = is_provider_installed(spec.id)
        status = "installed" if installed else "not installed"
        env_label = ", ".join(spec.required_env) if spec.required_env else "(none)"
        table.add_row(
            spec.id,
            spec.display_name,
            spec.install_kind,
            status,
            env_label,
        )

    console.print(table)


def _emit_coexistence(spec: ProviderSpec, *, mureo_block_present: bool) -> None:
    """Echo the coexistence warning for ``spec`` if any.

    The wording is driven by ``mureo_block_present`` — see
    :func:`mureo.providers.coexistence.coexistence_warning` for the two
    variants (auto-disable-confirmed vs. degraded "no mureo block").
    """
    warning = coexistence_warning(spec, mureo_block_present=mureo_block_present)
    if warning:
        typer.echo(warning)


def _emit_hosted_auth_notice(spec: ProviderSpec, *, dry_run: bool) -> None:
    """Print how to wire a hosted MCP via a Claude.ai connector.

    Meta's hosted Ads MCP cannot be OAuth-authenticated as a Claude Code
    *user-scope* server: it does not support RFC 7591 Dynamic Client
    Registration, so Claude Code's `/mcp` OAuth fails with
    "redirect_uris are not registered for this client". mureo therefore
    does NOT register it locally; the only path that works on Claude
    Code today is adding it as a Claude.ai account connector (Anthropic
    brokers the OAuth there). Once added at claude.ai it is available
    account-wide and surfaces in Claude Code automatically.
    """
    url = spec.mcp_server_config.get("url", "")
    prefix = "[dry-run] " if dry_run else ""
    typer.echo(
        f"{prefix}{spec.id}: Meta's hosted MCP cannot be OAuth-"
        f"authenticated as a Claude Code user-scope server (no dynamic "
        f"client registration), so mureo does NOT register it locally. "
        f"Add it as a Claude.ai connector instead:\n"
        f"{prefix}  1. Open claude.ai -> Settings -> Connectors "
        f"(https://claude.ai/customize/connectors). Requires a paid plan "
        f"(Pro/Max/Team/Enterprise; Free cannot add connectors).\n"
        f"{prefix}  2. Add custom connector -> URL: {url} -> Add, then "
        f"complete the Meta Business sign-in in the browser.\n"
        f"{prefix}  3. In Claude Code run /mcp to verify — Meta tools "
        f"load as mcp__claude_ai_MetaAds__* (free during Meta's beta).\n"
        f"{prefix}mureo-native Meta stays active until you switch it off "
        f"with `mureo providers confirm {spec.id}` (after the connector "
        f"is Connected)."
    )


def _dry_run_preview(spec: ProviderSpec) -> None:
    """Print the planned subprocess argv, ``mcpServers`` delta, and env write."""
    if spec.install_kind == "hosted_http":
        typer.echo(f"[dry-run] {spec.id}: hosted endpoint, no local install step")
    else:
        typer.echo(f"[dry-run] {spec.id}: would run argv {list(spec.install_argv)}")
    typer.echo(
        "[dry-run] "
        f"{spec.id}: would merge mcpServers entry "
        f"{json.dumps({spec.id: dict(spec.mcp_server_config)}, ensure_ascii=False)}"
    )
    platform = spec.coexists_with_mureo_platform
    if platform is not None:
        env_var = f"MUREO_DISABLE_{platform.upper()}"
        typer.echo(
            f'[dry-run] {spec.id}: would set mcpServers.mureo.env.{env_var}="1" '
            f"(if mureo block is present)"
        )


def _add_one(spec: ProviderSpec, *, dry_run: bool) -> bool:
    """Install one provider. Return True on success, False on failure.

    Failure here means subprocess exited non-zero. Exceptions propagate.
    Hosted entries (``install_kind="hosted_http"``) skip the install step
    entirely — only the ``mcpServers`` config write runs.

    When ``spec.coexists_with_mureo_platform`` is non-None and a native
    ``mcpServers.mureo`` block exists, the same atomic write also flips
    ``mcpServers.mureo.env.MUREO_DISABLE_<PLATFORM>=1`` so the mureo MCP
    server auto-disables its native tool family for that platform. When
    no mureo block exists, the provider is registered as before and a
    degraded coexistence note is emitted instead.
    """
    if spec.install_kind == "hosted_http":
        # Meta's hosted MCP has no Dynamic Client Registration, so it
        # CANNOT be OAuth-authenticated as a Claude Code user-scope
        # server (`/mcp` fails: "redirect_uris are not registered for
        # this client"). mureo therefore does NOT register it locally —
        # the only working Claude Code path is a Claude.ai account
        # connector. We print those steps and do not touch
        # ~/.claude.json. mureo-native Meta is left active (no-strand);
        # it steps aside only via `providers confirm` once the connector
        # is verified Connected.
        if dry_run:
            typer.echo(
                f"[dry-run] {spec.id}: would NOT register locally "
                f"(Meta has no dynamic client registration); add it via "
                f"a Claude.ai connector instead (no native auto-disable)"
            )
            _emit_hosted_auth_notice(spec, dry_run=True)
            return True
        _emit_hosted_auth_notice(spec, dry_run=False)
        return True

    if dry_run:
        _dry_run_preview(spec)
        # In dry-run we don't know whether a mureo block is on disk —
        # assume the common case (present) for the message.
        _emit_coexistence(spec, mureo_block_present=True)
        return True

    result = run_install(spec, dry_run=False)
    if result.returncode != 0:
        typer.echo(
            f"error: install failed for {spec.id} "
            f"(returncode={result.returncode}): {result.stderr.strip()}",
            err=True,
        )
        return False

    mureo_block_present = _register_provider(spec)
    typer.echo(f"installed {spec.id}")
    _emit_coexistence(spec, mureo_block_present=mureo_block_present)
    return True


def _register_provider(spec: ProviderSpec) -> bool:
    """Write the ``mcpServers`` entry (plus disable env var if applicable).

    Returns ``True`` if a ``mcpServers.mureo`` block was present in the
    settings file (so the auto-disable env var was written too), ``False``
    otherwise. When there is no coexistence overlap, returns ``True`` (the
    coexistence message is not emitted anyway).
    """
    if spec.coexists_with_mureo_platform is None:
        add_provider_to_claude_settings(spec)
        return True

    # Single atomic write covering both the new provider block AND the
    # disable env var on mureo's block (when present).
    add_provider_and_disable_in_mureo(spec)
    # Re-read to determine whether the mureo block was actually present —
    # ``add_provider_and_disable_in_mureo`` doesn't surface that flag (it
    # returns an ``AddResult`` because both writes share one ``os.replace``).
    return _mureo_block_exists()


def _mureo_block_exists() -> bool:
    """Return True iff ``mcpServers.mureo`` exists in the default settings file."""
    from mureo.providers.config_writer import (
        _default_settings_path,
        _load_existing,
    )

    target = _default_settings_path()
    if not target.exists():
        return False
    try:
        existing = _load_existing(target)
    except Exception:  # noqa: BLE001 — defensive: degraded message is acceptable
        return False
    mcp_servers = existing.get("mcpServers")
    return isinstance(mcp_servers, dict) and isinstance(mcp_servers.get("mureo"), dict)


@providers_app.command("list")
def list_cmd() -> None:
    """List every official MCP provider and its installation status."""
    _render_list()


def _add_single_provider(provider_id: str, *, dry_run: bool) -> int:
    """Resolve ``provider_id`` and install just that one provider.

    Returns the exit code: 0 on success, 1 on install failure, 2 on unknown id.
    """
    try:
        spec = get_provider(provider_id)
    except KeyError:
        valid = ", ".join(s.id for s in CATALOG)
        typer.echo(
            f"error: unknown provider {provider_id!r}. valid ids: {valid}",
            err=True,
        )
        return 2

    ok = _add_one(spec, dry_run=dry_run)
    return 0 if ok else 1


def _add_all_providers(*, dry_run: bool) -> int:
    """Install every entry in ``CATALOG``, continuing past per-entry failures.

    Returns 0 when every install succeeded, 1 if any failed (with failure ids
    printed to stderr).
    """
    failures: list[str] = []
    for spec in CATALOG:
        if not _add_one(spec, dry_run=dry_run):
            failures.append(spec.id)
    if failures:
        typer.echo(
            f"error: install failed for: {', '.join(failures)}",
            err=True,
        )
        return 1
    return 0


@providers_app.command("add")
def add_cmd(
    provider_id: str | None = typer.Argument(
        None,
        help="Catalog id to install (e.g. 'google-ads-official'). Omit when using --all.",
    ),
    all_: bool = typer.Option(
        False,
        "--all",
        help="Install every entry in the catalog.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the planned subprocess argv and JSON delta without executing.",
    ),
) -> None:
    """Install one provider (or all of them with ``--all``)."""
    if all_:
        if provider_id is not None:
            typer.echo(
                "error: provide either <id> or --all, not both.",
                err=True,
            )
            raise typer.Exit(code=2)
        code = _add_all_providers(dry_run=dry_run)
    else:
        if provider_id is None:
            typer.echo(
                "error: provider id is required (or pass --all).",
                err=True,
            )
            raise typer.Exit(code=2)
        code = _add_single_provider(provider_id, dry_run=dry_run)

    if code != 0:
        raise typer.Exit(code=code)


@providers_app.command("remove")
def remove_cmd(
    provider_id: str = typer.Argument(
        ...,
        help=(
            "Catalog id to remove from ~/.claude/settings.json. "
            "Does not uninstall the underlying pipx/npm package "
            "(no-op for hosted-HTTP providers, which have none). "
            "If the provider overlaps with a mureo-native platform, the "
            "matching MUREO_DISABLE_* env var on mcpServers.mureo.env is "
            "also popped so mureo's tools re-register on next startup."
        ),
    ),
) -> None:
    """Remove a provider's ``mcpServers`` entry from Claude Code settings."""
    try:
        spec = get_provider(provider_id)
    except KeyError:
        valid = ", ".join(s.id for s in CATALOG)
        typer.echo(
            f"error: unknown provider {provider_id!r}. valid ids: {valid}",
            err=True,
        )
        raise typer.Exit(code=2) from None

    result = remove_provider_from_claude_settings(provider_id)
    if result.changed:
        typer.echo(f"removed {provider_id} from ~/.claude/settings.json")
    else:
        typer.echo(f"{provider_id} was not registered; nothing to remove")

    # Pop the matching MUREO_DISABLE_* env var so mureo's native tools
    # re-register on next startup. No-op when the spec doesn't overlap
    # with a mureo-native platform or when the env var is absent.
    platform = spec.coexists_with_mureo_platform
    if platform is not None:
        env_result = unset_mureo_disable_env(platform)
        if env_result.changed:
            env_var = f"MUREO_DISABLE_{platform.upper()}"
            typer.echo(
                f"cleared mcpServers.mureo.env.{env_var}; "
                f"mureo's native tools for this platform will re-register"
            )


@providers_app.command("confirm")
def confirm_cmd(
    provider_id: str = typer.Argument(
        ...,
        help=(
            "Hosted provider id (e.g. meta-ads-official) to confirm. "
            "Once its account-level Connector shows Connected in "
            "`claude mcp list`, this disables the overlapping "
            "mureo-native tool family (MUREO_DISABLE_<PLATFORM>=1) so the "
            "model stops calling the credential-less native tools."
        ),
    ),
) -> None:
    """Switch mureo-native tools off ONCE the official hosted connector works.

    A ``hosted_http`` provider (Meta) can only be wired via Claude's
    account-level Connectors, authorised by a one-time browser OAuth that
    mureo cannot perform. We never auto-disable native before that — it
    would strand the user. This command is the explicit, safe follow-up:
    it disables native only after verifying the connector is actually
    Connected.
    """
    try:
        spec = get_provider(provider_id)
    except KeyError:
        valid = ", ".join(s.id for s in CATALOG)
        typer.echo(
            f"error: unknown provider {provider_id!r}. valid ids: {valid}",
            err=True,
        )
        raise typer.Exit(code=2) from None

    if spec.install_kind != "hosted_http":
        typer.echo(
            f"error: confirm only applies to hosted providers; "
            f"{provider_id!r} is install_kind={spec.install_kind!r} "
            f"(it is registered directly by `mureo providers add`).",
            err=True,
        )
        raise typer.Exit(code=2)

    platform = spec.coexists_with_mureo_platform
    if platform is None:
        typer.echo(
            f"{provider_id}: no overlapping mureo-native platform; "
            f"nothing to switch."
        )
        return

    if not is_hosted_provider_connected(spec):
        url = spec.mcp_server_config.get("url", "")
        typer.echo(
            f"{provider_id}: not detected as Connected yet.\n"
            f"Finish the one-time browser setup first — add the Meta Ads "
            f"connector in Claude's Connectors (claude.ai → Settings → "
            f"Connectors), sign in with Meta, then verify with "
            f"`claude mcp list` (look for {url} … ✓ Connected) and re-run "
            f"this command.",
            err=True,
        )
        raise typer.Exit(code=1)

    env_result = set_mureo_disable_env(platform)
    env_var = f"MUREO_DISABLE_{platform.upper()}"
    if env_result.changed:
        typer.echo(
            f"{provider_id} confirmed Connected. Set "
            f'mcpServers.mureo.env.{env_var}="1" — mureo-native '
            f"{platform} tools are now disabled so the model uses the "
            f"official connector. Restart Claude to apply."
        )
    elif env_result.mureo_block_present:
        typer.echo(
            f"{provider_id} confirmed Connected; "
            f"mcpServers.mureo.env.{env_var} was already set. Nothing to do."
        )
    else:
        typer.echo(
            f"{provider_id} confirmed Connected, but no mcpServers.mureo "
            f"block was found. Run `mureo setup claude-code` first, then "
            f"re-run this command to disable native {platform}."
        )
