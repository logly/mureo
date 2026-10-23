"""Every ``## Guardrails`` field, edited from the dashboard (#843).

#786 let ``mureo configure`` set ONE bullet of the section — the account
currency. Every other rule (budget and bid caps, change limits, the
learning-reset blocks, the exclusion-impact limits) could only be written
by hand, under names such as ``max_cumulative_delivery_share_removed_pct``
that do not explain themselves. This module serves all of them:

- ``GET /api/strategy/guardrails[?client=]`` lists every field of
  :data:`~mureo.policy.guardrail_fields.GUARDRAIL_FIELDS` with its kind,
  unit and range, its label and one-line description, and what the file
  currently declares for it;
- ``POST /api/strategy/guardrails`` with ``{client?, set: {key: value},
  clear: [key]}`` validates the whole request, rewrites exactly those
  bullets, and answers with the file re-read in the GET shape.

The labels are resolved on the server and carried in the payload, so a web
extension that shows these fields renders the same names without keeping a
translation table of its own. The language is the request's ``?lang=``
(an explicit choice, such as a UI language toggle), then its
``Accept-Language`` (the browser default), then English.

Writes follow the currency module to the letter: the same STRATEGY.md
(:func:`~mureo.web.strategy_currency.strategy_path_for_client`), the same
lock (:func:`~mureo.context.strategy.mutate_strategy_file`), a timestamped
backup before an existing file changes, and no write at all for a no-op.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from dataclasses import replace
from importlib import resources
from typing import TYPE_CHECKING, Any

from mureo.context.models import StrategyEntry
from mureo.context.strategy import (
    RAW_HEADING_TYPE,
    mutate_strategy_file,
    read_strategy_file,
)
from mureo.fsutil import backup_file
from mureo.web._helpers import send_failure, send_json
from mureo.web.guardrail_values import (
    StrategyGuardrailsError,
    content_with_bullets,
    describe_fields,
    parse_changes,
)
from mureo.web.strategy_currency import (
    StrategyCurrencyError,
    _guardrails_entry,
    _payload_client,
    _query_client,
    strategy_path_for_client,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from http.server import BaseHTTPRequestHandler
    from pathlib import Path

    from mureo.policy.guardrail_fields import GuardrailField

logger = logging.getLogger(__name__)

__all__ = [
    "StrategyGuardrailsError",
    "post_strategy_guardrails",
    "read_guardrails",
    "resolve_lang",
    "serve_strategy_guardrails",
    "write_guardrails",
]

_SUPPORTED_LANGS = ("en", "ja")
_DEFAULT_LANG = "en"

#: Heading of a section this module has to create (as the currency card does).
_GUARDRAILS_TITLE = "Guardrails"

#: Refusals the caller can fix (400). Anything else is a fault on our side.
_CALLER_FAULTS = frozenset(
    {
        "no_workspace",
        "invalid_payload",
        "unknown_field",
        "invalid_value",
        "out_of_range",
        "conflicting_fields",
    }
)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


#: The parsed catalog once it has loaded. A failed load is NOT kept: the
#: next request tries again instead of serving raw keys until a restart.
_catalog_cache: dict[str, dict[str, str]] | None = None


def _i18n_catalog() -> dict[str, dict[str, str]]:
    """The bundled ``i18n.json`` the browser UI translates from."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    ref = resources.files("mureo") / "_data" / "web" / "i18n.json"
    try:
        data = json.loads(ref.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("i18n.json could not be read for the Guardrails labels")
        return {}
    if not isinstance(data, dict):
        logger.error("i18n.json is not an object; the Guardrails labels fall back")
        return {}
    _catalog_cache = data
    return data


def _translate(key: str, lang: str) -> str:
    catalog = _i18n_catalog()
    for locale in (lang, _DEFAULT_LANG):
        value = catalog.get(locale, {}).get(key)
        if isinstance(value, str) and value:
            return value
    return key


def _labeller(lang: str) -> Callable[[GuardrailField], tuple[str, str]]:
    def labels(item: GuardrailField) -> tuple[str, str]:
        return _translate(item.label_key, lang), _translate(item.desc_key, lang)

    return labels


def _header_lang(header: str) -> str | None:
    """The highest-weighted supported language in an ``Accept-Language``."""
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate(header.split(",")):
        tag, _, params = part.strip().partition(";")
        weight = 1.0
        if params.strip().startswith("q="):
            try:
                weight = float(params.strip()[2:])
            except ValueError:
                continue
        primary = tag.strip().lower().split("-", 1)[0]
        if weight > 0 and primary in _SUPPORTED_LANGS:
            ranked.append((-weight, position, primary))
    return min(ranked)[2] if ranked else None


def resolve_lang(accept_language: str | None, query_lang: str | None) -> str:
    """``?lang=`` first, then ``Accept-Language``, then English.

    The query is an explicit choice (a page following its own language
    toggle), so it outranks the browser's default. An unsupported value in
    either is skipped, not an error.
    """
    if query_lang:
        primary = query_lang.strip().lower().split("-", 1)[0]
        if primary in _SUPPORTED_LANGS:
            return primary
    if accept_language:
        found = _header_lang(accept_language)
        if found is not None:
            return found
    return _DEFAULT_LANG


# ---------------------------------------------------------------------------
# Reading and writing
# ---------------------------------------------------------------------------


def _state(entries: list[StrategyEntry], *, exists: bool, lang: str) -> dict[str, Any]:
    entry = _guardrails_entry(entries)
    content = entry.content if entry is not None else ""
    return {
        "exists": exists,
        "guardrails_present": entry is not None,
        "fields": describe_fields(content, _labeller(lang)),
    }


def read_guardrails(path: Path, *, lang: str = _DEFAULT_LANG) -> dict[str, Any]:
    """Every field and what ``path`` declares for it. A missing file is the
    ordinary state of a workspace with no strategy yet, not an error.

    Describing the values is inside the ``try`` too: whatever a hand-edited
    file holds, the route answers ``read_failed`` rather than dropping the
    connection.
    """
    try:
        exists = path.exists()
        entries = read_strategy_file(path) if exists else []
        return _state(entries, exists=exists, lang=lang)
    except Exception as exc:  # noqa: BLE001 — every read fault is one code
        logger.exception("STRATEGY.md could not be read for its Guardrails")
        raise StrategyGuardrailsError("read_failed") from exc


def _with_changes(
    entries: list[StrategyEntry], changes: Mapping[str, str | None]
) -> list[StrategyEntry]:
    """``entries`` with the changes applied — a new list, or the input
    itself (``==``) when there is nothing to do."""
    entry = _guardrails_entry(entries)
    if entry is None:
        content = content_with_bullets("", changes)
        if not content:
            return entries
        return [*entries, StrategyEntry(RAW_HEADING_TYPE, _GUARDRAILS_TITLE, content)]
    content = content_with_bullets(entry.content, changes)
    if content == entry.content:
        return entries
    # An emptied section is kept: the operator made the heading.
    return [
        replace(item, content=content) if item is entry else item for item in entries
    ]


def _mutate(
    path: Path, entries: list[StrategyEntry], changes: Mapping[str, str | None]
) -> list[StrategyEntry]:
    """The locked half: back the file up, then hand back the new entries."""
    updated = _with_changes(entries, changes)
    if updated != entries:
        backup_file(path, timestamped=True)
    return updated


def write_guardrails(
    path: Path,
    changes: Mapping[str, str | None],
    *,
    lang: str = _DEFAULT_LANG,
) -> dict[str, Any]:
    """Apply already-validated ``changes`` (from :func:`parse_changes`).

    Decided twice like the currency writer: once unlocked, so a no-op never
    touches the file, and again under the lock — the answer that is written.
    """
    try:
        current = read_strategy_file(path)
        if _with_changes(current, changes) != current:
            mutate_strategy_file(path, lambda entries: _mutate(path, entries, changes))
    except Exception as exc:  # noqa: BLE001 — every write fault is one code
        logger.exception("STRATEGY.md Guardrails could not be written")
        raise StrategyGuardrailsError("write_failed") from exc
    return read_guardrails(path, lang=lang)


# ---------------------------------------------------------------------------
# Handler glue
# ---------------------------------------------------------------------------


def _request_lang(handler: BaseHTTPRequestHandler) -> str:
    query = handler.path.split("?", 1)[1] if "?" in handler.path else ""
    values = urllib.parse.parse_qs(query).get("lang") or []
    return resolve_lang(
        handler.headers.get("Accept-Language"), values[0] if values else None
    )


def _envelope(client: str | None, path: Path, state: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "client": client, "path": str(path), **state}


def _resolve_path(client: str | None) -> Path:
    try:
        return strategy_path_for_client(client)
    except StrategyCurrencyError as exc:
        raise StrategyGuardrailsError(exc.code) from exc


def serve_strategy_guardrails(handler: BaseHTTPRequestHandler) -> None:
    """GET ``/api/strategy/guardrails`` — every field, labelled, with its value.

    Read-only and secret-free, like the currency GET, so the Host-header
    gate alone suffices.
    """
    client = _query_client(handler.path)
    try:
        path = _resolve_path(client)
        state = read_guardrails(path, lang=_request_lang(handler))
    except StrategyGuardrailsError as exc:
        send_failure(handler, exc.code, _CALLER_FAULTS, field=exc.field)
        return
    send_json(handler, _envelope(client, path, state))


def post_strategy_guardrails(
    handler: BaseHTTPRequestHandler, payload: dict[str, Any]
) -> None:
    """POST ``/api/strategy/guardrails`` — set and clear bullets.

    The whole request is validated before the file is opened, so a refusal
    (400, with the offending ``field``) never leaves a half-applied change.
    """
    client = _payload_client(payload)
    try:
        changes = parse_changes(payload)
        path = _resolve_path(client)
        state = write_guardrails(path, changes, lang=_request_lang(handler))
    except StrategyGuardrailsError as exc:
        send_failure(handler, exc.code, _CALLER_FAULTS, field=exc.field)
        return
    send_json(handler, _envelope(client, path, state))
