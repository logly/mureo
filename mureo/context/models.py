"""Data model definitions for file-based context."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyEntry:
    """Immutable data model representing a single section in STRATEGY.md."""

    context_type: str
    title: str
    content: str


@dataclass(frozen=True)
class CampaignSnapshot:
    """Campaign state snapshot.

    frozen=True prevents field reassignment, but dict/list contents are still mutable,
    so __post_init__ takes defensive copies.
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
        """Take defensive copies of mutable fields."""
        if self.bidding_details is not None:
            object.__setattr__(
                self, "bidding_details", copy.deepcopy(self.bidding_details)
            )
        if self.device_targeting is not None:
            # Convert lists to tuples and deepcopy contents
            copied = tuple(copy.deepcopy(item) for item in self.device_targeting)
            object.__setattr__(self, "device_targeting", copied)


@dataclass(frozen=True)
class StateDocument:
    """Root document of STATE.json."""

    version: str = "1"
    last_synced_at: str | None = None
    customer_id: str | None = None
    campaigns: tuple[CampaignSnapshot, ...] = field(default_factory=tuple)
