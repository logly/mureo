"""Client archiving seam behind the Reports client index.

Archiving stops the agency digest from syncing that client, so it is a
decision *about the client* and has to live server-side — a browser-local
flag could not reach the digest process at all. OSS does not own that
state; it calls a seam on the active ``StateStore``:

- ``list_clients()`` items may carry ``archived: bool``. Absent means
  ``False``, and a non-bool value is coerced rather than raising.
- ``set_client_archived(slug, archived)`` is OPTIONAL and reached through
  ``getattr`` exactly like ``list_clients``. Absent (the OSS
  single-workspace default) → the capability is advertised as ``False``
  and the dashboard renders no archive control at all.

These pin the normalization, the capability probe, and the error mapping —
including that a seam which raises produces a short code, never the
backend's own exception text.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
)
from mureo.web.reports import (
    ClientArchiveError,
    list_report_clients,
    report_clients_payload,
    set_report_client_archived,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


def _use_store(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    ctx = dataclasses.replace(default_runtime_context(), state_store=store)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)


class _ArchivingStore:
    """An Agency backend that advertises the whole client-registry seam."""

    workspace_id = "agency"

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else [{"slug": "acme"}]
        self.calls: list[tuple[str, bool]] = []

    def list_clients(self) -> list[dict[str, Any]]:
        return self.rows

    def set_client_archived(self, slug: str, archived: bool) -> None:
        self.calls.append((slug, archived))


# ---------------------------------------------------------------------------
# ``archived`` normalization on the client rows
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_workspace_client_is_not_archived(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The OSS fallback row carries the flag too, so every consumer can read
    one shape regardless of which side produced the row."""
    ctx = default_runtime_context(workspace=tmp_path)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)

    clients = list_report_clients()
    assert len(clients) == 1
    assert clients[0]["archived"] is False


@pytest.mark.unit
def test_archived_absent_normalizes_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_store(monkeypatch, _ArchivingStore([{"slug": "acme", "name": "Acme"}]))
    assert list_report_clients()[0]["archived"] is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        (None, False),
        ("", False),
        ("yes", True),
        (1, True),
        (0, False),
        ([], False),
    ],
)
def test_archived_is_coerced_never_crashes(
    monkeypatch: pytest.MonkeyPatch, raw: Any, expected: bool
) -> None:
    """A backend that writes the flag as a string / number / null must not
    blank out the picker — the value is coerced, exactly like ``active``."""
    _use_store(monkeypatch, _ArchivingStore([{"slug": "acme", "archived": raw}]))
    row = list_report_clients()[0]
    assert row["archived"] is expected


# ---------------------------------------------------------------------------
# Capability probe — is the archive control renderable at all?
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_payload_reports_no_archive_capability_without_the_seam(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An OSS-only single-workspace install has no client registry, so the
    frontend must be told NOT to render the control."""
    ctx = default_runtime_context(workspace=tmp_path)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)

    payload = report_clients_payload()
    assert payload["can_archive"] is False
    assert len(payload["clients"]) == 1


@pytest.mark.unit
def test_payload_reports_archive_capability_with_the_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_store(monkeypatch, _ArchivingStore())
    payload = report_clients_payload()
    assert payload["can_archive"] is True
    assert [c["slug"] for c in payload["clients"]] == ["acme"]


@pytest.mark.unit
def test_a_non_callable_seam_attribute_is_not_a_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``getattr`` presence is not enough — a mistyped declaration (a plain
    attribute rather than a method) must read as absent, not as usable."""

    class _Broken:
        workspace_id = "agency"
        set_client_archived = "not callable"

        def list_clients(self) -> list[dict[str, Any]]:
            return [{"slug": "acme"}]

    _use_store(monkeypatch, _Broken())
    assert report_clients_payload()["can_archive"] is False


# ---------------------------------------------------------------------------
# set_report_client_archived
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_archived_delegates_to_the_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _ArchivingStore()
    _use_store(monkeypatch, store)

    set_report_client_archived("acme", True)
    set_report_client_archived("acme", False)

    assert store.calls == [("acme", True), ("acme", False)]


@pytest.mark.unit
def test_set_archived_trims_the_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _ArchivingStore()
    _use_store(monkeypatch, store)

    set_report_client_archived("  acme  ", True)

    assert store.calls == [("acme", True)]


@pytest.mark.unit
def test_blank_slug_is_refused_at_this_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ArchivingStore()
    _use_store(monkeypatch, store)

    with pytest.raises(ClientArchiveError) as exc:
        set_report_client_archived("   ", True)

    assert exc.value.code == "slug_required"
    assert store.calls == []


@pytest.mark.unit
def test_without_the_seam_the_call_is_unsupported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = default_runtime_context(workspace=tmp_path)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)

    with pytest.raises(ClientArchiveError) as exc:
        set_report_client_archived("acme", True)

    assert exc.value.code == "archive_unsupported"


@pytest.mark.unit
def test_a_raising_seam_becomes_a_clean_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backend fault is a clean 400-class refusal, and the backend's own
    message (which can carry deployment detail) never reaches the caller."""

    class _Exploding(_ArchivingStore):
        def set_client_archived(self, slug: str, archived: bool) -> None:
            raise RuntimeError("postgres://user:pw@internal-host/agency down")

    _use_store(monkeypatch, _Exploding())

    with pytest.raises(ClientArchiveError) as exc:
        set_report_client_archived("acme", True)

    assert exc.value.code == "archive_failed"
    assert "postgres" not in str(exc.value)
