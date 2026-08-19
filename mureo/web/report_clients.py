"""The multi-account (Agency) client seam behind the read-only Reports tab.

Split out of :mod:`mureo.web.reports` so the report builders and the client
registry stay separate concerns: nothing here reads STATE.json or shapes a
summary, and nothing in ``reports.py`` decides which clients exist.

Three optional capabilities on the active ``StateStore``, all read
defensively (``getattr`` + ``callable``) so a store that advertises none of
them keeps the standalone single-workspace behaviour:

- ``list_clients()`` → the selectable clients. Absent (OSS default) →
  exactly one client for the active workspace. Items may carry
  ``archived: bool`` (absent → ``False``).
- ``state_store_for_client(slug)`` → the ``StateStore`` for a non-default
  client. Absent → the active store is used regardless of the requested
  client.
- ``set_client_archived(slug, archived)`` → record that the digest must
  stop / resume syncing this client. Absent → the capability is advertised
  as ``False`` and the dashboard renders no archive control at all.

Every consumer of "which store do I read for this client" goes through
here — the Reports summary builder AND the Creative Studio gallery — so
``get_runtime_context`` is resolved in exactly one place and tests patch a
single seam: ``mureo.web.report_clients.get_runtime_context``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.core.runtime_context import get_runtime_context

if TYPE_CHECKING:
    from mureo.core.state_store import StateStore

logger = logging.getLogger(__name__)

__all__ = [
    "ClientArchiveError",
    "agency_clients_supplied",
    "list_report_clients",
    "report_clients_payload",
    "set_report_client_archived",
    "state_store_for_client",
]


class ClientArchiveError(Exception):
    """A client's archived state could not be changed (400-class).

    Carries a short, secret-free ``code`` the handler maps to an error
    envelope. The backend's own exception is logged server-side and never
    echoed — its message can carry deployment detail.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Multi-account (Agency) seam
# ---------------------------------------------------------------------------


def list_report_clients() -> list[dict[str, Any]]:
    """Enumerate the selectable reporting clients.

    Agency seam: when the active ``StateStore`` exposes a callable
    ``list_clients()`` (a multi-account backend), its result is normalized
    and returned. Otherwise (the OSS default single-workspace store) this
    returns exactly one entry describing the active workspace:
    ``[{"slug": <id>, "name": <id>, "active": True}]``.

    Never raises — a broken/odd ``list_clients`` degrades to the single
    active-workspace entry so the dashboard's client picker always renders.
    """
    store = _active_state_store()
    rows = _agency_list_clients(store)
    if rows is not None:
        return rows
    slug = _active_workspace_id(store)
    return [{"slug": slug, "name": slug, "active": True, "archived": False}]


def agency_clients_supplied() -> bool:
    """Is the client list coming from the Agency seam (#651)?

    ``True`` exactly when :func:`_agency_list_clients` answers — i.e. when
    :func:`list_report_clients` is returning a registry's clients rather
    than the synthesized single-workspace entry.

    It exists because one surface has to be OMITTED without it, not degraded
    to one row: the Reports triage layer ranks clients against each other,
    and a single workspace has no second client to rank. Asking this rather
    than counting :func:`list_report_clients` keeps that decision on the
    seam itself — a registry that happens to hold exactly one client today
    is still an Agency install, and the fallback entry is not a client
    anybody registered.
    """
    return _agency_list_clients(_active_state_store()) is not None


def report_clients_payload() -> dict[str, Any]:
    """The ``/api/reports/clients`` body: the rows plus the archive capability.

    ``can_archive`` is ``True`` only when the active store advertises a
    callable ``set_client_archived``. An OSS single-workspace install has no
    client registry to record the decision in, so the dashboard is told to
    render no archive control at all rather than one that cannot work.
    """
    return {
        "clients": list_report_clients(),
        "can_archive": _client_archive_seam() is not None,
    }


def _client_archive_seam() -> Any | None:
    """The active store's callable ``set_client_archived``, or ``None``.

    Read through ``getattr`` exactly like ``list_clients``: declaring the
    attribute IS the opt-in, and a mistyped (non-callable) declaration reads
    as absent rather than as a usable seam.
    """
    fn = getattr(_active_state_store(), "set_client_archived", None)
    return fn if callable(fn) else None


def set_report_client_archived(slug: str, archived: bool) -> None:
    """Archive / un-archive ``slug`` through the store's optional seam.

    Archiving stops the agency digest from syncing that client, so it is a
    decision ABOUT the client and belongs to whoever owns the client
    registry — OSS only relays it.

    Raises :class:`ClientArchiveError` and nothing else:

    - ``slug_required`` — blank slug (validated at this boundary, so every
      call site gets the check);
    - ``archive_unsupported`` — no seam (the OSS default);
    - ``archive_failed`` — the seam raised; logged with its traceback
      server-side and reported to the browser as a bare code.
    """
    name = str(slug).strip()
    if not name:
        raise ClientArchiveError("slug_required")
    fn = _client_archive_seam()
    if fn is None:
        raise ClientArchiveError("archive_unsupported")
    try:
        fn(name, bool(archived))
    except Exception as exc:  # noqa: BLE001 — a backend fault is a 400, not a 500
        logger.exception("set_client_archived(%r) failed", name)
        raise ClientArchiveError("archive_failed") from exc


def _agency_list_clients(store: StateStore) -> list[dict[str, Any]] | None:
    """Call the store's ``list_clients`` seam, normalized, or ``None``.

    ``None`` means "no Agency seam" (use the single-workspace fallback). A
    seam that raises or returns a non-list is treated as absent — a backend
    bug must not blank out the picker.

    ``archived`` is normalized exactly like ``active``: absent means
    ``False``, and a non-bool value is coerced rather than raising, so a
    backend that writes the flag as a string or a number still renders.
    """
    fn = getattr(store, "list_clients", None)
    if not callable(fn):
        return None
    try:
        raw = fn()
    except Exception:  # noqa: BLE001 — a backend bug must not 500 the picker
        logger.exception("state store list_clients() failed; using single workspace")
        return None
    if not isinstance(raw, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "")).strip()
        if not slug:
            continue
        rows.append(
            {
                "slug": slug,
                "name": str(item.get("name", slug)),
                "active": bool(item.get("active", False)),
                "archived": bool(item.get("archived", False)),
            }
        )
    return rows or None


def _active_state_store() -> StateStore:
    """The active workspace's ``StateStore`` (default single-workspace).

    Tolerant of a misconfigured ``mureo.runtime_context_factory`` (>1 entry
    point raises ``RuntimeContextFactoryError``): fall back to the default
    filesystem store so the Reports endpoints keep their documented "never
    raises" contract instead of dropping the connection with no envelope.
    """
    try:
        return get_runtime_context().state_store
    except Exception:  # noqa: BLE001 — a broken factory must not 500 the reports view
        logger.exception("runtime context factory failed; using default state store")
        from mureo.core.state_store import FilesystemStateStore

        return FilesystemStateStore()


def _active_workspace_id(store: StateStore) -> str:
    """A stable, non-empty client slug for the active workspace.

    Prefers the runtime context's opaque ``workspace_id`` (``"default"`` for
    OSS), falling back to a literal so the slug is never blank.
    """
    try:
        workspace_id = getattr(get_runtime_context(), "workspace_id", "")
    except Exception:  # noqa: BLE001 — mirror _active_state_store's tolerance
        workspace_id = ""
    slug = str(workspace_id).strip()
    return slug or "default"


def state_store_for_client(client: str | None) -> StateStore:
    """Resolve the ``StateStore`` to read for ``client``.

    Agency seam: when a non-default ``client`` is requested and the active
    store exposes a callable ``state_store_for_client(slug)``, its result is
    used. Otherwise the active store is returned — so OSS (single workspace)
    ignores the ``client`` argument by construction. A seam that raises or
    returns a non-store falls back to the active store rather than 500-ing.
    """
    active = _active_state_store()
    if not client:
        return active
    if client == _active_workspace_id(active):
        return active
    fn = getattr(active, "state_store_for_client", None)
    if not callable(fn):
        return active
    try:
        resolved = fn(client)
    except Exception:  # noqa: BLE001 — backend bug must not 500 the summary
        logger.exception("state_store_for_client(%r) failed; using active", client)
        return active
    # Duck-typed: a usable store exposes read_state(). Anything else is
    # ignored so a malformed return can't break the read below.
    return resolved if hasattr(resolved, "read_state") else active
