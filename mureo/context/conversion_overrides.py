"""Per-account conversion ``action_type`` override lookup (#342, split in #538).

The read half of :func:`~mureo.context.state.set_conversion_action_types`:
given an ad account id, answer "which Meta ``action_type`` rows count as this
account's conversions?" — or ``None`` when the operator declared nothing and
the counters fall back to the built-in generic set.

It lives beside :mod:`mureo.context.platform_accounts` rather than inside
:mod:`mureo.context.state` because it is an account-scoped **setting lookup**,
not part of the document read / write / merge layer. Two things follow from
that and neither belongs in ``state``:

- it resolves which STATE.json to read from the active runtime context, so
  that the override is read from the same file the MCP state tools wrote it
  to even under an agency / alternate ``StateStore``;
- it **never raises**. A conversion analysis that dies because a state file
  is missing or malformed is a worse outcome than one that falls back to the
  built-in set, which is the opposite of the writer contract ``state`` keeps.

The account join itself is not reimplemented here — it is
:func:`~mureo.context.platform_accounts.account_ids_match`, shared with the
duplicate-account write guard so the override's read side and the guard's
write side cannot disagree about what "the same account" means (#536).

Re-exported from :mod:`mureo.context.state`, which is where the analytics and
Meta modules import it from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.context.platform_accounts import account_ids_match
from mureo.context.state_codec import parse_state

if TYPE_CHECKING:
    from pathlib import Path


def _workspace_state_path() -> Path:
    """Resolve the ACTIVE workspace's STATE.json — the same file the MCP state
    tools write to (#342).

    Mirrors the default resolution of
    :func:`mureo.mcp._helpers.resolve_workspace_path`
    (``store.state_path`` → ``store.workspace / STATE.json``) via the runtime
    context, so the conversion override is read from the same file it is
    written to — even under an agency / alternate ``StateStore`` where the
    workspace diverges from the process cwd. ``get_runtime_context`` is
    imported lazily to avoid an import cycle (``runtime_context`` builds on
    ``context``). Any failure falls back to the cwd convention.
    """
    from pathlib import Path as _Path

    try:
        from mureo.core.runtime_context import get_runtime_context

        store = get_runtime_context().state_store
        attr = getattr(store, "state_path", None)
        if attr is not None:
            return _Path(attr)
        workspace = getattr(store, "workspace", None)
        if workspace is not None:
            return _Path(workspace) / "STATE.json"
    except Exception:  # noqa: BLE001 — best-effort; never break a live read.
        pass
    return _Path("STATE.json")


def load_conversion_action_types(
    account_id: str,
    *,
    path: Path | None = None,
    platform: str = "meta_ads",
) -> tuple[str, ...] | None:
    """Read an account's operator conversion override from STATE.json (#342).

    Returns the ``platforms[platform].conversion_action_types`` override when
    it is set AND the entry's ``account_id`` matches ``account_id`` (tolerant
    of the ``act_`` prefix); otherwise ``None`` so the conversion counters fall
    back to the built-in generic set.

    An **unknown** id on either side never matches (#536) — see
    :func:`~mureo.context.platform_accounts.account_ids_match`. An override
    applied to the wrong account silently redefines what counts as a
    conversion for it, so falling back to the built-in set is the safe
    direction.

    Reads the ACTIVE workspace ``STATE.json`` (resolved via the runtime context
    — the same file the MCP state tools write to). **Never raises**: a missing
    / unreadable / malformed file, or an absent platform entry, all yield
    ``None`` so a live analysis is never broken by a state-read failure.
    """
    state_path = path if path is not None else _workspace_state_path()
    try:
        if not state_path.exists():
            return None
        doc = parse_state(state_path.read_text(encoding="utf-8"), strict=False)
    except Exception:  # noqa: BLE001 — never break a live analysis on a bad file.
        # parse_state can raise OSError / ContextFileError / ValueError
        # (JSONDecodeError) AND AttributeError/TypeError on non-object JSON;
        # a best-effort override read must swallow all of them.
        return None
    if doc.platforms is None:
        return None
    entry = doc.platforms.get(platform)
    if entry is None or not entry.conversion_action_types:
        return None
    # Fail closed on an unknown id (#536), via the SHARED join so the
    # override's read side and the duplicate guard's write side cannot
    # disagree about what "the same account" means.
    if not account_ids_match(entry.account_id, account_id):
        return None
    return entry.conversion_action_types


__all__ = [
    "load_conversion_action_types",
]
