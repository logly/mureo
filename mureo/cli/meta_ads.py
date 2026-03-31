"""Meta Adsサブコマンド

``mureo meta-ads campaigns-list`` 等のコマンドを定義する。
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

# 日数 → Meta APIのdate_presetマッピング
_DAYS_TO_PERIOD: dict[int, str] = {
    1: "yesterday",
    7: "last_7d",
    30: "last_30d",
}


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _require_creds() -> MetaAdsCredentials:
    """認証情報を読み込み、なければエラー終了する"""
    creds = load_meta_ads_credentials()
    if creds is None:
        typer.echo("Error: Meta Ads認証情報が見つかりません", err=True)
        raise typer.Exit(1)
    return creds


def _output(data: Any) -> None:
    """結果をJSON形式で出力する"""
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# コマンド
# ---------------------------------------------------------------------------


@meta_ads_app.command("campaigns-list")
def campaigns_list(
    account_id: str = typer.Option(
        ..., "--account-id", help="Meta Ads account ID (act_XXXX)"
    ),
) -> None:
    """Meta Adsキャンペーン一覧を取得"""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.list_campaigns())
    _output(result)


@meta_ads_app.command("campaigns-get")
def campaigns_get(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
    campaign_id: str = typer.Option(..., "--campaign-id", help="Campaign ID"),
) -> None:
    """Meta Adsキャンペーン詳細を取得"""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.get_campaign(campaign_id))
    _output(result)


@meta_ads_app.command("ad-sets-list")
def ad_sets_list(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
) -> None:
    """広告セット一覧を取得"""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.list_ad_sets())
    _output(result)


@meta_ads_app.command("ads-list")
def ads_list(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
) -> None:
    """広告一覧を取得"""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    result = asyncio.run(client.list_ads())
    _output(result)


@meta_ads_app.command("insights-report")
def insights_report(
    account_id: str = typer.Option(..., "--account-id", help="Meta Ads account ID"),
    days: int = typer.Option(7, "--days", help="レポート期間（日数）"),
) -> None:
    """パフォーマンスレポートを取得"""
    creds = _require_creds()
    client = create_meta_ads_client(creds, account_id)
    period = _DAYS_TO_PERIOD.get(days, f"last_{days}d")
    result = asyncio.run(client.get_performance_report(period=period))
    _output(result)
