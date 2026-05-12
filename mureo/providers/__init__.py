"""Official MCP provider catalog and install helpers.

Phase 1 (Issue #86): one-command install of the three official platform
MCP servers (Google Ads, Meta Ads, GA4) into Claude Code. See planner
HANDOFF ``feat-providers-cli-phase1.md`` for the design.
"""

from __future__ import annotations

from mureo.providers.catalog import CATALOG, ProviderSpec, get_catalog, get_provider

__all__ = ["CATALOG", "ProviderSpec", "get_catalog", "get_provider"]
