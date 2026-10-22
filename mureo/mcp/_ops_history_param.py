"""The ``expected``, ``decision_id`` and ``approval`` parameters (#848, #854).

Ops history links every change to the decision it carried out. The agent
states two things on the mutating call itself — WHY (``reason``, injected by
:mod:`mureo.mcp._reason_param`) and WHAT SHOULD MOVE (``expected``, here) —
and mureo writes the decision record. ``decision_id`` is optional and only
for carrying out an earlier ``proposed`` decision. ``approval`` is optional
too: a reference to a sign-off made outside mureo (#854,
:mod:`mureo.context.approval`), recorded and shown, never verified, and
never required whatever the setting.

Injected exactly as ``reason`` is, and under the same three rules: a
tool that declares any of the three names itself is left alone, the
registry's ``Tool`` objects are never mutated, and a schema without a
``properties`` map is returned unchanged.

**Scope.** The tools that change something on a platform: every
reason-taking tool except mureo's own bookkeeping (``mureo_*``) and
``rollback_apply``. ``mureo_batch_begin`` is the one bookkeeping tool in
scope, because a batch's reason and expected effect become the decision
every member shares. A rollback is out of scope: it undoes a decision rather
than making one, and is recorded as such (``rollback_of``).

**Enforcement.** Only when the workspace switched ops history on
(``settings.ops_history.enabled``): a call in scope must carry ``reason``
and ``expected`` — unless it joins a decision that already has them (an
explicit ``decision_id`` whose decision declares ``expected``, or the open
batch's decision). Refused as ``invalid_args`` naming the missing
parameter. Off, nothing is refused — and a STATE.json that cannot be read
counts as off.

**A call that writes no entry.** Most changes on a native platform (budget,
bid, keyword, creative) leave no ``action_log`` entry, so the action-log
choke point never links them. After such a call succeeds,
:func:`ops_call_scope` records its decision with
:func:`mureo.context.ops_linkage.record_call_decision`: one per call, or
the batch's, carrying the parameters the call sent and the ``call_id`` of
its journal record, which in turn names the decision.
"""

from __future__ import annotations

import copy
import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

# Read through the modules (not bound to names here) so monkeypatched
# linkage functions are honoured at call time.
from mureo.context import ops_linkage
from mureo.context.approval import (
    APPROVAL_AT_MAX_CHARS,
    APPROVAL_BY_MAX_CHARS,
    APPROVAL_REFERENCE_MAX_CHARS,
    parse_approval,
)
from mureo.context.batch import active_batch
from mureo.context.decision_chain import chain_expected
from mureo.context.expected import (
    EXPECTED_DIRECTIONS,
    EXPECTED_HORIZON_MAX_DAYS,
    EXPECTED_MAX_ITEMS,
    EXPECTED_METRICS,
    parse_expected,
)
from mureo.context.models import StateDocument
from mureo.context.ops_intent import bind_ops_intent
from mureo.context.settings import ops_history_enabled
from mureo.context.state import read_state_file
from mureo.core.clock import server_now_iso
from mureo.mcp._helpers import resolve_workspace_path
from mureo.mcp._journal_hook import JournalledCall, tool_family
from mureo.mcp._tools_settings import check_settings_call
from mureo.mcp.journal import _open_batch_id
from mureo.mcp.plugin_audit import mask_arguments
from mureo.rollback.executor import is_rollback_dispatch_active

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
    from pathlib import Path

    from mcp.types import Tool

    from mureo.context.approval import ApprovalRef
    from mureo.context.expected import ExpectedEffect
    from mureo.context.ops_intent import OpsIntent

logger = logging.getLogger(__name__)

EXPECTED_PARAM: Final = "expected"
DECISION_ID_PARAM: Final = "decision_id"
APPROVAL_PARAM: Final = "approval"
BATCH_BEGIN_TOOL: Final = "mureo_batch_begin"
ROLLBACK_APPLY_TOOL: Final = "rollback_apply"
_BOOKKEEPING_PREFIX: Final = "mureo_"

#: Longest ``decision_id`` accepted. Minted ids are ~30 characters.
DECISION_ID_MAX_CHARS: Final = 128

#: Largest masked parameter set kept as ``applied_params``, in JSON
#: characters. A bulk call over it is still recorded, without its values.
APPLIED_PARAMS_MAX_CHARS: Final = 4000

#: The parameters this module injects; a tool declaring any one is left alone.
_OPS_PARAMS: Final[tuple[str, ...]] = (
    EXPECTED_PARAM,
    DECISION_ID_PARAM,
    APPROVAL_PARAM,
)

#: Journal families whose name is also the platform a change was made on.
_PLATFORM_FAMILIES: Final[frozenset[str]] = frozenset(
    {"google_ads", "meta_ads", "search_console"}
)

REASON_REQUIRED: Final = (
    "reason is required while ops history is enabled for this workspace: "
    "say why this change is being made."
)
EXPECTED_REQUIRED: Final = (
    "expected is required while ops history is enabled for this workspace: "
    "declare at least one {metric, direction} the change should move."
)
ADOPTION_EXPECTED_REQUIRED: Final = (
    "expected is required while ops history is enabled for this workspace: "
    "the decision named by decision_id declares none, so pass expected on "
    "this call."
)

#: The full ``expected`` schema, for the recording tools. Read-only.
EXPECTED_PROPERTY: Mapping[str, Any] = MappingProxyType(
    {
        "type": "array",
        "maxItems": EXPECTED_MAX_ITEMS,
        "description": "Metrics this change should move; recorded with reason.",
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
                "primary": {
                    "type": "boolean",
                    "description": (
                        "The effect the verdict is read off. One effect is "
                        "primary by itself; with several, mark exactly one."
                    ),
                },
            },
            "required": ["metric", "direction"],
            "additionalProperties": False,
        },
    }
)

#: The ``expected`` property injected into every mutating tool. Read-only;
#: copied per tool on injection. No item schema: repeated across every
#: mutating tool it would dominate the tool list, so the shape and the
#: vocabulary live in the one-sentence description and every item is
#: validated by :func:`split_ops_params` on the server instead.
INJECTED_EXPECTED_PROPERTY: Mapping[str, Any] = MappingProxyType(
    {
        "type": "array",
        "maxItems": EXPECTED_MAX_ITEMS,
        "description": (
            "Expected effects [{metric, direction, target?, horizon_days?, "
            "primary?}], exactly one primary:true when several; "
            f"metric {'/'.join(EXPECTED_METRICS)}; "
            f"direction {'/'.join(EXPECTED_DIRECTIONS)}."
        ),
    }
)

#: The ``decision_id`` property. Read-only; copied per tool on injection.
DECISION_ID_PROPERTY: Mapping[str, Any] = MappingProxyType(
    {
        "type": "string",
        "minLength": 1,
        "maxLength": DECISION_ID_MAX_CHARS,
        "description": "A proposed decision this change carries out.",
    }
)


#: The ``approval`` property. The lengths are stated for the agent; every
#: bound, these included, is checked by
#: :func:`mureo.context.approval.parse_approval` on the server, whose
#: constants they come from. Read-only; copied per tool on injection.
APPROVAL_PROPERTY: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "description": (
            "External approval this change carries out "
            "(recorded and shown, never verified)"
        ),
        "properties": {
            "reference": {
                "type": "string",
                "maxLength": APPROVAL_REFERENCE_MAX_CHARS,
            },
            "approved_by": {"type": "string", "maxLength": APPROVAL_BY_MAX_CHARS},
            "approved_at": {"type": "string", "maxLength": APPROVAL_AT_MAX_CHARS},
        },
        "required": ["reference", "approved_by", "approved_at"],
        "additionalProperties": False,
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


def approval_schema(description: str) -> dict[str, Any]:
    """A fresh copy of the ``approval`` schema with its own description."""
    schema = copy.deepcopy(dict(APPROVAL_PROPERTY))
    schema["description"] = description
    return schema


@dataclass(frozen=True)
class OpsParams:
    """The ops-history parameters as split off one call."""

    expected: tuple[ExpectedEffect, ...] = ()
    decision_id: str | None = None
    approval: ApprovalRef | None = None


def ops_scope(
    reason_tools: Collection[str],
) -> Callable[[str], bool]:
    """Which tools take the ops-history parameters (see module docstring)."""

    def _in_scope(name: str) -> bool:
        if name not in reason_tools or name == ROLLBACK_APPLY_TOOL:
            return False
        return name == BATCH_BEGIN_TOOL or not name.startswith(_BOOKKEEPING_PREFIX)

    return _in_scope


def with_ops_properties(tool: Tool) -> Tool:
    """Return ``tool`` with the three properties, or ``tool`` itself."""
    schema = getattr(tool, "inputSchema", None)
    if not isinstance(schema, dict):
        return tool
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return tool
    if any(name in properties for name in _OPS_PARAMS):
        return tool
    injected = copy.deepcopy(schema)
    injected["properties"][EXPECTED_PARAM] = dict(INJECTED_EXPECTED_PROPERTY)
    injected["properties"][DECISION_ID_PARAM] = dict(DECISION_ID_PROPERTY)
    injected["properties"][APPROVAL_PARAM] = copy.deepcopy(dict(APPROVAL_PROPERTY))
    return tool.model_copy(update={"inputSchema": injected})


def inject_ops_params(
    tools: Iterable[Tool], in_scope: Callable[[str], bool]
) -> tuple[list[Tool], frozenset[str]]:
    """Add the three properties to every tool in scope.

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
    """Separate the three parameters from the arguments the handler gets.

    Popped from a COPY; a tool outside ``injected`` gets its dict back
    untouched.

    Raises:
        ValueError: a parameter is malformed.
    """
    if name not in injected or not isinstance(arguments, dict):
        return OpsParams(), arguments
    rest = dict(arguments)
    expected = parse_expected(rest.pop(EXPECTED_PARAM, None))
    decision_id = parse_decision_id(rest.pop(DECISION_ID_PARAM, None))
    approval = parse_approval(rest.pop(APPROVAL_PARAM, None))
    params = OpsParams(expected=expected, decision_id=decision_id, approval=approval)
    return params, rest


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
    scoped = dict(handler_args) if name == BATCH_BEGIN_TOOL else {}
    return resolve_workspace_path(scoped, "STATE.json", store_attr="state_path")


def _read(path: Path) -> StateDocument | None:
    if not path.is_file():
        return None
    return read_state_file(path, strict=False)


def _readable_state(
    name: str, params: OpsParams, handler_args: Mapping[str, Any]
) -> StateDocument | None:
    """The workspace's document, or ``None`` when there is none to read.

    A STATE.json that exists but cannot be read — unparseable, not UTF-8,
    or valid JSON of the wrong shape — does not refuse the call: the
    setting lives in that file, so it cannot be known to be on, and a
    change accepted before ops history existed must not start failing here.
    Any read fault counts, whatever its type. The fault is logged, and the
    action-log append reports it in its own right. An explicit
    ``decision_id`` cannot be checked against such a file, so that call is
    refused.

    Raises:
        ValueError: ``decision_id`` was given and the file is unreadable.
    """
    try:
        return _read(_state_path(name, handler_args))
    except Exception as exc:  # noqa: BLE001 — every read fault means "off"
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
    if name == BATCH_BEGIN_TOOL:
        return False
    batch = active_batch(doc)
    return (
        batch is not None
        and ops_linkage.batch_decision_root(doc, batch.batch_id) is not None
    )


def check_ops_call(
    name: str, reason: str | None, params: OpsParams, handler_args: Mapping[str, Any]
) -> None:
    """Validate an explicit ``decision_id`` and enforce the setting.

    Raises:
        ValueError: the decision is not linkable, or ops history is on and
            ``reason`` / ``expected`` is missing.
    """
    doc = _readable_state(name, params, handler_args)
    if params.decision_id is not None:
        root = ops_linkage.check_linkable(
            doc or StateDocument(version="2"), params.decision_id
        )
    if doc is None or not ops_history_enabled(doc):
        return
    if params.decision_id is not None:
        if not params.expected and not chain_expected(doc, root):
            raise ValueError(ADOPTION_EXPECTED_REQUIRED)
        return
    if _joins_batch_decision(doc, name):
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
    try:
        check_settings_call(name, handler_args)
        if name not in injected or is_rollback_dispatch_active():
            return
        check_ops_call(name, reason, params, handler_args)
    except ValueError as exc:
        call.invalid_args(exc)
        raise


def applied_params_of(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """The call's parameters as they may be stored, or ``None``.

    Masked exactly as the journal masks ``args`` (the same function), so
    the two stores cannot disagree about what a secret is; ``None`` for an
    empty set or one over :data:`APPLIED_PARAMS_MAX_CHARS`.
    """
    masked = mask_arguments(dict(arguments))
    if not masked or not isinstance(masked, dict):
        return None
    size = len(json.dumps(masked, ensure_ascii=False, default=str))
    return masked if size <= APPLIED_PARAMS_MAX_CHARS else None


def _platform_of(name: str) -> str | None:
    family = tool_family(name)
    return family if family in _PLATFORM_FAMILIES else None


def _record_unentried(
    call: JournalledCall, name: str, intent: OpsIntent, reason: str | None
) -> None:
    """The decision of a successful call that wrote no ``action_log`` entry.

    Skipped without a STATE.json (nothing is created for it), for
    ``mureo_batch_begin`` (its decision is the batch's), for a rollback's
    reversal leg, and — without taking the lock — for a call with no
    reason, no ``approval``, no ``decision_id`` and no open batch, which
    links to nothing. An ``approval`` alone is recorded like a reason
    (#854): it is the caller's explicit statement about this change, and
    with no entry the decision is the only place it can be kept.
    The change happened, so a failure is logged rather than raised:
    failing the call would tell the agent a change that went through did
    not.
    """
    if (
        reason is None
        and intent.approval is None
        and intent.decision_id is None
        and _open_batch_id() is None
    ):
        return
    path = _state_path(name, intent.arguments)
    if name == BATCH_BEGIN_TOOL or is_rollback_dispatch_active() or not path.is_file():
        return
    request = ops_linkage.LinkRequest(
        reason=reason,
        now=server_now_iso(),
        expected=intent.expected,
        explicit_id=intent.decision_id,
        arguments=intent.arguments,
        applied_params=intent.applied_params,
        call_id=intent.call_id,
        approval=intent.approval,
    )
    try:
        root = ops_linkage.record_call_decision(
            path, request, tool=name, platform=_platform_of(name)
        )
    except Exception:  # noqa: BLE001 — the change itself already succeeded
        logger.warning("could not record the decision of %r", name, exc_info=True)
        return
    call.decision_id = root


@contextmanager
def ops_call_scope(
    call: JournalledCall,
    name: str,
    params: OpsParams,
    handler_args: Mapping[str, Any],
    injected: Collection[str],
    reason: str | None = None,
) -> Iterator[None]:
    """Bind the call's intent around dispatch, then link what it carried out.

    Outside scope this binds nothing, so a read-only call or a bookkeeping
    tool never links an entry to a decision through a stale intent. After
    a successful call the journal record is given the decision's id; a
    call that wrote no entry gets its decision recorded here.
    """
    if name not in injected:
        yield
        return
    with bind_ops_intent(
        expected=params.expected,
        decision_id=params.decision_id,
        arguments=handler_args,
        applied_params=applied_params_of(handler_args),
        call_id=call.call_id,
        approval=params.approval,
    ) as intent:
        yield
    if call.outcome != "ok":
        return
    if intent.slot.decision_id is not None:
        call.decision_id = intent.slot.decision_id
        return
    if intent.slot.wrote_entry:
        return
    _record_unentried(call, name, intent, reason)


__all__ = [
    "ADOPTION_EXPECTED_REQUIRED",
    "APPLIED_PARAMS_MAX_CHARS",
    "APPROVAL_PARAM",
    "APPROVAL_PROPERTY",
    "DECISION_ID_PROPERTY",
    "EXPECTED_PROPERTY",
    "EXPECTED_REQUIRED",
    "INJECTED_EXPECTED_PROPERTY",
    "REASON_REQUIRED",
    "OpsParams",
    "applied_params_of",
    "approval_schema",
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
