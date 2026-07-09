"""``RuntimeContext`` — frozen aggregate of the four core extension Protocols
plus an opaque workspace identifier, ``default_runtime_context()`` — the
factory that wires the four file-backed defaults, and
``get_runtime_context()`` — the resolver that lets alternate backends
inject a custom context via the ``mureo.runtime_context_factory`` entry
point group.

A ``RuntimeContext`` is the single object passed through mureo call sites
that need pluggable backends for credentials, persisted state, ``/learn``
knowledge, and API throttling. Today nothing in OSS constructs a
``RuntimeContext`` automatically — call sites still talk to the legacy
helpers in ``mureo.auth`` / ``mureo.context`` / ``mureo.mcp`` directly.
Hookup of consumers ships in follow-up commits; this module introduces
the type, the default factory, and the resolver so alternate backends
can be wired before the refactor lands.

``workspace_id`` is intentionally opaque. For single-workspace callers
the canonical value is the literal :data:`DEFAULT_WORKSPACE_ID`;
alternate runtimes are free to use any other non-empty string. Empty
strings are rejected at construction time.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Final

from mureo.core.knowledge_store import FilesystemKnowledgeStore, KnowledgeStore
from mureo.core.secret_store import FilesystemSecretStore, SecretStore
from mureo.core.state_store import FilesystemStateStore, StateStore
from mureo.core.throttle_store import ProcessLocalThrottleStore, ThrottleStore

if TYPE_CHECKING:
    from mureo.throttle import ThrottleConfig


#: Canonical sentinel for single-workspace callers. Exposed so consumers
#: can compare against the literal without hard-coding it; pinned by
#: :mod:`tests.core.test_runtime_context` so the value cannot drift.
DEFAULT_WORKSPACE_ID = "default"


@dataclass(frozen=True)
class RuntimeContext:
    """Immutable bundle of pluggable backends + a workspace identifier.

    The dataclass is frozen so a context can be passed safely across
    threads / coroutines without races on its fields. The pointed-to
    stores are *not* required to be immutable — they encapsulate their
    own concurrency story.
    """

    secret_store: SecretStore
    state_store: StateStore
    knowledge_store: KnowledgeStore
    throttle_store: ThrottleStore
    workspace_id: str

    def __post_init__(self) -> None:
        """Reject empty / whitespace-only ``workspace_id``.

        Matches the validation pattern used by
        :func:`mureo.core.providers.base.validate_provider_name` —
        identifiers in this layer must be unambiguous strings.
        """
        if not isinstance(self.workspace_id, str) or not self.workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty, non-whitespace string")


# ---------------------------------------------------------------------------
# Default factory — wires the four file-backed defaults
# ---------------------------------------------------------------------------


def default_runtime_context(
    *,
    workspace: Path | None = None,
    credentials_path: Path | None = None,
    operator_knowledge_path: Path | None = None,
    workspace_knowledge_path: Path | None = None,
    throttle_config: ThrottleConfig | None = None,
) -> RuntimeContext:
    """Return a ``RuntimeContext`` wired with the file-backed defaults.

    All keyword arguments are optional; when omitted, each store falls
    back to the legacy location it has used in mureo to date —
    ``~/.mureo/credentials.json``, CWD-relative ``STATE.json`` /
    ``STRATEGY.md``, ``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md``,
    and :data:`mureo.throttle.PLUGIN_THROTTLE` respectively. The
    workspace tier of the knowledge store is absent by default; pass
    ``workspace_knowledge_path`` to enable it.

    Note: ``workspace`` here is the state-store directory (passed
    through to :class:`FilesystemStateStore`), not the
    :attr:`RuntimeContext.workspace_id` identifier. The factory fixes
    ``workspace_id`` at :data:`DEFAULT_WORKSPACE_ID`; callers that need
    a different identifier should construct the ``RuntimeContext``
    directly rather than going through this factory.
    """
    return RuntimeContext(
        secret_store=FilesystemSecretStore(path=credentials_path),
        state_store=FilesystemStateStore(workspace=workspace),
        knowledge_store=FilesystemKnowledgeStore(
            operator_path=operator_knowledge_path,
            workspace_path=workspace_knowledge_path,
        ),
        throttle_store=ProcessLocalThrottleStore(default_config=throttle_config),
        workspace_id=DEFAULT_WORKSPACE_ID,
    )


# ---------------------------------------------------------------------------
# Entry-point resolver — lets alternate backends inject a custom context
# ---------------------------------------------------------------------------


#: Entry-point group name. A third-party distribution can register a
#: zero-arg callable returning a :class:`RuntimeContext` under this
#: group; the resolver discovers and uses it transparently.
RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP: Final[str] = "mureo.runtime_context_factory"


class RuntimeContextFactoryError(RuntimeError):
    """Raised when the entry-point lookup is misconfigured.

    Conditions:
    - More than one entry point is registered in the
      ``mureo.runtime_context_factory`` group (the integration point is
      global, so picking one silently would mask a packaging bug).
    - The registered factory raises during evaluation (the exception is
      wrapped so the entry-point name reaches the log).
    - The registered factory returns something other than a
      :class:`RuntimeContext`.
    """


_cached_context: RuntimeContext | None = None


def get_runtime_context() -> RuntimeContext:
    """Return the process-wide ``RuntimeContext``, resolving via entry
    points on first call.

    Resolution rules:

    - **0 entry points** in :data:`RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP` —
      :func:`default_runtime_context` is called and the result cached.
    - **1 entry point** — its zero-arg callable is loaded and called; the
      returned :class:`RuntimeContext` is cached.
    - **>1 entry points** — :class:`RuntimeContextFactoryError` is raised.
      No silent first-wins: a global integration hook must be
      unambiguous, and a packaging mistake should be visible. (Contrast
      with :mod:`mureo.core.providers.registry`, which uses first-wins
      plus a warning — providers are additive so "more" is benign, but a
      ``RuntimeContext`` is a process singleton.)

    Only successfully-constructed contexts are cached; if the configured
    factory raises (or returns the wrong type) the error surfaces on
    every call until the underlying packaging issue is fixed. This means
    a broken plugin re-runs ``ep.load()`` per call — acceptable because
    the load happens once per failing process and the alternative
    (caching the exception) hides a fix-in-place.

    Single-workspace and "1 dir = 1 session" callers do not change their
    workspace mid-run, so the cache is correct by construction. Tests
    that need to swap the underlying state must call
    :func:`reset_runtime_context` first.
    """
    global _cached_context
    if _cached_context is not None:
        return _cached_context

    eps = list(entry_points(group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP))
    if len(eps) == 0:
        ctx = default_runtime_context()
    elif len(eps) == 1:
        ep = eps[0]
        try:
            factory = ep.load()
            ctx = factory()
        except Exception as exc:
            raise RuntimeContextFactoryError(
                f"entry point {ep.name!r} failed to produce a RuntimeContext: {exc!r}"
            ) from exc
        if not isinstance(ctx, RuntimeContext):
            raise RuntimeContextFactoryError(
                f"entry point {ep.name!r} returned {type(ctx).__name__}, "
                f"expected RuntimeContext"
            )
    else:
        names = ", ".join(repr(ep.name) for ep in eps)
        raise RuntimeContextFactoryError(
            f"multiple {RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP} entry "
            f"points are registered ({names}); exactly one is allowed"
        )

    _cached_context = ctx
    return _cached_context


def reset_runtime_context() -> None:
    """Clear the cached ``RuntimeContext``. Intended for tests; production
    callers should not need this — a process has one workspace."""
    global _cached_context
    _cached_context = None


def runtime_credentials_path(default: Path) -> Path:
    """Return the credentials path the active ``RuntimeContext`` uses.

    Bridges the path-based configure-UI write functions (which take a
    ``credentials_path: Path``) to the pluggable ``SecretStore`` the MCP
    runtime reads from, so an alternate backend registered via
    :data:`RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP` is honored on
    *write* — not only on *read* (#194).

    Resolution (in order):

    - **No factory registered** → return ``default`` unchanged. This
      keeps single-backend installs on their existing location AND
      preserves a test- or caller-injected ``home`` (the default
      :class:`RuntimeContext`'s :class:`FilesystemSecretStore` resolves
      against the real ``Path.home()``, which must NOT override an
      injected path). The gate is on entry-point *presence*, not on the
      resolved path, precisely to avoid that real-home fall-through.
    - **Store declares ``credentials_write_path``** → return it. Any
      ``SecretStore`` may advertise the filesystem path its writes land
      in via an optional ``credentials_write_path: Path`` attribute
      (read defensively via :func:`getattr`). This is the protocol-based
      hook (#196): a filesystem-backed store that is not literally a
      :class:`FilesystemSecretStore` instance — e.g. a composite that
      layers an override file over a shared base — can still steer the
      configure-UI write path to where it actually persists. A non-
      ``Path`` declaration is ignored (a mis-typed store must not feed a
      bogus value to the path-based write functions).
    - **Built-in :class:`FilesystemSecretStore`** → return the store's
      ``path``. Back-compat fallback for the concrete default store,
      which does not declare ``credentials_write_path``.
    - **Otherwise (non-filesystem / undeclared)** → return ``default``.
      A ``credentials_path: Path`` cannot represent a non-filesystem
      backend; the path-based write functions stay on the host default
      (the honest ceiling of that API — a full ``SecretStore``-threaded
      write path is a separate, larger change).

    A registered-but-broken factory surfaces its
    :class:`RuntimeContextFactoryError` here, mirroring the read path's
    behavior — a packaging mistake is made visible rather than hidden
    behind a silent fall-back to the default location.
    """
    if not list(entry_points(group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP)):
        return default
    store = get_runtime_context().secret_store
    declared = getattr(store, "credentials_write_path", None)
    if isinstance(declared, Path):
        return declared
    if isinstance(store, FilesystemSecretStore):
        return store.path
    return default


def runtime_multi_account_auth() -> bool:
    """Return whether the active ``SecretStore`` is a multi-account backend.

    A backend whose credentials are operator-shared across many client
    accounts (e.g. an agency plugin: one Google ``developer_token`` +
    OAuth client, one Meta app, serving N clients whose
    ``customer_id`` / ``account_id`` are supplied per-request out of
    band) advertises this by exposing ``multi_account_auth = True`` on
    its store. The configure-UI OAuth flow then persists only the
    shared credentials and skips the per-account picker (#198).

    Resolution mirrors :func:`runtime_credentials_path`:

    - **No factory registered** → ``False``. Single-backend OSS installs
      (and any test- or caller-injected ``home``) keep the standalone
      behavior — the picker is shown. The gate is on entry-point
      *presence* so the default :class:`RuntimeContext` (whose
      :class:`FilesystemSecretStore` never declares the capability) is
      never even consulted.
    - **Store declares ``multi_account_auth``** → the value, accepted
      only when it is exactly ``True`` (read defensively via
      :func:`getattr`). A truthy-but-not-``True`` declaration from a
      mis-typed store must not silently suppress the picker, so
      ``"yes"`` / ``1`` / a non-empty list all resolve to ``False``.
    - **Otherwise** → ``False``.

    A registered-but-broken factory surfaces its
    :class:`RuntimeContextFactoryError` here, mirroring the read path —
    a packaging mistake is made visible rather than hidden behind a
    silent fall-back to the picker.
    """
    if not list(entry_points(group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP)):
        return False
    store = get_runtime_context().secret_store
    return getattr(store, "multi_account_auth", False) is True


def runtime_ui_plugin_credential_fields() -> dict[str, frozenset[str]] | None:
    """Return a per-provider allow-list of credential-field keys the
    dashboard "Plugin credentials" section should render, or ``None``.

    A multi-account backend whose per-account ids live in per-client
    config (not the operator-shared credential store) advertises this so
    the dashboard shows only operator-shared auth fields and stops
    offering a second, competing input for an account id that belongs on
    the backend's own per-client form — the failure mode behind the #202
    incident (a stale shared ``account_id`` hijacking a client). It joins
    the same store-capability family as :func:`runtime_credentials_path`
    (#196) and :func:`runtime_multi_account_auth` (#198).

    Resolution:

    - **No factory registered** → ``None``. Standalone OSS / default
      stores keep rendering every declared field (account ids included);
      the gate is on entry-point *presence* so the default store is never
      consulted.
    - **Store declares ``ui_plugin_credential_fields``** as a
      :class:`~collections.abc.Mapping` → a normalized
      ``{provider: frozenset(keys)}`` dict. Each value must be a non-str
      collection of keys; malformed entries are skipped.
    - **Not a Mapping / empty after normalization / attribute absent** →
      ``None``. A mis-typed declaration must NOT silently hide fields
      (defensive, mirroring #198's strict ``is True``), so anything the
      resolver cannot trust collapses to "no scoping".

    Consumers (the dashboard list builder) treat a returned mapping as:
    providers present → render only the listed keys (drop the card when
    none remain); providers absent → keep all fields (so an unknown
    future plugin stays fully usable).
    """
    if not list(entry_points(group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP)):
        return None
    store = get_runtime_context().secret_store
    declared = getattr(store, "ui_plugin_credential_fields", None)
    if not isinstance(declared, Mapping):
        return None
    scoped: dict[str, frozenset[str]] = {}
    for provider, keys in declared.items():
        if not isinstance(provider, str):
            continue
        if isinstance(keys, (str, bytes)) or not isinstance(keys, Collection):
            continue
        scoped[provider] = frozenset(str(k) for k in keys)
    return scoped or None


def runtime_search_console_sites() -> frozenset[str] | None:
    """Return the Search Console ``site_url`` allow-list for the ACTIVE
    client, or ``None`` when Search Console is not tenant-scoped.

    Search Console reuses the operator-shared Google OAuth — one identity
    that may see MANY clients' properties — and its MCP tools take
    ``site_url`` as a free caller argument. In a multi-account (agency)
    deployment nothing otherwise stops one client's workspace from querying a
    sibling client's property (cross-client data leak). A multi-account
    backend closes this by declaring, on its ``SecretStore``, the set of
    ``site_url``s that belong to the active client as ``search_console_sites``
    (a non-``str`` collection of strings). The Search Console handlers then
    resolve/enforce ``site_url`` against this set — fail-closed for an
    out-of-set value, fail-fast when none is configured — mirroring how
    Google Ads binds ``customer_id`` from per-client config. Joins the
    store-capability family of :func:`runtime_credentials_path` (#196),
    :func:`runtime_multi_account_auth` (#198), and
    :func:`runtime_ui_plugin_credential_fields` (#202).

    Resolution:

    - **No factory registered** → ``None``. Standalone OSS keeps the
      unrestricted behavior — the gate is on entry-point *presence* so the
      default store is never consulted and existing single-workspace use is
      byte-identical.
    - **Store declares a usable ``search_console_sites``** (a non-``str`` /
      non-``bytes`` :class:`~collections.abc.Collection`) → a ``frozenset`` of
      its non-blank string entries. An empty / all-blank / all-non-str
      collection resolves to an EMPTY ``frozenset`` (scoping ON, zero sites),
      which the handlers turn into a fail-fast — a security control errs
      CLOSED once engaged.
    - **Attribute absent or NOT a usable collection (bare ``str`` / ``bytes``
      / generator / other), on a multi-account backend** (``multi_account_auth
      is True``) → an EMPTY ``frozenset``, NOT ``None``. A shared-OAuth
      backend that reaches many clients' properties MUST scope Search Console;
      forgetting (or mistyping) the allow-list must fail CLOSED (a loud
      "not configured for this client") rather than silently reopen the
      cross-client leak. This is the key difference from the permissive
      members of the family: absence defaults to the SAFE side here.
    - **Attribute absent / not usable on a single-account backend** → ``None``
      (not scoped). A single-account factory carries no shared-OAuth
      cross-client risk, so it keeps the unrestricted behavior; a usable
      allow-list still scopes it if one is declared.
    """
    if not list(entry_points(group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP)):
        return None
    store = get_runtime_context().secret_store
    scoped = _coerce_site_allow_list(getattr(store, "search_console_sites", None))
    if scoped is not None:
        return scoped
    # No usable allow-list. Fail CLOSED for a shared-OAuth (multi-account)
    # backend — it can reach every client's property, so an un-declared or
    # mistyped list must scope to nothing, not everything. A single-account
    # backend has no such cross-client reach, so it stays unrestricted.
    if getattr(store, "multi_account_auth", False) is True:
        return frozenset()
    return None


def _coerce_site_allow_list(declared: object) -> frozenset[str] | None:
    """Normalize a declared ``search_console_sites`` value, or ``None``.

    ``None`` means "no usable declaration" (absent, or a non-collection /
    bare ``str`` / ``bytes`` — a mistyped scalar must never become a
    one-element allow-list). A usable collection yields a ``frozenset`` of its
    non-blank string entries (possibly empty).
    """
    if declared is None:
        return None
    if isinstance(declared, (str, bytes)) or not isinstance(declared, Collection):
        return None
    return frozenset(
        site.strip() for site in declared if isinstance(site, str) and site.strip()
    )
