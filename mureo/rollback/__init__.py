"""Rollback planner for mureo actions.

Given an :class:`ActionLogEntry` written by an AI agent with a
``reversible_params`` hint, produce a concrete :class:`RollbackPlan`
that describes which MCP tool to invoke (and with what arguments) to
reverse the change.

This package is the *data-model and planning* half of the rollback
feature. Actual execution — turning a plan into a live API call —
is a separate concern that lives with the MCP dispatcher.

:func:`plan_batch_rollback` (#549) does the same for a whole declared batch
(see :mod:`mureo.context.batch`): it classifies EVERY member through the same
planner and reports overall and per-platform coverage, so a batch that can
only be partly restored says so before anything is applied.
"""

from __future__ import annotations

from mureo.rollback.batch import plan_batch_rollback
from mureo.rollback.executor import RollbackExecutionError, execute_rollback
from mureo.rollback.models import (
    BatchCoverage,
    BatchMemberPlan,
    BatchMemberStatus,
    BatchRollbackPlan,
    RollbackPlan,
    RollbackStatus,
)
from mureo.rollback.planner import plan_rollback

__all__ = [
    "BatchCoverage",
    "BatchMemberPlan",
    "BatchMemberStatus",
    "BatchRollbackPlan",
    "RollbackExecutionError",
    "RollbackPlan",
    "RollbackStatus",
    "execute_rollback",
    "plan_batch_rollback",
    "plan_rollback",
]
