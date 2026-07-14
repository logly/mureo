"""Collect installation status across hosts, providers, and basic parts.

Pure read-only — nothing in this module mutates settings files or
credentials. The configure UI surfaces this snapshot on every
``GET /api/status`` poll and uses it to render ✓/✗ pills.

Security boundary: ``credentials.json`` is inspected both for the
**presence** of platform sections and, for the credentials panel,
for individual field values. Values are surfaced either fully masked
(for secret-named vars) or in full (for path-shaped vars such as
``GOOGLE_APPLICATION_CREDENTIALS``). The masked preview only ever
leaks the last 4 characters of a secret, matching the convention
used by AWS / Stripe surface UIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.web._helpers import read_json_safe
from mureo.web.env_var_writer import allowed_env_var_names, get_env_var_target
from mureo.web.host_paths import HostPaths, get_host_paths
from mureo.web.setup_state import SetupParts

_HOST_DESKTOP = "claude-desktop"
_HOST_CODEX = "codex"

if TYPE_CHECKING:
    from pathlib import Path

OFFICIAL_PROVIDER_IDS: tuple[str, ...] = (
    "google-ads-official",
    "meta-ads-official",
    "ga4-official",
    "tiktok-ads-official",
)

MUREO_NATIVE_ID = "mureo"

# Env var names matching this pattern get masked previews — only the
# last 4 chars survive, prefixed with bullets. Non-matching names
# (e.g. GOOGLE_APPLICATION_CREDENTIALS, META_ADS_ACCOUNT_ID) expose
# their full value because they are either filesystem paths or
# non-secret identifiers the operator may want to copy verbatim.
_SECRET_NAME_RE = re.compile(r"(TOKEN|SECRET|KEY|PASSWORD)", re.IGNORECASE)

# Minimum value length below which we mask the entire value to avoid
# leaking a short secret whose last-4-chars effectively *is* the
# secret. Mirrors AWS console's "shorter than threshold → all bullets".
_MASK_MIN_LENGTH = 8


@dataclass(frozen=True)
class StatusSnapshot:
    """Aggregated configure-UI status payload."""

    host: str
    setup_parts: SetupParts
    providers_installed: dict[str, bool]
    credentials_present: dict[str, bool]
    credentials_oauth: dict[str, bool]
    env_vars: dict[str, dict[str, Any]]
    legacy_commands_present: bool
    # Per-platform: True ⇔ mcpServers.mureo.env.MUREO_DISABLE_<P> == "1"
    # (mureo-native tools for that platform are stepped aside so the
    # official MCP is the single source). Drives the dashboard toggle.
    mureo_disable: dict[str, bool]
    # #222: True ⇔ the active store declares ``multi_account_auth`` (a
    # multi-account backend). The configure UI uses it to suppress the
    # bare-``mureo`` MCP registration (the backend writes per-client
    # ``mureo-<slug>`` entries instead). Computed by the handler behind the
    # ``home is None`` gate and relayed through here; defaults False so
    # standalone OSS and direct callers are unchanged.
    multi_account_auth: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "setup_parts": self.setup_parts.as_dict(),
            "providers_installed": dict(self.providers_installed),
            "credentials_present": dict(self.credentials_present),
            "credentials_oauth": dict(self.credentials_oauth),
            "env_vars": {k: dict(v) for k, v in self.env_vars.items()},
            "legacy_commands_present": self.legacy_commands_present,
            "mureo_disable": dict(self.mureo_disable),
            "multi_account_auth": self.multi_account_auth,
        }


def _detect_installed_providers(mcp_registry_path: Path) -> dict[str, bool]:
    """Report which official providers + the mureo native block are
    registered.

    Reads the file the host actually discovers MCP servers from
    (``~/.claude.json`` for Claude Code — NOT ``settings.json`` —;
    ``claude_desktop_config.json`` for Desktop; ``config.toml`` for Codex).
    A read-only parse is deterministic and race-safe for status display.
    """
    if mcp_registry_path.suffix == ".toml":
        from mureo.web.codex_mcp import installed_codex_server_ids

        ids = installed_codex_server_ids(mcp_registry_path)
        installed = {pid: pid in ids for pid in OFFICIAL_PROVIDER_IDS}
        installed[MUREO_NATIVE_ID] = MUREO_NATIVE_ID in ids
        return installed
    payload = read_json_safe(mcp_registry_path)
    raw = payload.get("mcpServers")
    mcp_servers: dict[str, Any] = raw if isinstance(raw, dict) else {}
    installed = {pid: pid in mcp_servers for pid in OFFICIAL_PROVIDER_IDS}
    installed[MUREO_NATIVE_ID] = MUREO_NATIVE_ID in mcp_servers
    return installed


# Platforms that have a MUREO_DISABLE_<P> toggle (mirror
# mureo.providers.mureo_env._PLATFORM_TO_ENV_VAR — Search Console is
# intentionally absent: mureo is always canonical for it).
_DISABLE_PLATFORMS: tuple[str, ...] = ("google_ads", "meta_ads", "ga4")


def _detect_mureo_disable(mcp_registry_path: Path) -> dict[str, bool]:
    """Per-platform: is ``mcpServers.mureo.env.MUREO_DISABLE_<P>`` ``"1"``.

    Read-only parse of the file the host actually reads MCP from. A
    missing/corrupt file or absent mureo block means nothing is
    disabled (all ``False``) — never raises.
    """
    if mcp_registry_path.suffix == ".toml":
        from mureo.web.codex_mcp import read_codex_server_env

        codex_env = read_codex_server_env(mcp_registry_path, MUREO_NATIVE_ID)
        return {
            p: codex_env.get("MUREO_DISABLE_" + p.upper()) == "1"
            for p in _DISABLE_PLATFORMS
        }
    payload = read_json_safe(mcp_registry_path)
    servers = payload.get("mcpServers")
    mureo = servers.get("mureo") if isinstance(servers, dict) else None
    env = mureo.get("env") if isinstance(mureo, dict) else None
    env = env if isinstance(env, dict) else {}
    return {p: env.get("MUREO_DISABLE_" + p.upper()) == "1" for p in _DISABLE_PLATFORMS}


def _detect_credentials_present(credentials_path: Path) -> dict[str, bool]:
    """Inspect credentials.json for presence of platform sections."""
    payload = read_json_safe(credentials_path)
    sections = ("google_ads", "meta_ads", "ga4")
    out: dict[str, bool] = {}
    for section in sections:
        value = payload.get(section)
        out[section] = isinstance(value, dict) and bool(value)
    return out


def _detect_credentials_oauth(credentials_path: Path) -> dict[str, bool]:
    """Report whether an OAuth refresh/access token has been saved.

    For Google the *adwords* and *webmasters* scopes share a single
    OAuth dance (see ``mureo.auth_setup._GOOGLE_SCOPES``), so this flag
    governs both Google Ads and Search Console re-auth UX.
    """
    payload = read_json_safe(credentials_path)
    google_section = payload.get("google_ads")
    meta_section = payload.get("meta_ads")
    return {
        "google": isinstance(google_section, dict)
        and bool(google_section.get("refresh_token")),
        "meta": isinstance(meta_section, dict)
        and bool(meta_section.get("access_token")),
    }


def _detect_legacy_commands(commands_dir: Path) -> bool:
    """Return True iff any known-legacy slash command file exists."""
    from mureo.web.legacy_commands import detect_legacy_commands

    return bool(detect_legacy_commands(commands_dir))


def _shipped_skill_names() -> frozenset[str]:
    """The skills this mureo would install (``mureo/_data/skills``)."""
    from mureo.cli.setup_cmd import _get_data_path

    try:
        src = _get_data_path("skills")
        return frozenset(
            d.name for d in src.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
        )
    except OSError:  # unreadable package data — cannot claim anything is installed
        return frozenset()


def _detect_workflow_skills(skills_dir: Path) -> bool:
    """Return True iff every skill mureo ships is present in ``skills_dir``.

    Detected, never recalled (#423). The old status came from a flag file that
    only the configure UI's own actions wrote, so a ``mureo setup`` install read
    ✗ while present, and a hand-deleted skill read ✓ while absent — the UI
    asserting a component is there when it is not.

    A *missing* skill reads as not-installed rather than partially-installed:
    the remedy is the same either way (re-run the install, which overwrites),
    and a half-installed set reported as ✓ is how an operator ends up without
    the workflow they think they have. Staleness (installed, but from an older
    mureo) is version drift and belongs to the upgrade action, not here.
    """
    expected = _shipped_skill_names()
    if not expected:
        return False
    return all((skills_dir / name / "SKILL.md").exists() for name in expected)


def _detect_auth_hook(host: str, settings_path: Path) -> bool:
    """Return True iff mureo's credential-guard PreToolUse hook is installed.

    Identified with :func:`mureo.credential_guard.is_guard_entry` — the same
    predicate the installer and the remover use. It is scoped to the entry's
    inner ``command`` field, so a user's own hook is never claimed as ours, and
    there is only ever one definition of "is this our guard" to keep correct.

    The path comes from ``settings_path``, never from a separately-threaded
    home: Codex keeps its hooks in ``hooks.json`` beside its config rather than
    inside it, and deriving that from the resolved :class:`HostPaths` keeps this
    reading the *same* tree the rest of the snapshot reads. (Taking a ``home``
    of its own would let a caller that passes only ``paths`` — as the handler
    does — silently read the operator's real ``~/.codex`` instead.)

    Claude Desktop has no ``PreToolUse`` surface, so the installer no-ops there
    and this is always False. A guard stranded in the *legacy* top-level
    ``PreToolUse`` list by a much older mureo reads as absent; re-running the
    install rewrites it into the nested shape, which is the safe direction.
    """
    if host == _HOST_DESKTOP:
        return False
    from mureo.credential_guard import is_guard_entry

    path = settings_path.parent / "hooks.json" if host == _HOST_CODEX else settings_path
    hooks = read_json_safe(path).get("hooks")
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get("PreToolUse")
    return isinstance(entries, list) and any(is_guard_entry(e) for e in entries)


def _mask_value(name: str, value: str) -> str:
    """Return a UI-safe preview for an env var value.

    Secret-named vars get bullets + last 4 chars (or full bullets for
    very short values). Non-secret vars surface the full value so the
    operator can verify a file path or non-sensitive identifier.
    """
    if not value:
        return ""
    if _SECRET_NAME_RE.search(name) is None:
        return value
    if len(value) < _MASK_MIN_LENGTH:
        return "•" * 8
    return "••••" + value[-4:]


def _collect_env_vars(credentials_path: Path) -> dict[str, dict[str, Any]]:
    """Snapshot the configure-UI's known credential fields.

    Despite the historical ``env_vars`` field name (kept stable so the
    JSON contract does not break), values are sourced from
    ``credentials.json`` — not from ``os.environ``. The wizard and the
    "Set environment variable" dashboard form both persist into that
    file, so this is the only source of truth the UI should read.

    Returns ``{name: {"set": bool, "value_preview": str | None}}``. The
    value preview is masked for secret-named vars; the full value is
    *never* placed in a log line by this function.
    """
    payload = read_json_safe(credentials_path)
    out: dict[str, dict[str, Any]] = {}
    for name in allowed_env_var_names():
        target = get_env_var_target(name)
        if target is None:
            out[name] = {"set": False, "value_preview": None}
            continue
        section = payload.get(target.section)
        raw: Any = section.get(target.field) if isinstance(section, dict) else None
        if not isinstance(raw, str) or raw == "":
            out[name] = {"set": False, "value_preview": None}
            continue
        out[name] = {"set": True, "value_preview": _mask_value(name, raw)}
    return out


def collect_status(
    host: str,
    *,
    home: Path | None = None,
    paths: HostPaths | None = None,
    multi_account_auth: bool = False,
) -> StatusSnapshot:
    """Build a status snapshot for ``host``.

    ``multi_account_auth`` (#222) is relayed verbatim onto the snapshot —
    the caller (the handler) computes it behind the ``home is None`` gate,
    so this stays a pure filesystem read with no runtime-context coupling.
    """
    resolved = paths if paths is not None else get_host_paths(host, home)
    providers = _detect_installed_providers(resolved.mcp_registry_path)
    # Detected from disk, like every other row here — never recalled from a
    # flag file (#423). ``mureo_mcp`` reuses the provider detection above
    # rather than keeping a second source of truth for the same fact.
    setup_parts = SetupParts(
        mureo_mcp=providers[MUREO_NATIVE_ID],
        auth_hook=_detect_auth_hook(resolved.host, resolved.settings_path),
        skills=_detect_workflow_skills(resolved.skills_dir),
    )
    creds = _detect_credentials_present(resolved.credentials_path)
    creds_oauth = _detect_credentials_oauth(resolved.credentials_path)
    env_vars = _collect_env_vars(resolved.credentials_path)
    legacy = _detect_legacy_commands(resolved.commands_dir)
    mureo_disable = _detect_mureo_disable(resolved.mcp_registry_path)
    return StatusSnapshot(
        host=resolved.host,
        setup_parts=setup_parts,
        providers_installed=providers,
        credentials_present=creds,
        credentials_oauth=creds_oauth,
        env_vars=env_vars,
        legacy_commands_present=legacy,
        mureo_disable=mureo_disable,
        multi_account_auth=multi_account_auth,
    )
