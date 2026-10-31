"""Subprocess wrapper for installing an official MCP provider.

``run_install`` invokes the catalog-defined ``install_argv`` via
``subprocess.run`` in list-form, with no ``shell=True`` and no ``env=``
kwarg (parent environment is inherited so credential env vars never get
re-serialized into call args that might be logged).

The executable is resolved on ``PATH`` first and then in the usual tool
directories (``/opt/homebrew/bin``, ``/usr/local/bin``, ``~/.local/bin``),
since a daemon started by launchd or systemd runs with a minimal ``PATH``
(#966). One found nowhere is reported as a result naming it rather than
raised, so callers can tell the operator which tool to install.

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

import os
import shutil
import subprocess  # module-level so tests can patch installer.subprocess.run
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.providers.catalog import ProviderSpec

# Executables permitted as ``install_argv[0]``. Kept tight on purpose.
_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({"pipx", "npm"})

#: Where a GUI- or supervisor-launched daemon's PATH usually lacks the
#: package managers the catalog spawns, in the order they are tried. They are
#: consulted only when PATH has no match, and they are the user's own tool
#: directories (Homebrew, the local prefix, pipx's ``~/.local/bin``).
_FALLBACK_BIN_DIRS: tuple[str, ...] = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "~/.local/bin",
)

#: ``InstallResult.returncode`` when ``argv[0]`` resolves nowhere; the
#: conventional shell exit status for "command not found".
EXECUTABLE_MISSING_RETURNCODE = 127


@dataclass(frozen=True)
class InstallResult:
    """Outcome of a (possibly dry-run) install attempt.

    ``argv`` is preserved even in dry-run mode so callers can surface the
    planned command without re-deriving it from the spec.
    ``missing_executable`` names ``argv[0]`` when it was found nowhere and no
    subprocess ran; it is ``None`` otherwise, so a package manager that ran
    and exited 127 is not mistaken for a missing one.
    """

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]
    missing_executable: str | None = None


def resolve_executable(name: str) -> str | None:
    """Absolute path of ``name`` on PATH, else in the usual tool directories."""
    found = shutil.which(name)
    if found:
        return found
    fallback = os.pathsep.join(str(Path(d).expanduser()) for d in _FALLBACK_BIN_DIRS)
    return shutil.which(name, path=fallback)


def _spawn(argv: list[str]) -> InstallResult:
    """Run the allow-listed ``argv`` from its resolved executable path.

    The result keeps ``argv`` as planned (the catalog's bare executable
    name), whichever directory the executable was found in.
    """
    resolved = resolve_executable(argv[0])
    if resolved is None:
        return InstallResult(
            returncode=EXECUTABLE_MISSING_RETURNCODE,
            stdout="",
            stderr=f"{argv[0]} not found on PATH ({os.environ.get('PATH', '')})",
            argv=argv,
            missing_executable=argv[0],
        )
    completed = subprocess.run(  # noqa: S603 — argv is list-form, allow-listed
        [resolved, *argv[1:]],
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


def run_install(spec: ProviderSpec, *, dry_run: bool = False) -> InstallResult:
    """Install ``spec`` via its declared package manager.

    Args:
        spec: catalog entry to install.
        dry_run: when True, do not invoke subprocess; return an
            ``InstallResult`` with ``returncode=0`` and the planned argv.

    Returns:
        ``InstallResult`` carrying the subprocess outcome (or a synthetic
        success when ``dry_run=True`` or when the spec is ``hosted_http``).
        ``argv`` is the catalog argv even though the subprocess is spawned
        from the executable's resolved path. When ``argv[0]`` is found
        neither on ``PATH`` nor in the usual tool directories, no
        subprocess runs and ``missing_executable`` names it (``returncode``
        is ``EXECUTABLE_MISSING_RETURNCODE`` and ``stderr`` says so, for the
        CLI); a spawned package manager that exits 127 leaves it ``None``.

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
    return _spawn(argv)
