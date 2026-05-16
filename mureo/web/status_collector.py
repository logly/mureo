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
from mureo.web.setup_state import SetupParts, read_setup_state

if TYPE_CHECKING:
    from pathlib import Path

OFFICIAL_PROVIDER_IDS: tuple[str, ...] = (
    "google-ads-official",
    "meta-ads-official",
    "ga4-official",
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "setup_parts": self.setup_parts.as_dict(),
            "providers_installed": dict(self.providers_installed),
            "credentials_present": dict(self.credentials_present),
            "credentials_oauth": dict(self.credentials_oauth),
            "env_vars": {k: dict(v) for k, v in self.env_vars.items()},
            "legacy_commands_present": self.legacy_commands_present,
        }


def _detect_installed_providers(mcp_registry_path: Path) -> dict[str, bool]:
    """Report which official providers + the mureo native block are
    registered.

    Reads the file the host actually discovers MCP servers from
    (``~/.claude.json`` for Claude Code — NOT ``settings.json`` —;
    ``claude_desktop_config.json`` for Desktop). A read-only parse is
    deterministic and race-safe for status display; writes still go
    through the ``claude`` CLI.
    """
    payload = read_json_safe(mcp_registry_path)
    raw = payload.get("mcpServers")
    mcp_servers: dict[str, Any] = raw if isinstance(raw, dict) else {}
    installed = {pid: pid in mcp_servers for pid in OFFICIAL_PROVIDER_IDS}
    installed[MUREO_NATIVE_ID] = MUREO_NATIVE_ID in mcp_servers
    return installed


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
) -> StatusSnapshot:
    """Build a status snapshot for ``host``."""
    resolved = paths if paths is not None else get_host_paths(host, home)
    setup_parts = read_setup_state(home)
    providers = _detect_installed_providers(resolved.mcp_registry_path)
    creds = _detect_credentials_present(resolved.credentials_path)
    creds_oauth = _detect_credentials_oauth(resolved.credentials_path)
    env_vars = _collect_env_vars(resolved.credentials_path)
    legacy = _detect_legacy_commands(resolved.commands_dir)
    return StatusSnapshot(
        host=resolved.host,
        setup_parts=setup_parts,
        providers_installed=providers,
        credentials_present=creds,
        credentials_oauth=creds_oauth,
        env_vars=env_vars,
        legacy_commands_present=legacy,
    )
