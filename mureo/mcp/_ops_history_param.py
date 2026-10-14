"""The ``expected`` and ``decision_id`` parameters of mutating tools (#848).

Ops history links every change to the decision it carried out. The agent
states two things on the mutating call itself — WHY (``reason``, injected by
:mod:`mureo.mcp._reason_param`) and WHAT SHOULD MOVE (``expected``, here) —
and mureo writes the decision record. ``decision_id`` is optional and only
for carrying out an earlier ``proposed`` decision.

Injected exactly as ``reason`` is, and under the same three rules: a tool
that declares either name itself is left alone, the registry's ``Tool``
objects are never mutated, and a schema without a ``properties`` map is
returned unchanged.

**Scope.** The tools that change something on a platform: every
reason-taking tool except mureo's own bookkeeping (``mureo_*``) and
``rollback_apply``. ``mureo_batch_begin`` is the one bookkeeping tool in
scope, because a batch's reason and expected effect become the decision
every member shares. A rollback is out of scope: it undoes a decision rather
than making one, and is recorded as such (``rollback_of``).

**Enforcement.** Only when the workspace switched ops history on
(``settings.ops_history.enabled``): a call in scope must carry ``reason``
and ``expected`` — unless it joins a decision that already has them (an
explicit ``decision_id``, or the open batch's decision). Refused as
``invalid_args`` naming the missing parameter. Off, nothing is refused.
"""

from __future__ import annotations

import copy
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from mureo.context.expected import (
    EXPECTED_DIRECTIONS,
    EXPECTED_HORIZON_MAX_DAYS,
    EXPECTED_MAX_ITEMS,
    EXPECTED_METRICS,
    parse_expected,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
    from pathlib import Path

    from mcp.types import Tool

    from mureo.context.expected import ExpectedEffect
    from mureo.context.models import StateDocument
    from mureo.mcp._journal_hook import JournalledCall

logger = logging.getLogger(__name__)

EXPECTED_PARAM: Final = "expected"
DECISION_ID_PARAM: Final = "decision_id"
BATCH_BEGIN_TOOL: Final = "mureo_batch_begin"
ROLLBACK_APPLY_TOOL: Final = "rollback_apply"
_BOOKKEEPING_PREFIX: Final = "mureo_"

#: Longest ``decision_id`` accepted. Minted ids are ~30 characters.
DECISION_ID_MAX_CHARS: Final = 128

REASON_REQUIRED: Final = (
    "reason is required while ops history is enabled for this workspace: "
    "say why this change is being made."
)
EXPECTED_REQUIRED: Final = (
    "expected is required while ops history is enabled for this workspace: "
    "declare at least one {metric, direction} the change should move."
)

#: The ``expected`` property. Read-only; copied per tool on injection.
EXPECTED_PROPERTY: Mapping[str, Any] = MappingProxyType(
    {
        "type": "array",
        "maxItems": EXPECTED_MAX_ITEMS,
        "description": (
            "What this change should move, judged when its observation window "
            'closes: e.g. [{"metric": "cpa", "direction": "down", '
            '"target": 4500, "horizon_days": 14}]. With reason, it becomes '
            "the decision record mureo writes for this change."
        ),
        "items": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "enum": list(EXPECTED_METRICS)},
                "direction": {"type": "string", "enum": list(EXPECTED_DIRECTIONS)},
                "target": {"type": "number"},
                "horizon_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": EXPECTED_HORIZON_MAX_DAYS,
                },
            },
            "required": ["metric", "direction"],
            "additionalProperties": False,
        },
    }
)

#: The ``decision_id`` property. Read-only; copied per tool on injection.
DECISION_ID_PROPERTY: Mapping[str, Any] = MappingProxyType(
    {
        "type": "string",
        "minLength": 1,
        "maxLength": DECISION_ID_MAX_CHARS,
        "description": (
            "Optional. The decision_id of an earlier proposed decision "
            "(mureo_decision_record) this change carries out; it becomes "
            "adopted. Omit it otherwise — mureo creates the decision itself."
        ),
    }
)


def expected_schema(description: str) -> dict[str, Any]:
    """A fresh copy of the ``expected`` schema with its own description.

    For the recording tools, which carry ``expected`` in their own record
    rather than as an injected call parameter.
    """
    schema = copy.deepcopy(dict(EXPECTED_PROPERTY))
    schema["description"] = description
    return schema


def decision_id_schema(description: str) -> dict[str, Any]:
    """A fresh copy of the ``decision_id`` schema with its own description."""
    return {**dict(DECISION_ID_PROPERTY), "description": description}


@dataclass(frozen=True)
class OpsParams:
    """The two parameters as split off one call."""

    expected: tuple[ExpectedEffect, ...] = ()
    decision_id: str | None = None


def ops_scope(
    reason_tools: Collection[str],
) -> Callable[[str], bool]:
    """Which tools take ``expected`` / ``decision_id`` (see module docstring)."""

    def _in_scope(name: str) -> bool:
        if name not in reason_tools or name == ROLLBACK_APPLY_TOOL:
            return False
        return name == BATCH_BEGIN_TOOL or not name.startswith(_BOOKKEEPING_PREFIX)

    return _in_scope


def with_ops_properties(tool: Tool) -> Tool:
    """Return ``tool`` with both properties, or ``tool`` itself."""
    schema = getattr(tool, "inputSchema", None)
    if not isinstance(schema, dict):
        return tool
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return tool
    if EXPECTED_PARAM in properties or DECISION_ID_PARAM in properties:
        return tool
    injected = copy.deepcopy(schema)
    injected["properties"][EXPECTED_PARAM] = copy.deepcopy(dict(EXPECTED_PROPERTY))
    injected["properties"][DECISION_ID_PARAM] = dict(DECISION_ID_PROPERTY)
    return tool.model_copy(update={"inputSchema": injected})


def inject_ops_params(
    tools: Iterable[Tool], in_scope: Callable[[str], bool]
) -> tuple[list[Tool], frozenset[str]]:
    """Add both properties to every tool in scope.

    Returns the new tool list and the names that gained them.
    """
    result: list[Tool] = []
    injected: set[str] = set()
    for tool in tools:
        replacement = with_ops_properties(tool) if in_scope(tool.name) else tool
        if replacement is not tool:
            injected.add(tool.name)
        result.append(replacement)
    return result, frozenset(injected)


def parse_decision_id(raw: Any) -> str | None:
    """A caller-supplied ``decision_id``, cleaned, or refused."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("decision_id must be a non-empty string")
    if len(raw.strip()) > DECISION_ID_MAX_CHARS:
        raise ValueError(
            f"decision_id must be at most {DECISION_ID_MAX_CHARS} characters"
        )
    return raw.strip()


def split_ops_params(
    name: str, arguments: dict[str, Any], injected: Collection[str]
) -> tuple[OpsParams, dict[str, Any]]:
    """Separate the two parameters from the arguments the handler gets.

    Popped from a COPY; a tool outside ``injected`` gets its dict back
    untouched.

    Raises:
        ValueError: either parameter is malformed.
    """
    if name not in injected or not isinstance(arguments, dict):
        return OpsParams(), arguments
    rest = dict(arguments)
    expected = parse_expected(rest.pop(EXPECTED_PARAM, None))
    decision_id = parse_decision_id(rest.pop(DECISION_ID_PARAM, None))
    return OpsParams(expected=expected, decision_id=decision_id), rest


def take_ops_params(
    call: JournalledCall,
    name: str,
    arguments: dict[str, Any],
    injected: Collection[str],
) -> tuple[OpsParams, dict[str, Any]]:
    """:func:`split_ops_params`, filing a malformed one as ``invalid_args``."""
    try:
        return split_ops_params(name, arguments, injected)
    except ValueError as exc:
        call.invalid_args(exc)
        raise


def _state_path(name: str, handler_args: Mapping[str, Any]) -> Path:
    """The STATE.json the call's change will be recorded in."""
    from mureo.mcp._helpers import resolve_workspace_path

    scoped = dict(handler_args) if name == BATCH_BEGIN_TOOL else {}
    return resolve_workspace_path(scoped, "STATE.json", store_attr="state_path")


def _read(path: Path) -> StateDocument | None:
    from mureo.context.state import read_state_file

    if not path.is_file():
        return None
    return read_state_file(path, strict=False)


def _readable_state(
    name: str, params: OpsParams, handler_args: Mapping[str, Any]
) -> StateDocument | None:
    """The workspace's document, or ``None`` when there is none to read.

    A STATE.json that exists but cannot be read does not refuse the call:
    the setting lives in that file, so it cannot be known to be on, and a
    change accepted before ops history existed must not start failing here.
    The fault is logged, and the action-log append reports it in its own
    right. An explicit ``decision_id`` cannot be checked against such a
    file, so that call is refused.

    Raises:
        ValueError: ``decision_id`` was given and the file is unreadable.
    """
    from mureo.context.errors import ContextFileError

    try:
        return _read(_state_path(name, handler_args))
    except ContextFileError as exc:
        if params.decision_id is not None:
            raise ValueError(
                "decision_id cannot be checked: STATE.json could not be read"
            ) from exc
        logger.warning(
            "ops history not enforced for %r: STATE.json could not be read",
            name,
            exc_info=True,
        )
        return None


def _joins_batch_decision(doc: StateDocument, name: str) -> bool:
    from mureo.context.batch import active_batch
    from mureo.context.ops_linkage import batch_decision_root

    if name == BATCH_BEGIN_TOOL:
        return False
    batch = active_batch(doc)
    return batch is not None and batch_decision_root(doc, batch.batch_id) is not None


def check_ops_call(
    name: str, reason: str | None, params: OpsParams, handler_args: Mapping[str, Any]
) -> None:
    """Validate an explicit ``decision_id`` and enforce the setting.

    Raises:
        ValueError: the decision is not linkable, or ops history is on and
            ``reason`` / ``expected`` is missing.
    """
    from mureo.context.models import StateDocument as _Doc
    from mureo.context.ops_linkage import check_linkable
    from mureo.context.settings import ops_history_enabled

    doc = _readable_state(name, params, handler_args)
    if params.decision_id is not None:
        check_linkable(doc or _Doc(version="2"), params.decision_id)
    if doc is None or not ops_history_enabled(doc):
        return
    if params.decision_id is not None or _joins_batch_decision(doc, name):
        return
    if reason is None:
        raise ValueError(REASON_REQUIRED)
    if not params.expected:
        raise ValueError(EXPECTED_REQUIRED)


def enforce_ops_call(
    call: JournalledCall,
    name: str,
    reason: str | None,
    params: OpsParams,
    handler_args: Mapping[str, Any],
    injected: Collection[str],
) -> None:
    """:func:`check_ops_call` for a tool in scope, filed as ``invalid_args``.

    Skipped for the reversal leg of a rollback: that call re-enters the
    dispatcher on mureo's behalf and carries no parameters of its own.
    """
    from mureo.rollback.executor import is_rollback_dispatch_active

    if name not in injected or is_rollback_dispatch_active():
        return
    try:
        check_ops_call(name, reason, params, handler_args)
    except ValueError as exc:
        call.invalid_args(exc)
        raise


def _adopt_unrecorded(
    name: str, params: OpsParams, linked: str | None, handler_args: Mapping[str, Any]
) -> None:
    """Adopt the named proposal when the call recorded no entry for it.

    The change happened, so a failure here is logged rather than raised:
    failing the call would tell the agent a change that went through did not.
    """
    if params.decision_id is None or linked is not None or name == BATCH_BEGIN_TOOL:
        return
    from mureo.context.ops_linkage import adopt_decision

    try:
        adopt_decision(_state_path(name, handler_args), params.decision_id)
    except Exception:  # noqa: BLE001 — the change itself already succeeded
        logger.warning(
            "could not adopt decision %r after %r",
            params.decision_id,
            name,
            exc_info=True,
        )


@contextmanager
def ops_call_scope(
    call: JournalledCall,
    name: str,
    params: OpsParams,
    handler_args: Mapping[str, Any],
    injected: Collection[str],
) -> Iterator[None]:
    """Bind the call's intent around dispatch, then finish a no-entry adoption.

    Outside scope this binds nothing, so a read-only call or a bookkeeping
    tool never links an entry to a decision through a stale intent.
    """
    if name not in injected:
        yield
        return
    from mureo.context.ops_intent import bind_ops_intent

    with bind_ops_intent(
        expected=params.expected,
        decision_id=params.decision_id,
        arguments=handler_args,
    ) as intent:
        yield
    if call.outcome == "ok":
        _adopt_unrecorded(name, params, intent.slot.decision_id, handler_args)


__all__ = [
    "DECISION_ID_PROPERTY",
    "EXPECTED_PROPERTY",
    "EXPECTED_REQUIRED",
    "REASON_REQUIRED",
    "OpsParams",
    "check_ops_call",
    "decision_id_schema",
    "enforce_ops_call",
    "expected_schema",
    "inject_ops_params",
    "ops_call_scope",
    "ops_scope",
    "parse_decision_id",
    "split_ops_params",
    "take_ops_params",
    "with_ops_properties",
]
