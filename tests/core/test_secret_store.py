"""Tests for ``mureo.core.secret_store`` — structural Protocol contract.

RED-phase tests for the new ``SecretStore`` Protocol that abstracts
credential persistence. Default callers continue to read from
``~/.mureo/credentials.json`` via the existing helpers in
``mureo.auth``; this Protocol exists so alternate backends (in-memory
fakes for tests, OS keychain, Vault, GCP Secret Manager, etc.) can be
swapped in without touching call sites.

This commit pins the Protocol shape only — concrete default
implementations land in a separate commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from mureo.core.secret_store import SecretStore


@dataclass
class _FakeSecretStore:
    """Minimal in-memory implementation used to exercise the Protocol shape."""

    data: dict[str, dict[str, Any]] = field(default_factory=dict)

    def load(self, key: str) -> dict[str, Any]:
        return dict(self.data.get(key, {}))

    def save(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = dict(value)

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.mark.unit
def test_protocol_is_runtime_checkable() -> None:
    assert isinstance(_FakeSecretStore(), SecretStore)


@pytest.mark.unit
def test_incomplete_implementation_is_rejected() -> None:
    class _MissingDelete:
        def load(self, key: str) -> dict[str, Any]:
            return {}

        def save(self, key: str, value: dict[str, Any]) -> None:
            pass

    assert not isinstance(_MissingDelete(), SecretStore)


@pytest.mark.unit
def test_fake_round_trip() -> None:
    store = _FakeSecretStore()
    store.save("google_ads", {"refresh_token": "abc"})
    assert store.load("google_ads") == {"refresh_token": "abc"}
    store.delete("google_ads")
    assert store.load("google_ads") == {}


@pytest.mark.unit
def test_load_missing_key_returns_empty_dict() -> None:
    """The Protocol contract: ``load`` of an unknown key returns ``{}`` (not raises)."""
    store = _FakeSecretStore()
    assert store.load("never-set") == {}


@pytest.mark.unit
def test_delete_missing_key_is_idempotent() -> None:
    """The Protocol contract: deleting an unknown key is a no-op (not raises)."""
    store = _FakeSecretStore()
    store.delete("never-set")  # must not raise
