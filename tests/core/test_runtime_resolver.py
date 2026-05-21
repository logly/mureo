"""Tests for the entry-point–based ``get_runtime_context()`` resolver.

The resolver is the integration point alternate backends use to inject
a custom ``RuntimeContext``: a single entry point in the
``mureo.runtime_context_factory`` group is enough — no callsite needs
to change. With zero entry points the resolver returns the file-backed
default, preserving today's single-workspace behaviour.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.core.runtime_context import (
    DEFAULT_WORKSPACE_ID,
    RuntimeContext,
    RuntimeContextFactoryError,
    default_runtime_context,
    get_runtime_context,
    reset_runtime_context,
)

# ---------------------------------------------------------------------------
# Fake entry-point objects matching the ``importlib.metadata`` shape just
# closely enough for the resolver: ``.name`` and ``.load()``.
# ---------------------------------------------------------------------------


class _FakeEP:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    """Replace ``mureo.core.runtime_context.entry_points`` with a stub."""

    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "mureo.runtime_context_factory"
        return eps

    monkeypatch.setattr(
        "mureo.core.runtime_context.entry_points", fake_entry_points
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Reset the resolver cache between tests so they cannot bleed state."""
    reset_runtime_context()
    yield
    reset_runtime_context()


# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_entry_point_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, [])
    ctx = get_runtime_context()
    assert isinstance(ctx, RuntimeContext)
    assert ctx.workspace_id == DEFAULT_WORKSPACE_ID


@pytest.mark.unit
def test_single_entry_point_factory_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel_ctx = default_runtime_context()  # any concrete RuntimeContext
    _patch_entry_points(
        monkeypatch, [_FakeEP("custom-runtime", lambda: sentinel_ctx)]
    )
    assert get_runtime_context() is sentinel_ctx


@pytest.mark.unit
def test_result_is_cached_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def factory() -> RuntimeContext:
        calls.append(1)
        return default_runtime_context()

    _patch_entry_points(monkeypatch, [_FakeEP("once", factory)])
    a = get_runtime_context()
    b = get_runtime_context()
    assert a is b
    assert calls == [1]


@pytest.mark.unit
def test_reset_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(monkeypatch, [])
    a = get_runtime_context()
    reset_runtime_context()
    b = get_runtime_context()
    # Different instances after reset (default factory builds a fresh one).
    assert a is not b


@pytest.mark.unit
def test_multiple_entry_points_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """More than one factory is a misconfiguration — the integration
    point is global, so silently picking one would mask bugs."""
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEP("first", lambda: default_runtime_context()),
            _FakeEP("second", lambda: default_runtime_context()),
        ],
    )
    with pytest.raises(RuntimeContextFactoryError, match="multiple"):
        get_runtime_context()


@pytest.mark.unit
def test_factory_returning_wrong_type_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_entry_points(
        monkeypatch, [_FakeEP("bad", lambda: "not a context")]
    )
    with pytest.raises(RuntimeContextFactoryError, match="expected RuntimeContext"):
        get_runtime_context()


@pytest.mark.unit
def test_factory_raising_propagates_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the third-party factory itself raises, the resolver wraps the
    cause so the entry-point name is in the error message — otherwise
    debugging a broken plugin requires reading a stack trace from
    elsewhere in the process."""

    def broken() -> RuntimeContext:
        raise ValueError("plugin internals exploded")

    _patch_entry_points(monkeypatch, [_FakeEP("broken-plugin", broken)])
    with pytest.raises(RuntimeContextFactoryError, match="broken-plugin"):
        get_runtime_context()


@pytest.mark.unit
def test_default_factory_used_when_no_plugin_installed() -> None:
    """Sanity: with the real ``entry_points`` call (no plugin installed
    in this test env) the resolver returns a real file-backed default."""
    # No monkeypatch — exercises the actual importlib.metadata call.
    ctx = get_runtime_context()
    assert isinstance(ctx, RuntimeContext)
    assert ctx.workspace_id == DEFAULT_WORKSPACE_ID


@pytest.mark.unit
def test_resolver_is_publicly_exported_from_mureo_core() -> None:
    from mureo.core import (
        RuntimeContextFactoryError,
        get_runtime_context,
        reset_runtime_context,
    )

    assert callable(get_runtime_context)
    assert callable(reset_runtime_context)
    assert issubclass(RuntimeContextFactoryError, RuntimeError)
