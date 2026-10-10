"""Child interpreters the suite measures something in.

Three test modules spawn child interpreters to ask what importing mureo costs or
drags in (``test_mcp_startup_budget.py``, ``test_mcp_tool_validators.py``,
``test_platform_submodule_imports.py``). They need the same three things: the
parent's ``sys.path``, none of the tooling that would make the child measure the
tooling, and — for the cases that have to be run against an installed plugin —
a throwaway distribution on one child's path and nowhere else. Shared from here
so a new way for the harness to leak in has one place to be closed.

What is dropped, and why:

``COV_CORE_*``
    How ``pytest-cov`` starts coverage in a subprocess. Inherited, it puts a
    trace function on the child's imports: measured on the development machine,
    importing the server cost 1.08 s of CPU without it and 1.47 s with it. The
    ubuntu CI job runs ``--cov=mureo``, so leaving it in is the difference
    between measuring the product and measuring the measuring kit.

``COVERAGE_PROCESS_START``
    The same thing by the other route — ``coverage``'s own subprocess hook, used
    by ``coverage run -m pytest``. CI does not run it that way today, which is
    exactly why it would come back silently if it ever did.

``PYTHONDONTWRITEBYTECODE``
    Set in a developer's shell (it is a reasonable thing to set), every child
    recompiles every module it imports, which roughly doubles the import's CPU
    time. The budget would then mean something different on their machine than
    in CI. Dropped so the figure is the warm-bytecode cost everywhere.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Nothing a measurement child does should take minutes; this is a deadlock
#: backstop, not a budget (the budget is asserted on CPU time, in the child).
CHILD_TIMEOUT_SECONDS = 300

#: Environment variables that would make a measurement child measure the
#: harness instead of the product. Prefixes are matched with ``startswith``.
MEASUREMENT_HARNESS_ENV_PREFIXES = ("COV_CORE_",)
MEASUREMENT_HARNESS_ENV_KEYS = ("COVERAGE_PROCESS_START", "PYTHONDONTWRITEBYTECODE")


def measurement_child_env(extra_path: Iterable[str] = ()) -> dict[str, str]:
    """Return the environment for a measurement child.

    ``extra_path`` is prepended to the inherited ``sys.path``, which is how a
    throwaway distribution is "installed" for one child and for nothing else.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in MEASUREMENT_HARNESS_ENV_KEYS
        and not key.startswith(MEASUREMENT_HARNESS_ENV_PREFIXES)
    }
    env["PYTHONPATH"] = os.pathsep.join([*extra_path, *sys.path])
    return env


def run_in_fresh_interpreter(
    code: str, *args: str, extra_path: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a child interpreter sharing this one's ``sys.path``.

    ``extra_path`` goes in front of it, which is how a throwaway distribution
    gets "installed" for one child and for nothing else.
    """
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        env=measurement_child_env(extra_path),
        timeout=CHILD_TIMEOUT_SECONDS,
    )


def install_fake_dist(
    root: pathlib.Path, *, module: str, source: str, group: str, target: str
) -> str:
    """Write a module plus the ``*.dist-info`` that declares its entry point.

    Enough of an installation for ``importlib.metadata.entry_points`` to find
    it, with no pip and no effect on the environment the suite itself runs in:
    the returned directory is only ever put on a child's ``sys.path``.
    """
    (root / f"{module}.py").write_text(source, encoding="utf-8")
    dist = root / f"{module}-0.0.dist-info"
    dist.mkdir(exist_ok=True)
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {module.replace('_', '-')}\nVersion: 0.0\n",
        encoding="utf-8",
    )
    (dist / "entry_points.txt").write_text(
        f"[{group}]\n{module} = {target}\n", encoding="utf-8"
    )
    return str(root)
