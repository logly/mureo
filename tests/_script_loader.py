"""Load or run a check from ``scripts/``.

Not a test module (no ``test_`` prefix, so pytest does not collect it).

``scripts/`` is not a package: each check runs as ``python scripts/<name>.py``,
which puts ``scripts/`` on ``sys.path``, so a check imports its shared
helpers (``shipped_text``) by plain module name. A test loads the check by
path instead, so the same directory has to be on ``sys.path`` before the
module executes.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# Set by git for a hook; a child that inherits them runs ``git`` against the
# repository the hook fired in, not the one the test points it at.
_GIT_LOCATION_VARS = frozenset({"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"})


def load_script(name: str) -> ModuleType:
    """Execute ``scripts/<name>.py`` and register it as ``_<name>``."""
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    module_name = f"_{name}"
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def clean_env(**extra: str) -> dict[str, str]:
    """Return the inherited environment without the git location variables.

    A ``git`` or check child started with it acts on the repository under
    its ``cwd`` or ``--root``, never on the one a surrounding hook fired in.
    ``extra`` is applied on top.
    """
    env = {
        key: value for key, value in os.environ.items() if key not in _GIT_LOCATION_VARS
    }
    env.update(extra)
    return env


def run_script(
    name: str, args: list[str], cwd: Path | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run ``scripts/<name>.py`` and decode its output as UTF-8 on any locale.

    ``env`` is merged over :func:`clean_env`, so a run from inside a git hook
    still checks the repository under ``--root`` (or the working tree) and
    never the outer one.
    """
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / f"{name}.py"), *args],
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=clean_env(**{"PYTHONIOENCODING": "utf-8", **env}),
        check=False,
    )
