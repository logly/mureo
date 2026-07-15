"""Canonical vocabulary and normalization for structured report flags.

A daily / weekly / goal report's ``flags`` list drives the coloured chips on
the read-only Reports dashboard. Historically each flag was a free-form
snake_case string with its detail baked in
(``adspot_4311492_invalid_traffic_spike_115740yen_0cv_ctr4.66pct``), which the
frontend could only render verbatim — cramming per-adspot detail into what is
meant to be a coarse, at-a-glance tag, and never localizing it.

A STRUCTURED flag fixes both problems::

    {"code": "invalid_traffic_suspected",
     "severity": "action",
     "params": {"adspot": "4311492", "spend": 115740, "ctr": 0.0466}}

* ``code`` is drawn from the fixed :data:`FLAG_SEVERITY` vocabulary, so the
  chip renders a coarse, localizable label (``MUREO.t`` on the frontend)
  instead of a de-slugged sentence.
* ``severity`` is one of the four visual buckets in :data:`SEVERITIES`
  (action / watch / info / positive → danger / warn / neutral / success). It
  defaults from the code, so most authors omit it.
* ``params`` carries the detail (adspot ids, yen, ctr) the dashboard shows on
  drill-down and the narrative — never on the chip face.

The ``custom`` code is an explicit escape hatch for a novel finding that does
not fit the vocabulary: it carries an author-written ``label`` (a string, or a
``{locale: text}`` map) and a required ``severity``.

Backward compatibility is a hard requirement: a bare STRING flag is passed
through untouched (the frontend still humanizes it), so existing STATE.json
documents and skills keep working. Only object flags are validated.
"""

from __future__ import annotations

from typing import Any

#: The severity axis — exactly the four visual buckets the dashboard colours:
#: ``action`` (danger / red), ``watch`` (warn / amber), ``info`` (neutral /
#: grey), ``positive`` (success / green). Kept separate from the alarm levels
#: so a positive ("goals met") or informational ("baseline not yet
#: established") flag is never mistaken for something needing action.
SEVERITIES: tuple[str, ...] = ("action", "watch", "info", "positive")

#: Canonical flag code → default severity. The keys ARE the allowed vocabulary
#: for a non-``custom`` structured flag; the value is the severity stamped when
#: the author omits one. ``custom`` is deliberately absent — it has no default
#: and must supply its own label + severity.
FLAG_SEVERITY: dict[str, str] = {
    # Goal / target status
    "cpa_over_target": "watch",
    "cpa_under_target": "positive",
    "cv_below_target": "watch",
    "cv_above_target": "positive",
    "goals_met": "positive",
    # Spend / efficiency anomalies
    "spend_spike": "watch",
    "cpa_spike": "watch",
    "invalid_traffic_suspected": "action",
    "zero_cv_adspots": "watch",
    "budget_overspend": "action",
    "budget_drift": "watch",
    # Measurement / data integrity
    "tracking_suspect": "action",
    "zero_conversions": "action",
    # Setup / operational context
    "supply_tools_unconfigured": "info",
    "anomaly_baseline_insufficient": "info",
    "pending_observations": "info",
    "search_console_no_property": "info",
    "ga4_not_configured": "info",
}

#: The escape-hatch code for a finding outside the vocabulary. It requires an
#: author-written ``label`` and an explicit ``severity``.
CUSTOM_CODE = "custom"


def normalize_flags(flags: Any) -> list[Any] | None:
    """Validate and normalize a report's ``flags`` list.

    Returns a NEW list (never mutates the input) where:

    * ``None`` → ``None`` (no flags section).
    * each bare string is passed through unchanged (legacy flag).
    * each object flag is validated against the vocabulary and returned with
      its ``severity`` filled from :data:`FLAG_SEVERITY` when omitted.

    Raises:
        ValueError: if ``flags`` is not a list, or any element is neither a
            string nor a valid flag object (unknown code, bad severity,
            non-object ``params``, or a ``custom`` flag missing its label /
            severity). The MCP handler surfaces this as a clean tool error.
    """
    if flags is None:
        return None
    if not isinstance(flags, list):
        raise ValueError("flags must be a list")
    return [_normalize_flag(flag) for flag in flags]


def _normalize_flag(flag: Any) -> Any:
    """Normalize one flag element (see :func:`normalize_flags`)."""
    # Legacy bare-string flag: preserved verbatim for backward compatibility.
    if isinstance(flag, str):
        return flag
    if not isinstance(flag, dict):
        raise ValueError("each flag must be a string or an object")

    code = flag.get("code")
    if not isinstance(code, str) or not code:
        raise ValueError("flag object must carry a non-empty string 'code'")

    severity = flag.get("severity")
    if code == CUSTOM_CODE:
        if not _is_valid_label(flag.get("label")):
            raise ValueError(
                "custom flag requires a 'label' (a non-empty string or a "
                "{locale: text} map)"
            )
        if severity is None:
            raise ValueError("custom flag requires an explicit 'severity'")
    else:
        if code not in FLAG_SEVERITY:
            raise ValueError(
                f"unknown flag code {code!r}; use a canonical code "
                f"({', '.join(sorted(FLAG_SEVERITY))}) or {CUSTOM_CODE!r}"
            )
        if severity is None:
            severity = FLAG_SEVERITY[code]

    if severity not in SEVERITIES:
        raise ValueError(
            f"flag 'severity' must be one of {SEVERITIES}; got {severity!r}"
        )

    params = flag.get("params")
    if params is not None and not isinstance(params, dict):
        raise ValueError("flag 'params' must be an object")

    # Shallow-copy so author extras (e.g. a pre-rendered note) survive, then
    # stamp the validated / defaulted fields. A new dict — the caller's flag
    # is never mutated.
    normalized = dict(flag)
    normalized["code"] = code
    normalized["severity"] = severity
    return normalized


def _is_valid_label(label: Any) -> bool:
    """A ``custom`` flag's label: a non-empty string or a ``{locale: text}``
    map of non-empty strings.

    Locale keys are intentionally unconstrained at this layer (any non-empty
    string is accepted, not a BCP-47 shape check): this is trusted-writer
    content, and the frontend picks the key matching the active configure-UI
    locale, falling back to a sensible default for anything it does not
    recognize.
    """
    if isinstance(label, str):
        return bool(label.strip())
    if isinstance(label, dict):
        return bool(label) and all(
            isinstance(k, str) and isinstance(v, str) and bool(v.strip())
            for k, v in label.items()
        )
    return False
