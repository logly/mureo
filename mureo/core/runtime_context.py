"""``RuntimeContext`` — frozen aggregate of the four core extension Protocols
plus an opaque workspace identifier.

A ``RuntimeContext`` is the single object passed through mureo call sites
that need pluggable backends for credentials, persisted state, ``/learn``
knowledge, and API throttling. Today nothing in OSS constructs a
``RuntimeContext`` automatically — call sites still talk to the legacy
helpers in ``mureo.auth`` / ``mureo.context`` / ``mureo.mcp`` directly.
Hookup of consumers ships in follow-up commits; this module only
introduces the type so alternate backends can be wired before the
refactor lands.

``workspace_id`` is intentionally opaque. For single-workspace callers
the canonical value is the literal ``"default"``; alternate runtimes are
free to use any other non-empty string. Empty strings are rejected at
construction time.
"""

from __future__ import annotations

from dataclasses import dataclass

from mureo.core.knowledge_store import KnowledgeStore
from mureo.core.secret_store import SecretStore
from mureo.core.state_store import StateStore
from mureo.core.throttle_store import ThrottleStore


@dataclass(frozen=True)
class RuntimeContext:
    """Immutable bundle of pluggable backends + a workspace identifier.

    The dataclass is frozen so a context can be passed safely across
    threads / coroutines without races on its fields. The pointed-to
    stores are *not* required to be immutable — they encapsulate their
    own concurrency story.
    """

    secret_store: SecretStore
    state_store: StateStore
    knowledge_store: KnowledgeStore
    throttle_store: ThrottleStore
    workspace_id: str

    def __post_init__(self) -> None:
        """Reject empty / whitespace-only ``workspace_id``.

        Matches the validation pattern used by
        :func:`mureo.core.providers.base.validate_provider_name` —
        identifiers in this layer must be unambiguous strings.
        """
        if not isinstance(self.workspace_id, str) or not self.workspace_id.strip():
            raise ValueError(
                "workspace_id must be a non-empty, non-whitespace string"
            )
