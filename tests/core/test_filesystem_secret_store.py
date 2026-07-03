"""Tests for ``mureo.core.secret_store.FilesystemSecretStore`` — the
default in-process implementation that persists credentials to a JSON
file (today: ``~/.mureo/credentials.json``).

The default is the behaviourally-equivalent wrapper of the existing
file format read by ``mureo.auth.load_credentials``. Tests below pin
the round-trip semantics and the platform-key-scoped CRUD that callers
will rely on once the consumers in ``mureo.auth`` are refactored in a
follow-up commit.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from mureo.core.secret_store import (
    FilesystemSecretStore,
    SecretStore,
    SecretStoreError,
)


@pytest.mark.unit
def test_satisfies_protocol(tmp_path: Path) -> None:
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    assert isinstance(store, SecretStore)


@pytest.mark.unit
def test_save_refuses_to_clobber_malformed_file(tmp_path: Path) -> None:
    """A save must NOT reset a corrupt (truncated) file to ``{}`` — that would
    drop every other provider's credentials. It backs the file up and raises."""
    path = tmp_path / "credentials.json"
    # Truncated JSON that once held multiple providers.
    path.write_text('{"google_ads": {"developer_token": "abc"}, "meta_a', encoding="utf-8")
    store = FilesystemSecretStore(path=path)

    with pytest.raises(SecretStoreError):
        store.save("meta_ads", {"access_token": "xyz"})

    # Original corrupt bytes are preserved (not overwritten) and a .bak exists.
    assert path.read_text(encoding="utf-8").startswith('{"google_ads"')
    assert (tmp_path / "credentials.json.bak").exists()


@pytest.mark.unit
def test_load_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    assert store.load("google_ads") == {}


@pytest.mark.unit
def test_save_then_load_round_trip(tmp_path: Path) -> None:
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    payload = {"developer_token": "abc", "client_id": "xyz"}
    store.save("google_ads", payload)
    assert store.load("google_ads") == payload


@pytest.mark.unit
def test_save_does_not_clobber_other_keys(tmp_path: Path) -> None:
    """Saving one platform must preserve credentials for unrelated platforms
    so existing call sites (which read the full file via
    ``auth.load_credentials``) keep seeing every entry they expect."""
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    store.save("google_ads", {"developer_token": "abc"})
    store.save("meta_ads", {"access_token": "fb-token"})
    assert store.load("google_ads") == {"developer_token": "abc"}
    assert store.load("meta_ads") == {"access_token": "fb-token"}


@pytest.mark.unit
def test_save_overwrites_existing_key(tmp_path: Path) -> None:
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    store.save("google_ads", {"developer_token": "old"})
    store.save("google_ads", {"developer_token": "new"})
    assert store.load("google_ads") == {"developer_token": "new"}


@pytest.mark.unit
def test_delete_removes_key(tmp_path: Path) -> None:
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    store.save("google_ads", {"developer_token": "abc"})
    store.delete("google_ads")
    assert store.load("google_ads") == {}


@pytest.mark.unit
def test_delete_missing_key_is_idempotent(tmp_path: Path) -> None:
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    store.delete("google_ads")  # file does not even exist; must not raise
    store.save("meta_ads", {"access_token": "x"})
    store.delete("google_ads")  # file exists but key absent; still must not raise


@pytest.mark.unit
def test_save_writes_secure_permissions(tmp_path: Path) -> None:
    """Credential files must land at 0600 (owner-only). Mirrors
    ``mureo.fsutil.secure_chmod`` semantics used elsewhere for secret
    material. Skipped on Windows because POSIX mode bits do not apply."""
    if os.name != "posix":
        pytest.skip("POSIX-only permission check")
    path = tmp_path / "credentials.json"
    store = FilesystemSecretStore(path=path)
    store.save("google_ads", {"developer_token": "abc"})
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got 0o{mode:o}"


@pytest.mark.unit
def test_corrupt_file_returns_empty_on_load(tmp_path: Path) -> None:
    """Mirrors ``mureo.auth.load_credentials`` — invalid JSON is treated
    as 'no credentials' rather than crashing, so an MCP server can still
    start."""
    path = tmp_path / "credentials.json"
    path.write_text("not json at all", encoding="utf-8")
    store = FilesystemSecretStore(path=path)
    assert store.load("google_ads") == {}


@pytest.mark.unit
def test_default_path_resolves_under_dot_mureo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Patches ``Path.home`` directly so the test is Windows-safe — see
    ``test_runtime_context.test_default_factory_no_args_uses_legacy_paths``
    for the rationale."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    store = FilesystemSecretStore()
    assert store.path == tmp_path / ".mureo" / "credentials.json"


@pytest.mark.unit
def test_saved_payload_is_isolated_from_caller_mutation(tmp_path: Path) -> None:
    store = FilesystemSecretStore(path=tmp_path / "credentials.json")
    payload = {"developer_token": "abc"}
    store.save("google_ads", payload)
    payload["developer_token"] = "MUTATED"
    assert store.load("google_ads") == {"developer_token": "abc"}


@pytest.mark.unit
def test_save_strips_non_dict_root(tmp_path: Path) -> None:
    """If the on-disk file's root is not a JSON object (e.g. a list left
    by a user mistake), ``save`` recovers by replacing it with a fresh
    object containing only the saved key — mirrors
    ``auth.load_credentials`` which already tolerates this shape."""
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    store = FilesystemSecretStore(path=path)
    store.save("google_ads", {"developer_token": "abc"})
    assert store.load("google_ads") == {"developer_token": "abc"}


# ---------------------------------------------------------------------------
# ensure_exists — materialize an empty file so "configured nothing" is
# distinguishable from "setup never ran" (#210)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ensure_exists_creates_empty_file_when_absent(tmp_path: Path) -> None:
    path = tmp_path / ".mureo" / "credentials.json"
    store = FilesystemSecretStore(path=path)
    created = store.ensure_exists()
    assert created is True
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.unit
def test_ensure_exists_noop_when_present(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    store = FilesystemSecretStore(path=path)
    store.save("meta_ads", {"access_token": "X"})
    created = store.ensure_exists()
    assert created is False
    # Existing content is never touched.
    assert store.load("meta_ads") == {"access_token": "X"}
