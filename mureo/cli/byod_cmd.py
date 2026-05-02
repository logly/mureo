"""``mureo byod`` CLI subcommands: import / status / remove / clear.

Drop a Sheet bundle XLSX (exported from the mureo Sheet template) into
mureo and analyse it locally — no OAuth, no developer token, no SaaS.
The Sheet bundle pipeline replaces the per-platform CSV imports the
v0.6 line shipped with.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TCH003 (used at runtime by typer)

import typer

from mureo.byod.bundle import BundleImportError, import_bundle
from mureo.byod.installer import clear_all, remove_platform
from mureo.byod.runtime import (
    SUPPORTED_PLATFORMS,
    byod_data_dir,
    read_manifest,
)

byod_app = typer.Typer(
    name="byod",
    help=(
        "Bring Your Own Data — analyse your real ad-account data locally "
        "by importing a Sheet bundle XLSX, no credentials required."
    ),
    no_args_is_help=True,
)


def _credentials_present() -> bool:
    return (Path.home() / ".mureo" / "credentials.json").exists()


def _print_status_block() -> None:
    manifest = read_manifest()
    creds_ok = _credentials_present()
    typer.echo("Mode summary:")
    if not manifest:
        if creds_ok:
            typer.echo(
                "  No BYOD data installed. mureo will use Live API "
                "(credentials present at ~/.mureo/credentials.json)."
            )
        else:
            typer.echo(
                "  No BYOD data installed and no credentials.json. "
                "Run `mureo byod import <bundle.xlsx>` or `mureo auth setup`."
            )
        return
    active = manifest["platforms"]
    for p in SUPPORTED_PLATFORMS:
        if p in active:
            info = active[p]
            start = info.get("date_range", {}).get("start") or ""
            end = info.get("date_range", {}).get("end") or ""
            range_str = f"{start}..{end}" if (start or end) else "no per-day breakdown"
            typer.echo(
                f"  {p:15s} BYOD ({info.get('rows', '?')} rows, " f"{range_str})"
            )
        else:
            if creds_ok:
                typer.echo(f"  {p:15s} Live API (credentials present)")
            else:
                typer.echo(
                    f"  {p:15s} not configured " "(no BYOD data, no credentials.json)"
                )

    # Surface stale entries from older mureo versions (pre-Phase-1
    # BYOD shipped google_analytics / search_console). Users see a
    # one-line hint pointing at the cleanup command rather than these
    # entries silently lingering on disk.
    stale = [p for p in active if p not in SUPPORTED_PLATFORMS]
    if stale:
        typer.echo(
            f"\nStale BYOD entries from a previous mureo version: "
            f"{', '.join(sorted(stale))}. "
            f"Run `mureo byod clear` or remove them by hand from "
            f"`{byod_data_dir()}`."
        )


@byod_app.command("import")  # type: ignore[untyped-decorator, unused-ignore]
def import_(
    file: Path = typer.Argument(  # noqa: B008
        ..., exists=True, dir_okay=False, readable=True
    ),
    replace: bool = typer.Option(
        False,
        "--replace",
        help="Overwrite existing BYOD data for any platform present " "in the bundle.",
    ),
) -> None:
    """Import a Sheet bundle XLSX into ~/.mureo/byod/.

    The file must be the XLSX export of the mureo Sheet template (see
    ``scripts/sheet-template/README.md``). Each recognized tab is
    dispatched to its adapter and the corresponding
    ``~/.mureo/byod/<platform>/`` directory is populated atomically.

    Recognized tabs:
      - ``campaigns`` / ``ad_groups`` / ``search_terms`` / ``keywords``
        → google_ads
    """
    if file.suffix.lower() not in {".xlsx", ".xlsm"}:
        typer.echo(
            f"Error: {file.name} is not an XLSX file. "
            "mureo byod import only accepts the Sheet bundle XLSX "
            "exported from the mureo Sheet template "
            "(File → Download → Microsoft Excel).",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        results = import_bundle(file, replace=replace)
    except BundleImportError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo("=== mureo byod import ===\n")
    for platform, entry in results.items():
        typer.echo(f"  [{platform}] format: {entry['source_format']}")
        start = entry["date_range"]["start"] or ""
        end = entry["date_range"]["end"] or ""
        range_str = (
            f"date range {start}..{end}"
            if (start or end)
            else "aggregated, no per-day breakdown"
        )
        typer.echo(f"    {entry['rows']} rows, {range_str}")
        typer.echo(f"    written to {byod_data_dir() / platform}/")
        for f in entry["files"]:
            typer.echo(f"      - {f}")
        typer.echo("")
    _print_status_block()
    typer.echo("\nNext: ask Claude Code: 'Run /daily-check'")


@byod_app.command("status")  # type: ignore[untyped-decorator, unused-ignore]
def status() -> None:
    """Show which platforms are in BYOD mode vs Live API mode."""
    typer.echo("=== mureo byod status ===\n")
    _print_status_block()


@byod_app.command("remove")  # type: ignore[untyped-decorator, unused-ignore]
def remove(
    google_ads: bool = typer.Option(False, "--google-ads"),
    meta_ads: bool = typer.Option(False, "--meta-ads"),
) -> None:
    """Remove BYOD data for a single platform."""
    flags = {
        "google_ads": google_ads,
        "meta_ads": meta_ads,
    }
    chosen = [p for p, v in flags.items() if v]
    if len(chosen) != 1:
        typer.echo(
            "Pass exactly one of --google-ads / --meta-ads.",
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
