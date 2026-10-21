"""Per-call credential source: moved to :mod:`mureo.core.credential_source` (#863).

This path re-exports the same objects (one ``ContextVar``, identical classes
and functions), so existing imports keep working. Unlike the new path, it
imports the MCP server: new code should import ``mureo.core.credential_source``.
"""

from __future__ import annotations

from mureo.core.credential_source import CredentialSource as CredentialSource
from mureo.core.credential_source import (
    CredentialSourceError as CredentialSourceError,
)
from mureo.core.credential_source import (
    GoogleCredentialSource as GoogleCredentialSource,
)
from mureo.core.credential_source import (
    MetaCredentialSource as MetaCredentialSource,
)
from mureo.core.credential_source import (
    active_source_identity as active_source_identity,
)
from mureo.core.credential_source import call_source as call_source
from mureo.core.credential_source import (
    current_credential_source as current_credential_source,
)
from mureo.core.credential_source import (
    current_google_source as current_google_source,
)
from mureo.core.credential_source import current_meta_source as current_meta_source
from mureo.core.credential_source import (
    use_credential_source as use_credential_source,
)

__all__ = [
    "CredentialSource",
    "CredentialSourceError",
    "GoogleCredentialSource",
    "MetaCredentialSource",
    "active_source_identity",
    "call_source",
    "current_credential_source",
    "current_google_source",
    "current_meta_source",
    "use_credential_source",
]
