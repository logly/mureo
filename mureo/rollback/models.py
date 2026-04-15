"""Immutable data models for the rollback planner."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RollbackStatus(str, Enum):
    """Outcome of a rollback planning attempt.

    ``str`` mixin keeps JSON serialization trivial.
    """

    SUPPORTED = "supported"
    """Rollback is clean: replaying ``operation(**params)`` restores the
    prior state."""

    PARTIAL = "partial"
    """Rollback reverses the configuration change but side effects (spend
    that was already incurred, impressions served, etc.) cannot be
    undone. ``caveats`` explains what remains irreversible."""

    NOT_SUPPORTED = "not_supported"
    """Rollback cannot be attempted — the source action was destructive
    (delete), carries no reversible hint, or the hint was malformed.
    ``operation`` and ``params`` are ``None`` in this case."""


@dataclass(frozen=True)
class RollbackPlan:
    """Concrete plan describing how to reverse one ``ActionLogEntry``.

    The plan is data, not execution. Executing it means invoking the
    MCP tool named in ``operation`` with ``params`` as kwargs — that
    responsibility sits with the caller.

    ``frozen=True`` blocks attribute reassignment but does not freeze
    dict contents, so ``__post_init__`` takes a defensive deep-copy of
    ``params`` to ensure a caller mutating the dict afterwards cannot
    corrupt the stored plan.
    """

    source_timestamp: str
    source_action: str
    platform: str
    status: RollbackStatus
    operation: str | None
    params: dict[str, Any] | None
    description: str
    caveats: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if self.params is not None:
            object.__setattr__(self, "params", copy.deepcopy(self.params))
