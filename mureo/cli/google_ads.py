"""Google Adsサブコマンド

``mureo google-ads campaigns-list`` 等のコマンドを定義する。
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
# ヘルパー
# ---------------------------------------------------------------------------


def _require_creds() -> GoogleAdsCredentials:
    """認証情報を読み込み、なければエラー終了する"""
    creds = load_google_ads_credentials()
    if creds is None:
        typer.echo("Error: Google Ads認証情報が見つかりません", err=True)
        raise typer.Exit(1)
    return creds


def _output(data: Any) -> None:
    """結果をJSON形式で出力する"""
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# コマンド
# ---------------------------------------------------------------------------


@google_ads_app.command("campaigns-list")
def campaigns_list(
    customer_id: str = typer.Option(..., "--customer-id", help="Google Ads customer ID"),
) -> None:
    """Google Adsキャンペーン一覧を取得"""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.list_campaigns())
    _output(result)


@google_ads_app.command("campaigns-get")
def campaigns_get(
    customer_id: str = typer.Option(..., "--customer-id", help="Google Ads customer ID"),
    campaign_id: str = typer.Option(..., "--campaign-id", help="Campaign ID"),
) -> None:
    """Google Adsキャンペーン詳細を取得"""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.get_campaign(campaign_id))
    _output(result)


@google_ads_app.command("ads-list")
def ads_list(
    customer_id: str = typer.Option(..., "--customer-id", help="Google Ads customer ID"),
    ad_group_id: str = typer.Option(..., "--ad-group-id", help="Ad group ID"),
) -> None:
    """広告一覧を取得"""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.list_ads(ad_group_id=ad_group_id))
    _output(result)


@google_ads_app.command("keywords-list")
def keywords_list(
    customer_id: str = typer.Option(..., "--customer-id", help="Google Ads customer ID"),
    ad_group_id: str = typer.Option(..., "--ad-group-id", help="Ad group ID"),
) -> None:
    """キーワード一覧を取得"""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.list_keywords(ad_group_id=ad_group_id))
    _output(result)


@google_ads_app.command("budget-get")
def budget_get(
    customer_id: str = typer.Option(..., "--customer-id", help="Google Ads customer ID"),
    campaign_id: str = typer.Option(..., "--campaign-id", help="Campaign ID"),
) -> None:
    """キャンペーン予算を取得"""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.get_budget(campaign_id))
    _output(result)


@google_ads_app.command("performance-report")
def performance_report(
    customer_id: str = typer.Option(..., "--customer-id", help="Google Ads customer ID"),
    days: int = typer.Option(7, "--days", help="レポート期間（日数）"),
) -> None:
    """パフォーマンスレポートを取得"""
    creds = _require_creds()
    client = create_google_ads_client(creds, customer_id)
    result = asyncio.run(client.get_performance_report(days=days))
    _output(result)
