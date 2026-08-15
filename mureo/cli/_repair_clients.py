"""Which STATE.json files ``mureo repair platform-key --all`` sweeps.

The incident #610 exists for — LOGLY snapshots written under the invented key
``logly_ads`` instead of the bridge's ``logly_ads_context`` — was never
confined to one directory. It was made by an agent that ran against every
client on the machine, so the repair has to be able to run against every
client on the machine.

No client registry is invented here
-----------------------------------
mureo OSS has no notion of "the other client". The one that exists is the
optional pair of ``StateStore`` capabilities the read-only Reports tab
already reads — ``list_clients()`` and ``state_store_for_client(slug)`` —
resolved in :mod:`mureo.web.report_clients` and supplied by a multi-account
backend. This module calls **that** seam rather than a second one: two
answers to "which clients exist" that can drift is the same defect class
#609/#610 are about, and OSS must not grow a dependency on the backend that
supplies them.

Everything the seam does defensively is therefore inherited: a store
declaring neither capability yields exactly one target (the active
workspace), which is what every OSS install gets, and a registry that cannot
be read at all degrades to that same single target. The degradation is
**visible** rather than silent because the summary always leads with how many
clients were surveyed — an operator who runs twelve clients and is told
"Surveyed 1 client." has the signal they need.

A store that advertises ``list_clients`` but no ``state_store_for_client``
resolves every slug to the active store, so several targets can name one
file. They are not de-duplicated: the summary prints each target's path, and
inventing a merge here would hide a misconfigured backend rather than show
it.

Reading is where a client fails, not the sweep
----------------------------------------------
:func:`survey_client` converts any failure to read one client — an
unparseable document, no permission, a store that will not name a file — into
a :class:`ClientSurvey` carrying ``error``. Nothing raises out of the survey,
so one bad client costs the operator that client and not the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.cli._state_file import resolve_default_state_file, state_file_for_store
from mureo.cli._tty import terminal_safe as _safe
from mureo.context.platform_repair import plan_platform_keys
from mureo.context.state import read_state_file

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from mureo.context.models import StateDocument
    from mureo.context.platform_repair import PlatformKeyFinding, PlatformKeyRepair

_UNRESOLVED_STORE = "its state store did not say where its STATE.json lives"


@dataclass(frozen=True)
class ClientTarget:
    """One client the sweep will look at, and the file it will look at.

    ``state_file`` is ``None`` exactly when ``error`` explains why the client
    could not be located at all; the two are never both set.
    """

    slug: str
    name: str
    archived: bool
    state_file: Path | None
    error: str | None


@dataclass(frozen=True)
class ClientRegistry:
    """The sweep's targets, plus why the enumeration itself is untrustworthy.

    ``warning`` is set only when the client seam raised on the way out —
    something its own guards are documented to prevent. It is not set for the
    ordinary "no seam declared" case, which is not a fault: that is every OSS
    install, and it means one target rather than none.
    """

    targets: tuple[ClientTarget, ...]
    warning: str | None


@dataclass(frozen=True)
class ClientSurvey:
    """What one client's STATE.json turned out to hold.

    Read in this order: ``error`` set (could not be read), ``repairs``
    non-empty (needs work), ``kept`` non-empty (needs the operator's
    decision), or none of them (clean). ``kept`` carries the unresolvable
    entries the repair deliberately will NOT remove (#616/#617) — a client
    with only those is not clean and is not repairable either, so a summary
    that reads ``repairs`` alone would file it wrongly whichever way it went.
    ``doc`` is kept so the caller can also report the other finding this
    command does not repair — a duplicate whose two keys both name real
    platforms — without re-reading the file.
    """

    target: ClientTarget
    doc: StateDocument | None
    repairs: tuple[PlatformKeyRepair, ...]
    kept: tuple[PlatformKeyFinding, ...]
    error: str | None

    @property
    def missing(self) -> bool:
        """Is this client simply without a STATE.json yet?

        Not a failure: a client that has never synced has nothing to repair.
        Worth saying out loud though, because an operator expecting figures
        for it is looking at the wrong workspace.
        """
        return self.doc is None and self.error is None


def list_repair_targets() -> ClientRegistry:
    """Every client the active ``StateStore`` advertises, in registry order.

    Falls back to a single target for the active workspace when the store
    declares no client seam (the OSS default) or when the seam raises.
    """
    try:
        from mureo.web.report_clients import list_report_clients

        rows = list_report_clients()
    except Exception as exc:  # noqa: BLE001 — a backend fault degrades the sweep
        return ClientRegistry(
            targets=(_active_workspace_target(),),
            warning=(
                f"the client list could not be read ({type(exc).__name__}), so "
                f"only the active workspace was surveyed"
            ),
        )
    targets = tuple(_target_for_row(row) for row in rows if isinstance(row, dict))
    if not targets:
        return ClientRegistry(targets=(_active_workspace_target(),), warning=None)
    return ClientRegistry(targets=targets, warning=None)


def survey_client(
    target: ClientTarget, *, keys: Iterable[str] | None = None
) -> ClientSurvey:
    """Read one client and plan its repairs, converting failure to a report.

    ``keys`` narrows the plan exactly as
    :func:`~mureo.context.platform_repair.plan_platform_keys` does. The read is
    strict, like the single-workspace command's: a document that only parses
    tolerantly must not be rewritten, because the entries the tolerant parse
    skipped would be dropped by the write-back.
    """
    if target.state_file is None:
        return ClientSurvey(target, None, (), (), target.error or _UNRESOLVED_STORE)
    if not target.state_file.exists():
        return ClientSurvey(target, None, (), (), None)
    try:
        doc = read_state_file(target.state_file)
    except Exception as exc:  # noqa: BLE001 — one bad client is not a bad sweep
        return ClientSurvey(target, None, (), (), _reason(exc))
    plan = plan_platform_keys(doc, keys=keys)
    return ClientSurvey(target, doc, plan.repairs, plan.kept, None)


def survey_clients(
    targets: Iterable[ClientTarget], *, keys: Iterable[str] | None = None
) -> tuple[ClientSurvey, ...]:
    """Survey every target, in order."""
    return tuple(survey_client(target, keys=keys) for target in targets)


def _target_for_row(row: dict[str, Any]) -> ClientTarget:
    """Normalize one ``list_clients()`` row into a target.

    Field handling matches :func:`mureo.web.report_clients.list_report_clients`
    (which already normalized these): ``name`` falls back to the slug and
    ``archived`` is a coerced bool.
    """
    slug = str(row.get("slug", "")).strip()
    name = str(row.get("name", slug)).strip() or slug
    archived = bool(row.get("archived", False))
    if not slug:
        return ClientTarget("(unnamed)", "(unnamed)", archived, None, "it has no slug")
    try:
        from mureo.web.report_clients import state_store_for_client

        store = state_store_for_client(slug)
    except Exception as exc:  # noqa: BLE001 — a backend fault is one bad client
        return ClientTarget(
            slug, name, archived, None, f"its state store raised {type(exc).__name__}"
        )
    path = state_file_for_store(store)
    if path is None:
        return ClientTarget(slug, name, archived, None, _UNRESOLVED_STORE)
    return ClientTarget(slug, name, archived, path, None)


def _active_workspace_target() -> ClientTarget:
    """The single target every OSS install sweeps: this workspace."""
    try:
        state_file: Path | None = resolve_default_state_file()
        error = None
    except Exception as exc:  # noqa: BLE001 — a broken factory is still reportable
        state_file, error = None, f"its state store raised {type(exc).__name__}"
    return ClientTarget(
        slug="this workspace",
        name="this workspace",
        archived=False,
        state_file=state_file,
        error=error,
    )


def _reason(exc: Exception) -> str:
    """One scrubbed line saying why a client could not be read.

    STATE.json is agent-writable, so an exception carrying a fragment of it
    carries attacker-influenceable text straight to a terminal — the same
    reason every other string this command prints goes through
    ``terminal_safe``.
    """
    text = _safe(str(exc)).strip()
    return text or type(exc).__name__


__all__ = [
    "ClientRegistry",
    "ClientSurvey",
    "ClientTarget",
    "list_repair_targets",
    "survey_client",
    "survey_clients",
]
