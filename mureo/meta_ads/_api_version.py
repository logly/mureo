"""The Meta Graph / Marketing API version mureo speaks.

One constant, from which every facebook.com URL mureo builds is derived —
the Graph base the ad client and the ad-account listing call
(``mureo.meta_ads.client``, ``mureo.meta_ads.accounts``), the OAuth dialog
the setup wizard sends an operator to (``mureo.auth_setup``) and the
token-grant endpoint the refresher POSTs to (``mureo.auth``) — so a bump
lands in one place instead of five that drift apart.

Bumping it is a deliberate migration (#770), never a drive-by edit: Meta's
breaking changes apply to ALL versions on a published date regardless of
what a caller pins, so the changelog has to be walked field by field
against what mureo sends. The pin sat at v21.0 while Marketing API v21.0
was already expired (2025-09-09), which meant Meta silently served our ads
calls on whatever the oldest live version happened to be — the opposite of
a pin. ``tests/test_meta_api_version.py`` scans the package so a literal
version can never come back into a module or a packaged skill.
"""

from typing import Final

META_GRAPH_API_VERSION: Final = "v26.0"

GRAPH_API_BASE: Final = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"
OAUTH_DIALOG_URL: Final = (
    f"https://www.facebook.com/{META_GRAPH_API_VERSION}/dialog/oauth"
)
OAUTH_TOKEN_URL: Final = f"{GRAPH_API_BASE}/oauth/access_token"
