"""Reload ``mureo.mcp.server`` under patches and clean up in the right order.

Not a test module (no ``test_`` prefix, so pytest does not collect it).

``mureo.mcp.server`` builds ``_ALL_TOOLS`` / ``_PLUGIN_NAMES`` /
``_PLUGIN_DISPATCH`` at IMPORT time, so a test that wants a fake plugin
served has to patch discovery and reload the module — and then reload it
again to give the rest of the suite its clean server back.

#760: that restoring reload must happen with the patches ALREADY UNDONE.
``monkeypatch`` cannot express this. It reverts at fixture teardown, i.e.
after the test body and after any fixture that requested it, so both of the
shapes the suite used —

    monkeypatch.setattr(..., fake); reload(); yield; reload()
    monkeypatch.setattr(..., fake); reload(); try: ... finally: reload()

— ran their "restore" while the fake was still installed and re-collected it
into the module. The leak then rode along in every later test module that
imports ``server`` without reloading it; only collection order kept it from
being noticed.

``reloaded_server`` closes the patches first and reloads afterwards, so the
module is clean the moment the ``with`` block ends, with no second reload at
the call site.

Only what ``server`` reads at IMPORT time belongs here — discovery, the
``MUREO_DISABLE_*`` env gates, the Amazon bridge attributes captured when
the bridge is constructed. Runtime-only patches (``plugin_audit._audit_path``,
throttle spies, strategy-reminder context) stay on ``monkeypatch``: undoing
them early would change nothing, and they are not what leaks.
"""

from __future__ import annotations

import contextlib
import importlib
import os
from collections.abc import Callable, Iterator, Mapping
from types import ModuleType
from typing import Any
from unittest import mock

#: ``collect_plugin_tools`` resolves this attribute live at call time, so
#: patching it on the registry module is what a reload picks up.
DISCOVER_TARGET = "mureo.core.providers.registry.discover_providers"


@contextlib.contextmanager
def reloaded_server(
    discover: Callable[..., Any] | None = None,
    *,
    patches: Mapping[str, Any] | None = None,
    env: Mapping[str, str | None] | None = None,
) -> Iterator[ModuleType]:
    """Yield ``mureo.mcp.server`` reloaded under the given patches (#760).

    ``discover`` is installed as :data:`DISCOVER_TARGET`; ``patches`` maps
    any other dotted target to its replacement; ``env`` sets environment
    variables (a ``None`` value deletes one). Every patch is undone BEFORE
    the module is reloaded one last time on exit.
    """
    from mureo.mcp import server

    try:
        with contextlib.ExitStack() as stack:
            if env is not None:
                stack.enter_context(mock.patch.dict(os.environ))
                for name, value in env.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
            if discover is not None:
                stack.enter_context(mock.patch(DISCOVER_TARGET, discover))
            for target, replacement in (patches or {}).items():
                stack.enter_context(mock.patch(target, replacement))
            yield importlib.reload(server)
    finally:
        importlib.reload(server)
