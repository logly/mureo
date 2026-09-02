"""Authentication management commands

``mureo auth status`` / ``mureo auth check-google`` / ``mureo auth check-meta``
/ ``mureo auth check-amazon``
"""

from __future__ import annotations

import json

import typer

from mureo.auth import (
    AmazonAdsCredentials,
    MetaAdsCredentials,
    load_amazon_ads_credentials,
    load_google_ads_credentials,
    load_meta_ads_credentials,
)

auth_app = typer.Typer(name="auth", help="Authentication management")

# Where an operator actually finishes the Amazon setup. Amazon has no
# terminal OAuth flow of its own (its credentials are LwA material entered
# in the configure UI's Amazon card), so every Amazon auth surface points
# here rather than offering a prompt that cannot complete.
_AMAZON_SETUP_HINT = "Configure it from the Amazon Ads card in `mureo configure`."
#: The step that turns saved Amazon credentials into usable tools.
_AMAZON_NEXT_STEP = "mureo amazon refresh-manifest"


def _amazon_token_shape(creds: AmazonAdsCredentials) -> str:
    """Describe HOW usable an Amazon credential set is.

    A stored access token works until it expires and then needs manual
    replacement; the refresh-token + client-secret pair lets mureo mint a
    fresh one on demand. The operator needs to know which one they have.
    """
    if creds.refresh_token and creds.client_secret:
        return (
            "access token + refresh token stored"
            if creds.access_token
            else "refresh token stored (access token minted automatically)"
        )
    return "access token stored (no refresh pair — renew it manually)"


def _meta_token_lifetime(creds: MetaAdsCredentials) -> str:
    """How long the stored Meta token has, as a suffix for the status line.

    Three states, and only two of them are facts worth printing. Meta
    reports a token issued without an expiry as permanent, which mureo
    records as ``token_never_expires`` and never renews (#740) — that
    outranks any date left on record, because it is Graph's own verdict
    about the token on disk. Otherwise the expiry the paste card learned is
    shown as a plain date. An unknown expiry prints nothing: mureo simply
    never asked, and inventing a countdown from the obtained-at stamp is
    what the age clock already gets wrong for a system-user token.
    """

    if creds.token_never_expires:
        return " (token does not expire)"
    raw = creds.token_expires_at
    if isinstance(raw, str) and raw.strip():
        return f" (expires {raw.strip()[:10]})"
    return ""


@auth_app.command("status")  # type: ignore[untyped-decorator, unused-ignore]
def auth_status() -> None:
    """Display authentication status."""
    google_creds = load_google_ads_credentials()
    meta_creds = load_meta_ads_credentials()
    amazon_creds = load_amazon_ads_credentials()

    typer.echo("=== Authentication Status ===")
    typer.echo("")

    if google_creds is not None:
        cid = google_creds.customer_id or google_creds.login_customer_id or "not set"
        login_cid = google_creds.login_customer_id or cid
        if login_cid != cid:
            typer.echo(
                f"Google Ads: Authenticated (customer_id: {cid}, "
                f"login_customer_id: {login_cid})"
            )
        else:
            typer.echo(f"Google Ads: Authenticated (customer_id: {cid})")
    else:
        typer.echo("Google Ads: Not authenticated")

    if meta_creds is not None:
        aid = meta_creds.account_id or "not set"
        typer.echo(
            f"Meta Ads: Authenticated (account_id: {aid})"
            f"{_meta_token_lifetime(meta_creds)}"
        )
    else:
        typer.echo("Meta Ads: Not authenticated")

    if amazon_creds is not None:
        typer.echo(
            f"Amazon Ads: Authenticated (region: {amazon_creds.region}, "
            f"{_amazon_token_shape(amazon_creds)})"
        )
    else:
        typer.echo("Amazon Ads: Not authenticated")


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
        "customer_id": creds.customer_id,
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


@auth_app.command("check-amazon")  # type: ignore[untyped-decorator, unused-ignore]
def check_amazon() -> None:
    """Check Amazon Ads credentials.

    Local read only — the same depth as ``check-google`` / ``check-meta``:
    it never contacts Amazon. Reaching this point means the credentials
    are USABLE (the loader returns ``None`` for a half-filled section), so
    the report also names the step that turns them into working tools.
    """
    creds = load_amazon_ads_credentials()
    if creds is None:
        typer.echo(
            f"Error: Amazon Ads credentials not found. {_AMAZON_SETUP_HINT}", err=True
        )
        raise typer.Exit(1)

    info = {
        "client_id": creds.client_id,
        "access_token": _mask(creds.access_token) if creds.access_token else None,
        "refresh_token": _mask(creds.refresh_token) if creds.refresh_token else None,
        "client_secret": _mask(creds.client_secret) if creds.client_secret else None,
        "region": creds.region,
        "account_mode": creds.account_mode,
        "profile_id": creds.profile_id,
        "account_id": creds.account_id,
        "manager_account_id": creds.manager_account_id,
        "token_status": _amazon_token_shape(creds),
        "next_step": _AMAZON_NEXT_STEP,
    }
    typer.echo(json.dumps(info, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@auth_app.command("setup")  # type: ignore[untyped-decorator, unused-ignore]
def auth_setup() -> None:
    """Interactive setup wizard (terminal)."""
    import asyncio

    typer.echo("=== mureo Setup Wizard ===")
    typer.echo("")
    # Amazon Ads gets no prompt here on purpose: it authenticates with
    # Login-with-Amazon material that is entered (and validated) in the
    # configure UI's Amazon Ads card, not through a terminal OAuth dance.
    # Say so instead of leaving the platform unmentioned.
    typer.echo(f"Amazon Ads: {_AMAZON_SETUP_HINT}")
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
        customer_id=creds.customer_id,
    )

    save_credentials(google=updated_creds)

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
