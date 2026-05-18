"""Unit tests for the plugin audit trail (mureo.mcp.plugin_audit).

Phase 1 of #114: every plugin tool call is recorded to a dedicated
append-only JSONL log; secrets are masked; auditing never raises.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.mcp import plugin_audit
from mureo.mcp.plugin_audit import _mask, record_plugin_call

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
class TestMask:
    def test_sensitive_keys_redacted(self) -> None:
        masked = _mask(
            {
                "access_token": "abc",
                "client_secret": "s",
                "Authorization": "Bearer x",
                "api_key": "k",
                "refresh_token": "r",
                "cookie": "c",
                "campaign_id": "123",
                "name": "ok",
            }
        )
        assert masked["access_token"] == "***"
        assert masked["client_secret"] == "***"
        assert masked["Authorization"] == "***"
        assert masked["api_key"] == "***"
        assert masked["refresh_token"] == "***"
        assert masked["cookie"] == "***"
        # Non-sensitive values pass through unchanged.
        assert masked["campaign_id"] == "123"
        assert masked["name"] == "ok"

    def test_long_string_truncated(self) -> None:
        out = _mask("x" * 1000)
        assert out.endswith("…<truncated>")
        assert len(out) < 1000

    def test_nested_and_list_masked_and_capped(self) -> None:
        out = _mask({"outer": {"secret": "v", "ok": 1}, "items": list(range(80))})
        assert out["outer"]["secret"] == "***"
        assert out["outer"]["ok"] == 1
        assert len(out["items"]) == 50  # list cap

    def test_depth_guard(self) -> None:
        deep: dict = {}
        cur = deep
        for _ in range(8):
            cur["n"] = {}
            cur = cur["n"]
        # Does not raise / infinite-recurse; deep levels collapse.
        assert _mask(deep) is not None


@pytest.mark.unit
class TestRecordPluginCall:
    def test_writes_masked_jsonl_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "sub" / "plugin_audit.jsonl"
        monkeypatch.setattr(plugin_audit, "_audit_path", lambda: log)

        record_plugin_call(
            tool="acme_ads_pause",
            arguments={"campaign_id": "c1", "api_key": "SHHH"},
            source="acme-ads-plugin",
            ok=True,
        )
        record_plugin_call(
            tool="acme_ads_pause",
            arguments={"x": 1},
            source="acme-ads-plugin",
            ok=False,
            error="boom",
        )

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2  # append-only
        first = json.loads(lines[0])
        assert first["tool"] == "acme_ads_pause"
        assert first["source"] == "acme-ads-plugin"
        assert first["ok"] is True
        assert first["args"]["campaign_id"] == "c1"
        assert first["args"]["api_key"] == "***"  # secret masked
        assert "ts" in first
        second = json.loads(lines[1])
        assert second["ok"] is False
        assert second["error"] == "boom"

    def test_never_raises_on_io_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> Path:
            raise OSError("disk gone")

        monkeypatch.setattr(plugin_audit, "_audit_path", _boom)
        # Must swallow — auditing can never break the tool call.
        record_plugin_call(tool="t", arguments={}, source="s", ok=True)  # no exception
