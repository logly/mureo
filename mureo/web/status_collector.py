"""Collect installation status across hosts, providers, and basic parts.

Pure read-only — nothing in this module mutates settings files or
credentials. The configure UI surfaces this snapshot on every
``GET /api/status`` poll and uses it to render ✓/✗ pills.

Security boundary: credentials.json is only inspected for the
**presence** of platform keys, never the values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mureo.web._helpers import read_json_safe
from mureo.web.host_paths import HostPaths, get_host_paths
from mureo.web.setup_state import SetupParts, read_setup_state

OFFICIAL_PROVIDER_IDS: tuple[str, ...] = (
    "google-ads-official",
    "meta-ads-official",
    "ga4-official",
)

MUREO_NATIVE_ID = "mureo"


@dataclass(frozen=True)
class StatusSnapshot:
    """Aggregated configure-UI status payload."""

    host: str
    setup_parts: SetupParts
    providers_installed: dict[str, bool]
    credentials_present: dict[str, bool]
    legacy_commands_present: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "setup_parts": self.setup_parts.as_dict(),
            "providers_installed": dict(self.providers_installed),
            "credentials_present": dict(self.credentials_present),
            "legacy_commands_present": self.legacy_commands_present,
        }


def _detect_installed_providers(settings_path: Path) -> dict[str, bool]:
    """Read mcpServers from settings.json and report installed provider ids."""
    payload = read_json_safe(settings_path)
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


def _detect_legacy_commands(commands_dir: Path) -> bool:
    """Return True iff any known-legacy slash command file exists."""
    from mureo.web.legacy_commands import detect_legacy_commands

    return bool(detect_legacy_commands(commands_dir))


def collect_status(
    host: str,
    *,
    home: Path | None = None,
    paths: HostPaths | None = None,
) -> StatusSnapshot:
    """Build a status snapshot for ``host``."""
    resolved = paths if paths is not None else get_host_paths(host, home)
    setup_parts = read_setup_state(home)
    providers = _detect_installed_providers(resolved.settings_path)
    creds = _detect_credentials_present(resolved.credentials_path)
    legacy = _detect_legacy_commands(resolved.commands_dir)
    return StatusSnapshot(
        host=resolved.host,
        setup_parts=setup_parts,
        providers_installed=providers,
        credentials_present=creds,
        legacy_commands_present=legacy,
    )
