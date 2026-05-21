"""Tests for ``mureo.auth`` integration with the ``RuntimeContext``
extension layer.

When ``load_google_ads_credentials()`` / ``load_meta_ads_credentials()``
are called without an explicit ``path``, they consult
``mureo.core.runtime_context.get_runtime_context().secret_store``.
This lets an alternate backend (registered via the
``mureo.runtime_context_factory`` entry-point group) intercept the
credential read without each call site having to change.

Tests that pass an explicit ``path`` keep their current
file-direct semantics — covered by the long-standing ``tests/test_auth.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mureo.auth import load_google_ads_credentials, load_meta_ads_credentials
from mureo.core.runtime_context import (
    RuntimeContext,
    default_runtime_context,
    reset_runtime_context,
)


@dataclass
class _RecordingSecretStore:
    """In-memory SecretStore that records every ``load(key)`` call so the
    test can assert the auth helper went through the runtime context."""

    payload: dict[str, dict[str, Any]] = field(default_factory=dict)
    loads: list[str] = field(default_factory=list)

    def load(self, key: str) -> dict[str, Any]:
        self.loads.append(key)
        return dict(self.payload.get(key, {}))

    def save(self, key: str, value: dict[str, Any]) -> None:  # pragma: no cover
        self.payload[key] = dict(value)

    def delete(self, key: str) -> None:  # pragma: no cover
        self.payload.pop(key, None)


def _make_ctx(secret_store: _RecordingSecretStore) -> RuntimeContext:
    base = default_runtime_context()
    return RuntimeContext(
        secret_store=secret_store,
        state_store=base.state_store,
        knowledge_store=base.knowledge_store,
        throttle_store=base.throttle_store,
        workspace_id=base.workspace_id,
    )


def _patch_runtime_context(
    monkeypatch: pytest.MonkeyPatch, store: _RecordingSecretStore
) -> None:
    """Replace the cached RuntimeContext used by ``mureo.auth``."""
    ctx = _make_ctx(store)
    # Pre-fill the cache so the resolver short-circuits to our context.
    monkeypatch.setattr("mureo.core.runtime_context._cached_context", ctx)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    reset_runtime_context()
    yield
    reset_runtime_context()


# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_google_ads_uses_runtime_context_when_path_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RecordingSecretStore(
        payload={
            "google_ads": {
                "developer_token": "dev-token-X",
                "client_id": "client-id-X",
                "client_secret": "secret-X",
                "refresh_token": "refresh-X",
                "customer_id": "111-222-3333",
            }
        }
    )
    _patch_runtime_context(monkeypatch, store)

    creds = load_google_ads_credentials()
    assert creds is not None
    assert creds.developer_token == "dev-token-X"
    assert creds.customer_id == "111-222-3333"
    assert store.loads == ["google_ads"]


@pytest.mark.unit
def test_load_meta_ads_uses_runtime_context_when_path_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RecordingSecretStore(
        payload={
            "meta_ads": {
                "access_token": "fb-token-X",
                "account_id": "act_999",
            }
        }
    )
    _patch_runtime_context(monkeypatch, store)

    creds = load_meta_ads_credentials()
    assert creds is not None
    assert creds.access_token == "fb-token-X"
    assert creds.account_id == "act_999"
    assert store.loads == ["meta_ads"]


@pytest.mark.unit
def test_explicit_path_bypasses_runtime_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Passing ``path=`` must keep using the file-backed default —
    otherwise the long-standing tests that rely on per-test temp files
    would silently leak through the resolver cache."""
    # Wire a recording store that, if consulted, would return DIFFERENT
    # creds than the file. The auth helper must NOT consult it.
    store = _RecordingSecretStore(
        payload={"google_ads": {"developer_token": "WRONG"}}
    )
    _patch_runtime_context(monkeypatch, store)

    # Write a real credentials file that the explicit-path branch reads.
    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(
        json.dumps(
            {
                "google_ads": {
                    "developer_token": "FROM-FILE",
                    "client_id": "c",
                    "client_secret": "s",
                    "refresh_token": "r",
                }
            }
        ),
        encoding="utf-8",
    )

    creds = load_google_ads_credentials(path=cred_path)
    assert creds is not None
    assert creds.developer_token == "FROM-FILE"
    assert store.loads == [], "explicit-path call must not touch runtime context"


@pytest.mark.unit
def test_load_google_ads_falls_back_to_env_when_context_store_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the resolved SecretStore has no google_ads entry, the env-var
    fallback must still kick in — same precedence rule the existing
    file-direct path enforces."""
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "from-env")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "env-cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "env-refresh")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "777-888-9999")

    empty_store = _RecordingSecretStore()
    _patch_runtime_context(monkeypatch, empty_store)

    creds = load_google_ads_credentials()
    assert creds is not None
    assert creds.developer_token == "from-env"
    assert creds.login_customer_id == "777-888-9999"
    assert empty_store.loads == ["google_ads"]  # consulted, then fell through
