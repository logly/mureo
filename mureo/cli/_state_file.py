"""The ``--state-file`` option every STATE.json command shares.

``mureo rollback`` inspects STATE.json and ``mureo repair`` rewrites it, and
both have to point at the same file by default or an operator would inspect
one document and repair another. The option text and the workspace lookup
therefore live here once rather than being copied per command.
"""

from __future__ import annotations

from pathlib import Path

import typer

STATE_FILE_OPTION = typer.Option(
    None,
    "--state-file",
    help=(
        "Path to the STATE.json file to work on. Defaults to the active "
        "workspace's STATE.json — CWD-relative in the default file-backed "
        "configuration, or whatever location an installed alternate "
        "backend exposes via the mureo.runtime_context_factory entry "
        "point."
    ),
)
"""Shared ``--state-file`` declaration.

A module-level constant because a ``typer.Option(...)`` call written straight
into a signature default is a function call in a default argument (ruff B008).
The object carries no per-command state — Typer builds a fresh click parameter
from it for each command that uses it.
"""


def state_file_for_store(store: object) -> Path | None:
    """Where ``store`` keeps its STATE.json, or ``None`` if it will not say.

    Duck-typed on the two attributes the filesystem store (and the per-client
    stores an Agency backend hands back) expose: ``state_path`` wins, else
    ``<workspace>/STATE.json``. A store advertising neither has no file for a
    file-level command to work on — ``None`` says so rather than guessing at
    the process's CWD, which would point a repair at the wrong document.
    """
    attr = getattr(store, "state_path", None)
    if attr is not None:
        return Path(attr).resolve()
    workspace = getattr(store, "workspace", None)
    if workspace is None:
        return None
    return Path(workspace) / "STATE.json"


def resolve_default_state_file() -> Path:
    """Return the workspace-derived default for ``--state-file``.

    Mirrors the workspace lookup the MCP handlers (rollback, analysis,
    mureo_context) perform: the file lives at the active StateStore's
    ``state_path`` if exposed, otherwise ``<workspace>/STATE.json``
    where workspace falls back to ``Path.cwd()``.

    Lazy import keeps the CLI modules import-time-free of the
    runtime_context resolver, so Typer's startup remains cheap.
    """
    from mureo.core.runtime_context import get_runtime_context

    store = get_runtime_context().state_store
    return state_file_for_store(store) or Path.cwd() / "STATE.json"


__all__ = [
    "STATE_FILE_OPTION",
    "resolve_default_state_file",
    "state_file_for_store",
]
