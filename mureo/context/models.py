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
class ActionLogEntry:
    """Immutable record of a single action performed on a campaign."""

    timestamp: str
    action: str
    platform: str
    campaign_id: str | None = None
    summary: str | None = None
    command: str | None = None


@dataclass(frozen=True)
class PlatformState:
    """Per-platform state snapshot (Google Ads, Meta Ads, etc.).

    frozen=True prevents field reassignment; __post_init__ takes defensive
    copies of mutable inner contents.
    """

    account_id: str
    campaigns: tuple[CampaignSnapshot, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Ensure campaigns is a tuple (defensive copy)."""
        if not isinstance(self.campaigns, tuple):
            object.__setattr__(self, "campaigns", tuple(self.campaigns))


@dataclass(frozen=True)
class StateDocument:
    """Root document of STATE.json."""

    version: str = "1"
    last_synced_at: str | None = None
    customer_id: str | None = None  # Kept for backward compatibility (v1)
    campaigns: tuple[CampaignSnapshot, ...] = field(
        default_factory=tuple
    )  # Kept for v1
    platforms: dict[str, PlatformState] | None = None  # v2: per-platform state
    action_log: tuple[ActionLogEntry, ...] = field(
        default_factory=tuple
    )  # v2: action log

    def __post_init__(self) -> None:
        """Defensive copies for mutable fields."""
        if self.platforms is not None:
            object.__setattr__(self, "platforms", dict(self.platforms))
        if not isinstance(self.action_log, tuple):
            object.__setattr__(self, "action_log", tuple(self.action_log))
