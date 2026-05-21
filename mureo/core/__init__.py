"""Public surface of ``mureo.core``: extension Protocols, file-backed
default implementations, and the ``RuntimeContext`` aggregate used to
pass them through call sites.

Importing from this package is the supported way for callers (tests,
alternate backends, future consumers) to reach the extension layer.
The Protocols and the names re-exported below are an ABI commitment —
each rename or removal needs a deprecation cycle.

The pre-existing :mod:`mureo.core.providers` and :mod:`mureo.core.skills`
sub-packages are not re-exported here; reach them by their fully
qualified module names as before.
"""

from __future__ import annotations

from mureo.core.knowledge_store import FilesystemKnowledgeStore, KnowledgeStore
from mureo.core.runtime_context import (
    DEFAULT_WORKSPACE_ID,
    RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
    RuntimeContext,
    RuntimeContextFactoryError,
    default_runtime_context,
    get_runtime_context,
    reset_runtime_context,
)
from mureo.core.secret_store import FilesystemSecretStore, SecretStore
from mureo.core.state_store import FilesystemStateStore, StateStore
from mureo.core.throttle_store import ProcessLocalThrottleStore, ThrottleStore

__all__ = [
    "DEFAULT_WORKSPACE_ID",
    "FilesystemKnowledgeStore",
    "FilesystemSecretStore",
    "FilesystemStateStore",
    "KnowledgeStore",
    "ProcessLocalThrottleStore",
    "RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP",
    "RuntimeContext",
    "RuntimeContextFactoryError",
    "SecretStore",
    "StateStore",
    "ThrottleStore",
    "default_runtime_context",
    "get_runtime_context",
    "reset_runtime_context",
]
