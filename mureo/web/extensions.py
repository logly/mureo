"""Entry-point–based extension layer for the configure-UI HTTP server.

A third-party distribution can register a zero-arg callable returning
a class (or instance) satisfying :class:`WebExtension` under the
``mureo.web_extensions`` entry-point group; discovery iterates that
group exactly once, isolates faults per entry, and exposes survivors
as frozen :class:`WebExtensionEntry` records consumed by
``mureo.web.handlers``.

Design mirrors :mod:`mureo.core.providers.registry`:

* per-plugin try/except around the whole load → introspect → validate
  pipeline so a broken plugin cannot break discovery for the rest
* :class:`WebExtensionWarning` so strict-mode deployments can opt into
  ``warnings.filterwarnings("error", category=WebExtensionWarning)``
* first-wins on duplicate names (deterministic; a malicious plugin
  installed after a legitimate one cannot silently take its slot)
* result cached for the process lifetime — entry points are populated
  by ``pip install`` and do not change at runtime

Security posture:

* ``RouteContribution.subpath`` is regex-validated at construction so
  ``..`` / double-slash / ``?`` / ``#`` cannot smuggle the dispatcher
  outside ``/api/ext/<name>/``.
* ``StaticAsset.filename`` is regex-validated for the same reason.
  Bodies are kept in memory; the dispatcher never reads from disk so
  filesystem traversal is impossible by construction.
* ``ViewContribution.html_fragment`` is rejected if it contains
  ``<script>``, ``<style>``, ``on*=`` event handlers, or
  ``javascript:`` URLs. The configure-UI CSP only allows ``script-src
  'self'`` / ``style-src 'self'``; extensions ship assets via
  ``/static/ext/<name>/<file>`` so the CSP never has to relax. The
  regex check is an author-feedback signal — the **CSP is the actual
  enforcement** — so HTML-entity-encoded bypasses
  (``&#x6A;avascript:``) that skip the regex are blocked at runtime.

Warning-flood note (mirrors
:class:`mureo.core.providers.registry.RegistryWarning`):
:class:`WebExtensionWarning` messages embed attacker-controllable
strings (entry-point name, distribution name, exception ``repr``).
Python's default warning deduplication does not coalesce them — every
unique message is a fresh warning — so a hostile environment that
installs many malformed plugins can flood operator logs. Strict-mode
deployments should opt into
``warnings.filterwarnings("error", category=WebExtensionWarning)``.
"""

from __future__ import annotations

import dataclasses
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Literal,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable
    from http.server import BaseHTTPRequestHandler
    from pathlib import Path

#: Entry-point group iterated by :func:`discover_web_extensions`.
WEB_EXTENSIONS_ENTRY_POINT_GROUP: Final[str] = "mureo.web_extensions"

#: ``WebExtension.name`` and ``WebExtensionEntry.name`` — kebab-case,
#: 1–33 chars, must start with a lowercase letter. Used as the
#: URL-path segment (``/api/ext/<name>/...``) and as the dict key for
#: duplicate-name detection. Exposed as a bare string so the dispatch
#: layer in :mod:`mureo.web.handlers` can build its URL-matching
#: regex from the same source of truth.
NAME_PATTERN: Final[str] = r"[a-z][a-z0-9-]{0,32}"

#: ``StaticAsset.filename`` — lowercase, alphanumeric + ``._-``, no
#: directory separator, must start with a letter, must contain at
#: least one dot. Internal dots are permitted (``app.min.js``,
#: ``vendor.bundle.js``, ``i18n.en-us.json``) — modern JS toolchain
#: outputs use them routinely. Leading dot, ``..``, ``/``, ``\``,
#: whitespace, and uppercase remain rejected.
FILENAME_PATTERN: Final[str] = r"[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)*\.[a-z0-9]+"

#: ``RouteContribution.subpath`` — leading slash, then one or more
#: segments of ``[A-Za-z0-9_-]``, separated by single slashes. No
#: query string, no fragment, no traversal, no double-slash, no
#: trailing slash.
SUBPATH_PATTERN: Final[str] = r"(?:/[A-Za-z0-9_-]+)+"

_NAME_RE: Final[re.Pattern[str]] = re.compile(rf"^{NAME_PATTERN}$")
_FILENAME_RE: Final[re.Pattern[str]] = re.compile(rf"^{FILENAME_PATTERN}$")
_SUBPATH_RE: Final[re.Pattern[str]] = re.compile(rf"^{SUBPATH_PATTERN}$")

#: Stable identifiers of the built-in dashboard tabs an extension may
#: hide via ``hidden_builtin_tabs`` (#189). These are the
#: ``data-dashboard-nav`` / ``data-dashboard-group`` attribute values
#: hardcoded in ``mureo/_data/web/app.html`` — extending this tuple
#: requires a matching markup change there.
BUILTIN_DASHBOARD_TABS: Final[tuple[str, ...]] = ("setup", "demo", "byod", "danger")

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
BUILTIN_CARD_GROUPS: Final[tuple[str, ...]] = ("advanced",)

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


class WebExtensionWarning(UserWarning):
    """Emitted when a discovered web extension is skipped or shadowed.

    Mirrors :class:`mureo.core.providers.registry.RegistryWarning`
    so strict-mode deployments can opt into
    ``warnings.filterwarnings("error", category=WebExtensionWarning)``.
    """


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
class RouteContribution:
    """One HTTP route registered by a :class:`WebExtension`.

    Mounted under ``/api/ext/<extension-name>``: a route with
    ``subpath="/ping"`` becomes ``GET /api/ext/<name>/ping``.

    ``handler`` signature:
        ``def handler(request: BaseHTTPRequestHandler,
                      payload: dict[str, str | Any]) -> None``

    For ``GET`` the payload is the flattened query string
    (``urllib.parse.parse_qs`` with ``first-value-wins``); for ``POST``
    it is the parsed JSON object body. Multi-value query strings or
    raw bodies are reachable via ``request.path`` / ``request.rfile``;
    no rich Request abstraction is provided in v0 (YAGNI).

    The dispatcher runs the existing Host-header + CSRF gate before
    calling ``handler`` (POST only — GET has no CSRF requirement).
    Errors raised by ``handler`` are caught by the dispatcher and
    surfaced as a 500 JSON envelope; the dispatcher never lets one
    extension crash the configure server.
    """

    method: Literal["GET", "POST"]
    subpath: str
    handler: Callable[[BaseHTTPRequestHandler, dict[str, Any]], None]

    def __post_init__(self) -> None:
        if self.method not in ("GET", "POST"):
            raise ValueError(
                f"RouteContribution.method must be 'GET' or 'POST'; got {self.method!r}"
            )
        if not isinstance(self.subpath, str) or not _SUBPATH_RE.match(self.subpath):
            raise ValueError(
                f"RouteContribution.subpath must match {_SUBPATH_RE.pattern!r}; "
                f"got {self.subpath!r}"
            )
        if not callable(self.handler):
            raise TypeError("RouteContribution.handler must be callable")


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
    group (``group`` must be one of :data:`BUILTIN_CARD_GROUPS`,
    currently only ``"advanced"``).

    For small, operator-wide companion settings that belong next to an
    existing built-in card — e.g. a plugin that pairs a write-side
    setting with the built-in "External advisor MCP" (read-side) card —
    where a whole extension tab would be disproportionate.

    Same safety contract as :class:`ViewContribution`: the fragment may
    not contain inline-executable content; behaviour ships as
    :class:`StaticAsset` ``scripts`` / ``styles`` served from
    ``/static/ext/<name>/…`` alongside the extension's view assets.
    Unlike a view, cards are injected when extension discovery renders
    (not lazily on tab click), so card scripts must be idempotent and
    cheap to load.
    """

    group: str
    html_fragment: str
    scripts: tuple[StaticAsset, ...] = ()
    styles: tuple[StaticAsset, ...] = ()

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


@dataclass(frozen=True)
class ServeContext:
    """Context handed to :py:meth:`WebExtension.on_serve_start` by the
    always-on daemon so an extension can run a clean background job (#249).

    * ``stop_event`` — set when the daemon is shutting down. An extension's
      own thread should ``wait()`` on it (never a bare ``sleep``) and exit
      promptly when it fires.
    * ``request_stop`` — ask the daemon itself to stop serving (the same
      path ``/api/shutdown`` and SIGTERM use). Rarely needed; present so an
      extension can trigger an orderly shutdown.
    * ``home`` — the resolved home root (honours an injected ``home``, else
      ``Path.home()``) so an extension reads its own state under
      ``<home>/.mureo`` exactly as the rest of configure does.
    """

    stop_event: threading.Event
    request_stop: Callable[[], None]
    home: Path


@runtime_checkable
class WebExtension(Protocol):
    """Structural type a third-party web extension must satisfy.

    Discovery calls :py:meth:`routes` and :py:meth:`view` exactly once
    per entry point during startup; their return values are stored in
    a :class:`WebExtensionEntry`. Exceptions raised by either method
    skip the extension (with :class:`WebExtensionWarning`) without
    affecting other extensions or the configure server.

    Optional class attributes (read via :func:`getattr` so the Protocol
    itself stays backward-compatible):

    * ``display_name_i18n: Mapping[str, str]`` — per-locale labels
      keyed by BCP-47 language code (``"en"``, ``"ja"``). When the
      configure-UI swaps locale, the renderer prefers
      ``display_name_i18n[locale]``, falling back to
      ``display_name_i18n["en"]``, then to ``display_name``.
      Extensions that do not declare it behave exactly as before —
      ``display_name`` is shown unchanged in every locale.
    * ``hidden_builtin_tabs: tuple[str, ...]`` — built-in dashboard
      tabs (subset of :data:`BUILTIN_DASHBOARD_TABS`) this extension
      supersedes. The renderer hides the matching nav items + panes;
      the extension's own tab becomes the default selection when a
      hidden tab would have been the default. Unknown keys are
      dropped with a :class:`WebExtensionWarning`; a non-tuple value
      skips the extension. Added in #189 for full-surface plugins.
    * ``replaces_landing: bool`` — when ``True`` and the extension
      supplies a ``view()``, the renderer skips the built-in landing
      and shows the extension's view directly on first load.
      ``True`` without a view is downgraded to ``False`` with a
      :class:`WebExtensionWarning`. When several installed
      extensions claim the landing the first-discovered one wins
      (later claims are downgraded with a warning). Added in #189.
    * ``dashboard_cards() -> tuple[DashboardCard, ...]`` — cards the
      renderer injects into built-in dashboard groups (each card's
      ``group`` must be in :data:`BUILTIN_CARD_GROUPS`; currently only
      ``"advanced"``). Use for small operator-wide settings that pair
      with a built-in card and do not warrant a whole extension tab;
      an extension may ship cards with or without a ``view()``. Called
      exactly once during discovery, like ``view()``. A non-callable
      attribute, a non-tuple return, or a non-``DashboardCard``
      element skips the extension.
    * ``on_serve_start(ctx: ServeContext) -> None`` and
      ``on_serve_stop() -> None`` — lifecycle hooks invoked ONLY by the
      always-on daemon (``mureo configure --serve``), never by a
      short-lived interactive ``mureo configure`` (mirrors #244's "only
      the always-on service runs background jobs"). ``on_serve_start``
      fires once after the server is ready; ``on_serve_stop`` once at
      shutdown. Use them to start/stop a self-managed background thread —
      the extension owns its own scheduling, staggering, and backoff.
      Both hooks run synchronously on the daemon's startup/shutdown path
      (``on_serve_start`` BEFORE the SIGINT/SIGTERM handlers are
      installed) and sequentially across extensions, so a hook MUST
      return promptly: spawn a thread for any ongoing work and never
      block in the hook body, or it will stall daemon startup/shutdown
      and delay the other extensions. An extension that declares neither
      behaves exactly as before. A hook
      that raises is isolated as a :class:`WebExtensionWarning`, and an
      extension whose ``on_serve_start`` raised does NOT receive
      ``on_serve_stop``. Added in #249.
    """

    @property
    def name(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    def routes(self) -> tuple[RouteContribution, ...]: ...

    def view(self) -> ViewContribution | None: ...


@dataclass(frozen=True)
class WebExtensionEntry:
    """Frozen record of one successfully-discovered extension.

    ``display_name_i18n`` defaults to an empty mapping so callers that
    construct an entry without supplying the field continue to work
    after the field was added. The renderer treats an empty mapping
    the same as a missing one — ``display_name`` is the fallback in
    both cases.
    """

    name: str
    display_name: str
    routes: tuple[RouteContribution, ...]
    view: ViewContribution | None
    source_distribution: str | None
    display_name_i18n: Mapping[str, str] = field(default_factory=dict)
    # #189 — surface overrides for full-surface plugins. Both default
    # to the no-op values so entries constructed before the feature
    # existed (and every additive-only plugin) behave exactly as
    # before.
    hidden_builtin_tabs: tuple[str, ...] = ()
    replaces_landing: bool = False
    # Cards injected into built-in dashboard groups. Defaults to () so
    # entries constructed before the feature existed (and every
    # extension that ships none) behave exactly as before.
    dashboard_cards: tuple[DashboardCard, ...] = ()
    # #249 — optional always-on lifecycle hooks, captured as bound
    # callables during discovery (``None`` when the extension declares
    # neither). Invoked only in ``serve_forever`` (daemon) mode by
    # :func:`start_serve_lifecycles` / :func:`stop_serve_lifecycles`.
    on_serve_start: Callable[[ServeContext], None] | None = None
    on_serve_stop: Callable[[], None] | None = None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


_cached_entries: tuple[WebExtensionEntry, ...] | None = None


def reset_web_extensions() -> None:
    """Clear the discovery cache. Intended for tests; production
    callers should not need this — entry points do not change at
    runtime."""
    global _cached_entries
    _cached_entries = None


def discover_web_extensions() -> tuple[WebExtensionEntry, ...]:
    """Discover and validate every entry point in
    :data:`WEB_EXTENSIONS_ENTRY_POINT_GROUP`.

    The result is cached for the process lifetime; subsequent calls
    return the same tuple by identity. Tests that need to re-run
    discovery against a different entry-point set must call
    :func:`reset_web_extensions` first.

    Per-plugin fault isolation: any exception raised by ``ep.load()``,
    by the extension's ``routes()`` / ``view()`` method, or by
    construction of a :class:`WebExtensionEntry` (e.g. when an
    extension returns a ``RouteContribution`` that fails its own
    ``__post_init__`` check) is converted to a
    :class:`WebExtensionWarning` and skips just that one entry.
    Duplicate names are first-wins with a warning.
    """
    global _cached_entries
    if _cached_entries is not None:
        return _cached_entries

    by_name: dict[str, WebExtensionEntry] = {}
    landing_owner: str | None = None
    for ep in entry_points(group=WEB_EXTENSIONS_ENTRY_POINT_GROUP):
        entry = _load_entry_point(ep)
        if entry is None:
            continue
        if entry.name in by_name:
            warnings.warn(
                f"duplicate web extension name {entry.name!r} "
                f"(first registration wins; rejected "
                f"{entry.source_distribution!r})",
                WebExtensionWarning,
                stacklevel=2,
            )
            continue
        # #189 — at most one installed extension may own the landing.
        # First-discovered wins; later claims are downgraded with a
        # warning (mirrors the duplicate-name discipline above).
        if entry.replaces_landing:
            if landing_owner is None:
                landing_owner = entry.name
            else:
                warnings.warn(
                    f"web extension {entry.name!r} sets "
                    f"replaces_landing=True but {landing_owner!r} already "
                    f"owns the landing (first discovered wins); downgraded",
                    WebExtensionWarning,
                    stacklevel=2,
                )
                entry = dataclasses.replace(entry, replaces_landing=False)
        by_name[entry.name] = entry

    _cached_entries = tuple(by_name.values())
    return _cached_entries


def _load_entry_point(ep: Any) -> WebExtensionEntry | None:
    """Load, validate, and freeze one entry point.

    The try/except spans the entire load → introspect → freeze
    sequence so an adversarial plugin cannot bypass fault isolation
    via a metaclass side effect or a property that raises.
    """
    ep_name = getattr(ep, "name", "<unknown>")
    try:
        loaded = ep.load()
        extension = loaded() if isinstance(loaded, type) else loaded
        # ``isinstance(extension, WebExtension)`` only verifies method
        # presence (``@runtime_checkable`` Protocol semantics); the
        # deeper validation (regex-checked name, type-checked routes
        # tuple, etc.) lives in the explicit blocks below.
        if not isinstance(extension, WebExtension):
            warnings.warn(
                f"entry point {ep_name!r} did not yield a WebExtension "
                f"(got {type(extension).__name__}); skipped",
                WebExtensionWarning,
                stacklevel=3,
            )
            return None
        name = extension.name
        if not isinstance(name, str) or not _NAME_RE.match(name):
            warnings.warn(
                f"entry point {ep_name!r} has invalid web-extension "
                f"name {name!r} (must match {_NAME_RE.pattern!r}); "
                f"skipped",
                WebExtensionWarning,
                stacklevel=3,
            )
            return None
        display_name = extension.display_name
        if not isinstance(display_name, str) or not display_name:
            warnings.warn(
                f"web extension {name!r} has empty display_name; skipped",
                WebExtensionWarning,
                stacklevel=3,
            )
            return None
        routes_value = extension.routes()
        if not isinstance(routes_value, tuple):
            raise TypeError(
                f"routes() must return tuple, got {type(routes_value).__name__}"
            )
        for r in routes_value:
            if not isinstance(r, RouteContribution):
                raise TypeError(
                    f"routes() returned {type(r).__name__}, expected RouteContribution"
                )
        view_value = extension.view()
        if view_value is not None and not isinstance(view_value, ViewContribution):
            raise TypeError(
                f"view() returned {type(view_value).__name__}, "
                f"expected ViewContribution or None"
            )
        # Optional dashboard cards (additive — absent means no cards).
        # Read via ``getattr`` like the other optional attributes so
        # pre-feature extensions keep working unmodified. Any type
        # problem (non-callable attribute, non-tuple return, foreign
        # element) is a packaging bug that skips the whole extension
        # via the surrounding try/except; value problems (unknown
        # group, inline-executable HTML) already raise inside
        # ``DashboardCard.__post_init__`` with the same effect.
        cards_method = getattr(extension, "dashboard_cards", None)
        cards_value: tuple[DashboardCard, ...] = ()
        if cards_method is not None:
            if not callable(cards_method):
                raise TypeError(
                    f"dashboard_cards must be callable, "
                    f"got {type(cards_method).__name__}"
                )
            cards_raw = cards_method()
            if not isinstance(cards_raw, tuple):
                raise TypeError(
                    f"dashboard_cards() must return tuple, "
                    f"got {type(cards_raw).__name__}"
                )
            for card in cards_raw:
                if not isinstance(card, DashboardCard):
                    raise TypeError(
                        f"dashboard_cards() returned {type(card).__name__}, "
                        f"expected DashboardCard"
                    )
            cards_value = cards_raw
        # ``display_name_i18n`` is read defensively so the Protocol
        # itself does not require the attribute — every pre-feature
        # extension keeps working without modification. When present
        # the value must be a mapping of ``str -> str``; anything else
        # is a packaging bug and the entry is skipped (defence against
        # mistakes like ``[("en", "Foo")]``, ``{"en": 123}``, or
        # ``{1: "Foo"}`` reaching the JSON serialiser later).
        i18n_value = getattr(extension, "display_name_i18n", {})
        if not isinstance(i18n_value, Mapping):
            raise TypeError(
                f"display_name_i18n must be a Mapping, "
                f"got {type(i18n_value).__name__}"
            )
        i18n_normalised: dict[str, str] = {}
        for key, value in i18n_value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"display_name_i18n keys must be str, got {type(key).__name__}"
                )
            if not isinstance(value, str):
                raise TypeError(
                    f"display_name_i18n values must be str, "
                    f"got {type(value).__name__} for key {key!r}"
                )
            i18n_normalised[key] = value
        # #189 — surface overrides. Type-level problems (wrong container
        # type, non-str element, non-bool flag) are packaging bugs and
        # skip the whole extension via the surrounding try/except —
        # mirroring the ``display_name_i18n`` discipline. Value-level
        # problems (unknown tab key, landing claim without a view) are
        # soft: warn + drop / downgrade, keep the extension.
        hidden_raw = getattr(extension, "hidden_builtin_tabs", ())
        if not isinstance(hidden_raw, tuple):
            raise TypeError(
                f"hidden_builtin_tabs must be tuple[str, ...], "
                f"got {type(hidden_raw).__name__}"
            )
        hidden_tabs: list[str] = []
        for tab in hidden_raw:
            if not isinstance(tab, str):
                raise TypeError(
                    f"hidden_builtin_tabs elements must be str, "
                    f"got {type(tab).__name__}"
                )
            if tab not in BUILTIN_DASHBOARD_TABS:
                warnings.warn(
                    f"web extension {name!r} lists unknown built-in tab "
                    f"{tab!r} in hidden_builtin_tabs (known: "
                    f"{BUILTIN_DASHBOARD_TABS}); key dropped",
                    WebExtensionWarning,
                    stacklevel=3,
                )
                continue
            if tab not in hidden_tabs:
                hidden_tabs.append(tab)
        replaces_landing = getattr(extension, "replaces_landing", False)
        if not isinstance(replaces_landing, bool):
            raise TypeError(
                f"replaces_landing must be bool, "
                f"got {type(replaces_landing).__name__}"
            )
        if replaces_landing and view_value is None:
            warnings.warn(
                f"web extension {name!r} sets replaces_landing=True but "
                f"supplies no view() — the operator would have nowhere "
                f"to land; downgraded to False",
                WebExtensionWarning,
                stacklevel=3,
            )
            replaces_landing = False
        # #249 — capture optional lifecycle hooks as bound callables.
        # Read defensively (``getattr``) so the Protocol stays additive;
        # a non-callable hook is a packaging bug and skips the whole
        # extension via the surrounding try/except (mirroring the
        # ``display_name_i18n`` type-level discipline).
        on_serve_start = getattr(extension, "on_serve_start", None)
        if on_serve_start is not None and not callable(on_serve_start):
            raise TypeError(
                f"on_serve_start must be callable, "
                f"got {type(on_serve_start).__name__}"
            )
        on_serve_stop = getattr(extension, "on_serve_stop", None)
        if on_serve_stop is not None and not callable(on_serve_stop):
            raise TypeError(
                f"on_serve_stop must be callable, "
                f"got {type(on_serve_stop).__name__}"
            )
    except Exception as exc:  # noqa: BLE001 — per-plugin fault isolation
        warnings.warn(
            f"failed to load web extension {ep_name!r}: {exc!r}",
            WebExtensionWarning,
            stacklevel=3,
        )
        return None

    return WebExtensionEntry(
        name=name,
        display_name=display_name,
        routes=routes_value,
        view=view_value,
        source_distribution=_resolve_source(ep),
        display_name_i18n=i18n_normalised,
        hidden_builtin_tabs=tuple(hidden_tabs),
        replaces_landing=replaces_landing,
        dashboard_cards=cards_value,
        on_serve_start=on_serve_start,
        on_serve_stop=on_serve_stop,
    )


def _resolve_source(ep: Any) -> str | None:
    """Best-effort extraction of the source pip distribution name.

    Returns ``None`` for in-process registrations whose ``ep.dist`` is
    absent, and also for adversarial ``dist`` objects exposing a
    non-``str`` ``name`` (matches the defensive posture in
    :func:`mureo.core.providers.registry._resolve_source`).
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    name = getattr(dist, "name", None)
    return name if isinstance(name, str) else None


# ---------------------------------------------------------------------------
# Always-on lifecycle (#249)
# ---------------------------------------------------------------------------


def start_serve_lifecycles(
    entries: tuple[WebExtensionEntry, ...], ctx: ServeContext
) -> tuple[WebExtensionEntry, ...]:
    """Call ``on_serve_start(ctx)`` on every entry that declares it (#249).

    Returns the entries whose hook ran without raising — only those get a
    matching :func:`stop_serve_lifecycles` call later. A hook that raises
    is isolated as a :class:`WebExtensionWarning` so one bad extension can
    neither crash the daemon nor block the others' startup.

    Intended for the always-on daemon (``serve_forever``) only; a
    short-lived interactive launch never calls this. Hooks run
    sequentially on the caller's thread, so a hook that blocks delays the
    daemon's startup and the other extensions — extensions must return
    promptly and offload ongoing work to their own thread.
    """
    started: list[WebExtensionEntry] = []
    for entry in entries:
        hook = entry.on_serve_start
        if hook is None:
            continue
        try:
            hook(ctx)
        except Exception as exc:  # noqa: BLE001 — per-plugin fault isolation
            warnings.warn(
                f"web extension {entry.name!r} on_serve_start raised "
                f"{exc!r}; skipped (it will not be stopped)",
                WebExtensionWarning,
                stacklevel=2,
            )
            continue
        started.append(entry)
    return tuple(started)


def stop_serve_lifecycles(entries: tuple[WebExtensionEntry, ...]) -> None:
    """Call ``on_serve_stop()`` on each entry, isolating faults (#249).

    Pass the tuple returned by :func:`start_serve_lifecycles` so only
    extensions whose ``on_serve_start`` succeeded are stopped. A hook that
    raises is isolated as a :class:`WebExtensionWarning`; the remaining
    extensions are still stopped.
    """
    for entry in entries:
        hook = entry.on_serve_stop
        if hook is None:
            continue
        try:
            hook()
        except Exception as exc:  # noqa: BLE001 — per-plugin fault isolation
            warnings.warn(
                f"web extension {entry.name!r} on_serve_stop raised "
                f"{exc!r}; ignored",
                WebExtensionWarning,
                stacklevel=2,
            )


__all__ = [
    "BUILTIN_CARD_GROUPS",
    "BUILTIN_DASHBOARD_TABS",
    "DashboardCard",
    "FILENAME_PATTERN",
    "NAME_PATTERN",
    "RouteContribution",
    "SUBPATH_PATTERN",
    "ServeContext",
    "StaticAsset",
    "ViewContribution",
    "WEB_EXTENSIONS_ENTRY_POINT_GROUP",
    "WebExtension",
    "WebExtensionEntry",
    "WebExtensionWarning",
    "discover_web_extensions",
    "reset_web_extensions",
    "start_serve_lifecycles",
    "stop_serve_lifecycles",
]
