"""ファイルベースコンテキストのデータモデル定義."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyEntry:
    """STRATEGY.md の1セクションを表すイミュータブルなデータモデル."""

    context_type: str
    title: str
    content: str


@dataclass(frozen=True)
class CampaignSnapshot:
    """キャンペーン状態のスナップショット.

    frozen=True はフィールドの再代入を防ぐが、dict/list の中身は変更可能なため、
    __post_init__ で防御コピーを取る。
    """

    campaign_id: str
    campaign_name: str
    status: str
    bidding_strategy_type: str | None = None
    bidding_details: dict[str, Any] | None = None
    daily_budget: float | None = None
    device_targeting: tuple[dict[str, Any], ...] | None = None
    campaign_goal: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        """mutableフィールドの防御コピーを取る."""
        if self.bidding_details is not None:
            object.__setattr__(
                self, "bidding_details", copy.deepcopy(self.bidding_details)
            )
        if self.device_targeting is not None:
            # list が渡された場合も tuple に変換し、中身を deepcopy
            copied = tuple(copy.deepcopy(item) for item in self.device_targeting)
            object.__setattr__(self, "device_targeting", copied)


@dataclass(frozen=True)
class StateDocument:
    """STATE.json のルートドキュメント."""

    version: str = "1"
    last_synced_at: str | None = None
    customer_id: str | None = None
    campaigns: tuple[CampaignSnapshot, ...] = field(default_factory=tuple)
