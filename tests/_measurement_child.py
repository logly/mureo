"""Environment for a child interpreter the suite measures something in.

Two test modules spawn child interpreters to ask what importing mureo costs or
drags in (``test_mcp_startup_budget.py``, ``test_platform_submodule_imports.py``).
Both need the same thing from the environment: the parent's ``sys.path``, and
none of the tooling that would make the child measure the tooling. Shared from
here so a new way for the harness to leak in has one place to be closed.

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
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

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
