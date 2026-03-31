"""STATE.json の読み書き."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from mureo.context.errors import ContextFileError
from mureo.context.models import CampaignSnapshot, StateDocument

# キャンペーンの必須フィールド
_CAMPAIGN_REQUIRED_FIELDS: tuple[str, ...] = (
    "campaign_id",
    "campaign_name",
    "status",
)


def parse_state(text: str) -> StateDocument:
    """JSON文字列をパースしてStateDocumentを返す."""
    data = json.loads(text)
    campaigns_raw = data.get("campaigns", [])
    campaigns = tuple(_parse_campaign(c) for c in campaigns_raw)
    return StateDocument(
        version=data.get("version", "1"),
        last_synced_at=data.get("last_synced_at"),
        customer_id=data.get("customer_id"),
        campaigns=campaigns,
    )


def _parse_campaign(c: dict[str, Any]) -> CampaignSnapshot:
    """辞書からCampaignSnapshotを生成する（必須フィールドバリデーション付き）."""
    for field_name in _CAMPAIGN_REQUIRED_FIELDS:
        if field_name not in c:
            raise ValueError(
                f"キャンペーンに必須フィールド '{field_name}' がありません: {c}"
            )
    device_targeting_raw = c.get("device_targeting")
    device_targeting: tuple[dict[str, Any], ...] | None = None
    if device_targeting_raw is not None:
        device_targeting = tuple(device_targeting_raw)
    return CampaignSnapshot(
        campaign_id=c["campaign_id"],
        campaign_name=c["campaign_name"],
        status=c["status"],
        bidding_strategy_type=c.get("bidding_strategy_type"),
        bidding_details=c.get("bidding_details"),
        daily_budget=c.get("daily_budget"),
        device_targeting=device_targeting,
        campaign_goal=c.get("campaign_goal"),
        notes=c.get("notes"),
    )


def render_state(doc: StateDocument) -> str:
    """StateDocumentからJSON文字列を生成する."""
    data: dict[str, Any] = {
        "version": doc.version,
        "last_synced_at": doc.last_synced_at,
        "customer_id": doc.customer_id,
        "campaigns": [_snapshot_to_dict(c) for c in doc.campaigns],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _snapshot_to_dict(c: CampaignSnapshot) -> dict[str, Any]:
    """CampaignSnapshotを辞書に変換する."""
    device_targeting: list[dict[str, Any]] | None = None
    if c.device_targeting is not None:
        device_targeting = list(c.device_targeting)
    return {
        "campaign_id": c.campaign_id,
        "campaign_name": c.campaign_name,
        "status": c.status,
        "bidding_strategy_type": c.bidding_strategy_type,
        "bidding_details": c.bidding_details,
        "daily_budget": c.daily_budget,
        "device_targeting": device_targeting,
        "campaign_goal": c.campaign_goal,
        "notes": c.notes,
    }


def _atomic_write(path: Path, content: str) -> None:
    """アトミックにファイルを書き込む（一時ファイル→rename）."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def read_state_file(path: Path) -> StateDocument:
    """STATE.json ファイルを読み取ってStateDocumentを返す.

    ファイルが存在しない場合はデフォルト値のStateDocumentを返す。
    """
    if not path.exists():
        return StateDocument()
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(
            f"STATE.json の読み取り権限がありません: {path}"
        ) from exc
    try:
        return parse_state(text)
    except json.JSONDecodeError as exc:
        raise ContextFileError(
            f"STATE.json の JSON パースに失敗しました: {path}"
        ) from exc


def write_state_file(path: Path, doc: StateDocument) -> None:
    """StateDocumentをSTATE.json ファイルにアトミックに書き込む."""
    text = render_state(doc)
    _atomic_write(path, text)


def upsert_campaign(path: Path, campaign: CampaignSnapshot) -> StateDocument:
    """キャンペーンをupsertする（既存なら更新、なければ追加）.

    Returns:
        更新後のStateDocument
    """
    doc = read_state_file(path)
    found = False
    new_campaigns: list[CampaignSnapshot] = []
    for c in doc.campaigns:
        if c.campaign_id == campaign.campaign_id:
            new_campaigns.append(campaign)
            found = True
        else:
            new_campaigns.append(c)
    if not found:
        new_campaigns.append(campaign)

    new_doc = StateDocument(
        version=doc.version,
        last_synced_at=doc.last_synced_at,
        customer_id=doc.customer_id,
        campaigns=tuple(new_campaigns),
    )
    write_state_file(path, new_doc)
    return new_doc


def get_campaign(
    doc: StateDocument, campaign_id: str
) -> CampaignSnapshot | None:
    """campaign_idでキャンペーンを検索する."""
    for c in doc.campaigns:
        if c.campaign_id == campaign_id:
            return c
    return None
