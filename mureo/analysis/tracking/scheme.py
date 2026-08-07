"""URL → tracking-scheme reduction.

Three fixed rules carry the whole false-positive story. All three are
deliberate and documented — mureo never *infers* an account's naming
convention:

1. **Which parameters are read at all.** Only ``utm_*`` by default. A
   parameter mureo does not recognise as tracking (a product id, a
   variant flag) is never compared on, so an account that puts content
   parameters in its final URLs is not judged on them. An account whose
   tracking does not use ``utm_`` names declares those names in
   STRATEGY.md — see :mod:`mureo.analysis.tracking.convention`.

2. **Which parameters identify a campaign.** Only
   :data:`DEFAULT_IDENTIFYING` — ``utm_source`` / ``utm_medium`` /
   ``utm_campaign`` — take part in the scheme-consistency comparison.
   ``utm_content`` and ``utm_term`` exist precisely so that one campaign
   can tell its creatives and keywords apart on a single landing page;
   comparing on them would flag ordinary creative differentiation
   (``utm_content=hero`` vs ``utm_content=video``) as an inconsistency,
   which is the single most likely way an operator ends up muting this
   check. They are still read — the presence checks and any declared
   value patterns see them — but they never make two ads "disagree".

3. **What counts as the same value.** A maximal run of digits is
   collapsed to ``#`` when comparing values, so ``segb01`` and
   ``segb02`` are the same *scheme* while ``sega01`` is a different
   one. This is the single rule that lets the check tell "article 2
   instead of article 1" (legitimate) from "segment A instead of
   segment B" (the incident). It errs toward treating values as the
   same, i.e. toward FEWER findings.

Schemes are compared as a **whole identifying signature**, never one
parameter at a time. Per-parameter comparison reports "these ads
borrowed campaign Y's ``utm_source``" for a value like ``google`` that
Y merely happens to share, which is noise; a full signature match means
the ads carry another campaign's entire tracking identity, which is the
defect.

The destination (scheme + host + path, query and fragment dropped) is
kept separately: two ads pointing at the same landing page with
different schemes are comparable, ads pointing at different landing
pages are not necessarily.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: Parameter-name globs inspected when the operator declares nothing.
#: ``utm_*`` is the only cross-platform tracking namespace mureo can
#: assume; everything else is account convention and must be declared.
DEFAULT_RECOGNIZED: tuple[str, ...] = ("utm_*",)

#: Parameter-name globs whose values identify **which campaign** traffic
#: came from, and therefore the only ones the scheme-consistency checks
#: compare on. Everything else that is recognised (notably ``utm_content``
#: and ``utm_term``) is creative- or keyword-differentiating: it varies
#: within one campaign by design. Extend with ``identify:`` in
#: STRATEGY.md, or narrow with ``differentiate:``.
DEFAULT_IDENTIFYING: tuple[str, ...] = ("utm_source", "utm_medium", "utm_campaign")

#: Placeholder a maximal digit run collapses to when values are compared.
SERIAL_PLACEHOLDER = "#"

_DIGIT_RUN = re.compile(r"\d+")


def value_shape(value: str) -> str:
    """Collapse every maximal digit run in ``value`` to ``#``.

    ``"segb01"`` and ``"segb02"`` both become ``"segb#"``; ``"sega01"``
    becomes ``"sega#"`` and stays distinguishable.
    """
    return _DIGIT_RUN.sub(SERIAL_PLACEHOLDER, value)


def is_recognized(name: str, recognized: Sequence[str]) -> bool:
    """Whether parameter ``name`` matches any recognised glob.

    Matching is case-insensitive on the name because query-string keys
    are written inconsistently in practice, while *values* stay
    case-sensitive (``segB`` and ``segb`` are different segments).
    """
    lowered = name.lower()
    return any(fnmatchcase(lowered, pattern.lower()) for pattern in recognized)


def tracking_parameters(
    url: str,
    recognized: Sequence[str] = DEFAULT_RECOGNIZED,
) -> tuple[tuple[str, str], ...]:
    """Recognised tracking parameters of ``url``, sorted by name.

    A repeated parameter keeps its first value — duplicate keys are
    ambiguous at delivery time and mureo does not guess which one the
    platform wins with.
    """
    try:
        query = urlsplit(url).query
    except ValueError:
        return ()
    seen: dict[str, str] = {}
    for name, value in parse_qsl(query, keep_blank_values=True):
        if not is_recognized(name, recognized):
            continue
        seen.setdefault(name, value)
    return tuple(sorted(seen.items()))


def destination(url: str) -> str:
    """Scheme + host + path of ``url``, with query and fragment dropped.

    Host is lower-cased (case-insensitive per RFC 3986); the path is
    left verbatim because paths ARE case-sensitive and two differently
    cased paths may be two different pages.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def scheme_signature(
    parameters: Iterable[tuple[str, str]],
    identifying: Sequence[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Reduce parameters to the comparable shape signature.

    Two ads share a signature when they carry the same tracking
    parameter names with values of the same shape. When ``identifying``
    is given, only parameters matching it contribute — that is the
    signature the scheme-consistency checks compare, and it is what
    keeps ``utm_content``-per-creative out of the comparison.
    """
    return tuple(
        sorted(
            (name, value_shape(value))
            for name, value in parameters
            if identifying is None or is_recognized(name, identifying)
        )
    )


def format_signature(signature: Sequence[tuple[str, str]]) -> str:
    """Render a signature as a query-string-like string for messages."""
    return "&".join(f"{name}={shape}" for name, shape in signature)


__all__ = [
    "DEFAULT_IDENTIFYING",
    "DEFAULT_RECOGNIZED",
    "SERIAL_PLACEHOLDER",
    "destination",
    "format_signature",
    "is_recognized",
    "scheme_signature",
    "tracking_parameters",
    "value_shape",
]
