"""Google Ads subcommands.

Defines commands such as ``mureo google-ads campaigns-list``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from mureo.auth import (
    GoogleAdsCredentials,
    create_google_ads_client,
    load_google_ads_credentials,
)

google_ads_app = typer.Typer(name="google-ads", help="Google Ads operations")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_creds() -> GoogleAdsCredentials:
    """Load credentials or exit with an error if not found."""
    creds = load_google_ads_credentials()
    if creds is None:
        typer.echo("Error: Google Ads credentials not found", err=True)
        raise typer.Exit(1)
    return creds


def _output(data: Any) -> None:
    """Output results in JSON format."""
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@google_ads_app.command("campaigns-list")  # type: ignore[untyped-decorator, unused-ignore]
def campaigns_list(
    customer_id: str = typer.Option(
        ..., "--customer-id", help="Google Ads customer ID"
    ),
) -> None:
    """List Google Ads campaigns."""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.list_campaigns())
    _output(result)


@google_ads_app.command("campaigns-get")  # type: ignore[untyped-decorator, unused-ignore]
def campaigns_get(
    customer_id: str = typer.Option(
        ..., "--customer-id", help="Google Ads customer ID"
    ),
    campaign_id: str = typer.Option(..., "--campaign-id", help="Campaign ID"),
) -> None:
    """Get Google Ads campaign details."""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.get_campaign(campaign_id))
    _output(result)


@google_ads_app.command("ads-list")  # type: ignore[untyped-decorator, unused-ignore]
def ads_list(
    customer_id: str = typer.Option(
        ..., "--customer-id", help="Google Ads customer ID"
    ),
    ad_group_id: str = typer.Option(..., "--ad-group-id", help="Ad group ID"),
) -> None:
    """List ads."""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.list_ads(ad_group_id=ad_group_id))
    _output(result)


@google_ads_app.command("keywords-list")  # type: ignore[untyped-decorator, unused-ignore]
def keywords_list(
    customer_id: str = typer.Option(
        ..., "--customer-id", help="Google Ads customer ID"
    ),
    ad_group_id: str = typer.Option(..., "--ad-group-id", help="Ad group ID"),
) -> None:
    """List keywords."""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.list_keywords(ad_group_id=ad_group_id))
    _output(result)


@google_ads_app.command("budget-get")  # type: ignore[untyped-decorator, unused-ignore]
def budget_get(
    customer_id: str = typer.Option(
        ..., "--customer-id", help="Google Ads customer ID"
    ),
    campaign_id: str = typer.Option(..., "--campaign-id", help="Campaign ID"),
) -> None:
    """Get campaign budget."""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.get_budget(campaign_id))
    _output(result)


@google_ads_app.command("performance-report")  # type: ignore[untyped-decorator, unused-ignore]
def performance_report(
    customer_id: str = typer.Option(
        ..., "--customer-id", help="Google Ads customer ID"
    ),
    days: int = typer.Option(7, "--days", help="Report period (days)"),
) -> None:
    """Get performance report."""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.get_performance_report(days=days))  # type: ignore[call-arg]
    _output(result)
