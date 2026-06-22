"""`mureo upgrade` — pipx venv-aware bulk upgrade for mureo + its plugins.

Solves the UX gap documented in issue #177: when mureo is installed via
``pipx install mureo`` and third-party packages are added via
``pipx inject`` / ``pip install`` into the same venv (typically through
the ``mureo.providers`` / ``mureo.policy_gates`` entry-point groups),
neither ``pipx upgrade mureo`` (only upgrades the primary) nor
``pipx upgrade <plugin>`` (the plugin has no same-named venv) gives the
operator a single, memorable command for keeping the whole stack fresh.

Design contract
---------------

- The target venv is the one running this CLI, so ``sys.executable`` is
  authoritative — independent of ``cwd``, ``PATH``, and ``PYTHONPATH``.
- ``--all`` discovers same-venv packages via
  ``importlib.metadata.distributions()``, PEP 503 normalises each name,
  and accepts only ``mureo`` exact match or ``mureo-<rest>``. This
  excludes prefix squatters such as ``mureology`` or ``mureoextras``.
- Operator-supplied package specs are validated with a strict PEP 503
  regex (optionally followed by a single ``==<version>`` pin) before
  being passed to pip. ``--``  is then inserted as a sentinel so pip's
  option parser cannot reinterpret a hostile target as a flag.
- ``python -m pip --version`` is probed first. Only the specific failure
  mode "No module named pip" triggers an ``ensurepip --upgrade``
  bootstrap; every other pip failure is surfaced verbatim so we do not
  silently bypass permission / network errors.
- pip's stdout / stderr is streamed straight through to the terminal
  (no capture) so progress and error context reach the operator.
- pip's exit code is propagated as the CLI exit code, enabling
  automation scripts to retry / branch on the result.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from importlib import metadata

import typer

from mureo.pip_env import pip_subprocess_env

upgrade_app = typer.Typer(
    name="upgrade",
    help=(
        "Upgrade mureo and its plugins in the current pipx venv. "
        "Use `--all` to upgrade every installed `mureo-*` together."
    ),
    invoke_without_command=True,
)

# PEP 503: lowercase, separators normalised to '-'.
_NORMALIZE_RE = re.compile(r"[-_.]+")

# Accept either ``name`` or ``name==version``. Names are PEP 503 canonical
# form only (lowercase letters, digits, ``-``), and version uses the
# minimum subset that pip will accept without further interpretation
# (digits, dots, letters, ``+``, ``-``). Anything else — extras, markers,
# URLs, options — is refused at the boundary.
_PACKAGE_SPEC_RE = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:==[A-Za-z0-9][A-Za-z0-9.+\-]*)?$"
)


def _canonicalise(name: str) -> str:
    """Return the PEP 503 canonical form of ``name``."""

    return _NORMALIZE_RE.sub("-", name).lower()


def _is_mureo_package(name: str) -> bool:
    """Return True iff ``name`` is ``mureo`` or ``mureo-<rest>``."""

    canonical = _canonicalise(name)
    return canonical == "mureo" or canonical.startswith("mureo-")


def _validate_spec(spec: str) -> str:
    """Return the canonicalised spec, or raise ``typer.BadParameter``."""

    canonical = spec
    # Lowercase only the name portion; preserve version exactly.
    if "==" in spec:
        name_part, _, version_part = spec.partition("==")
        canonical = f"{_canonicalise(name_part)}=={version_part}"
    else:
        canonical = _canonicalise(spec)
    if not _PACKAGE_SPEC_RE.match(canonical):
        msg = (
            f"Refusing to upgrade {spec!r}: package spec must match "
            "PEP 503 name (optionally `==version`). URLs, extras, markers, "
            "and pip options are not accepted here."
        )
        raise typer.BadParameter(msg)
    return canonical


def _discover_all_mureo_packages() -> list[str]:
    """Return canonical names of every ``mureo`` / ``mureo-*`` dist found.

    Walks ``importlib.metadata.distributions()`` and dedupes after PEP 503
    canonicalisation. The result is deterministic: ``mureo`` first (if
    present), then the rest sorted alphabetically.
    """

    seen: set[str] = set()
    for dist in metadata.distributions():
        try:
            # ``Distribution.name`` (3.10+) routes through ``metadata`` but
            # tolerates a few of the more common dist-info quirks. We still
            # wrap it because a single broken dist-info in the venv must
            # not crash ``mureo upgrade --all``.
            name = dist.name
        except Exception:
            continue
        if not name or not _is_mureo_package(name):
            continue
        seen.add(_canonicalise(name))
    ordered: list[str] = []
    if "mureo" in seen:
        ordered.append("mureo")
        seen.discard("mureo")
    ordered.extend(sorted(seen))
    return ordered


def _pip_is_available() -> tuple[bool, str]:
    """Return ``(ok, stderr)`` for ``python -m pip --version`` on this venv."""

    proc = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        # UTF-8, not the locale codec (cp932 on a Japanese Windows), so
        # capturing pip's output never raises UnicodeDecodeError.
        encoding="utf-8",
        errors="replace",
        # …and force pip to ENCODE its stdout as UTF-8 too (cp932 cannot encode
        # every char pip may emit, crashing the child). See pip_env.
        env=pip_subprocess_env(),
        check=False,
    )
    return proc.returncode == 0, proc.stderr or ""


def _bootstrap_pip() -> int:
    """Run ``ensurepip --upgrade``; return its exit code."""

    proc = subprocess.run(
        [sys.executable, "-m", "ensurepip", "--upgrade"],
        # UTF-8 child stdio so a cp932 console cannot crash the bootstrap on a
        # non-cp932 char in its output. See pip_env.
        env=pip_subprocess_env(),
        check=False,
    )
    return proc.returncode


def _run_pip_install(targets: list[str]) -> int:
    """Invoke ``pip install --upgrade -- <targets>``; return exit code."""

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--",
        *targets,
    ]
    # UTF-8 child stdio so streaming pip output to a cp932 console never crashes
    # pip on a non-cp932 char (e.g. U+00B7 in a package's metadata). See pip_env.
    proc = subprocess.run(cmd, env=pip_subprocess_env(), check=False)
    return proc.returncode


def _resolve_targets(packages: list[str], upgrade_all: bool) -> list[str]:
    """Compute the target list from CLI inputs."""

    if upgrade_all and packages:
        msg = "`--all` cannot be combined with explicit package names."
        raise typer.BadParameter(msg)
    if upgrade_all:
        targets = _discover_all_mureo_packages()
        if "mureo" not in targets:
            # mureo itself must always be upgraded under --all even if its
            # dist metadata is hidden for some reason (e.g. editable installs
            # without dist-info, or a corrupted METADATA file). Belt-and-
            # braces — prepend without disturbing the sorted tail.
            targets = ["mureo", *targets]
        return targets
    if not packages:
        return ["mureo"]
    return [_validate_spec(p) for p in packages]


@upgrade_app.callback(invoke_without_command=True)
def upgrade(
    packages: list[str] | None = typer.Argument(  # noqa: B008
        None,
        metavar="[PACKAGE]...",
        help=(
            "Package(s) to upgrade in the mureo venv. Defaults to `mureo` "
            "itself. Each entry may be a bare name (`mureo-foo`) or a "
            "pinned spec (`mureo-foo==1.2.3`)."
        ),
    ),
    all_: bool = typer.Option(
        False,
        "--all",
        help=(
            "Upgrade mureo and every installed `mureo-<name>` plugin found "
            "in the current venv (sys.executable). Prefix squatters like "
            "`mureology` are not matched."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the pip command that would run; do not invoke pip.",
    ),
) -> None:
    """Upgrade mureo and/or its plugins in the active pipx venv."""

    targets = _resolve_targets(packages or [], all_)

    cmd_preview = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--",
        *targets,
    ]
    if dry_run:
        # shlex.join keeps the preview shell-safe and copy-pasteable —
        # ``sys.executable`` on macOS pipx installs typically contains
        # spaces (e.g. ``Library/Application Support/pipx/...``).
        typer.echo(shlex.join(cmd_preview))
        return

    ok, stderr = _pip_is_available()
    if not ok:
        if "No module named pip" in stderr:
            typer.echo(
                "pip is not available in this venv — bootstrapping with "
                "ensurepip...",
                err=True,
            )
            rc = _bootstrap_pip()
            if rc != 0:
                typer.echo(
                    f"ensurepip failed with exit code {rc}; aborting upgrade.",
                    err=True,
                )
                raise typer.Exit(code=rc)
            # Verify the bootstrap actually wired pip in — broken
            # site-packages / stale ``__pycache__`` can leave the venv in a
            # state where ensurepip succeeds but ``import pip`` still fails.
            ok_after, stderr_after = _pip_is_available()
            if not ok_after:
                typer.echo(
                    "ensurepip succeeded but `python -m pip --version` is "
                    f"still failing:\n{stderr_after}",
                    err=True,
                )
                raise typer.Exit(code=1)
        else:
            typer.echo(f"`python -m pip --version` failed:\n{stderr}", err=True)
            raise typer.Exit(code=1)

    rc = _run_pip_install(targets)
    if rc != 0:
        raise typer.Exit(code=rc)
