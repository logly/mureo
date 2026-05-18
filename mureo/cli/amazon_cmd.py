"""Amazon Ads (official-MCP bridge) CLI — #113 Phase 1.

``mureo amazon refresh-manifest`` performs the one-time (repeatable)
authenticated discovery: it connects to the region endpoint using the
``amazon_ads`` credentials in ``~/.mureo/credentials.json``, lists
Amazon's MCP tools, and writes ``~/.mureo/amazon_tools.json``. The
mureo MCP server then reads that manifest at start (pure, no network)
to expose the Amazon tools through mureo's safety layer.
"""

from __future__ import annotations

import typer

from mureo.amazon_ads.manifest import generate_manifest_sync
from mureo.auth import load_amazon_ads_credentials
from mureo.mcp.plugin_audit import _scrub as _scrub_secrets

amazon_app = typer.Typer(name="amazon", help="Amazon Ads official-MCP bridge setup")


@amazon_app.command("refresh-manifest")
def refresh_manifest() -> None:
    """Discover Amazon's MCP tools and (re)write the local manifest.

    Requires an ``amazon_ads`` section in ~/.mureo/credentials.json
    (client_id + access_token, plus region/account_mode). Re-run this
    whenever the access token is renewed or the tool surface changes.
    """
    creds = load_amazon_ads_credentials()
    if creds is None:
        typer.echo(
            "amazon_ads credentials not found in ~/.mureo/credentials.json. "
            "Add the amazon_ads section (client_id, access_token, region) "
            "first — see docs/amazon-ads.md.",
            err=True,
        )
        raise typer.Exit(1)
    try:
        path = generate_manifest_sync(creds)
    except Exception as exc:  # noqa: BLE001 — surface a clean CLI error
        typer.echo(
            f"Failed to refresh the Amazon tool manifest "
            f"(region={creds.region}): {type(exc).__name__}: "
            f"{_scrub_secrets(str(exc))}",
            err=True,
        )
        raise typer.Exit(1) from None
    typer.echo(f"Wrote Amazon tool manifest: {path}")
