"""``RuntimeContext`` — frozen aggregate of the four core extension Protocols
plus an opaque workspace identifier, and ``default_runtime_context()`` —
the factory that wires the four file-backed defaults.

A ``RuntimeContext`` is the single object passed through mureo call sites
that need pluggable backends for credentials, persisted state, ``/learn``
knowledge, and API throttling. Today nothing in OSS constructs a
``RuntimeContext`` automatically — call sites still talk to the legacy
helpers in ``mureo.auth`` / ``mureo.context`` / ``mureo.mcp`` directly.
Hookup of consumers ships in follow-up commits; this module introduces
the type and the default factory so alternate backends can be wired
before the refactor lands.

``workspace_id`` is intentionally opaque. For single-workspace callers
the canonical value is the literal :data:`DEFAULT_WORKSPACE_ID`;
alternate runtimes are free to use any other non-empty string. Empty
strings are rejected at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mureo.core.knowledge_store import FilesystemKnowledgeStore, KnowledgeStore
from mureo.core.secret_store import FilesystemSecretStore, SecretStore
from mureo.core.state_store import FilesystemStateStore, StateStore
from mureo.core.throttle_store import ProcessLocalThrottleStore, ThrottleStore

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.throttle import ThrottleConfig


#: Canonical sentinel for single-workspace callers. Exposed so consumers
#: can compare against the literal without hard-coding it; pinned by
#: :mod:`tests.core.test_runtime_context` so the value cannot drift.
DEFAULT_WORKSPACE_ID = "default"


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
            raise ValueError("workspace_id must be a non-empty, non-whitespace string")


# ---------------------------------------------------------------------------
# Default factory — wires the four file-backed defaults
# ---------------------------------------------------------------------------


def default_runtime_context(
    *,
    workspace: Path | None = None,
    credentials_path: Path | None = None,
    operator_knowledge_path: Path | None = None,
    workspace_knowledge_path: Path | None = None,
    throttle_config: ThrottleConfig | None = None,
) -> RuntimeContext:
    """Return a ``RuntimeContext`` wired with the file-backed defaults.

    All keyword arguments are optional; when omitted, each store falls
    back to the legacy location it has used in mureo to date —
    ``~/.mureo/credentials.json``, CWD-relative ``STATE.json`` /
    ``STRATEGY.md``, ``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md``,
    and :data:`mureo.throttle.PLUGIN_THROTTLE` respectively. The
    workspace tier of the knowledge store is absent by default; pass
    ``workspace_knowledge_path`` to enable it.

    Note: ``workspace`` here is the state-store directory (passed
    through to :class:`FilesystemStateStore`), not the
    :attr:`RuntimeContext.workspace_id` identifier. The factory fixes
    ``workspace_id`` at :data:`DEFAULT_WORKSPACE_ID`; callers that need
    a different identifier should construct the ``RuntimeContext``
    directly rather than going through this factory.
    """
    return RuntimeContext(
        secret_store=FilesystemSecretStore(path=credentials_path),
        state_store=FilesystemStateStore(workspace=workspace),
        knowledge_store=FilesystemKnowledgeStore(
            operator_path=operator_knowledge_path,
            workspace_path=workspace_knowledge_path,
        ),
        throttle_store=ProcessLocalThrottleStore(default_config=throttle_config),
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
