"""Rollback planner for mureo actions.

Given an :class:`ActionLogEntry` written by an AI agent with a
``reversible_params`` hint, produce a concrete :class:`RollbackPlan`
that describes which MCP tool to invoke (and with what arguments) to
reverse the change.

This package is the *data-model and planning* half of the rollback
feature. Actual execution — turning a plan into a live API call —
is a separate concern that lives with the MCP dispatcher.
"""

from __future__ import annotations

from mureo.rollback.executor import RollbackExecutionError, execute_rollback
from mureo.rollback.models import RollbackPlan, RollbackStatus
from mureo.rollback.planner import plan_rollback

__all__ = [
    "RollbackExecutionError",
    "RollbackPlan",
    "RollbackStatus",
    "execute_rollback",
    "plan_rollback",
]
