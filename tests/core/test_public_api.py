"""Pin the public surface re-exported by :mod:`mureo.core`.

The package was previously empty (no ``__all__``, no re-exports). This
test guards the new exports added alongside the extension-Protocol
work so a downstream consumer that does ``from mureo.core import
RuntimeContext`` keeps compiling across releases.

A new symbol added here is an ABI commitment — drop one only with a
deprecation cycle.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_public_protocols_are_importable() -> None:
    from mureo.core import (
        KnowledgeStore,
        SecretStore,
        StateStore,
        ThrottleStore,
    )

    # Sanity: each is a Protocol with the expected runtime_checkable shape.
    for proto in (SecretStore, StateStore, KnowledgeStore, ThrottleStore):
        assert hasattr(proto, "__instancecheck__")


@pytest.mark.unit
def test_public_default_implementations_are_importable() -> None:
    from mureo.core import (
        FilesystemKnowledgeStore,
        FilesystemSecretStore,
        FilesystemStateStore,
        ProcessLocalThrottleStore,
    )

    # Sanity: each can be instantiated with no required args.
    FilesystemSecretStore()
    FilesystemStateStore()
    FilesystemKnowledgeStore()
    ProcessLocalThrottleStore()


@pytest.mark.unit
def test_public_runtime_context_is_importable() -> None:
    """Exercise the factory through the public package path so a future
    accidental rewiring of the re-export (e.g. shadowing in
    ``__init__.py``) is caught by this test."""
    from mureo.core import (
        DEFAULT_WORKSPACE_ID,
        RuntimeContext,
        default_runtime_context,
    )

    assert RuntimeContext.__name__ == "RuntimeContext"
    ctx = default_runtime_context()
    assert isinstance(ctx, RuntimeContext)
    assert ctx.workspace_id == DEFAULT_WORKSPACE_ID


@pytest.mark.unit
def test_public_all_matches_documented_surface() -> None:
    """``__all__`` is the contract — every name above must be in it, no
    surprise extras should appear without a code review."""
    import mureo.core as core

    assert sorted(core.__all__) == sorted([
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
    ])


@pytest.mark.unit
def test_public_does_not_reexport_subpackages() -> None:
    """``mureo.core.providers`` and ``mureo.core.skills`` are reached by
    their fully qualified module names; re-exporting them here would
    silently widen the ABI. Guard against accidental future re-exports."""
    import mureo.core as core

    for name in ("providers", "skills"):
        assert name not in core.__all__
