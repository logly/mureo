"""A stored row note, read back into parts (#894).

The evaluation table's row ``note`` is an English string, and it is the only
place a row says which way its metric is better, whether it was compared per
day, which target it was held to and why a verdict was held back. It is
stored as it is and never rewritten; :func:`note_parts` reads it back so a
reader (the dashboard) can say the same thing in its own words.

Only the notes :mod:`mureo.analysis.outcome_eval` and
:mod:`mureo.analysis.expected_eval` build are read, from the very templates
they build them with. Anything else — a hand-written note, an older wording,
one this version does not know — is ``None``, and the reader shows the
stored string instead. Pure, I/O-free; nothing imports this module back.
"""

from __future__ import annotations

import re
from typing import Any, Final

from mureo.analysis.expected_eval import (
    NOTE_EXPECTED,
    NOTE_EXPECTED_UNSCORED,
    NOTE_TARGET,
    NOTE_TARGET_NOT_REACHED,
    NOTE_TARGET_REACHED,
    NOTE_WINDOW_TOTAL,
)
from mureo.analysis.outcome_eval import (
    NOTE_DIRECTION,
    NOTE_DIRECTION_WORDS,
    NOTE_HELD_BACK,
    NOTE_NEUTRAL,
    NOTE_NOISE_BAND,
    NOTE_PER_DAY,
    NOTE_RAW_TOTALS,
    NOTE_ZERO_BASELINE,
    OUTCOME_REASONS,
)
from mureo.context.expected import EXPECTED_DIRECTIONS

#: ``kind`` values: which of the builders' notes the row's note is.
KIND_BAND: Final = "band"
KIND_DIRECTION: Final = "direction"
KIND_NEUTRAL: Final = "neutral"
KIND_ZERO_BASELINE: Final = "zero_baseline"
KIND_EXPECTED: Final = "expected"

#: A number as ``format(value, "g")`` (or ``"+g"``) writes one.
_NUMBER: Final = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"
_DAYS: Final = r"\d+"
_FIELD: Final = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def _pattern(template: str, **fields: str) -> str:
    """``template`` as a regex: its text literal, each field a named group."""
    parts: list[str] = []
    end = 0
    for field in _FIELD.finditer(template):
        parts.append(re.escape(template[end : field.start()]))
        parts.append(f"(?P<{field.group(1)}>{fields[field.group(1)]})")
        end = field.end()
    parts.append(re.escape(template[end:]))
    return "".join(parts)


def _choice(values: tuple[str, ...]) -> str:
    return "|".join(re.escape(value) for value in values)


_PER_DAY: Final = _pattern(NOTE_PER_DAY, before_days=_DAYS, after_days=_DAYS)
_SUFFIX: Final = (
    f"(?:(?P<raw_totals>{re.escape(NOTE_RAW_TOTALS)})|(?P<per_day>{_PER_DAY}))?"
)
_BAND: Final = _pattern(NOTE_NOISE_BAND, noise_pct=_NUMBER)
_SIDED: Final = _pattern(
    NOTE_DIRECTION, direction=_choice(NOTE_DIRECTION_WORDS), delta_pct=_NUMBER
)
_ROW: Final = re.compile(
    f"(?:(?P<band>{_BAND})|(?P<sided>{_SIDED})"
    f"|(?P<neutral>{re.escape(NOTE_NEUTRAL)})"
    f"|(?P<zero>{re.escape(NOTE_ZERO_BASELINE)})){_SUFFIX}"
)
_HELD_BACK: Final = re.compile(
    _pattern(NOTE_HELD_BACK, reason=_choice(OUTCOME_REASONS), note=".+")
)
_TARGET: Final = (
    "(?:"
    + _pattern(
        NOTE_TARGET,
        target=_NUMBER,
        state=_choice((NOTE_TARGET_NOT_REACHED, NOTE_TARGET_REACHED)),
    )
    + f"(?:{_pattern(NOTE_WINDOW_TOTAL, total=_NUMBER)})?)?"
)
_DIRECTIONS: Final = _choice(EXPECTED_DIRECTIONS)
_EXPECTED: Final = re.compile(
    _pattern(NOTE_EXPECTED, direction=_DIRECTIONS, delta_pct=_NUMBER, noise_pct=_NUMBER)
    + f"(?:{_PER_DAY})?"
    + _TARGET
)
_EXPECTED_UNSCORED: Final = re.compile(
    _pattern(NOTE_EXPECTED_UNSCORED, direction=_DIRECTIONS, note=".+?") + _TARGET
)


def _empty() -> dict[str, Any]:
    return {
        "kind": None,
        "direction": None,
        "noise_pct": None,
        "per_day": None,
        "raw_totals": False,
        "held_back": None,
        "target": None,
        "zero_baseline": False,
    }


def _per_day(match: re.Match[str]) -> dict[str, int] | None:
    if match.group("before_days") is None:
        return None
    return {
        "before_days": int(match.group("before_days")),
        "after_days": int(match.group("after_days")),
    }


def _row_kind(match: re.Match[str]) -> dict[str, Any]:
    if match.group("band") is not None:
        return {"kind": KIND_BAND, "noise_pct": float(match.group("noise_pct"))}
    if match.group("sided") is not None:
        return {"kind": KIND_DIRECTION, "direction": match.group("direction")}
    if match.group("neutral") is not None:
        return {"kind": KIND_NEUTRAL}
    return {"kind": KIND_ZERO_BASELINE, "zero_baseline": True}


def _row_parts(note: str) -> dict[str, Any] | None:
    """A note :mod:`mureo.analysis.outcome_eval` builds, lead included."""
    held_back = None
    lead = _HELD_BACK.fullmatch(note)
    if lead is not None:
        held_back, note = lead.group("reason"), lead.group("note")
    match = _ROW.fullmatch(note)
    if match is None:
        return None
    return {
        **_empty(),
        **_row_kind(match),
        "per_day": _per_day(match),
        "raw_totals": match.group("raw_totals") is not None,
        "held_back": held_back,
    }


def _target(match: re.Match[str]) -> dict[str, Any] | None:
    if match.group("target") is None:
        return None
    total = match.group("total")
    return {
        "value": float(match.group("target")),
        "reached": match.group("state") == NOTE_TARGET_REACHED,
        "window_total": None if total is None else float(total),
    }


def _expected_parts(note: str) -> dict[str, Any] | None:
    """A declared primary's note, as :mod:`mureo.analysis.expected_eval`
    builds it: scored (change and band), or around a zero baseline."""
    scored = _EXPECTED.fullmatch(note)
    if scored is not None:
        return {
            **_empty(),
            "kind": KIND_EXPECTED,
            "direction": scored.group("direction"),
            "noise_pct": float(scored.group("noise_pct")),
            "per_day": _per_day(scored),
            "target": _target(scored),
        }
    unscored = _EXPECTED_UNSCORED.fullmatch(note)
    inner = None if unscored is None else _row_parts(unscored.group("note"))
    if unscored is None or inner is None or inner["kind"] != KIND_ZERO_BASELINE:
        return None
    return {
        **inner,
        "kind": KIND_EXPECTED,
        "direction": unscored.group("direction"),
        "held_back": None,
        "target": _target(unscored),
    }


def note_parts(note: str) -> dict[str, Any] | None:
    """The parts of a row note the evaluators build, or ``None``.

    Returns every key, a part that does not apply ``None`` / ``False``:

    - ``kind``: ``band`` (inside the noise band), ``direction`` (a
      directional metric that moved), ``neutral`` (a volume metric),
      ``zero_baseline`` or ``expected`` (a declared primary);
    - ``direction``: ``lower_is_better`` / ``higher_is_better`` for
      ``direction``, the declared ``up`` / ``down`` / ``hold`` for
      ``expected``;
    - ``noise_pct``: the band a ``band`` or a scored ``expected`` note names;
    - ``per_day``: ``{"before_days", "after_days"}`` when compared per day;
    - ``raw_totals``: compared as totals because the periods are unknown;
    - ``held_back``: the reason code leading a held-back primary's note;
    - ``target``: ``{"value", "reached", "window_total"}`` for a declared
      target, ``window_total`` only on a per-day row;
    - ``zero_baseline``: the note says the baseline was zero, so there is
      no change rate (a ``zero_baseline`` row, or an ``expected`` one).

    A declared primary with a zero baseline whose target decided is
    ``expected`` with no ``noise_pct`` and ``zero_baseline`` set: the
    target is what was judged.
    """
    if not isinstance(note, str) or not note:
        return None
    return _expected_parts(note) or _row_parts(note)


__all__ = [
    "KIND_BAND",
    "KIND_DIRECTION",
    "KIND_EXPECTED",
    "KIND_NEUTRAL",
    "KIND_ZERO_BASELINE",
    "note_parts",
]
