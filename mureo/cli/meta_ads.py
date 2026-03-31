"""Meta Ads subcommands.

Defines commands such as ``mureo meta-ads campaigns-list``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from mureo.auth import (
    MetaAdsCredentials,
    create_meta_ads_client,
    load_meta_ads_credentials,
)

meta_ads_app = typer.Typer(name="meta-ads", help="Meta Ads operations")

# Days -> Meta API date_preset mapping
_DAYS_TO_PERIOD: dict[int, str] = {
    1: "yesterday",
    7: "last_7d",
    30: "last_30d",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_creds() -> MetaAdsCredentials:
    """Load credentials or exit with an error if not found."""
    creds = load_meta_ads_credentials()
    if creds is None:
        typer.echo("Error: Meta Ads credentials not found", err=True)
        raise typer.Exit(1)
    return creds


def _output(data: Any) -> None:
    """Output results in JSON format."""
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@meta_ads_app.command("campaigns-list")  # type: ignore[untyped-decorator, unused-ignore]
def campaigns_list(
    account_id: str = typer.Option(
        ..., "--account-id", help="Meta Ads account ID (act_XXXX)"
    ),
) -> None:
    """List Meta Ads campaigns."""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.list_campaigns())
    _output(result)


@meta_ads_app.command("campaigns-get")  # type: ignore[untyped-decorator, unused-ignore]
def campaigns_get(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
    campaign_id: str = typer.Option(..., "--campaign-id", help="Campaign ID"),
) -> None:
    """Get Meta Ads campaign details."""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.get_campaign(campaign_id))
    _output(result)


@meta_ads_app.command("ad-sets-list")  # type: ignore[untyped-decorator, unused-ignore]
def ad_sets_list(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
) -> None:
    """List ad sets."""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.list_ad_sets())
    _output(result)


@meta_ads_app.command("ads-list")  # type: ignore[untyped-decorator, unused-ignore]
def ads_list(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
) -> None:
    """List ads."""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.list_ads())
    _output(result)


@meta_ads_app.command("insights-report")  # type: ignore[untyped-decorator, unused-ignore]
def insights_report(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
    days: int = typer.Option(7, "--days", help="Report period (days)"),
) -> None:
    """Get performance report."""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    period = _DAYS_TO_PERIOD.get(days, f"last_{days}d")
    result = asyncio.run(client.get_performance_report(period=period))
    _output(result)
