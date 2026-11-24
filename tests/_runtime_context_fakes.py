"""Runtime-context factory stubs shared by tests of store capabilities.

The root ``conftest.py`` already hides every installed
``mureo.runtime_context_factory`` entry point and drops the cached context
around each test, so a test that installs nothing here runs as a
single-account install. These helpers register one fake factory on top of
that for the duration of a test.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from mureo.core.runtime_context import (
    RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
    default_runtime_context,
)


class MultiAccountStore:
    """A ``SecretStore`` holding fixed sections that declares
    ``multi_account_auth`` (``True`` unless another value is given, so the
    resolver's strictness about non-``True`` values can be exercised)."""

    def __init__(
        self,
        sections: dict[str, dict[str, Any]] | None = None,
        *,
        multi_account_auth: object = True,
    ) -> None:
        self._sections = dict(sections or {})
        self.multi_account_auth = multi_account_auth

    def load(self, key: str) -> dict[str, Any]:
        return dict(self._sections.get(key, {}))

    def save(self, key: str, value: dict[str, Any]) -> None:  # pragma: no cover
        return None

    def delete(self, key: str) -> None:  # pragma: no cover
        return None


class _FactoryEntryPoint:
    """A ``mureo.runtime_context_factory`` entry point loading ``factory``."""

    name = "test-factory"

    def __init__(self, factory: Callable[[], object]) -> None:
        self._factory = factory

    def load(self) -> Callable[[], object]:
        return self._factory


def install_runtime_factory(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[[], object]
) -> None:
    """Register ``factory`` as the only runtime-context factory."""

    def fake_entry_points(*, group: str) -> list[_FactoryEntryPoint]:
        assert group == RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP
        return [_FactoryEntryPoint(factory)]

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)


def install_runtime_store(monkeypatch: pytest.MonkeyPatch, store: object) -> None:
    """Register a factory whose context carries ``store`` as its secret store."""
    ctx = dataclasses.replace(default_runtime_context(), secret_store=store)
    install_runtime_factory(monkeypatch, lambda: ctx)
