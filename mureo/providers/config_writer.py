"""Register / remove official MCP providers with Claude Code.

Primary path delegates to the official ``claude mcp`` CLI (user scope);
the no-CLI fallback atomically edits ``~/.claude.json`` directly. NOTE:
Claude Code reads user-scope MCP servers from ``~/.claude.json`` — NOT
``~/.claude/settings.json`` (that file is hooks/permissions/env only).

Each public function:
- defaults the fallback target to ``Path.home() / ".claude.json"``
  computed *inside* the function so monkeypatched ``Path.home`` is honored
  by tests and by future re-homing of the user config directory;
- writes via a same-directory unpredictable ``tempfile``-allocated file
  followed by ``os.fsync`` + ``os.replace`` so a crash mid-write cannot
  corrupt the existing file and data is durably on disk before the rename;
- preserves unrelated top-level keys (``permissions`` etc.) and unrelated
  ``mcpServers`` entries (notably the native ``mureo`` block).

A separate writer (rather than reusing ``mureo.auth_setup.install_mcp_config``)
is intentional — the four existing ``setup`` commands continue to use the
older non-atomic writer; refactoring it is out of scope for Phase 1.

The generic atomic-JSON machinery this module used to own now lives in
:mod:`mureo.core.atomic_json` (#500) — new code writing any JSON config
file must import it from there, not from here.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess  # noqa: S404 - fixed argv, shell=False (claude mcp ...)
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from mureo.core.atomic_json import (
    ConfigWriteError,
    atomic_write_json,
    load_existing_json,
)
from mureo.fsutil import file_lock

HostedConnectivity = Literal["connected", "not_connected", "unknown"]

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.providers.catalog import ProviderSpec

logger = logging.getLogger(__name__)


# DEPRECATED aliases — the atomic-JSON trio moved to
# :mod:`mureo.core.atomic_json` (#500). New code imports it from there;
# these names preserve IMPORT compatibility only (``from
# mureo.providers.config_writer import _load_existing`` still resolves to
# the same object). They are NOT a monkeypatch seam: this module's own
# functions call ``load_existing_json`` / ``atomic_write_json`` directly,
# so patching these aliases has no effect on behaviour — patch
# ``mureo.core.atomic_json`` instead. ``ConfigWriteError`` is re-exported
# by the import above.
_load_existing = load_existing_json
_atomic_write_json = atomic_write_json


@dataclass(frozen=True)
class AddResult:
    """Outcome of an ``add_provider_to_claude_settings`` call."""

    changed: bool


@dataclass(frozen=True)
class RemoveResult:
    """Outcome of a ``remove_provider_from_claude_settings`` call."""

    changed: bool


def _default_settings_path() -> Path:
    """File ``claude mcp ... --scope user`` persists to (``~/.claude.json``).

    Claude Code reads *user-scope* MCP servers from the root-level
    ``mcpServers`` object of ``~/.claude.json`` — NOT from
    ``~/.claude/settings.json`` (that file is hooks/permissions/env only
    and is never consulted for MCP discovery). This is the no-CLI
    fallback target; the primary path delegates to the ``claude`` CLI.
    """
    return Path.home() / ".claude.json"


def _settings_lock_path(settings_path: Path) -> Path:
    """Sidecar lock file for ``settings_path`` (``<name>.lock``).

    Mirrors ``mureo.context.state._state_lock_path``. Serialises the
    read-modify-write of ``~/.claude.json`` across mureo processes so two
    concurrent provider add/remove calls cannot last-writer-wins away each
    other's ``mcpServers`` edit. Advisory (a non-mureo writer such as Claude
    Code itself is not obliged to honor it), but it protects mureo's own
    fallback file-mode writers.
    """
    return settings_path.with_name(settings_path.name + ".lock")


_VALID_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _check_provider_id(provider_id: str) -> None:
    """Reject ids that could be parsed as a ``claude`` CLI option.

    Defense-in-depth: every production caller already allow-lists
    ``provider_id`` against the source-baked catalog, but guarding here
    eliminates the argv-injection class (a leading ``-`` would be read as
    an option flag — ``shell=False`` does not prevent that) for any
    future caller that forgets the catalog lookup.
    """
    if not _VALID_PROVIDER_ID.match(provider_id):
        raise ConfigWriteError(f"invalid provider id: {provider_id!r}")


def _claude_bin() -> str | None:
    """Return the ``claude`` CLI path, or ``None`` if not on PATH."""
    return shutil.which("claude")


def _claude_mcp(
    *args: str, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``claude mcp <args>`` (fixed argv, shell=False) and return it.

    ``timeout`` (seconds) is forwarded to ``subprocess.run``; pass it for
    subcommands that probe the network (``mcp list`` health-checks every
    endpoint) so an unreachable server can't hang an interactive caller.
    On expiry ``subprocess.run`` raises ``subprocess.TimeoutExpired`` —
    callers that promise not to raise must catch it.
    """
    claude_bin = _claude_bin()
    assert claude_bin is not None  # callers check first  # noqa: S101
    return subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [claude_bin, "mcp", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _redact(text: str, secrets: Mapping[str, str] | None) -> str:
    """Replace every known secret value in ``text`` with ``***``.

    Used to scrub CLI stderr before it lands in a ``ConfigWriteError``
    that callers log. Longest values first so a short value that is a
    substring of a longer one cannot leave a partial leak.
    """
    if not secrets:
        return text
    for value in sorted((v for v in secrets.values() if v), key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def _build_desired_config(
    spec: ProviderSpec,
    extra_env: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Normalise a spec's block to the on-disk shape, with optional env.

    JSON round-trip (tuple → list, same as the on-disk read), add the
    required ``type`` for stdio entries, then merge ``extra_env`` into
    the block's ``env``. The provider block is mureo-managed, so our
    keys win over any catalog-supplied env of the same name; non-empty
    ``extra_env`` is what makes an official MCP — which reads ONLY env
    vars, never mureo's credentials.json — actually usable once added.
    """
    desired_config: dict[str, Any] = json.loads(
        json.dumps(dict(spec.mcp_server_config), ensure_ascii=False)
    )
    # Claude Code's ``mcp add-json`` schema (and the ~/.claude.json
    # user-scope entry shape) REQUIRE an explicit transport ``type``. The
    # catalog stores stdio entries as ``{"command","args"}`` without it
    # (hosted entries already carry ``"type":"http"``); a missing ``type``
    # makes ``add-json`` silently reject the entry — it builds but never
    # registers. Default command-based configs to ``stdio``.
    if "type" not in desired_config and "command" in desired_config:
        desired_config = {"type": "stdio", **desired_config}
    if extra_env:
        merged_env = {**desired_config.get("env", {}), **dict(extra_env)}
        desired_config = {**desired_config, "env": merged_env}
    return desired_config


def add_provider_to_claude_settings(
    spec: ProviderSpec,
    *,
    settings_path: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> AddResult:
    """Register ``spec`` with Claude Code (user scope) idempotently.

    When ``settings_path`` is omitted and the ``claude`` CLI is on PATH,
    delegates to ``claude mcp add-json <id> '<json>' --scope user`` so
    Claude Code mutates its own live ``~/.claude.json`` safely (a stale
    entry is removed first — self-heal). Otherwise atomically merges into
    the root ``mcpServers`` of ``~/.claude.json`` (or ``settings_path``).

    Args:
        spec: catalog entry to register.
        settings_path: override target file (forces file mode, skips the
            CLI). Defaults to ``~/.claude.json``.
        extra_env: credential env vars to write into the provider block's
            ``env`` (e.g. ``GOOGLE_ADS_*`` resolved from credentials.json).
            Empty/omitted keeps the pre-fix bare-block shape. Flows into
            both the CLI ``add-json`` payload and the file-mode merge.

    Returns:
        ``AddResult(changed=True)`` when registration was (re)written.
        File mode returns ``changed=False`` on a byte-for-byte idempotent
        re-add. CLI mode (``claude`` on PATH) always does remove+add and
        therefore always reports ``changed=True`` — callers must not rely
        on ``changed`` to suppress work in that path.

    Raises:
        ConfigWriteError: target file is malformed JSON, or the
            ``claude`` CLI is present but ``add-json`` failed.
    """
    desired_config = _build_desired_config(spec, extra_env)

    if settings_path is None and _claude_bin() is not None:
        _check_provider_id(spec.id)
        _claude_mcp("remove", spec.id, "--scope", "user")  # best-effort
        completed = _claude_mcp(
            "add-json",
            spec.id,
            json.dumps(desired_config),
            "--scope",
            "user",
        )
        if completed.returncode != 0:
            # The add-json payload now carries credential env values
            # (GOOGLE_ADS_*). A rejecting CLI commonly echoes the
            # offending input back on stderr, and this message is logged
            # by callers — redact every known secret value before it can
            # reach a log line (security boundary: secrets never logged).
            safe_stderr = _redact(completed.stderr.strip(), extra_env)
            raise ConfigWriteError(
                f"claude mcp add-json {spec.id} failed "
                f"(rc={completed.returncode}): {safe_stderr}"
            )
        logger.info("provider %s registered (user scope) via claude CLI", spec.id)
        return AddResult(changed=True)

    target = settings_path or _default_settings_path()
    # Hold the cross-process lock across the read-modify-write so a concurrent
    # add/remove cannot clobber this edit (the atomic replace only makes the
    # write itself atomic, not the surrounding read + write).
    target.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_settings_lock_path(target)):
        existing = load_existing_json(target)

        mcp_servers_raw = existing.get("mcpServers")
        if mcp_servers_raw is None:
            mcp_servers: dict[str, Any] = {}
        elif isinstance(mcp_servers_raw, dict):
            mcp_servers = mcp_servers_raw
        else:
            raise ConfigWriteError(
                f"existing settings at {target} has a non-object 'mcpServers' "
                f"value (got {type(mcp_servers_raw).__name__}); refusing to "
                f"overwrite to protect user data."
            )

        # ``desired_config`` was normalized through a JSON round-trip above so
        # the comparison key matches what would actually be written to disk:
        # ``_freeze_config`` converts nested lists to tuples for catalog
        # immutability, but JSON has no tuple type — the on-disk shape (and
        # the value re-read by ``load_existing_json``) is always list-form. A
        # direct ``current == dict(spec.mcp_server_config)`` would compare
        # ``[..] != (..)`` and report ``changed=True`` on every re-add,
        # breaking the idempotency contract documented above.
        current = mcp_servers.get(spec.id)
        if current == desired_config:
            return AddResult(changed=False)

        mcp_servers[spec.id] = desired_config
        existing["mcpServers"] = mcp_servers

        atomic_write_json(existing, target)
    return AddResult(changed=True)


def remove_provider_from_claude_settings(
    provider_id: str,
    *,
    settings_path: Path | None = None,
) -> RemoveResult:
    """Remove ``mcpServers[provider_id]`` from ``settings.json``.

    Idempotent: if the key is absent, returns ``RemoveResult(changed=False)``
    without rewriting anything. When ``settings_path`` is omitted and the
    ``claude`` CLI is on PATH, delegates to
    ``claude mcp remove <id> --scope user``.

    Raises:
        ConfigWriteError: target file is malformed JSON, or the
            ``claude`` CLI is present but the remove command failed.
    """
    if settings_path is None and _claude_bin() is not None:
        _check_provider_id(provider_id)
        if _claude_mcp("get", provider_id).returncode != 0:
            return RemoveResult(changed=False)  # not registered
        removed = _claude_mcp("remove", provider_id, "--scope", "user")
        if removed.returncode != 0:
            raise ConfigWriteError(
                f"claude mcp remove {provider_id} failed "
                f"(rc={removed.returncode}): {removed.stderr.strip()}"
            )
        logger.info(
            "provider %s unregistered (user scope) via claude CLI",
            provider_id,
        )
        return RemoveResult(changed=True)

    target = settings_path or _default_settings_path()
    if not target.exists():
        return RemoveResult(changed=False)

    # Same cross-process lock as the add path so the read-modify-write is
    # serialised against a concurrent provider edit.
    with file_lock(_settings_lock_path(target)):
        existing = load_existing_json(target)
        mcp_servers = existing.get("mcpServers")
        if not isinstance(mcp_servers, dict) or provider_id not in mcp_servers:
            return RemoveResult(changed=False)

        del mcp_servers[provider_id]
        existing["mcpServers"] = mcp_servers
        atomic_write_json(existing, target)
    return RemoveResult(changed=True)


def hosted_provider_connectivity(spec: ProviderSpec) -> HostedConnectivity:
    """Tri-state connectivity of a ``hosted_http`` provider's connector.

    A ``hosted_http`` provider (Meta) can only be wired through Claude's
    account-level Connectors, authorised by a one-time browser OAuth.
    The only programmatic signal is ``claude mcp list`` showing the
    endpoint URL on a line marked connected (``✓``/``Connected``) and
    NOT ``Needs authentication`` / ``Failed``.

    Returns (never raises):

    - ``"connected"`` — the URL is listed in a connected state.
    - ``"not_connected"`` — verification *ran* and the connector is
      genuinely absent / needs-auth / failed (spec has no URL, or the
      URL is not in a connected line). The user must still finish the
      browser setup.
    - ``"unknown"`` — verification could NOT run, so connectivity is
      undetermined: the Claude **Code** CLI is absent (e.g. a
      Desktop-only machine, or it is not on the ``mureo configure``
      process PATH), ``claude mcp list`` timed out, or it exited
      non-zero. This is NOT "not connected" — callers must not tell the
      user their browser login failed; they should offer an explicit
      "I verified it" path instead.

    All three states keep the no-strand guarantee: only ``"connected"``
    (or an explicit user affirmation, handled by the caller) may flip
    ``MUREO_DISABLE_<platform>``.
    """
    url = spec.mcp_server_config.get("url")
    if not url:
        return "not_connected"  # nothing to connect — genuinely absent
    if _claude_bin() is None:
        return "unknown"  # no Claude Code CLI here ⇒ cannot verify
    try:
        # `claude mcp list` health-checks every endpoint over the
        # network; cap it so an unreachable server can't hang the
        # interactive caller (CLI / confirm request).
        completed = _claude_mcp("list", timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"  # could not determine — not "not connected"
    if completed.returncode != 0:
        return "unknown"
    # NOTE: substring match on the endpoint URL. The two hosted providers
    # (Meta `mcp.facebook.com/ads`, TikTok
    # `business-api.tiktok.com/open_mcp/tt-ads-mcp-layer`) share no prefix,
    # so cross-provider collisions are not a concern; revisit if a future
    # hosted endpoint shares a prefix. Edge case: a user who manually
    # registers TikTok's alternate `tt-ads-mcp-flat` endpoint (not the
    # layered one mureo points at) will not match here and reads as
    # not_connected — mureo only guides users to the layered endpoint.
    for line in completed.stdout.splitlines():
        if url not in line:
            continue
        if re.search(r"needs authentication|failed", line, re.IGNORECASE):
            return "not_connected"
        # ``\bconnected\b`` so "Disconnected"/"Reconnecting" don't match;
        # "Failed to connect" is already excluded above.
        if re.search(r"\bconnected\b", line, re.IGNORECASE):
            return "connected"
        return "not_connected"
    return "not_connected"  # CLI ran, list ok, endpoint simply absent


def is_hosted_provider_connected(spec: ProviderSpec) -> bool:
    """Boolean view of :func:`hosted_provider_connectivity`.

    ``True`` only for ``"connected"``. ``"not_connected"`` and
    ``"unknown"`` both map to ``False`` so existing guards
    (``set_native_preference`` / ``hosted_provider_status`` /
    ``providers confirm`` CLI) keep their conservative no-strand
    behaviour unchanged. Callers that must distinguish "can't verify"
    from "verified-absent" call ``hosted_provider_connectivity``
    directly.
    """
    return hosted_provider_connectivity(spec) == "connected"


def is_provider_installed(
    provider_id: str,
    *,
    settings_path: Path | None = None,
) -> bool:
    """Return True iff ``provider_id`` is registered in ``settings.json``.

    Returns False (does not raise) when the file is missing or malformed,
    so ``mureo providers list`` keeps working in degraded environments.
    When ``settings_path`` is omitted and the ``claude`` CLI is on PATH,
    probes via ``claude mcp get <id>`` (registered ⇔ rc 0).
    """
    if settings_path is None and _claude_bin() is not None:
        # This function never raises (degraded-env contract): an
        # injection-shaped id is simply "not installed".
        if not _VALID_PROVIDER_ID.match(provider_id):
            return False
        return _claude_mcp("get", provider_id).returncode == 0

    target = settings_path or _default_settings_path()
    if not target.exists():
        return False
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(loaded, dict):
        return False
    mcp_servers = loaded.get("mcpServers")
    return isinstance(mcp_servers, dict) and provider_id in mcp_servers
