"""High-level demo actions invoked by the configure-UI demo endpoints.

Wraps the ``mureo demo`` CLI primitives (scenario registry +
``materialize``) and returns JSON-friendly frozen result envelopes that
the configure UI surfaces directly, rather than propagating exceptions.
``init_demo`` answers a refused request with ``ActionResult.refused`` and
an attempt that raised with ``ActionResult.failed``, and
``list_demo_scenarios`` answers a registry failure with
``ActionResult.failed``; the routes send either with ``send_result``
(#864).

Mirrors the wrapper / frozen-result-envelope pattern of
``mureo.web.setup_actions``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from mureo.demo.installer import DemoInitError, materialize
from mureo.demo.scenarios import DEFAULT_SCENARIO, SCENARIOS
from mureo.web.action_result import ActionResult, refuse_error_status

logger = logging.getLogger(__name__)

# Re-exported so tests can patch ``mureo.web.demo_actions.materialize`` /
# ``mureo.web.demo_actions.SCENARIOS``.
__all__ = ["DemoListResult", "DemoInitResult", "list_demo_scenarios", "init_demo"]


@dataclass(frozen=True)
class DemoListResult:
    """JSON-friendly result of a ``list_demo_scenarios`` that succeeded."""

    status: str  # "ok"
    scenarios: tuple[dict[str, Any], ...] = ()
    detail: str | None = None

    def __post_init__(self) -> None:
        refuse_error_status(self, self.status)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.status == "ok":
            out["scenarios"] = [dict(s) for s in self.scenarios]
        if self.detail is not None:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class DemoInitResult:
    """JSON-friendly result of an ``init_demo`` that succeeded."""

    status: str  # "ok"
    created_path: str | None = None
    imported: bool | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        refuse_error_status(self, self.status)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.status == "ok":
            out["created_path"] = self.created_path
            out["imported"] = self.imported
        if self.detail is not None:
            out["detail"] = self.detail
        return out


def list_demo_scenarios() -> DemoListResult | ActionResult:
    """Return the registered demo scenarios sorted by name.

    Exactly one row carries ``default=True`` (the ``DEFAULT_SCENARIO``).
    A registry failure is ``ActionResult.failed("internal_error")`` with
    the exception class name as its detail (HTTP 500).
    """
    try:
        rows: list[dict[str, Any]] = []
        for name in sorted(SCENARIOS):
            scenario = SCENARIOS[name]
            rows.append(
                {
                    "name": name,
                    "title": scenario.title,
                    "blurb": scenario.blurb,
                    "default": name == DEFAULT_SCENARIO,
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_demo_scenarios failed")
        return ActionResult.failed("internal_error", type(exc).__name__)
    return DemoListResult(status="ok", scenarios=tuple(rows))


def _validate_target(target: object) -> str:
    """Validate the demo ``target`` directory before any FS call.

    Rejects non-str, empty, NUL/control chars, ``..`` traversal and
    symlink-escape (via ``os.path.realpath``). Returns the resolved
    absolute path on success; raises ``ValueError`` otherwise, whose
    message is the refusal's error code.
    """
    if not isinstance(target, str):
        raise ValueError("target_invalid")
    if not target.strip():
        raise ValueError("target_required")
    if any(ord(c) < 0x20 for c in target):
        raise ValueError("target_control_characters")
    # Reject traversal segments outright — the UI never has a
    # legitimate reason to pass ``..`` and ``realpath`` could silently
    # normalize an escape away.
    parts = target.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError("target_traversal")
    resolved = os.path.realpath(target)
    if ".." in resolved.replace("\\", "/").split("/"):
        raise ValueError("target_traversal")
    return resolved


def init_demo(
    scenario_name: str,
    target: str,
    force: bool,
    skip_import: bool,
) -> DemoInitResult | ActionResult:
    """Materialize a demo workspace at ``target``.

    ``target`` is validated *before* ``materialize`` is invoked. An
    invalid target or an unknown scenario is a refused result; a
    ``DemoInitError`` or an unexpected exception is a failed one. Neither
    echoes file contents or a traceback.
    """
    try:
        resolved = _validate_target(target)
    except ValueError as exc:
        return ActionResult.refused(str(exc))

    try:
        materialize(
            resolved,
            force=force,
            skip_import=skip_import,
            scenario_name=scenario_name,
        )
    except ValueError:
        logger.warning("init_demo rejected: unknown scenario %r", scenario_name)
        return ActionResult.refused("unknown_scenario")
    except DemoInitError as exc:
        logger.warning("init_demo failed: %s", type(exc).__name__)
        return ActionResult.failed("demo_init_failed", "DemoInitError")
    except Exception as exc:  # noqa: BLE001
        logger.exception("init_demo unexpected failure")
        return ActionResult.failed("internal_error", type(exc).__name__)

    return DemoInitResult(
        status="ok",
        created_path=resolved,
        imported=not skip_import,
    )
