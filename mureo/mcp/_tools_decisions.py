"""The ``mureo_decision_record`` tool definition (#758, phase 3).

A partial of the ``mureo_context`` family rather than a family of its own:
it writes STATE.json like every other tool there, so it joins their
dispatch branch and their journal label with no change to ``server.py``.
Kept in its own module because ``tools_mureo_context.py`` is well over the
repo's 800-line limit.

**Not classified as a mutation.** ``mureo_decision_record`` writes a record
ABOUT a change; it does not touch an ad account. So no strategy reminder is
appended to its result, and the dispatcher injects no call-level ``reason``
into its schema — it already carries a ``rationale``, and a second sentence
at call level ("why am I writing this row") would land beside it and quietly
compete with it. That is the same call
:data:`mureo.mcp._reason_param.REASON_EXEMPT_BUILTINS` makes for
``mureo_state_action_log_append``, reached here by the name simply not
ending in a mutating suffix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.context.decisions import (
    DECISION_METRIC_VALUE_MAX_CHARS,
    DECISION_METRICS_MAX_KEYS,
    DECISION_RATIONALE_MAX_CHARS,
    DECISION_RELATED_ACTIONS_MAX,
    DECISION_STATUSES,
    DECISION_TITLE_MAX_CHARS,
)
from mureo.mcp._handlers_decisions import DECISIONS_SCOPES, handle_decision_record

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from mcp.types import TextContent

    #: The shape every handler in this family already has. Spelled out so
    #: splicing HANDLERS into the family's table does not widen its value
    #: type to ``Any`` and silence the dispatcher's own return check.
    _Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, list[TextContent]]]

#: Same wording as the batch tools': one sentence, and the sandbox rule
#: stated rather than implied.
_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional path to STATE.json. Defaults to STATE.json in the MCP "
        "server's current working directory. Paths outside it are refused."
    ),
}

#: The scalar types a ``metrics`` value may take, and how wide one may be.
#: Stated in the schema as well as enforced by the model, so the dispatcher
#: refuses a nested object before the handler runs and the agent sees which
#: key was wrong. Every bound here is the model's own constant: a schema
#: looser than the model turns a caller error into what reads as an mureo
#: error, since the call would be accepted and then raise.
_METRIC_VALUE_SCHEMA: dict[str, Any] = {
    "type": ["string", "number", "boolean", "null"],
    "maxLength": DECISION_METRIC_VALUE_MAX_CHARS,
}

#: The ``decisions`` scope on ``mureo_state_get``. Defined here because the
#: bounds and the vocabulary of this section live in this pair of modules,
#: not in ``tools_mureo_context.py``, which is already far over the
#: repo's file-length limit.
DECISIONS_SCOPE_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(DECISIONS_SCOPES),
    "description": (
        "Scope of the returned decisions trail. ``all`` (default) = every "
        "recorded decision. ``none`` = omit the section; the response still "
        "carries ``decisions_total`` and a ``decisions_scope`` marker, so an "
        "omitted trail is never read as an empty one. Independent of "
        "``action_log``."
    ),
}

_DESCRIPTION = (
    "Record a decision — a proposal, or the operator's answer to one — so "
    "the reasoning survives the session. Call it BEFORE you surface a "
    "proposal to the operator, with status='proposed', the figures you "
    "judged it on in `metrics`, and your reasoning in `rationale`. When the "
    "operator answers, call it AGAIN with status='adopted' / 'rejected' / "
    "'deferred' and `supersedes` set to the first record's `decision_id`: "
    "the section is APPEND-ONLY, so a status change is a new record, never "
    "an edit — that is what keeps 'we proposed this on the 4th and it was "
    "turned down' recoverable. After you carry a decision out, record it "
    "once more (or name the entries in `related_actions`) so the change and "
    "the reason for it are joined. `display.proposals` is the SCREEN — one "
    "moment, replaced whole on every dashboard write; this is the RECORD. "
    "`decision_id` and `recorded_at` are minted by the server; do not "
    "compute either. Every bound below refuses the write rather than "
    "truncating it."
)


TOOLS: list[Tool] = [
    Tool(
        name="mureo_decision_record",
        description=_DESCRIPTION,
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": list(DECISION_STATUSES),
                    "description": (
                        "Where the decision stands. 'proposed' before the "
                        "operator has answered; 'adopted' / 'rejected' / "
                        "'deferred' afterwards, with `supersedes` set. "
                        "'deferred' is not 'rejected' — 'not now' and 'no' "
                        "call for different behaviour next week."
                    ),
                },
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": DECISION_TITLE_MAX_CHARS,
                    "description": (
                        "What is being decided, in one line (e.g. 'Pause the "
                        "generic ad group in Search_Lead-Gen')."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": DECISION_RATIONALE_MAX_CHARS,
                    "description": (
                        "Why — the evidence you acted on and the effect you "
                        "expect. This is the payload: nothing downstream can "
                        "reconstruct it, and you are the last point at which "
                        "it exists."
                    ),
                },
                "metrics": {
                    "type": "object",
                    "description": (
                        "The figures the decision was judged on, as they "
                        'stood THEN (e.g. {"cpa_7d": 5200, '
                        '"conversions_7d": 45}). At most '
                        f"{DECISION_METRICS_MAX_KEYS} keys, each value a "
                        "string, number, boolean or null — a nested object "
                        "is refused, and so is a string longer than "
                        f"{DECISION_METRIC_VALUE_MAX_CHARS} characters (a "
                        "figure that needs a sentence belongs in "
                        "`rationale`). Without them a rationale read next "
                        "month against today's numbers is unfalsifiable."
                    ),
                    "maxProperties": DECISION_METRICS_MAX_KEYS,
                    "additionalProperties": _METRIC_VALUE_SCHEMA,
                },
                "platform": {
                    "type": "string",
                    "description": (
                        "Platform the decision is about (google_ads / "
                        "meta_ads / ...), when it is about one."
                    ),
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Campaign the decision is about, if any.",
                },
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Sub-campaign entity kind (ad_group / ad_set / "
                        "placement / ...). Must be given together with "
                        "`entity_id`."
                    ),
                },
                "entity_id": {
                    "type": "string",
                    "description": (
                        "The entity's id. Must be given together with " "`entity_type`."
                    ),
                },
                "related_actions": {
                    "type": "array",
                    "maxItems": DECISION_RELATED_ACTIONS_MAX,
                    "items": {"type": "integer", "minimum": 0},
                    "description": (
                        "Positional indices into the full action_log of the "
                        "entries this decision produced. Validated against "
                        "the log — an index past its end is refused."
                    ),
                },
                "supersedes": {
                    "type": "string",
                    "description": (
                        "The `decision_id` of the record this one updates. "
                        "Required in practice for any status other than the "
                        "first 'proposed', and validated: it must name a "
                        "decision already on record."
                    ),
                },
                "batch_id": {
                    "type": "string",
                    "description": (
                        "The declared change set this decision concerns. A "
                        "CLOSED batch is fine — the verdict on a bulk pass "
                        "is normally recorded after it finished."
                    ),
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["status", "title", "rationale"],
            "additionalProperties": False,
        },
    ),
]

HANDLERS: dict[str, _Handler] = {"mureo_decision_record": handle_decision_record}


__all__ = ["DECISIONS_SCOPE_PROPERTY", "HANDLERS", "TOOLS"]
