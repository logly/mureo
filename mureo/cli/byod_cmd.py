"""``mureo byod`` CLI subcommands: import / status / remove / clear.

Drop a CSV exported from Google Ads / Meta Ads / Search Console into
mureo and analyse it locally — no OAuth, no developer token, no SaaS.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TCH003 (used at runtime by typer)

import typer

from mureo.byod.installer import (
    BYODImportError,
    clear_all,
    import_csv,
    remove_platform,
)
from mureo.byod.runtime import (
    SUPPORTED_PLATFORMS,
    byod_data_dir,
    read_manifest,
)

byod_app = typer.Typer(
    name="byod",
    help=(
        "Bring Your Own Data — analyse your real ad-account CSV exports "
        "locally, no credentials required."
    ),
    no_args_is_help=True,
)


def _resolve_platform_flag(
    google_ads: bool,
    meta_ads: bool,
    search_console: bool,
    as_: str | None,
) -> str | None:
    flags = {
        "google_ads": google_ads,
        "meta_ads": meta_ads,
        "search_console": search_console,
    }
    explicit = [p for p, v in flags.items() if v]
    if as_:
        if as_ not in SUPPORTED_PLATFORMS:
            raise typer.BadParameter(
                f"--as must be one of {sorted(SUPPORTED_PLATFORMS)}"
            )
        explicit.append(as_)
    if len(explicit) > 1:
        raise typer.BadParameter(
            "Pass at most one of --google-ads / --meta-ads / "
            "--search-console / --as <platform>."
        )
    return explicit[0] if explicit else None


def _print_status_block() -> None:
    manifest = read_manifest()
    typer.echo("Mode summary:")
    if not manifest:
        typer.echo(
            "  No BYOD data installed. mureo will use real API for all platforms."
        )
        return
    active = manifest["platforms"]
    for p in SUPPORTED_PLATFORMS:
        if p in active:
            info = active[p]
            typer.echo(
                f"  {p:15s} BYOD ({info.get('rows', '?')} rows, "
                f"{info['date_range']['start']}..{info['date_range']['end']})"
            )
        else:
            typer.echo(
                f"  {p:15s} not imported -> real API "
                "(requires ~/.mureo/credentials.json)"
            )


@byod_app.command("import")  # type: ignore[untyped-decorator, unused-ignore]
def import_(
    file: Path = typer.Argument(  # noqa: B008
        ..., exists=True, dir_okay=False, readable=True
    ),
    google_ads: bool = typer.Option(
        False, "--google-ads", help="Source is a Google Ads CSV export"
    ),
    meta_ads: bool = typer.Option(
        False, "--meta-ads", help="Source is a Meta Ads CSV export"
    ),
    search_console: bool = typer.Option(
        False, "--search-console", help="Source is a Search Console CSV export"
    ),
    as_: str = typer.Option(
        None,
        "--as",
        help="Override platform auto-detection (google_ads / meta_ads / search_console)",
    ),
    replace: bool = typer.Option(
        False,
        "--replace",
        help="Overwrite existing BYOD data for this platform",
    ),
) -> None:
    """Import a CSV export into ~/.mureo/byod/<platform>/."""
    platform = _resolve_platform_flag(google_ads, meta_ads, search_console, as_)
    try:
        entry = import_csv(file, platform=platform, replace=replace)
    except BYODImportError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    # Find the platform key from the freshly written manifest.
    manifest = read_manifest()
    actual_platform = "?"
    if manifest:
        for p, info in manifest["platforms"].items():
            if info.get("source_file_sha256") == entry.get("source_file_sha256"):
                actual_platform = p
                break

    typer.echo("=== mureo byod import ===\n")
    typer.echo(f"  Detected format: {entry['source_format']}")
    typer.echo(
        f"  Validated {entry['rows']} rows, "
        f"date range {entry['date_range']['start']} to "
        f"{entry['date_range']['end']}"
    )
    typer.echo(f"  Normalized to {byod_data_dir() / actual_platform}/")
    for f in entry["files"]:
        typer.echo(f"    - {f}")
    typer.echo("")
    _print_status_block()
    typer.echo("\nNext: ask Claude Code: 'Run /daily-check'")


@byod_app.command("status")  # type: ignore[untyped-decorator, unused-ignore]
def status() -> None:
    """Show which platforms are in BYOD mode vs real-API mode."""
    typer.echo("=== mureo byod status ===\n")
    _print_status_block()


@byod_app.command("remove")  # type: ignore[untyped-decorator, unused-ignore]
def remove(
    google_ads: bool = typer.Option(False, "--google-ads"),
    meta_ads: bool = typer.Option(False, "--meta-ads"),
    search_console: bool = typer.Option(False, "--search-console"),
) -> None:
    """Remove BYOD data for a single platform."""
    flags = {
        "google_ads": google_ads,
        "meta_ads": meta_ads,
        "search_console": search_console,
    }
    chosen = [p for p, v in flags.items() if v]
    if len(chosen) != 1:
        typer.echo(
            "Pass exactly one of --google-ads / --meta-ads / --search-console.",
            err=True,
        )
        raise typer.Exit(code=1)
    platform = chosen[0]
    removed = remove_platform(platform)
    if not removed:
        typer.echo(f"Nothing to remove (no BYOD data for {platform}).")
        return
    typer.echo(f"Removed BYOD data for {platform}.")
    typer.echo("")
    _print_status_block()


@byod_app.command("clear")  # type: ignore[untyped-decorator, unused-ignore]
def clear(
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Remove all BYOD data at ~/.mureo/byod/."""
    target = byod_data_dir()
    if not target.exists():
        typer.echo(f"No BYOD data to remove ({target} does not exist).")
        return
    if not yes:
        confirm = typer.confirm(f"Remove {target} and all BYOD data?", default=False)
        if not confirm:
            typer.echo("Aborted.")
            return
    if clear_all():
        typer.echo(f"Removed {target}")
    else:
        typer.echo(f"Nothing removed ({target} did not exist)")
