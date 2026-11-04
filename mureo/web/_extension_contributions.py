"""Value types a web extension returns to the configure UI.

:class:`StaticAsset`, :class:`ViewContribution` and :class:`DashboardCard`
are the frozen records a :class:`mureo.web.extensions.WebExtension` hands
back from ``view()`` and ``dashboard_cards()`` (static assets ride inside
both), kept here with the patterns that validate them at construction.
:mod:`mureo.web.extensions` re-exports every public name, so plugins keep
importing from ``mureo.web.extensions``; the split keeps that module under
the file length limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: ``StaticAsset.filename`` — lowercase, alphanumeric + ``._-``, no
#: directory separator, must start with a letter, must contain at
#: least one dot. Internal dots are permitted (``app.min.js``,
#: ``vendor.bundle.js``, ``i18n.en-us.json``) — modern JS toolchain
#: outputs use them routinely. Leading dot, ``..``, ``/``, ``\``,
#: whitespace, and uppercase remain rejected.
FILENAME_PATTERN: Final[str] = r"[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)*\.[a-z0-9]+"

_FILENAME_RE: Final[re.Pattern[str]] = re.compile(rf"^{FILENAME_PATTERN}$")

#: Built-in dashboard groups an extension may contribute cards to via
#: ``dashboard_cards()``. Deliberately a fixed allowlist (mirroring
#: the *discipline* of ``BUILTIN_DASHBOARD_TABS``, not its values):
#: opening every group would couple extensions to the app's internal
#: layout, so new groups are added here intentionally, one review at a
#: time. Each value is the ``data-dashboard-group`` attribute
#: hardcoded in ``mureo/_data/web/app.html``. NB: before adding a
#: group that also appears in ``BUILTIN_DASHBOARD_TABS``, decide what
#: a card inside a tab hidden via ``hidden_builtin_tabs`` should do —
#: today the two sets are disjoint so a card can never be hidden.
BUILTIN_CARD_GROUPS: Final[tuple[str, ...]] = ("advanced", "reports")

#: Inline-executable patterns banned in ``html_fragment``. The
#: configure-UI CSP forbids ``unsafe-inline`` so these would not
#: execute anyway, but discovery refuses them so plugin authors get
#: an explicit failure instead of a silently inert UI.
_BANNED_HTML_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"<\s*style\b", re.IGNORECASE),
    re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE),
    re.compile(r"\bjavascript\s*:", re.IGNORECASE),
)


@dataclass(frozen=True)
class StaticAsset:
    """One static asset (JS / CSS / image / JSON) served verbatim under
    ``/static/ext/<extension-name>/<filename>``.

    ``body`` is in-memory ``bytes``; the dispatcher never reads from
    disk so filesystem traversal is impossible by construction. Plugin
    authors that want to ship a large CSS/JS file should read it with
    :mod:`importlib.resources` at import time and pass the bytes here.
    """

    filename: str
    content_type: str
    body: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or not _FILENAME_RE.match(self.filename):
            raise ValueError(
                f"StaticAsset.filename must match {_FILENAME_RE.pattern!r}; "
                f"got {self.filename!r}"
            )
        if not isinstance(self.content_type, str) or not self.content_type:
            raise ValueError("StaticAsset.content_type must be a non-empty string")
        if not isinstance(self.body, (bytes, bytearray)):
            raise TypeError("StaticAsset.body must be bytes")


@dataclass(frozen=True)
class ViewContribution:
    """Optional UI fragment + asset list shown in the configure UI.

    ``html_fragment`` is injected verbatim into the main area when the
    user selects the extension's tab. It must NOT contain
    ``<script>`` / ``<style>`` / ``on*=`` event handlers /
    ``javascript:`` URLs — the configure-UI Content-Security-Policy
    forbids ``unsafe-inline`` so those would not execute, but we
    reject them at discovery time so the plugin author sees the
    failure instead of a silently inert UI.

    ``scripts`` / ``styles`` reference :class:`StaticAsset`s shipped
    by the same extension. The renderer emits ``<script>`` /
    ``<link rel="stylesheet">`` tags pointing at
    ``/static/ext/<name>/<filename>``; the CSP's ``script-src 'self'``
    / ``style-src 'self'`` rules permit the load.
    """

    html_fragment: str
    scripts: tuple[StaticAsset, ...] = ()
    styles: tuple[StaticAsset, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.html_fragment, str):
            raise TypeError("ViewContribution.html_fragment must be str")
        for pat in _BANNED_HTML_PATTERNS:
            if pat.search(self.html_fragment):
                raise ValueError(
                    "ViewContribution.html_fragment may not contain "
                    "<script>, <style>, on*= handlers, or javascript: URLs; "
                    f"matched {pat.pattern!r}"
                )
        if not isinstance(self.scripts, tuple) or not all(
            isinstance(s, StaticAsset) for s in self.scripts
        ):
            raise TypeError("ViewContribution.scripts must be tuple[StaticAsset, ...]")
        if not isinstance(self.styles, tuple) or not all(
            isinstance(s, StaticAsset) for s in self.styles
        ):
            raise TypeError("ViewContribution.styles must be tuple[StaticAsset, ...]")


@dataclass(frozen=True)
class DashboardCard:
    """One extension-supplied card rendered INSIDE a built-in dashboard
    group (``group`` must be one of :data:`BUILTIN_CARD_GROUPS`:
    ``"advanced"`` or ``"reports"``).

    For a small companion that belongs next to an existing built-in card,
    where a whole extension tab would be disproportionate — e.g. a plugin
    that pairs a write-side setting with the built-in "External advisor
    MCP" (read-side) card under ``"advanced"``, or an operator reporting
    action (refresh every client's numbers now) beside the report cards
    under ``"reports"`` (#425).

    Same safety contract as :class:`ViewContribution`: the fragment may
    not contain inline-executable content; behaviour ships as
    :class:`StaticAsset` ``scripts`` / ``styles`` served from
    ``/static/ext/<name>/…`` alongside the extension's view assets.
    Unlike a view, cards are injected when extension discovery renders
    (not lazily on tab click), so card scripts must be idempotent and
    cheap to load.

    ``order`` places the card within its group: cards of one group sit
    in ascending ``order``, and cards with equal ``order`` keep discovery
    order (the sort is stable). Built-in cards always come first. A card
    that must sit at the bottom of its group (e.g. a destructive restore
    action after the ordinary settings) uses a large value such as 100.
    """

    group: str
    html_fragment: str
    scripts: tuple[StaticAsset, ...] = ()
    styles: tuple[StaticAsset, ...] = ()
    order: int = 0

    def __post_init__(self) -> None:
        if self.group not in BUILTIN_CARD_GROUPS:
            raise ValueError(
                f"DashboardCard.group must be one of {BUILTIN_CARD_GROUPS}; "
                f"got {self.group!r}"
            )
        if not isinstance(self.html_fragment, str):
            raise TypeError("DashboardCard.html_fragment must be str")
        for pat in _BANNED_HTML_PATTERNS:
            if pat.search(self.html_fragment):
                raise ValueError(
                    "DashboardCard.html_fragment may not contain "
                    "<script>, <style>, on*= handlers, or javascript: URLs; "
                    f"matched {pat.pattern!r}"
                )
        if not isinstance(self.scripts, tuple) or not all(
            isinstance(s, StaticAsset) for s in self.scripts
        ):
            raise TypeError("DashboardCard.scripts must be tuple[StaticAsset, ...]")
        if not isinstance(self.styles, tuple) or not all(
            isinstance(s, StaticAsset) for s in self.styles
        ):
            raise TypeError("DashboardCard.styles must be tuple[StaticAsset, ...]")
        if not isinstance(self.order, int) or isinstance(self.order, bool):
            raise TypeError("DashboardCard.order must be int")
