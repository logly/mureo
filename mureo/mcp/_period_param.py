"""The ``period`` parameter of the Google Ads MCP tools — one definition.

Three byte-identical copies of the same ``enum`` used to live in
``_tools_google_ads_analysis.py`` (twice) and ``_tools_google_ads_extensions.py``,
and none of them agreed with the whitelist
``mureo.google_ads._gaql_validator`` enforces at query-build time: they
offered ``LAST_90_DAYS``, which always failed, and hid five week constants
that always worked (#717). This module is the single definition all of them
now build on, and ``tests/test_google_ads_period_contract.py`` pins the
schemas to the validator so the lists cannot drift apart again.

Two builders, because the tools honour ``period`` in two different ways:

- :func:`period_param` — the window is handed to
  ``GoogleAdsApiClient._period_to_date_clause`` verbatim, so every constant
  the GAQL layer knows plus an explicit ``BETWEEN`` range is fair game (#716).
- :func:`comparison_period_param` — the tool also reads the equal-length
  window immediately before the requested one, so it needs a *length*.
  Calendar constants have none and are left out of the enum rather than
  accepted and silently rounded down to seven days (#716 caveat, #718).
"""

from __future__ import annotations

from typing import Any

from mureo.google_ads._gaql_validator import (
    PERIOD_BETWEEN_PATTERN,
    SUPPORTED_PERIOD_CONSTANTS,
)

# Presentation only — shortest window first, so the published enum reads in an
# order an operator can scan. Membership is NOT decided here: it comes from
# SUPPORTED_PERIOD_CONSTANTS below. A constant added to the GAQL whitelist and
# not listed here still ships; it just sorts last.
_PRESENTATION_ORDER: tuple[str, ...] = (
    "TODAY",
    "YESTERDAY",
    "THIS_WEEK_SUN_TODAY",
    "THIS_WEEK_MON_TODAY",
    "LAST_BUSINESS_WEEK",
    "LAST_WEEK_SUN_SAT",
    "LAST_WEEK_MON_SUN",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
)


def _display_rank(constant: str) -> tuple[int, str]:
    """Sort key: ranked constants in listed order, the rest alphabetically last."""
    if constant in _PRESENTATION_ORDER:
        return (_PRESENTATION_ORDER.index(constant), "")
    return (len(_PRESENTATION_ORDER), constant)


# Derived, not transcribed: whatever the GAQL layer can resolve is what the
# tools offer. A constant added to VALID_DATE_RANGE_CONSTANTS (or to
# DERIVED_DATE_RANGE_DAYS) appears here with no edit to this file, and one that
# leaves the whitelist stops being advertised the same way — which is the whole
# point of #717.
PERIOD_CONSTANTS: tuple[str, ...] = tuple(
    sorted(SUPPORTED_PERIOD_CONSTANTS, key=_display_rank)
)

# Pinned to mureo.google_ads._analysis_constants._PERIOD_DAYS by
# test_comparison_constants_match_the_comparison_resolver.
COMPARISON_PERIOD_CONSTANTS: tuple[str, ...] = (
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
)

# Appended to every period description so the capability is documented on the
# tool that has it — it was undocumented everywhere before #718.
#
# The LAST_90_DAYS sentence is not a footnote: every other constant is resolved
# by Google against the ACCOUNT's reporting time zone, while LAST_90_DAYS has no
# API constant and is resolved by mureo against the SERVER's date. When the two
# zones differ the boundary can sit one day apart, and a caller comparing a
# 90-day baseline against a 30-day window deserves to know which clock each was
# measured on.
CUSTOM_RANGE_HINT = (
    "Also accepts an explicit range in GAQL spelling — "
    "\"BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'\", both endpoints inclusive, in "
    "the account's time zone — for a window no trailing constant can reach "
    "(e.g. a single past calendar month). One asymmetry to know about: every "
    "constant except LAST_90_DAYS is resolved by Google Ads in the account's "
    "reporting time zone, whereas LAST_90_DAYS has no API constant and is "
    "expanded by mureo into the 90 days ending yesterday **on the server's "
    "date**, so its edges can differ by a day when the server and the account "
    "are in different zones. Pass an explicit range when the exact boundary "
    "matters."
)

_COMPARISON_HINT = (
    "This tool also reads the equal-length window immediately before the one "
    "you request, so only fixed-length windows are accepted — calendar "
    "constants such as THIS_MONTH are rejected rather than silently replaced."
)


def _build(description: str, constants: tuple[str, ...]) -> dict[str, Any]:
    """Return a fresh ``period`` schema fragment.

    A fresh dict per call: the fragment is embedded in 18 tool schemas, and a
    shared mutable singleton would let an edit on one tool leak into the rest.
    """
    return {
        "type": "string",
        "anyOf": [
            {"type": "string", "enum": list(constants)},
            {"type": "string", "pattern": PERIOD_BETWEEN_PATTERN},
        ],
        "description": description,
    }


def period_param(description: str) -> dict[str, Any]:
    """``period`` for a tool that reports on the window as given."""
    return _build(f"{description} {CUSTOM_RANGE_HINT}", PERIOD_CONSTANTS)


def comparison_period_param(description: str) -> dict[str, Any]:
    """``period`` for a tool that compares the window against the one before it."""
    return _build(
        f"{description} {_COMPARISON_HINT} {CUSTOM_RANGE_HINT}",
        COMPARISON_PERIOD_CONSTANTS,
    )
