"""Amazon Ads (official-MCP bridge) CLI — #113 Phase 1.

``mureo amazon refresh-manifest`` performs the one-time (repeatable)
authenticated discovery: it connects to the region endpoint using the
``amazon_ads`` credentials in ``~/.mureo/credentials.json``, lists
Amazon's MCP tools, and writes ``~/.mureo/amazon_tools.json``. The
mureo MCP server then reads that manifest at start (pure, no network)
to expose the Amazon tools through mureo's safety layer.

Two things happen before the connection:

- the CURRENT manifest's age is reported, so the operator can see
  whether this is a routine refresh or a long-overdue one (audit #47);
- when only the durable LwA material is stored (``refresh_token`` +
  ``client_secret``, the recommended setup), an access token is minted
  and persisted first (audit #49). Without that this command sent an
  empty bearer token and 401'd against a perfectly valid configuration
  — on the very first command an operator runs.
"""

from __future__ import annotations

import dataclasses

import typer

from mureo.amazon_ads.lwa import AmazonAuthError, refresh_access_token
from mureo.amazon_ads.manifest import (
    generate_manifest_sync,
    is_stale,
    manifest_age_days,
    manifest_max_age_days,
    manifest_path,
)
from mureo.auth import (
    AmazonAdsCredentials,
    load_amazon_ads_credentials,
    save_amazon_access_token,
)
from mureo.core.atomic_json import ConfigWriteError
from mureo.mcp.plugin_audit import _scrub as _scrub_secrets

amazon_app = typer.Typer(name="amazon", help="Amazon Ads official-MCP bridge setup")


def _echo_manifest_age() -> None:
    """Report how old the manifest being replaced is (never raises)."""
    path = manifest_path()
    if not path.exists():
        typer.echo("No existing Amazon tool manifest; generating the first one.")
        return
    age = manifest_age_days(path)
    if age is None:
        typer.echo(
            "An Amazon tool manifest exists but its age is unknown "
            "(no usable generated_at); refreshing it."
        )
        return
    line = f"Existing Amazon tool manifest is {age:.1f} days old."
    if is_stale(age):
        line += (
            f" That is past the {manifest_max_age_days():.0f}-day staleness "
            f"threshold — refreshing is overdue."
        )
    typer.echo(line)


def _ensure_access_token(creds: AmazonAdsCredentials) -> AmazonAdsCredentials:
    """Mint + persist an access token when only durable LwA material is stored.

    The dispatch path already does this before its first forwarded call; this
    command did not, so the recommended refresh-token-only setup made it send
    an empty bearer token and fail with Amazon's 401 instead of mureo's own
    message. Exactly one LwA exchange, never a loop — a failure exits rather
    than retrying.
    """
    if creds.access_token:
        return creds
    if not (creds.refresh_token and creds.client_secret):
        typer.echo(
            "no amazon_ads access_token is stored, and there is no "
            "refresh_token + client_secret pair to mint one from. Add them "
            "(or paste an access_token) in the configure UI's Amazon Ads "
            "card, via the AMAZON_ADS_* env vars, or in "
            "~/.mureo/credentials.json — see docs/amazon-ads.md.",
            err=True,
        )
        raise typer.Exit(1)
    try:
        tokens = refresh_access_token(creds)
    except AmazonAuthError as exc:
        typer.echo(
            f"no amazon_ads access_token is stored and one could not be "
            f"obtained from the refresh token: {_scrub_secrets(str(exc))}",
            err=True,
        )
        raise typer.Exit(1) from None
    try:
        save_amazon_access_token(tokens.access_token, tokens.refresh_token)
    except (ConfigWriteError, OSError) as exc:
        # Fatal, mirroring the bridge: the new token is valid but not on disk,
        # so every later call would re-mint against a refresh token Amazon has
        # already rotated. The underlying reason (typically a malformed
        # credentials.json mureo deliberately refuses to overwrite) is what the
        # operator needs to fix.
        typer.echo(
            f"Amazon access token was minted but could not be saved to "
            f"~/.mureo/credentials.json: {_scrub_secrets(str(exc))}",
            err=True,
        )
        raise typer.Exit(1) from None
    typer.echo("Minted a fresh Amazon access token from the stored refresh token.")
    return dataclasses.replace(
        creds,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )


@amazon_app.command("refresh-manifest")
def refresh_manifest() -> None:
    """Discover Amazon's MCP tools and (re)write the local manifest.

    Requires an ``amazon_ads`` section in ~/.mureo/credentials.json
    (client_id plus either an access_token or the refresh_token +
    client_secret pair mureo mints one from, along with
    region/account_mode). Re-run this whenever the tool surface changes.
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
    _echo_manifest_age()
    creds = _ensure_access_token(creds)
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
