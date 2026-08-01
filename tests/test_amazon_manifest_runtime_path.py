"""#516 — the Amazon tool manifest must live in ONE runtime-resolved place.

Before the fix the writers and the readers disagreed whenever a
``mureo.runtime_context_factory`` relocated the credentials file:

- the configure-UI generator and the dashboard's staleness row derived
  the manifest from the runtime-resolved ``credentials_path``
  (``<relocated>/amazon_tools.json``);
- ``AmazonAdsBridge`` and ``mureo amazon`` read
  ``mureo.amazon_ads.manifest.manifest_path()``, hardcoded to
  ``~/.mureo/amazon_tools.json``.

Live proof of the split-brain: a manifest carrying 85 Amazon tools sat on
disk while ``AmazonAdsBridge().mcp_tools()`` returned zero.

The fix makes ``manifest_path()`` resolve the credentials path through
:func:`mureo.core.runtime_context.runtime_credentials_path` (the #512
precedent) and routes every consumer through
:func:`mureo.amazon_ads.manifest.manifest_path_for`, so exactly one place
decides the location. With no factory registered the result is
byte-identical to the historical default.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from mcp.types import Tool

from mureo.amazon_ads.bridge import AmazonAdsBridge
from mureo.amazon_ads.manifest import (
    MANIFEST_FILENAME,
    manifest_path,
    manifest_path_for,
)
from mureo.auth import AmazonAdsCredentials
from mureo.core.runtime_context import default_runtime_context, reset_runtime_context

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Entry-point stubs — same shape as tests/test_web_credentials_runtime_alignment
# ---------------------------------------------------------------------------


class _FakeEP:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "mureo.runtime_context_factory"
        return eps

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)


def _relocate(monkeypatch: pytest.MonkeyPatch, credentials_path: Path) -> None:
    """Register a runtime context whose credentials live at ``credentials_path``."""
    _patch_entry_points(
        monkeypatch,
        [
            _FakeEP(
                "alt",
                lambda: default_runtime_context(credentials_path=credentials_path),
            )
        ],
    )


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    """The resolved context is a process-wide singleton; keep it out of
    neighbouring tests."""
    reset_runtime_context()
    yield
    reset_runtime_context()


# Two REAL Amazon tool names (region ``fe`` manifest, 85 tools), with their
# schemas cut down to what the round trip asserts on.
_REAL_TOOLS = [
    Tool(
        name="campaign_management-update_campaign_budget",
        description="Update the budget of one or more campaigns.",
        inputSchema={"type": "object", "properties": {"body": {"type": "object"}}},
    ),
    Tool(
        name="billing-list_invoice_summaries",
        description="List invoice summaries.",
        inputSchema={"type": "object", "properties": {"body": {"type": "object"}}},
    ),
]


def _fake_connect(tools: list[Tool]) -> Any:
    class _Session:
        async def initialize(self) -> None:
            return None

        async def list_tools(self) -> Any:
            return type("R", (), {"tools": tools})()

    class _CM:
        def __init__(self, url: str, headers: dict[str, str]) -> None:
            pass

        async def __aenter__(self) -> Any:
            return _Session()

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return _CM


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManifestPathResolver:
    def test_no_runtime_context_keeps_the_legacy_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Byte-identical to what shipped before: ``~/.mureo/amazon_tools.json``."""
        _patch_entry_points(monkeypatch, [])
        assert manifest_path() == Path.home() / ".mureo" / MANIFEST_FILENAME

    def test_a_relocating_runtime_moves_the_manifest_with_the_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _relocate(monkeypatch, tmp_path / "shared" / "credentials.json")
        assert manifest_path() == tmp_path / "shared" / MANIFEST_FILENAME

    def test_manifest_path_for_is_the_single_location_rule(
        self, tmp_path: Path
    ) -> None:
        creds = tmp_path / "anywhere" / "credentials.json"
        assert manifest_path_for(creds) == tmp_path / "anywhere" / MANIFEST_FILENAME


# ---------------------------------------------------------------------------
# Consumers resolve through the same rule
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConsumersAgree:
    def test_bridge_default_follows_the_relocated_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        relocated = tmp_path / "shared" / "credentials.json"
        _relocate(monkeypatch, relocated)
        from mureo.amazon_ads.bridge import _default_manifest_path

        assert _default_manifest_path() == manifest_path_for(relocated)

    def test_status_collector_row_reads_the_same_file(self, tmp_path: Path) -> None:
        from mureo.web.status_collector import _detect_amazon_manifest

        relocated = tmp_path / "shared" / "credentials.json"
        relocated.parent.mkdir(parents=True)
        manifest_path_for(relocated).write_text(
            json.dumps({"generated_at": "2026-08-01T00:00:00+00:00", "tools": []}),
            encoding="utf-8",
        )
        assert _detect_amazon_manifest(relocated)["present"] is True

    def test_handler_writes_where_the_bridge_reads(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The round trip that #516 broke: generate through the configure-UI
        helper, then read through the bridge's own default path."""
        from mureo.web.handlers import _generate_amazon_manifest

        relocated = tmp_path / "shared" / "credentials.json"
        relocated.parent.mkdir(parents=True)
        _relocate(monkeypatch, relocated)
        monkeypatch.setattr(
            "mureo.amazon_ads.manifest._default_connect", _fake_connect(_REAL_TOOLS)
        )

        written, detail = _generate_amazon_manifest(
            AmazonAdsCredentials(client_id="cid", access_token="Atza|tok", region="fe"),
            relocated,
        )
        assert detail == ""
        assert written == tmp_path / "shared" / MANIFEST_FILENAME

        served = AmazonAdsBridge().mcp_tools()
        assert [t.name for t in served] == [t.name for t in _REAL_TOOLS]

    def test_without_a_runtime_context_the_round_trip_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No factory ⇒ the writer still targets the handed-in credentials
        tree (an injected home must never be answered with the real one)."""
        from mureo.web.handlers import _generate_amazon_manifest

        _patch_entry_points(monkeypatch, [])
        creds_path = tmp_path / "home" / ".mureo" / "credentials.json"
        creds_path.parent.mkdir(parents=True)
        monkeypatch.setattr(
            "mureo.amazon_ads.manifest._default_connect", _fake_connect(_REAL_TOOLS)
        )

        written, detail = _generate_amazon_manifest(
            AmazonAdsCredentials(client_id="cid", access_token="Atza|tok", region="fe"),
            creds_path,
        )
        assert detail == ""
        assert written == creds_path.parent / MANIFEST_FILENAME
        assert AmazonAdsBridge(manifest_path=written).mcp_tools()
