"""Authentication management commands

``mureo auth status`` / ``mureo auth check-google`` / ``mureo auth check-meta``
"""

from __future__ import annotations

import json

import typer

from mureo.auth import load_google_ads_credentials, load_meta_ads_credentials

auth_app = typer.Typer(name="auth", help="Authentication management")


@auth_app.command("status")  # type: ignore[untyped-decorator, unused-ignore]
def auth_status() -> None:
    """Display authentication status."""
    google_creds = load_google_ads_credentials()
    meta_creds = load_meta_ads_credentials()

    typer.echo("=== Authentication Status ===")
    typer.echo("")

    if google_creds is not None:
        cid = google_creds.login_customer_id or "not set"
        typer.echo(f"Google Ads: Authenticated (customer_id: {cid})")
    else:
        typer.echo("Google Ads: Not authenticated")

    if meta_creds is not None:
        aid = meta_creds.account_id or "not set"
        typer.echo(f"Meta Ads: Authenticated (account_id: {aid})")
    else:
        typer.echo("Meta Ads: Not authenticated")


@auth_app.command("check-google")  # type: ignore[untyped-decorator, unused-ignore]
def check_google() -> None:
    """Check Google Ads credentials."""
    creds = load_google_ads_credentials()
    if creds is None:
        typer.echo("Error: Google Ads credentials not found", err=True)
        raise typer.Exit(1)

    # Display with masked secret parts
    info = {
        "developer_token": _mask(creds.developer_token),
        "client_id": creds.client_id,
        "client_secret": _mask(creds.client_secret),
        "refresh_token": _mask(creds.refresh_token),
        "login_customer_id": creds.login_customer_id,
    }
    typer.echo(json.dumps(info, indent=2, ensure_ascii=False))


@auth_app.command("check-meta")  # type: ignore[untyped-decorator, unused-ignore]
def check_meta() -> None:
    """Check Meta Ads credentials."""
    creds = load_meta_ads_credentials()
    if creds is None:
        typer.echo("Error: Meta Ads credentials not found", err=True)
        raise typer.Exit(1)

    info = {
        "access_token": _mask(creds.access_token),
        "app_id": creds.app_id,
        "app_secret": _mask(creds.app_secret) if creds.app_secret else None,
    }
    typer.echo(json.dumps(info, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@auth_app.command("setup")  # type: ignore[untyped-decorator, unused-ignore]
def auth_setup() -> None:
    """Interactive setup wizard."""
    import asyncio

    typer.echo("=== mureo Setup Wizard ===")
    typer.echo("")

    google = typer.confirm("Configure Google Ads?", default=True)
    meta = typer.confirm("Configure Meta Ads?", default=True)

    if google:
        from mureo.auth_setup import setup_google_ads

        asyncio.run(setup_google_ads())

    if meta:
        from mureo.auth_setup import setup_meta_ads

        asyncio.run(setup_meta_ads())

    if not google and not meta:
        typer.echo("Setup skipped.")
        return

    # MCP configuration deployment
    from mureo.auth_setup import setup_mcp_config

    setup_mcp_config()

    # Credential guard hook
    from mureo.auth_setup import install_credential_guard

    result = install_credential_guard()
    if result is not None:
        typer.echo(f"Credential guard installed: {result}")
        typer.echo("  AI agents are now blocked from reading ~/.mureo/credentials.json")
    else:
        typer.echo("Credential guard already installed.")

    typer.echo("\nSetup complete.")


@auth_app.command("upgrade-google")  # type: ignore[untyped-decorator, unused-ignore]
def auth_upgrade_google() -> None:
    """Re-authenticate Google to add Search Console access.

    Uses existing client_id/client_secret from credentials.json
    to run a new OAuth flow with expanded scopes (Google Ads +
    Search Console). The new refresh_token replaces the old one.
    """
    import asyncio

    from mureo.auth import load_google_ads_credentials
    from mureo.auth_setup import run_google_oauth, save_credentials

    creds = load_google_ads_credentials()
    if creds is None:
        typer.echo(
            "Error: Google Ads credentials not found. Run mureo auth setup first."
        )
        raise typer.Exit(1)

    typer.echo("=== Upgrade Google OAuth Scopes ===")
    typer.echo("")
    typer.echo("This will open a browser to re-authenticate with Google.")
    typer.echo(
        "Your existing credentials (Developer Token, Client ID, etc.) are preserved."
    )
    typer.echo("Only the refresh_token will be updated with expanded scopes")
    typer.echo("(Google Ads + Search Console).")
    typer.echo("")

    oauth_result = asyncio.run(
        run_google_oauth(
            client_id=creds.client_id,
            client_secret=creds.client_secret,
        )
    )

    from mureo.auth import GoogleAdsCredentials

    updated_creds = GoogleAdsCredentials(
        developer_token=creds.developer_token,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        refresh_token=oauth_result.refresh_token,
        login_customer_id=creds.login_customer_id,
    )

    save_credentials(google=updated_creds, customer_id=creds.login_customer_id)

    typer.echo("\nGoogle OAuth scopes upgraded successfully.")
    typer.echo("Search Console access is now available.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask(value: str, visible: int = 4) -> str:
    """Mask all but the last characters of a secret string."""
    if len(value) <= visible:
        return "****"
    return "*" * (len(value) - visible) + value[-visible:]
