"""The pure half of the Guardrails editor (#843): read, validate, rewrite.

Three decisions, none of which touches a file:

- :func:`describe_fields` — what a ``## Guardrails`` body declares for each
  field of :data:`~mureo.policy.guardrail_fields.GUARDRAIL_FIELDS`, as the
  policy gate itself would read it (the parsed value, the raw text, and
  whether the text was usable or is being silently ignored);
- :func:`parse_changes` — a request body turned into one normalised bullet
  value per key (``None`` = remove the bullet), or a refusal with a fixed,
  secret-free code. A blank is a removal, never a ``0``;
- :func:`content_with_bullets` — a section body with exactly those bullets
  replaced, added or removed and every other line handed back as it was.

The I/O around them (which STRATEGY.md, the lock, the backup, the routes)
is :mod:`mureo.web.strategy_guardrails`.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any

from mureo.analysis.exclusion_impact.models import METRICS
from mureo.policy.guardrail_fields import (
    GUARDRAIL_FIELDS,
    GuardrailField,
    guardrail_field,
)
from mureo.policy.guardrails import (
    _TRUE_WORDS,
    GUARDRAILS_BULLET_RE,
    parse_guardrails,
)
from mureo.web.strategy_currency import CURRENCY_OPTIONS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "StrategyGuardrailsError",
    "content_with_bullets",
    "describe_fields",
    "parse_changes",
]

#: The spellings of "off" the editor accepts and recognises. The gate reads
#: anything outside :data:`_TRUE_WORDS` as off, so these are not needed to
#: ENFORCE — they let the card tell a deliberate ``off`` from a typo.
_FALSE_WORDS = frozenset({"false", "no", "off", "0"})

#: A blocked tool name: the characters MCP tool names are built from. Also
#: what keeps a newline (and with it a forged heading) out of the bullet.
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.:/-]+$")

_CURRENCY_CODES = frozenset(str(option["code"]) for option in CURRENCY_OPTIONS)

#: The numeric strings the editor accepts: ASCII digits only, with commas
#: allowed solely as three-digit thousands groups. ``1,5`` (a decimal comma
#: or a typo?), ``1_0`` and full-width digits are refused rather than
#: guessed at, so the bullet written is the number the operator meant.
_NUMBER_PATTERNS = tuple(
    re.compile(pattern, re.ASCII)
    for pattern in (
        r"-?\d{1,3}(,\d{3})+(\.\d+)?",
        r"-?\d+(\.\d+)?",
        r"-?\d+(\.\d+)?[eE][-+]?\d+",
    )
)

#: The key a brand-new bullet is inserted FIRST for, not after the last
#: bullet — the currency card's rule, because the caps below are in it.
_LEADING_KEY = "currency"


class StrategyGuardrailsError(Exception):
    """A Guardrails read or write was refused or failed.

    ``code`` is a fixed word the handler maps to a status; ``field`` names
    the offending key when there is one, so the card can say which row was
    refused. Neither ever carries the underlying exception's message.
    """

    def __init__(self, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _raw_values(content: str) -> dict[str, str]:
    """Raw bullet values by lower-cased key, the LAST occurrence winning —
    exactly the rule :func:`~mureo.policy.strategy_gate.parse_guardrails`
    applies, so the card shows the value the gate enforces."""
    found: dict[str, str] = {}
    for line in content.split("\n"):
        match = GUARDRAILS_BULLET_RE.match(line)
        if match is not None:
            found[match.group(1).lower()] = match.group(2).strip()
    return found


def _split_list(raw: str) -> list[str]:
    items: list[str] = []
    for part in raw.split(","):
        item = part.strip()
        if item and item not in items:
            items.append(item)
    return items


def _non_finite(value: Any) -> bool:
    return isinstance(value, float) and not math.isfinite(value)


def _parsed_value(item: GuardrailField, raw: str, parsed: Any) -> Any:
    """The gate's reading of ``raw``, in a JSON-friendly shape.

    A non-finite number is ``None``: the gate cannot enforce it, and the
    JSON encoder would emit a bare ``NaN`` no browser parses.
    """
    if _non_finite(parsed):
        return None
    if item.kind == "string_set":
        # The gate holds a frozenset; the written order is the useful one.
        return _split_list(raw)
    if item.kind == "metric_set":
        return list(parsed)
    return parsed


def _recognised(item: GuardrailField, raw: str, value: Any) -> bool:
    """Whether the gate can USE ``raw``, as opposed to dropping it."""
    if item.kind == "bool":
        return raw.lower() in _TRUE_WORDS | _FALSE_WORDS
    if item.kind == "string_set":
        return bool(value)
    if item.kind == "metric_set":
        return bool(value) and all(metric in METRICS for metric in value)
    return value is not None and not _non_finite(value)


def describe_fields(
    content: str, labels: Callable[[GuardrailField], tuple[str, str]]
) -> list[dict[str, Any]]:
    """One row per catalog field: its description and what ``content`` says.

    ``value`` is ``None`` for a field the section does not declare (no
    limit); ``raw`` is the text as written; ``recognised`` is ``False`` when
    a line is there but the gate cannot use it and ignores it.
    """
    raws = _raw_values(content)
    parsed = parse_guardrails(content)
    rows: list[dict[str, Any]] = []
    for item in GUARDRAIL_FIELDS:
        raw = raws.get(item.key)
        value = (
            None if raw is None else _parsed_value(item, raw, getattr(parsed, item.key))
        )
        label, desc = labels(item)
        rows.append(
            {
                "key": item.key,
                "kind": item.kind,
                "unit": item.unit,
                "min": item.minimum,
                "max": item.maximum,
                "label": label,
                "desc": desc,
                "value": value,
                "raw": raw,
                "recognised": True if raw is None else _recognised(item, raw, value),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Validating
# ---------------------------------------------------------------------------


def _numeric_text(item: GuardrailField, value: str) -> str:
    """``value`` without its thousands commas, if it is a number we accept."""
    text = value.strip()
    if not any(pattern.fullmatch(text) for pattern in _NUMBER_PATTERNS):
        raise StrategyGuardrailsError("invalid_value", item.key)
    return text.replace(",", "")


def _number(item: GuardrailField, value: Any) -> float:
    """A finite number from a JSON number or a numeric string."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise StrategyGuardrailsError("invalid_value", item.key)
    try:
        # An int past float range (``10**400``) raises OverflowError here.
        number = float(_numeric_text(item, value) if isinstance(value, str) else value)
    except (OverflowError, ValueError):
        raise StrategyGuardrailsError("invalid_value", item.key) from None
    if not math.isfinite(number):
        raise StrategyGuardrailsError("invalid_value", item.key)
    return number


def _in_range(item: GuardrailField, number: float) -> None:
    too_low = item.minimum is not None and number < item.minimum
    too_high = item.maximum is not None and number > item.maximum
    if too_low or too_high:
        raise StrategyGuardrailsError("out_of_range", item.key)


def _normalise_amount(item: GuardrailField, value: Any) -> str:
    number = _number(item, value)
    _in_range(item, number)
    return str(int(number)) if number.is_integer() else repr(number)


def _normalise_days(item: GuardrailField, value: Any) -> str:
    number = _number(item, value)
    if not number.is_integer():
        # The gate drops a fractional day count rather than truncating it.
        raise StrategyGuardrailsError("invalid_value", item.key)
    _in_range(item, number)
    return str(int(number))


def _normalise_bool(item: GuardrailField, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return "true"
        if word in _FALSE_WORDS:
            return "false"
    raise StrategyGuardrailsError("invalid_value", item.key)


def _text(item: GuardrailField, value: Any) -> str:
    if not isinstance(value, str):
        raise StrategyGuardrailsError("invalid_value", item.key)
    return value


def _normalise_currency(item: GuardrailField, value: Any) -> str:
    code = _text(item, value).strip().upper()
    if code not in _CURRENCY_CODES:
        raise StrategyGuardrailsError("invalid_value", item.key)
    return code


def _normalise_tools(item: GuardrailField, value: Any) -> str | None:
    names = _split_list(_text(item, value))
    if not all(_TOOL_NAME_RE.match(name) for name in names):
        raise StrategyGuardrailsError("invalid_value", item.key)
    return ", ".join(names) or None


def _normalise_metrics(item: GuardrailField, value: Any) -> str | None:
    metrics = _split_list(_text(item, value).lower())
    if not all(metric in METRICS for metric in metrics):
        raise StrategyGuardrailsError("invalid_value", item.key)
    return ", ".join(metrics) or None


_NORMALISERS: dict[str, Callable[[GuardrailField, Any], str | None]] = {
    "money": _normalise_amount,
    "percent": _normalise_amount,
    "integer_days": _normalise_days,
    "bool": _normalise_bool,
    "currency": _normalise_currency,
    "string_set": _normalise_tools,
    "metric_set": _normalise_metrics,
}


def _field(key: Any) -> GuardrailField:
    if not isinstance(key, str):
        raise StrategyGuardrailsError("invalid_payload")
    item = guardrail_field(key)
    if item is None:
        raise StrategyGuardrailsError("unknown_field", key)
    return item


def _normalise(item: GuardrailField, value: Any) -> str | None:
    """The bullet text for ``value``, or ``None`` to remove the bullet.

    ``None`` and a blank string both mean "not declared": they remove the
    bullet and are never written as ``0``.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _NORMALISERS[item.kind](item, value)


def parse_changes(payload: Mapping[str, Any]) -> dict[str, str | None]:
    """``{set: {key: value}, clear: [key]}`` → ``{key: bullet text | None}``.

    Every key is checked against the catalog and every value against its
    kind and range BEFORE anything is written, so a refused request leaves
    the document untouched.
    """
    sets = payload.get("set")
    clears = payload.get("clear")
    sets = {} if sets is None else sets
    clears = [] if clears is None else clears
    if not isinstance(sets, dict) or not isinstance(clears, list):
        raise StrategyGuardrailsError("invalid_payload")
    changes: dict[str, str | None] = {}
    for key in clears:
        changes[_field(key).key] = None
    for key, value in sets.items():
        item = _field(key)
        if item.key in changes:
            raise StrategyGuardrailsError("conflicting_fields", item.key)
        changes[item.key] = _normalise(item, value)
    return changes


# ---------------------------------------------------------------------------
# The line surgery
# ---------------------------------------------------------------------------


def _hits(lines: list[str], key: str) -> list[int]:
    """Indices of ``key``'s bullets, matched case-insensitively like the gate."""
    hits: list[int] = []
    for index, line in enumerate(lines):
        match = GUARDRAILS_BULLET_RE.match(line)
        if match is not None and match.group(1).lower() == key:
            hits.append(index)
    return hits


def _insert_at(lines: list[str], key: str) -> int:
    """Where a new bullet goes: first for the currency, else after the last
    bullet (so the rules stay together above any prose), else at the end."""
    if key == _LEADING_KEY:
        return 0
    bullets = [i for i, line in enumerate(lines) if GUARDRAILS_BULLET_RE.match(line)]
    return bullets[-1] + 1 if bullets else len(lines)


def _with_bullet(content: str, key: str, value: str | None) -> str:
    # ``\n`` only, as the gate reads it: a ``\x85`` or ``\u2028``
    # inside a prose line must come back unchanged.
    lines = content.split("\n")
    hits = _hits(lines, key)
    if value is None:
        if not hits:
            return content
        dropped = set(hits)
        return "\n".join(line for i, line in enumerate(lines) if i not in dropped)
    if not hits:
        if not content:
            return f"- {key}: {value}"
        at = _insert_at(lines, key)
        return "\n".join([*lines[:at], f"- {key}: {value}", *lines[at:]])
    first, extra = hits[0], set(hits[1:])
    match = GUARDRAILS_BULLET_RE.match(lines[first])
    if not extra and match is not None and match.group(2) == value:
        # Already says exactly this: keep the operator's own spelling.
        return content
    return "\n".join(
        f"- {key}: {value}" if i == first else line
        for i, line in enumerate(lines)
        if i not in extra
    )


def content_with_bullets(content: str, changes: Mapping[str, str | None]) -> str:
    """``content`` with each changed bullet replaced, added or removed.

    Pure and line-surgical: an existing bullet is rewritten where it stands,
    a duplicate collapses to that one line (the gate reads the LAST one, so a
    stale twin would shadow the new value), and every other line comes back
    as it was. A rewritten bullet is the bare value: a trailing comment on
    it (``5000 # approved``, which the gate cannot read) is not kept.
    Returns ``content`` itself when nothing changes.
    """
    result = content
    for key, value in changes.items():
        result = _with_bullet(result, key, value)
    return result
