"""Rollback inspection commands.

``mureo rollback list`` — list every action_log entry that describes a
state-changing action and the planner's verdict on reversing it.
``mureo rollback show <index>`` — print the full :class:`RollbackPlan`
for one entry.

This module is inspection-only. It does **not** call any ad platform
API — executing a plan lives with the MCP dispatcher so rollback goes
through the same policy gate as forward actions. The CLI's job is to
let an operator see, before executing anything, what mureo would do.
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TCH003 (used at runtime by typer)

import typer

from mureo.cli._state_file import STATE_FILE_OPTION, resolve_default_state_file
from mureo.cli._tty import terminal_safe as _safe
from mureo.context.errors import ContextFileError
from mureo.context.state import read_state_file
from mureo.core.platform_keys import (
    plugin_platform_key_matches,
    plugin_platform_parts,
)
from mureo.rollback import RollbackPlan, plan_rollback

rollback_app = typer.Typer(name="rollback", help="Inspect reversible actions")

# ``STATE_FILE_OPTION`` / ``resolve_default_state_file`` are shared with
# ``mureo repair`` (mureo/cli/_state_file.py): a command that inspects
# STATE.json and one that rewrites it must resolve the same file by default.
# ``terminal_safe`` is likewise shared — STATE.json is agent-writable, so
# every string it contributes to terminal output is scrubbed of control bytes
# before echo.


def _platform_filter_matches(entry_platform: str, wanted: str) -> bool:
    """Does an ``action_log`` entry's platform satisfy a ``--platform`` filter?

    Exact string match, plus one widening: a legacy ``plugin:<dist>``
    filter still selects that distribution's per-provider entries
    (``plugin:<dist>:<provider>``, #537). The old key stays valid on read
    everywhere else, so an operator whose muscle memory — or whose older
    history — uses it must not silently get an empty list.

    Deliberately NOT widened the other way: a ``plugin:<dist>:<provider>``
    filter does not select bare ``plugin:<dist>`` entries, because such an
    entry may belong to a sibling provider and mureo does not guess which.
    """
    if entry_platform == wanted:
        return True
    distribution, provider = plugin_platform_parts(entry_platform)
    if not distribution or not provider:
        return False
    return plugin_platform_key_matches(wanted, distribution, provider)


def _load_plans(
    state_file: Path,
    *,
    platform: str | None = None,
) -> list[tuple[int, RollbackPlan]]:
    """Load STATE.json and return (index, plan) pairs for write actions.

    Read-only actions (``plan_rollback`` returns ``None``) are filtered
    out. The index is the position in ``doc.action_log`` so callers can
    reference entries by number.
    """
    if not state_file.exists():
        typer.echo(f"Error: STATE.json not found at {state_file}", err=True)
        raise typer.Exit(1)

    try:
        doc = read_state_file(state_file)
    except ContextFileError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    plans: list[tuple[int, RollbackPlan]] = []
    for index, entry in enumerate(doc.action_log):
        if platform is not None and not _platform_filter_matches(
            entry.platform, platform
        ):
            continue
        plan = plan_rollback(entry)
        if plan is None:
            continue
        plans.append((index, plan))
    return plans


@rollback_app.command("list")  # type: ignore[untyped-decorator, unused-ignore]
def rollback_list(
    state_file: Path | None = STATE_FILE_OPTION,
    platform: str | None = typer.Option(
        None,
        "--platform",
        help="Filter to one platform (e.g. google_ads, meta_ads).",
    ),
) -> None:
    """List action_log entries and whether they can be rolled back."""
    if state_file is None:
        state_file = resolve_default_state_file()
    plans = _load_plans(state_file, platform=platform)
    if not plans:
        typer.echo("No reversible actions recorded in the action log.")
        return

    typer.echo(f"{'#':>3}  {'timestamp':19}  {'platform':10}  {'status':14}  action")
    typer.echo("-" * 72)
    for index, plan in plans:
        caveat_marker = "*" if plan.caveats else " "
        typer.echo(
            f"{index:>3}  {_safe(plan.source_timestamp):19}  "
            f"{_safe(plan.platform):10}  {plan.status.value:14}{caveat_marker} "
            f"{_safe(plan.source_action)}"
        )
    if any(p.caveats for _, p in plans):
        typer.echo("")
        typer.echo("(*) Has caveats — run `mureo rollback show <#>` for detail.")


@rollback_app.command("show")  # type: ignore[untyped-decorator, unused-ignore]
def rollback_show(
    index: int = typer.Argument(..., help="Index into STATE.json action_log.", min=0),
    state_file: Path | None = STATE_FILE_OPTION,
) -> None:
    """Show the full rollback plan for one action_log entry."""
    if state_file is None:
        state_file = resolve_default_state_file()
    if not state_file.exists():
        typer.echo(f"Error: STATE.json not found at {state_file}", err=True)
        raise typer.Exit(1)

    try:
        doc = read_state_file(state_file)
    except ContextFileError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if index < 0 or index >= len(doc.action_log):
        typer.echo(
            f"Error: index {index} is out of range "
            f"(action_log has {len(doc.action_log)} entries).",
            err=True,
        )
        raise typer.Exit(1)

    entry = doc.action_log[index]
    plan = plan_rollback(entry)
    if plan is None:
        typer.echo(
            f"Entry #{index} ({_safe(entry.action)}) is read-only — "
            "nothing to roll back."
        )
        return

    payload = {
        "index": index,
        "source_timestamp": plan.source_timestamp,
        "source_action": plan.source_action,
        "platform": plan.platform,
        "status": plan.status.value,
        "description": plan.description,
        "operation": plan.operation,
        "params": plan.params,
        "caveats": list(plan.caveats),
        "notes": plan.notes,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
