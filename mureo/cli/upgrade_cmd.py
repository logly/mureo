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

import json
import re
import shlex
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

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


def _refresh_deployed_skills() -> None:
    """Re-copy the bundled skills into ``~/.claude/skills`` after an upgrade.

    A new mureo version ships new skill content, but the deployed copies under
    ``~/.claude/skills`` are only written by the setup wizard — an upgrade alone
    leaves them on the OLD format. Re-deploy here so ``mureo upgrade`` reliably
    refreshes the skills too. Only refresh when the user already has a skills
    directory, so an upgrade never force-installs skills someone deliberately
    removed. Best-effort: a failure is reported but never fails the upgrade.
    """
    dest = Path.home() / ".claude" / "skills"
    if not dest.exists():
        return
    try:
        from mureo.cli.setup_cmd import install_skills

        count, where = install_skills()
        typer.echo(f"Refreshed {count} skills at {where}.")
    except Exception as exc:  # noqa: BLE001 — refresh is best-effort
        typer.echo(
            f"Skill refresh skipped ({type(exc).__name__}); "
            "re-run `mureo configure` to update skills.",
            err=True,
        )


def _refresh_native_skills() -> None:
    """Re-deploy plugin ``mureo.native_skills`` after an upgrade (#439).

    A plugin upgrade may ship new/changed native slash skills, but the
    deployed copies under ``~/.claude/skills`` / ``~/.codex/skills`` are only
    written at setup time — an upgrade alone leaves them stale. Re-deploy into
    whichever host skill dir already exists, so an upgrade never force-creates
    one the operator does not use. Symmetric across both hosts (unlike the
    bundle refresh, which only targets Claude today). Best-effort: a failure is
    reported but never fails the upgrade.
    """
    from mureo.cli.native_skills import install_native_skills

    for dest in (
        Path.home() / ".claude" / "skills",
        Path.home() / ".codex" / "skills",
    ):
        if not dest.exists():
            continue
        try:
            count, where = install_native_skills(dest)
            if count:
                typer.echo(f"Refreshed {count} plugin native skills at {where}.")
        except Exception as exc:  # noqa: BLE001 — refresh is best-effort
            typer.echo(
                f"Plugin native-skill refresh skipped for {dest} "
                f"({type(exc).__name__}).",
                err=True,
            )


def _restart_managed_service() -> None:
    """Restart the always-on configure daemon so it loads the new code.

    A long-running ``mureo service`` daemon keeps the pre-upgrade code in memory
    until restarted — the exact reason an upgrade can appear to have "no effect"
    (stale tools, old static assets). Restart it when one is installed; a no-op
    otherwise. Best-effort: never fails the upgrade.
    """
    try:
        from mureo.cli.service_cmd import _resolve_backend
        from mureo.web.service import SERVICE_PORT

        backend = _resolve_backend()
    except Exception:  # noqa: BLE001 — unsupported platform / no backend; nothing to do
        return

    # Resolution succeeded → this platform HAS a service backend. A failure
    # past here is a genuine error worth a one-line hint (not a silent no-op),
    # but must still never fail the upgrade.
    try:
        if not backend.status(port=SERVICE_PORT).installed:
            return
        result = backend.restart(port=SERVICE_PORT)
    except Exception as exc:  # noqa: BLE001 — never fail the upgrade
        typer.echo(
            f"Could not auto-restart the mureo service ({type(exc).__name__}); "
            "run `mureo service restart` to finish applying the upgrade.",
            err=True,
        )
        return
    if result.ok:
        typer.echo("Restarted the mureo service so it runs the new version.")
    else:
        typer.echo(
            f"Could not auto-restart the mureo service: {result.message}. "
            "Run `mureo service restart` to finish applying the upgrade.",
            err=True,
        )


def _has_installed_guard(config: Path) -> bool:
    """True when ``config`` actually carries a tagged guard hook entry.

    Deliberately stricter than a whole-file substring search: the tag
    literal appearing anywhere else (a comment field, an unrelated key)
    must not count as "installed", because the refresh below would then
    re-append a guard the user deliberately removed. Checks the nested
    ``hooks.PreToolUse`` list (Claude settings.json / current Codex
    hooks.json) and the legacy Codex top-level ``PreToolUse`` list.
    Unreadable or malformed files count as "not installed" — the refresh
    then skips them instead of poking an installer at a file it would
    refuse anyway.
    """
    from mureo.credential_guard import is_guard_entry

    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    candidates: list[Any] = []
    hooks = data.get("hooks")
    if isinstance(hooks, dict) and isinstance(hooks.get("PreToolUse"), list):
        candidates.extend(hooks["PreToolUse"])
    if isinstance(data.get("PreToolUse"), list):
        candidates.extend(data["PreToolUse"])
    return any(is_guard_entry(entry) for entry in candidates)


def _refresh_credential_guard() -> None:
    """Upgrade previously installed credential-guard hooks after an upgrade.

    #393 shipped guard hooks whose ``sys.exit(1)`` never blocked anything.
    The installers are upgrade-aware, but they only run from setup — an
    upgrade alone leaves the stale hooks in ``~/.claude/settings.json`` /
    ``~/.codex/hooks.json`` forever (#398). Refresh here, but only on
    surfaces where a tagged hook already exists, so an upgrade never
    (re)installs the guard someone deliberately removed. Best-effort: a
    failure is reported but never fails the upgrade.
    """
    from mureo.auth_setup import install_credential_guard
    from mureo.cli.setup_codex import install_codex_credential_guard

    surfaces: list[tuple[Path, Callable[[], Path | None]]] = [
        (Path.home() / ".claude" / "settings.json", install_credential_guard),
        (Path.home() / ".codex" / "hooks.json", install_codex_credential_guard),
    ]
    for config, installer in surfaces:
        try:
            if not _has_installed_guard(config):
                continue
            if installer() is not None:
                typer.echo(f"Refreshed credential-guard hooks at {config}.")
        except Exception as exc:  # noqa: BLE001 — refresh is best-effort
            typer.echo(
                f"Credential-guard refresh skipped for {config} "
                f"({type(exc).__name__}); re-run `mureo configure` to update it.",
                err=True,
            )


def _post_upgrade_refresh() -> None:
    """Make a successful upgrade actually take effect.

    The deployed skills (bundle + plugin native), the installed
    credential-guard hooks, and any always-on daemon otherwise keep the
    pre-upgrade version: skills are not re-copied, stale hooks stay in the host
    configs, and the daemon holds old code in memory. Refresh all of them so
    ``mureo upgrade`` is a single, reliable step.
    """
    _refresh_deployed_skills()
    _refresh_native_skills()
    _refresh_credential_guard()
    _restart_managed_service()


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
    no_refresh: bool = typer.Option(
        False,
        "--no-refresh",
        help=(
            "Skip the post-upgrade refresh (re-deploying skills, upgrading "
            "installed credential-guard hooks, and restarting the always-on "
            "service). By default a successful upgrade refreshes all three "
            "so the new version actually takes effect."
        ),
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

    # The upgrade landed. Make it actually take effect: refresh the deployed
    # skills (otherwise still the old format) and restart any always-on daemon
    # (otherwise still running old code). Best-effort; never fails the upgrade.
    if not no_refresh:
        _post_upgrade_refresh()
