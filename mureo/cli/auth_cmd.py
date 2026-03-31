"""認証管理コマンド

``mureo auth status`` / ``mureo auth check-google`` / ``mureo auth check-meta``
"""

from __future__ import annotations

import json

import typer

from mureo.auth import load_google_ads_credentials, load_meta_ads_credentials

auth_app = typer.Typer(name="auth", help="Authentication management")


@auth_app.command("status")  # type: ignore[untyped-decorator, unused-ignore]
def auth_status() -> None:
    """認証状態の表示"""
    google_creds = load_google_ads_credentials()
    meta_creds = load_meta_ads_credentials()

    typer.echo("=== 認証状態 ===")
    typer.echo("")

    if google_creds is not None:
        typer.echo("Google Ads: 認証済み")
    else:
        typer.echo("Google Ads: 未認証")

    if meta_creds is not None:
        typer.echo("Meta Ads: 認証済み")
    else:
        typer.echo("Meta Ads: 未認証")


@auth_app.command("check-google")  # type: ignore[untyped-decorator, unused-ignore]
def check_google() -> None:
    """Google Ads認証情報のチェック"""
    creds = load_google_ads_credentials()
    if creds is None:
        typer.echo("Error: Google Ads認証情報が見つかりません", err=True)
        raise typer.Exit(1)

    # シークレット部分をマスクして表示
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
    """Meta Ads認証情報のチェック"""
    creds = load_meta_ads_credentials()
    if creds is None:
        typer.echo("Error: Meta Ads認証情報が見つかりません", err=True)
        raise typer.Exit(1)

    info = {
        "access_token": _mask(creds.access_token),
        "app_id": creds.app_id,
        "app_secret": _mask(creds.app_secret) if creds.app_secret else None,
    }
    typer.echo(json.dumps(info, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


@auth_app.command("setup")  # type: ignore[untyped-decorator, unused-ignore]
def auth_setup() -> None:
    """対話型セットアップウィザード"""
    import asyncio

    typer.echo("=== mureo セットアップウィザード ===")
    typer.echo("")

    google = typer.confirm("Google Adsを設定しますか？", default=True)
    meta = typer.confirm("Meta Adsを設定しますか？", default=False)

    if google:
        from mureo.auth_setup import setup_google_ads

        asyncio.run(setup_google_ads())

    if meta:
        from mureo.auth_setup import setup_meta_ads

        asyncio.run(setup_meta_ads())

    if not google and not meta:
        typer.echo("セットアップをスキップしました。")
        return

    # MCP設定の配置
    from mureo.auth_setup import setup_mcp_config

    setup_mcp_config()

    typer.echo("\nセットアップが完了しました。")


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _mask(value: str, visible: int = 4) -> str:
    """シークレット文字列の末尾以外をマスクする"""
    if len(value) <= visible:
        return "****"
    return "*" * (len(value) - visible) + value[-visible:]
