"""The ``## Guardrails`` ``currency`` bullet, edited from the dashboard (#786).

#783/#785 gave the strategy gate a ``currency`` bullet so it can divide
Meta's minor-unit ``daily_budget`` / ``lifetime_budget`` / ``bid_amount``
into the currency units every cap is written in. Until now that bullet could
only be written by hand or by the ``onboard`` skill, which leaves the most
consequential line in ``## Guardrails`` — the one that decides whether a cap
of ``250`` means €250.00 or €2.50 — as the one line nothing in ``mureo
configure`` can set.

This module is the whole feature except the route hooks: the option table
the dropdown is built from, a surgical read/write of that one bullet, and
the two handler functions ``handlers.py`` calls. It lives here rather than
in ``handlers.py`` because that file is already over the project's
file-size budget.

**Surgical is the point.** STRATEGY.md is the operator's document; mureo
edits one line of it. The writer replaces (or inserts, or drops) exactly the
``currency`` bullet and hands every other entry back untouched, takes a
timestamped backup before it changes an existing file — the same protection
``mureo_strategy_set`` gives a full replacement — and does the whole
read-modify-write under the STRATEGY.md lock so a concurrent MCP write
cannot be lost.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.context.models import StrategyEntry
from mureo.context.strategy import (
    RAW_HEADING_TYPE,
    mutate_strategy_file,
    read_strategy_file,
)
from mureo.core.providers.models import (
    META_OFFSET_100_CURRENCIES,
    ZERO_DECIMAL_CURRENCIES,
    minor_units_per_unit,
)
from mureo.fsutil import backup_file
from mureo.policy.currency_units import parse_currency_code
from mureo.policy.strategy_gate import GUARDRAILS_BULLET_RE, GUARDRAILS_HEADING
from mureo.web._helpers import send_error_json, send_json
from mureo.web.report_clients import state_store_for_client

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

__all__ = [
    "CURRENCY_OPTIONS",
    "StrategyCurrencyError",
    "post_strategy_currency",
    "read_currency",
    "serve_strategy_currency",
    "strategy_path_for_client",
    "write_currency",
]

#: The bullet key this module owns. Every other key in the section belongs
#: to the gate's cap vocabulary and is never touched here.
_CURRENCY_KEY = "currency"

#: The heading a section gets when this module has to create one. Written in
#: the casing the docs and the ``onboard`` skill use; the gate matches it
#: case-insensitively (:data:`~mureo.policy.strategy_gate.GUARDRAILS_HEADING`).
_GUARDRAILS_TITLE = "Guardrails"

#: FBZ is Meta's own internal credits unit, not a currency an ad account is
#: ever denominated in — it is in the offset table because Meta lists it
#: there, not because an operator could pick it. Offering it would put a
#: divisor on the caps that no real account's amounts are expressed in.
_NON_ACCOUNT_CURRENCIES = frozenset({"FBZ"})

#: Every code the dropdown may offer, with Meta's offset for each, so the
#: browser can label a zero-decimal currency without a second table.
CURRENCY_OPTIONS: tuple[dict[str, Any], ...] = tuple(
    {"code": code, "minor_units": minor_units_per_unit(code)}
    for code in sorted(
        (ZERO_DECIMAL_CURRENCIES | META_OFFSET_100_CURRENCIES) - _NON_ACCOUNT_CURRENCIES
    )
)

_CURRENCY_CODES: frozenset[str] = frozenset(
    str(option["code"]) for option in CURRENCY_OPTIONS
)


class StrategyCurrencyError(Exception):
    """The currency bullet could not be read or written.

    Carries a short, secret-free ``code`` the handler maps to an error
    envelope, modelled on
    :class:`~mureo.web.report_clients.ClientArchiveError`. The underlying
    exception is logged server-side and never echoed — its message can carry
    a filesystem path or other deployment detail.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Which STRATEGY.md
# ---------------------------------------------------------------------------


def strategy_path_for_client(client: str | None) -> Path:
    """The STRATEGY.md of ``client``'s workspace.

    Goes through the one multi-account seam the Reports tab uses, so OSS
    (single workspace) ignores ``client`` by construction and an Agency
    backend resolves it. A store that exposes neither ``strategy_path`` nor
    ``workspace`` has no document to edit, which is a refusal rather than a
    guess at a path.
    """
    store = state_store_for_client(client)
    strategy_path = getattr(store, "strategy_path", None)
    if strategy_path is not None:
        return Path(strategy_path)
    workspace = getattr(store, "workspace", None)
    if workspace is not None:
        return Path(workspace) / "STRATEGY.md"
    raise StrategyCurrencyError("no_workspace")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _guardrails_entry(entries: list[StrategyEntry]) -> StrategyEntry | None:
    """The ``## Guardrails`` entry, found exactly as the gate finds it."""
    for entry in entries:
        if entry.title.strip().lower() == GUARDRAILS_HEADING:
            return entry
    return None


def _currency_line_indices(content: str) -> list[int]:
    """Line numbers of the ``currency`` bullets in a section body."""
    hits: list[int] = []
    for index, line in enumerate(content.splitlines()):
        match = GUARDRAILS_BULLET_RE.match(line)
        if match is not None and match.group(1).lower() == _CURRENCY_KEY:
            hits.append(index)
    return hits


def _raw_currency(entry: StrategyEntry | None) -> str | None:
    """The bullet's value as written, or ``None``.

    The LAST occurrence wins, which is what
    :func:`~mureo.policy.strategy_gate.parse_guardrails` does — the
    dashboard must report the value the gate would actually enforce.
    """
    if entry is None:
        return None
    hits = _currency_line_indices(entry.content)
    if not hits:
        return None
    match = GUARDRAILS_BULLET_RE.match(entry.content.splitlines()[hits[-1]])
    return None if match is None else match.group(2)


def _state(entries: list[StrategyEntry], *, exists: bool) -> dict[str, Any]:
    entry = _guardrails_entry(entries)
    raw = _raw_currency(entry)
    return {
        # An unrecognized code parses to None with ``raw_value`` still set,
        # so the browser can say the line is there and being ignored.
        "currency": parse_currency_code(raw),
        "raw_value": raw,
        "guardrails_present": entry is not None,
        "exists": exists,
    }


def read_currency(path: Path) -> dict[str, Any]:
    """What ``path`` currently declares: the code, the raw line, the section.

    A missing file is not an error — it is the ordinary state of a workspace
    nobody has written a strategy for yet.
    """
    if not path.exists():
        return _state([], exists=False)
    try:
        entries = read_strategy_file(path)
    except Exception as exc:  # noqa: BLE001 — every read fault is one code
        logger.exception("STRATEGY.md could not be read for its currency bullet")
        raise StrategyCurrencyError("read_failed") from exc
    return _state(entries, exists=True)


# ---------------------------------------------------------------------------
# Writing — pure decisions first
# ---------------------------------------------------------------------------


def _bullet(code: str) -> str:
    return f"- {_CURRENCY_KEY}: {code}"


def _content_with_currency(content: str, code: str | None) -> str:
    """A section body with the ``currency`` bullet set to / cleared of ``code``.

    Pure, and deliberately line-surgical: an existing bullet is replaced
    where it stands so the operator's ordering and comments survive, a new
    one goes FIRST (the order the docs and the ``onboard`` skill write the
    section in, because it is the line the caps below are denominated by),
    and clearing takes the line out and leaves everything else alone.

    A section carrying the key twice is degenerate but possible by hand. The
    read above reports the LAST one, so setting has to leave exactly one
    line behind or the new value would be shadowed by the stale one.
    """
    lines = content.splitlines()
    hits = _currency_line_indices(content)
    if code is None:
        if not hits:
            return content
        dropped = set(hits)
        return "\n".join(
            line for index, line in enumerate(lines) if index not in dropped
        )
    bullet = _bullet(code)
    if not hits:
        return f"{bullet}\n{content}" if content else bullet
    first, extra = hits[0], set(hits[1:])
    kept = [
        bullet if index == first else line
        for index, line in enumerate(lines)
        if index == first or index not in extra
    ]
    return "\n".join(kept)


def _with_currency(
    entries: list[StrategyEntry], code: str | None
) -> list[StrategyEntry]:
    """``entries`` with the Guardrails currency set to / cleared of ``code``.

    Pure: a new list of new entries, never a mutation of the input. Returns
    the input unchanged (``==``) when there is nothing to do, which is how
    the caller knows not to rewrite the file at all.
    """
    entry = _guardrails_entry(entries)
    if entry is None:
        if code is None:
            return entries
        return [
            *entries,
            StrategyEntry(RAW_HEADING_TYPE, _GUARDRAILS_TITLE, _bullet(code)),
        ]
    content = _content_with_currency(entry.content, code)
    if content == entry.content:
        return entries
    # The section is kept even when clearing empties it: the operator made
    # it, and dropping a heading is not what "not set" was asked for.
    return [
        replace(item, content=content) if item is entry else item for item in entries
    ]


def write_currency(path: Path, code: str | None) -> dict[str, Any]:
    """Set (or clear, with ``None``) the ``currency`` bullet of ``path``.

    ``code`` must already be stripped and upper-cased by the caller — the
    handler normalises at the HTTP boundary and this writer is strict, so a
    call that skipped the boundary fails loudly instead of writing a code
    the gate would then drop with a warning.

    The change is decided twice: once unlocked, to answer "is there anything
    to do at all" without touching the file (a no-op must not churn the
    mtime or leave a backup beside a document mureo did not change), and
    again inside :func:`~mureo.context.strategy.mutate_strategy_file`, which
    holds the lock — that second answer is the one that gets written.
    """
    if code is not None and code not in _CURRENCY_CODES:
        raise StrategyCurrencyError("invalid_currency")
    try:
        current = read_strategy_file(path)
        if _with_currency(current, code) != current:
            mutate_strategy_file(path, lambda entries: _mutate(path, entries, code))
    except Exception as exc:  # noqa: BLE001 — every write fault is one code
        logger.exception("STRATEGY.md currency bullet could not be written")
        raise StrategyCurrencyError("write_failed") from exc
    return read_currency(path)


def _mutate(
    path: Path, entries: list[StrategyEntry], code: str | None
) -> list[StrategyEntry]:
    """The locked half: back the file up, then hand back the new entries."""
    updated = _with_currency(entries, code)
    if updated != entries:
        # Before the write, under the lock, exactly like mureo_strategy_set.
        backup_file(path, timestamped=True)
    return updated


# ---------------------------------------------------------------------------
# Handler glue — module-level so handlers.py only carries the route hooks
# ---------------------------------------------------------------------------


def _query_client(request_path: str) -> str | None:
    """The ``client`` query parameter of a request path, or ``None``."""
    if "?" not in request_path:
        return None
    parsed = urllib.parse.parse_qs(request_path.split("?", 1)[1])
    values = parsed.get("client") or []
    slug = values[0].strip() if values else ""
    return slug or None


def _envelope(client: str | None, path: Path, state: dict[str, Any]) -> dict[str, Any]:
    """One body shape for both routes, so the browser has one parser."""
    return {
        "status": "ok",
        "client": client,
        "path": str(path),
        "options": list(CURRENCY_OPTIONS),
        **state,
    }


def _send_failure(
    handler: BaseHTTPRequestHandler, error: StrategyCurrencyError
) -> None:
    """A refusal the caller can fix is a 400; a fault on our side is a 500."""
    caller_fault = {"no_workspace", "invalid_currency"}
    status = 400 if error.code in caller_fault else 500
    send_error_json(handler, status, error.code)


def serve_strategy_currency(handler: BaseHTTPRequestHandler) -> None:
    """GET ``/api/strategy/currency`` — the current code and the options.

    Read-only and secret-free (the STRATEGY.md path is the same one the
    Reports tab already reports), so the Host-header gate alone suffices
    like every other GET JSON endpoint.
    """
    client = _query_client(handler.path)
    try:
        path = strategy_path_for_client(client)
        state = read_currency(path)
    except StrategyCurrencyError as exc:
        _send_failure(handler, exc)
        return
    send_json(handler, _envelope(client, path, state))


def post_strategy_currency(
    handler: BaseHTTPRequestHandler, payload: dict[str, Any]
) -> None:
    """POST ``/api/strategy/currency`` — write or clear the bullet.

    ``currency`` is ``null`` / ``""`` to clear, or one of
    :data:`CURRENCY_OPTIONS`; it is normalised here (strip + upper-case) so
    the operator's ``eur`` lands as ``EUR`` in the document, and anything
    that is not a string is refused rather than coerced — ``str(5)`` is a
    perfectly good way to write nonsense into someone's strategy.
    """
    raw = payload.get("currency")
    if raw is None:
        code: str | None = None
    elif isinstance(raw, str):
        code = raw.strip().upper() or None
    else:
        send_error_json(handler, 400, "invalid_currency")
        return
    client = _payload_client(payload)
    try:
        path = strategy_path_for_client(client)
        state = write_currency(path, code)
    except StrategyCurrencyError as exc:
        _send_failure(handler, exc)
        return
    send_json(handler, _envelope(client, path, state))


def _payload_client(payload: dict[str, Any]) -> str | None:
    value = payload.get("client")
    if not isinstance(value, str):
        return None
    return value.strip() or None
