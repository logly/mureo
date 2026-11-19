"""The ChatGPT Ads custom audience tools (#995).

Pure data, built by :func:`mureo.chatgpt_ads.tools.build_tool` and from the
fragments the other tool modules use. Member identifiers are personal data,
so they never travel as tool arguments: tool arguments are persisted in the
audit trail and pass through the model. The add and remove tools take the
path of a local file instead, and mureo hashes email addresses and phone
numbers before anything is sent (:mod:`mureo.chatgpt_ads._hashing`).

Neither add nor remove records a reversal: removing what was added would also
remove members that were in the audience before, so the opposite call is not
a restore. Remove carries the archive tools' destructive annotation: what it
takes out is gone, and it can take an audience below the size it needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.chatgpt_ads._api import (
    MAX_IDENTIFIER_FILE_LABEL,
    MAX_INLINE_IDENTIFIERS,
)
from mureo.chatgpt_ads._hashing import IDENTIFIER_TYPES
from mureo.chatgpt_ads.tools import (
    ENTITY_LIMIT,
    NAME_MAX_CHARS,
    NAME_MIN_CHARS,
    build_tool,
    id_param,
)
from mureo.chatgpt_ads.tools_create import DESTROYS, IDEMPOTENCY_KEY
from mureo.chatgpt_ads.tools_mutations import MUTATES, NAME

if TYPE_CHECKING:
    from mcp.types import Tool, ToolAnnotations

#: ``intended_use`` values the audience list filters on.
AUDIENCE_INTENDED_USES = ("inclusion", "exclusion", "bid_multiplier")
#: Length of an audience description: the reference states none; this
#: bounds one request body at the name's limit.
AUDIENCE_DESCRIPTION_MAX_CHARS = NAME_MAX_CHARS
#: Length of a local file path: the reference states none (the path never
#: leaves the machine); 4096 is the common ``PATH_MAX``.
FILE_PATH_MAX_CHARS = 4096
#: Extensions the identifier file may have: plain text, one value per line.
IDENTIFIER_FILE_EXTENSIONS = ("txt", "csv")
#: Matched users an audience needs before it can target or carry a bid
#: multiplier; exclusion has no minimum.
MIN_MATCHED_USERS = 25_000

AUDIENCE_IDENTITY = {
    "identity": {"entity_type": "audience", "entity_id": "audience_id"}
}

_AUDIENCE_ID = id_param("Custom audience", "caud_123")

_ELIGIBILITY_NOTE = (
    "An audience used for inclusion or a bid multiplier needs at least "
    f"{MIN_MATCHED_USERS:,} matched users; exclusion has no minimum. Custom "
    "audiences are not supported for campaigns that target the EEA or "
    "Switzerland. Upload only first-party data you have the right to use."
)

_LIST = build_tool(
    "chatgpt_ads_audiences_list",
    "Lists the custom audiences of the ChatGPT Ads account. Returns a JSON "
    "array of audience objects as the platform returns them (id, name, "
    "description, status such as processing / ready / too_small, matched "
    "count ranges, membership_revision). Read-only. Use this to find an "
    "audience_id; for one audience use chatgpt_ads_audiences_get.",
    {
        "intended_use": {
            "type": "string",
            "enum": list(AUDIENCE_INTENDED_USES),
            "description": (
                "Return only audiences usable for this purpose: inclusion, "
                "exclusion or bid_multiplier. Omit for all."
            ),
        },
        "limit": ENTITY_LIMIT,
    },
    [],
)

_GET = build_tool(
    "chatgpt_ads_audiences_get",
    "Gets one ChatGPT Ads custom audience. Returns the platform object "
    "unchanged: name, description, status, matched count ranges and "
    "membership_revision. Read-only. Use this to see whether an audience is "
    "ready and large enough to use. To list audiences use "
    "chatgpt_ads_audiences_list.",
    {"audience_id": _AUDIENCE_ID},
    ["audience_id"],
)

_CREATE = build_tool(
    "chatgpt_ads_audiences_create",
    "Creates one empty ChatGPT Ads custom audience; add members afterwards "
    "with chatgpt_ads_audiences_members_add. Returns the new platform object "
    "unchanged; wait for status ready before using it. Mutates the account. "
    "An empty audience needs the account's small-audience enablement. "
    f"{_ELIGIBILITY_NOTE} The platform offers no idempotency key for this "
    "call: if the answer is lost, check chatgpt_ads_audiences_list before "
    "creating another. No reversal is recorded.",
    {
        "name": {
            **NAME,
            "description": (
                f"Audience name: {NAME_MIN_CHARS} to {NAME_MAX_CHARS} characters "
                "on one line, not all spaces."
            ),
        },
        "description": {
            "type": "string",
            "maxLength": AUDIENCE_DESCRIPTION_MAX_CHARS,
            "description": (
                "Optional note on what the audience holds, up to "
                f"{AUDIENCE_DESCRIPTION_MAX_CHARS} characters."
            ),
        },
    },
    ["name"],
    annotations=MUTATES,
)

_MEMBERS_IDEMPOTENCY_KEY = {
    **IDEMPOTENCY_KEY,
    "description": (
        "Optional key for repeating this add or remove: letters, digits, '_' "
        "or '-'. Omit it on a first attempt and mureo generates one; pass the "
        "key an error message names, with the same arguments and file, to "
        "get the first accepted operation back instead of starting a second."
    ),
}


_REMOVE_NOTE = (
    "A removal can take an audience below the "
    f"{MIN_MATCHED_USERS:,} matched users that inclusion and bid multipliers "
    "need. "
)


def _members_tool(
    verb: str, effect: str, annotations: ToolAnnotations, note: str = ""
) -> Tool:
    description = (
        f"{effect} one ChatGPT Ads custom audience from a local file. {note}Returns "
        "the platform's operation object unchanged (operation_id, status "
        "processing / succeeded / failed). The operation is asynchronous: "
        "poll chatgpt_ads_audiences_operations_get until it is not processing. "
        "Mutates the account. The file holds one identifier per line, all of "
        f"identifier_type, between 1 and {MAX_INLINE_IDENTIFIERS:,} distinct "
        f"values, at most {MAX_IDENTIFIER_FILE_LABEL}; blank lines and "
        "duplicates are dropped. email and phone (E.164 with '+' and country "
        "code) are normalised and SHA-256 hashed before sending; gaid is sent "
        "as given, as the platform requires. One invalid line refuses the whole "
        "call before any request, naming line numbers only. The identifiers "
        "never pass through tool arguments. No reversal is recorded: the "
        "opposite call would also touch members that were there before. "
        f"{_ELIGIBILITY_NOTE}"
    )
    return build_tool(
        f"chatgpt_ads_audiences_members_{verb}",
        description,
        {
            "audience_id": _AUDIENCE_ID,
            "file_path": {
                "type": "string",
                "minLength": 1,
                "maxLength": FILE_PATH_MAX_CHARS,
                "description": (
                    "Path of a local UTF-8 .txt or .csv file with one "
                    "identifier per line and no header row (e.g. "
                    "'/Users/me/audiences/list.txt'). Only the hashed or "
                    "raw-advertising-id values are sent, never the path."
                ),
            },
            "identifier_type": {
                "type": "string",
                "enum": list(IDENTIFIER_TYPES),
                "description": (
                    "What every line holds: email, phone, gaid (Google "
                    "advertising id), or email_sha256 / phone_number_sha256 "
                    "already hashed by the same rule (64 hex characters)."
                ),
            },
            "idempotency_key": _MEMBERS_IDEMPOTENCY_KEY,
        },
        ["audience_id", "file_path", "identifier_type"],
        annotations=annotations,
        declarations=AUDIENCE_IDENTITY,
    )


_OPERATIONS_GET = build_tool(
    "chatgpt_ads_audiences_operations_get",
    "Gets one membership operation of a ChatGPT Ads custom audience, as "
    "started by chatgpt_ads_audiences_members_add or _remove. Returns the "
    "platform object unchanged: status processing, succeeded or failed, and "
    "failure_reason when it failed. Read-only. Use this to learn whether an "
    "add or remove finished.",
    {
        "audience_id": _AUDIENCE_ID,
        "operation_id": id_param("Operation", "caudop_123"),
    },
    ["audience_id", "operation_id"],
)

AUDIENCE_TOOLS: tuple[Tool, ...] = (
    _LIST,
    _GET,
    _CREATE,
    _members_tool("add", "Adds members to", MUTATES),
    _members_tool("remove", "Removes members from", DESTROYS, _REMOVE_NOTE),
    _OPERATIONS_GET,
)

#: The tools whose lost answer names an operation rather than an entity.
MEMBERS_TOOL_NAMES = frozenset(
    {"chatgpt_ads_audiences_members_add", "chatgpt_ads_audiences_members_remove"}
)

__all__ = [
    "AUDIENCE_DESCRIPTION_MAX_CHARS",
    "AUDIENCE_IDENTITY",
    "AUDIENCE_INTENDED_USES",
    "AUDIENCE_TOOLS",
    "FILE_PATH_MAX_CHARS",
    "IDENTIFIER_FILE_EXTENSIONS",
    "MEMBERS_TOOL_NAMES",
    "MIN_MATCHED_USERS",
]
