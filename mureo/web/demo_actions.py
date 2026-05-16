"""High-level demo actions invoked by the configure-UI demo endpoints.

Wraps the ``mureo demo`` CLI primitives (scenario registry +
``materialize``) and returns JSON-friendly frozen result envelopes that
the configure UI surfaces directly. Failures degrade to
``status="error"`` envelopes rather than propagating exceptions, so a
click in the configure UI never produces a 500.

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

logger = logging.getLogger(__name__)

# Re-exported so tests can patch ``mureo.web.demo_actions.materialize`` /
# ``mureo.web.demo_actions.SCENARIOS``.
__all__ = ["DemoListResult", "DemoInitResult", "list_demo_scenarios", "init_demo"]


@dataclass(frozen=True)
class DemoListResult:
    """JSON-friendly result of ``list_demo_scenarios``."""

    status: str  # "ok" | "error"
    scenarios: tuple[dict[str, Any], ...] = ()
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.status == "ok":
            out["scenarios"] = [dict(s) for s in self.scenarios]
        if self.detail is not None:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class DemoInitResult:
    """JSON-friendly result of ``init_demo``."""

    status: str  # "ok" | "error"
    created_path: str | None = None
    imported: bool | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.status == "ok":
            out["created_path"] = self.created_path
            out["imported"] = self.imported
        if self.detail is not None:
            out["detail"] = self.detail
        return out


def list_demo_scenarios() -> DemoListResult:
    """Return the registered demo scenarios sorted by name.

    Exactly one row carries ``default=True`` (the ``DEFAULT_SCENARIO``).
    A registry failure degrades to an ``error`` envelope with no path
    or secret leakage.
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
        return DemoListResult(status="error", detail=type(exc).__name__)
    return DemoListResult(status="ok", scenarios=tuple(rows))


def _validate_target(target: object) -> str:
    """Validate the demo ``target`` directory before any FS call.

    Rejects non-str, empty, NUL/control chars, ``..`` traversal and
    symlink-escape (via ``os.path.realpath``). Returns the resolved
    absolute path on success; raises ``ValueError`` otherwise.
    """
    if not isinstance(target, str):
        raise ValueError("target must be a string")
    if not target.strip():
        raise ValueError("target must not be empty")
    if any(ord(c) < 0x20 for c in target):
        raise ValueError("target contains control characters")
    # Reject traversal segments outright — the UI never has a
    # legitimate reason to pass ``..`` and ``realpath`` could silently
    # normalize an escape away.
    parts = target.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError("target must not contain '..' traversal")
    resolved = os.path.realpath(target)
    if ".." in resolved.replace("\\", "/").split("/"):
        raise ValueError("target resolved to a traversal path")
    return resolved


def init_demo(
    scenario_name: str,
    target: str,
    force: bool,
    skip_import: bool,
) -> DemoInitResult:
    """Materialize a demo workspace at ``target``.

    ``target`` is validated *before* ``materialize`` is invoked. Any
    failure (validation, unknown scenario, ``DemoInitError`` or an
    unexpected exception) degrades to an ``error`` envelope that never
    echoes file contents or a traceback.
    """
    try:
        resolved = _validate_target(target)
    except ValueError as exc:
        return DemoInitResult(status="error", detail=str(exc))

    try:
        materialize(
            resolved,
            force=force,
            skip_import=skip_import,
            scenario_name=scenario_name,
        )
    except ValueError:
        logger.warning("init_demo rejected: unknown scenario %r", scenario_name)
        return DemoInitResult(status="error", detail="unknown_scenario")
    except DemoInitError as exc:
        logger.warning("init_demo failed: %s", type(exc).__name__)
        return DemoInitResult(status="error", detail="DemoInitError")
    except Exception as exc:  # noqa: BLE001
        logger.exception("init_demo unexpected failure")
        return DemoInitResult(status="error", detail=type(exc).__name__)

    return DemoInitResult(
        status="ok",
        created_path=resolved,
        imported=not skip_import,
    )
