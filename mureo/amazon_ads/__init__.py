"""Amazon Ads official-MCP bridge (#113 Phase 1).

mureo sits in the request path (Claude → local mureo → Amazon hosted
MCP), exactly like mureo-native Google/Meta: credentials live in
``~/.mureo/credentials.json``, Claude never sees them, and Amazon calls
inherit mureo's audit / throttle / strategy / rollback safety layer.

Phase 1: manifest-backed tool list (pure ``mcp_tools()``) + run-time
forwarding. No taxonomy remap — Amazon's own tool names are exposed
(namespaced), consistent with how mureo treats other official MCPs.
"""

from __future__ import annotations

__all__ = ["endpoint_url", "request_headers"]

from mureo.amazon_ads.endpoints import endpoint_url, request_headers
