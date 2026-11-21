"""One coroutine per ChatGPT Ads custom audience tool (#995).

Merged into :data:`mureo.chatgpt_ads.handlers.HANDLERS`. The identifier file
of an add or remove is read by :func:`mureo._image_validation.read_data_file`
(the upload tool's path rules, one open, a bounded read) off the event loop,
and every line is normalised by :mod:`mureo.chatgpt_ads._hashing` before the
first request: one invalid line refuses the whole call, so a partial list is
never applied. No message here quotes a line of the file, not even in part;
the lines are personal data, and an error travels to the model and the logs.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from mureo._image_validation import read_data_file
from mureo.chatgpt_ads._api import (
    MAX_IDENTIFIER_FILE_BYTES,
    MAX_IDENTIFIER_FILE_LABEL,
    MAX_INLINE_IDENTIFIERS,
    PAGE_MAX_ENTITIES,
)
from mureo.chatgpt_ads._hashing import (
    IDENTIFIER_TYPES,
    SENT_IDENTIFIER_TYPES,
    normalized_identifier,
)
from mureo.chatgpt_ads._validation import limit_value, path_id
from mureo.chatgpt_ads.handlers_create import idempotency_key_value
from mureo.chatgpt_ads.handlers_mutations import required_name
from mureo.chatgpt_ads.tools import DEFAULT_LIST_LIMIT
from mureo.chatgpt_ads.tools_audiences import (
    AUDIENCE_DESCRIPTION_MAX_CHARS,
    AUDIENCE_INTENDED_USES,
    FILE_PATH_MAX_CHARS,
    IDENTIFIER_FILE_EXTENSIONS,
)

if TYPE_CHECKING:
    from mureo.chatgpt_ads.client import ChatGPTAdsClient
    from mureo.chatgpt_ads.handlers_mutations import Handler

_FILE_EXTENSIONS = frozenset(IDENTIFIER_FILE_EXTENSIONS)
#: Line numbers one refusal names; the count says how many more there are.
MAX_REPORTED_LINES = 10


async def _audiences_list(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    params: list[tuple[str, str]] = []
    intended_use = arguments.get("intended_use")
    if intended_use is not None:
        if intended_use not in AUDIENCE_INTENDED_USES:
            raise ValueError(
                f"intended_use must be one of {', '.join(AUDIENCE_INTENDED_USES)}"
            )
        params.append(("intended_use", intended_use))
    limit = limit_value(arguments, DEFAULT_LIST_LIMIT)
    return await client.list_all(
        "/custom_audiences", params, limit=limit, page_max=PAGE_MAX_ENTITIES
    )


async def _audiences_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    return await client.get(f"/custom_audiences/{path_id(arguments, 'audience_id')}")


async def _audiences_create(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    # Only name and description: no file field is ever sent, so the
    # audience is created empty.
    body = {"name": required_name(arguments)}
    if "description" in arguments:
        description = arguments["description"]
        if (
            not isinstance(description, str)
            or len(description) > AUDIENCE_DESCRIPTION_MAX_CHARS
        ):
            raise ValueError(
                "description must be a string of at most "
                f"{AUDIENCE_DESCRIPTION_MAX_CHARS} characters"
            )
        body["description"] = description
    return await client.post("/custom_audiences", body)


def _identifier_type(arguments: dict[str, Any]) -> str:
    value = arguments.get("identifier_type")
    if value not in IDENTIFIER_TYPES:
        raise ValueError(f"identifier_type is required: {', '.join(IDENTIFIER_TYPES)}")
    return str(value)


def _file_path(arguments: dict[str, Any]) -> str:
    value = arguments.get("file_path")
    if not isinstance(value, str) or not 1 <= len(value) <= FILE_PATH_MAX_CHARS:
        raise ValueError(
            "file_path is required: the path of a local .txt or .csv file, at "
            f"most {FILE_PATH_MAX_CHARS} characters"
        )
    return value


def _file_lines(content: bytes) -> list[str]:
    """The file's lines, numbered the way an editor numbers them.

    ``utf-8-sig`` accepts the byte-order mark spreadsheet exports write.
    The refusal is raised after the ``except`` block, so neither its cause
    nor its context holds the decode error, whose ``object`` is the whole
    file.
    """
    try:
        return content.decode("utf-8-sig").split("\n")
    except UnicodeDecodeError:
        pass
    raise ValueError("file_path must be a UTF-8 text file")


def _invalid_lines_error(numbers: list[int], identifier_type: str) -> ValueError:
    shown = ", ".join(str(n) for n in numbers[:MAX_REPORTED_LINES])
    more = (
        f" (the first {MAX_REPORTED_LINES} shown)"
        if len(numbers) > MAX_REPORTED_LINES
        else ""
    )
    return ValueError(
        f"{len(numbers)} line(s) of file_path are not valid {identifier_type} "
        f"values: line {shown}{more}. Nothing was sent; fix or remove those "
        "lines and call again."
    )


def identifiers_body(lines: list[str], identifier_type: str) -> dict[str, Any]:
    """The request body for ``lines``, each normalised as ``identifier_type``.

    Blank lines are skipped and duplicates dropped after normalisation, so
    ``A@example.com`` and ``a@example.com`` count once.
    """
    distinct: dict[str, None] = {}
    invalid: list[int] = []
    for number, line in enumerate(lines, start=1):
        raw = line.strip()
        if not raw:
            continue
        value = normalized_identifier(identifier_type, raw)
        if value is None:
            invalid.append(number)
        else:
            distinct.setdefault(value, None)
    if invalid:
        raise _invalid_lines_error(invalid, identifier_type)
    if not distinct:
        raise ValueError("file_path holds no identifiers; give one per line")
    if len(distinct) > MAX_INLINE_IDENTIFIERS:
        raise ValueError(
            f"file_path holds {len(distinct):,} distinct identifiers; one call "
            f"sends 1 to {MAX_INLINE_IDENTIFIERS:,}: split the file and call "
            "once per part"
        )
    sent_type = SENT_IDENTIFIER_TYPES[identifier_type]
    return {
        "identifiers": [
            {"identifier_type": sent_type, "identifier": value} for value in distinct
        ]
    }


def _members_handler(action: str) -> Handler:
    async def handler(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
        audience_id = path_id(arguments, "audience_id")
        identifier_type = _identifier_type(arguments)
        file_path = _file_path(arguments)
        key = idempotency_key_value(arguments)
        _, content = await asyncio.to_thread(
            read_data_file,
            file_path,
            max_size_bytes=MAX_IDENTIFIER_FILE_BYTES,
            max_size_label=MAX_IDENTIFIER_FILE_LABEL,
            allowed_extensions=_FILE_EXTENSIONS,
        )
        body = identifiers_body(_file_lines(content), identifier_type)
        return await client.post_operation(
            f"/custom_audiences/{audience_id}/{action}", body, idempotency_key=key
        )

    return handler


async def _operations_get(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    audience_id = path_id(arguments, "audience_id")
    operation_id = path_id(arguments, "operation_id")
    return await client.get(
        f"/custom_audiences/{audience_id}/operations/{operation_id}"
    )


AUDIENCE_HANDLERS: dict[str, Handler] = {
    "chatgpt_ads_audiences_list": _audiences_list,
    "chatgpt_ads_audiences_get": _audiences_get,
    "chatgpt_ads_audiences_create": _audiences_create,
    "chatgpt_ads_audiences_members_add": _members_handler("add"),
    "chatgpt_ads_audiences_members_remove": _members_handler("remove"),
    "chatgpt_ads_audiences_operations_get": _operations_get,
}

__all__ = [
    "AUDIENCE_HANDLERS",
    "MAX_REPORTED_LINES",
    "identifiers_body",
]
