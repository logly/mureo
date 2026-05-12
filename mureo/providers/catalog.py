"""Catalog of official Phase 1 MCP providers.

Each entry describes:
- how to install the underlying package (``install_argv`` — list-form only,
  first element constrained to the ``{pipx, npm}`` allow-list enforced by
  ``mureo.providers.installer.run_install``; hosted entries use an empty
  tuple and skip the subprocess path entirely);
- the ``mcpServers.<id>`` payload written into ``~/.claude/settings.json``
  (for ``hosted_http`` entries this is the Claude Code ``{"type": "http",
  "url": "..."}`` shape; for local-install entries it is the
  ``{"command": "...", "args": [...]}`` shape);
- which credential env vars the user must set for the server to function
  (hosted entries use interactive browser OAuth on first connect, so this
  is the empty tuple);
- whether this provider overlaps with a platform that mureo also serves
  natively (drives the coexistence warning surfaced by the CLI).

The catalog is intentionally baked into source — values are not user-supplied
in Phase 1, which keeps subprocess argv safe by construction.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

InstallKind = Literal["pipx", "npm", "hosted_http"]
CoexistsPlatform = Literal["google_ads", "meta_ads", "ga4"]


def _freeze_config(payload: dict[str, Any]) -> Mapping[str, Any]:
    """Wrap a dict in ``MappingProxyType`` so catalog entries are read-only.

    Only the top-level dict is frozen — nested lists are converted to tuples
    so the entire payload is immutable by interface, foreclosing mutation as
    a vector for catalog tampering.
    """

    def _freeze_value(value: Any) -> Any:
        if isinstance(value, list):
            return tuple(_freeze_value(v) for v in value)
        if isinstance(value, dict):
            return types.MappingProxyType(
                {k: _freeze_value(v) for k, v in value.items()}
            )
        return value

    return types.MappingProxyType({k: _freeze_value(v) for k, v in payload.items()})


@dataclass(frozen=True)
class ProviderSpec:
    """Immutable description of an official MCP provider.

    Fields:
        id: stable identifier used as the ``mcpServers`` key and CLI argument.
        display_name: human label shown in ``mureo providers list``.
        install_kind: package-manager family — ``pipx``, ``npm``, or
            ``hosted_http``. Hosted entries skip the subprocess path
            entirely (``install_argv`` is empty); their
            ``mcp_server_config`` is written directly into the host's
            settings file and the MCP client handles auth on first
            connect (typically OAuth in a browser).
        install_argv: exact argv tuple passed to ``subprocess.run`` (list-form
            only — never a shell string). First element must be in the
            installer allow-list. Empty tuple for ``hosted_http`` entries
            (no subprocess invoked). Tuple instead of list so the catalog
            is immutable by interface, not only by attribute reassignment.
        mcp_server_config: payload written to ``mcpServers[id]`` in the
            host config file (Claude Code's ``settings.json``). Typed as
            ``Mapping`` (a read-only ``MappingProxyType`` in practice) so
            callers cannot mutate a shared catalog payload in place.
        required_env: tuple of environment variable names the user must
            populate before the official server functions. Never logged or
            printed with values.
        notes: short human note rendered alongside ``list``; may mention
            authentication caveats.
        coexists_with_mureo_platform: when non-None, mureo also serves this
            platform natively; the CLI emits a coexistence warning.
    """

    id: str
    display_name: str
    install_kind: InstallKind
    install_argv: tuple[str, ...]
    mcp_server_config: Mapping[str, Any]
    required_env: tuple[str, ...]
    notes: str
    coexists_with_mureo_platform: CoexistsPlatform | None


CATALOG: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="google-ads-official",
        display_name="Google Ads (official MCP)",
        install_kind="pipx",
        install_argv=(
            "pipx",
            "install",
            "git+https://github.com/googleads/google-ads-mcp.git",
        ),
        mcp_server_config=_freeze_config(
            {
                "command": "pipx",
                "args": [
                    "run",
                    "--spec",
                    "git+https://github.com/googleads/google-ads-mcp.git",
                    "google-ads-mcp",
                ],
            }
        ),
        required_env=(
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN",
        ),
        notes=(
            "Installs the official Google Ads MCP from "
            "github.com/googleads/google-ads-mcp via pipx. "
            "Phase 1 uses Client Library config mode — env vars match "
            "`mureo auth setup` output, so existing mureo users need no "
            "additional credentials. OAuth Proxy and ADC modes are deferred "
            "to Phase 2. Developer Token required "
            "(see Google Cloud Console > Google Ads API)."
        ),
        coexists_with_mureo_platform="google_ads",
    ),
    ProviderSpec(
        id="meta-ads-official",
        display_name="Meta Ads (official hosted MCP)",
        install_kind="hosted_http",
        # Hosted endpoint — no local install step. Meta delivers its official
        # Ads MCP as a hosted HTTP service at `https://mcp.facebook.com/ads`
        # (announced 2026-04-29 as "Meta Ads AI Connectors"; verified
        # 2026-05-12 via live HTTP probe — endpoint returns HTTP 401 with
        # `WWW-Authenticate: Bearer resource_metadata=...oauth-protected-
        # resource/ads`, the standard MCP HTTP-transport OAuth handshake).
        install_argv=(),
        mcp_server_config=_freeze_config(
            {
                "type": "http",
                "url": "https://mcp.facebook.com/ads",
            }
        ),
        # Auth is interactive browser-OAuth via Meta Business Login on first
        # connect — no env vars need to be pre-populated. The user picks
        # which Business Manager / ad account(s) to authorize during the
        # OAuth consent flow.
        required_env=(),
        notes=(
            "Registers Meta's official hosted MCP at "
            "`https://mcp.facebook.com/ads` (announced 2026-04-29 as "
            "Meta Ads AI Connectors). No local install needed. "
            "Authentication is interactive Meta Business OAuth in the "
            "browser on first connect — no Meta Developer App, no API "
            "tokens, and no env vars to pre-populate. The user selects the "
            "Business Manager / ad accounts to share during OAuth consent. "
            "Currently in public beta and free during the beta."
        ),
        coexists_with_mureo_platform="meta_ads",
    ),
    ProviderSpec(
        id="ga4-official",
        display_name="Google Analytics 4 (official MCP)",
        install_kind="pipx",
        install_argv=("pipx", "install", "analytics-mcp"),
        mcp_server_config=_freeze_config(
            {
                "command": "pipx",
                "args": ["run", "analytics-mcp"],
            }
        ),
        required_env=(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_PROJECT_ID",
        ),
        notes=(
            "Installs Google's official Analytics MCP (`analytics-mcp` on "
            "PyPI, repo github.com/googleanalytics/google-analytics-mcp) "
            "via pipx. Read-only access to GA4 Reporting and Admin APIs. "
            "Requires a service-account JSON file referenced by "
            "`GOOGLE_APPLICATION_CREDENTIALS` with the "
            "`https://www.googleapis.com/auth/analytics.readonly` scope. "
            "The GA4 property id is passed per-request, not via env var."
        ),
        coexists_with_mureo_platform="ga4",
    ),
)


def get_catalog() -> tuple[ProviderSpec, ...]:
    """Return the immutable Phase 1 catalog."""
    return CATALOG


def get_provider(provider_id: str) -> ProviderSpec:
    """Return the spec for ``provider_id``.

    Raises:
        KeyError: when no entry matches ``provider_id``.
    """
    for spec in CATALOG:
        if spec.id == provider_id:
            return spec
    raise KeyError(provider_id)
