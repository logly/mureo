"""Subprocess wrapper for installing an official MCP provider.

``run_install`` invokes the catalog-defined ``install_argv`` via
``subprocess.run`` in list-form, with no ``shell=True`` and no ``env=``
kwarg (parent environment is inherited so credential env vars never get
re-serialized into call args that might be logged).

A hard executable allow-list (``pipx``, ``npm``) is enforced before any
subprocess call as defense-in-depth against catalog tampering — even though
the Phase 1 catalog is source-baked, this prevents a future hostile entry
from running arbitrary commands.

Hosted entries (``install_kind="hosted_http"``) take a separate, subprocess-
free path: ``run_install`` returns a synthetic success result so the caller
can proceed straight to ``mcpServers`` registration. No allow-list check
runs for hosted entries because no executable is invoked.
"""

from __future__ import annotations

import subprocess  # module-level so tests can patch installer.subprocess.run
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.providers.catalog import ProviderSpec

# Executables permitted as ``install_argv[0]``. Kept tight on purpose.
_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({"pipx", "npm"})


@dataclass(frozen=True)
class InstallResult:
    """Outcome of a (possibly dry-run) install attempt.

    ``argv`` is preserved even in dry-run mode so callers can surface the
    planned command without re-deriving it from the spec.
    """

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


def run_install(spec: ProviderSpec, *, dry_run: bool = False) -> InstallResult:
    """Install ``spec`` via its declared package manager.

    Args:
        spec: catalog entry to install.
        dry_run: when True, do not invoke subprocess; return an
            ``InstallResult`` with ``returncode=0`` and the planned argv.

    Returns:
        ``InstallResult`` carrying the subprocess outcome (or a synthetic
        success when ``dry_run=True`` or when the spec is ``hosted_http``).

    Raises:
        ValueError: when ``spec.install_argv`` is empty for a non-hosted
            spec, or when ``spec.install_argv[0]`` is not in the allow-list.
            Raised before any subprocess call.
    """
    # Hosted endpoints have no local install step — short-circuit before
    # touching the allow-list or subprocess. Both dry-run and real invocation
    # produce the same result: no work to do.
    if spec.install_kind == "hosted_http":
        return InstallResult(
            returncode=0,
            stdout="No local install needed (hosted endpoint).",
            stderr="",
            argv=[],
        )

    argv = list(spec.install_argv)
    if not argv:
        raise ValueError(f"empty install_argv for provider {spec.id!r}")
    if argv[0] not in _ALLOWED_EXECUTABLES:
        raise ValueError(
            f"refusing to invoke disallowed executable {argv[0]!r} "
            f"for provider {spec.id!r}; "
            f"allow-list is {sorted(_ALLOWED_EXECUTABLES)}"
        )

    if dry_run:
        return InstallResult(returncode=0, stdout="", stderr="", argv=argv)

    completed = subprocess.run(  # noqa: S603 — argv is list-form, allow-listed
        argv,
        check=False,
        capture_output=True,
        text=True,
    )
    return InstallResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        argv=argv,
    )
