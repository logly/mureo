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

    def test_error_string_secret_shapes_scrubbed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M1: ``error`` is free text (not key/value-masked). Bearer /
        LwA token shapes in it must be redacted — the Amazon bridge is
        the first credentialed plugin path."""
        log = tmp_path / "audit.jsonl"
        monkeypatch.setattr(plugin_audit, "_audit_path", lambda: log)
        record_plugin_call(
            tool="t",
            arguments={},
            source="s",
            ok=False,
            error=(
                "HTTPError 401: Authorization: Bearer Atza|SECRETTOKEN.abc "
                "refresh Atzr|SECRETREFRESH-xyz failed"
            ),
        )
        rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        assert "SECRETTOKEN" not in rec["error"]
        assert "SECRETREFRESH" not in rec["error"]
        assert "***" in rec["error"]
        assert "HTTPError 401" in rec["error"]  # non-secret text preserved

    def test_error_string_key_value_secrets_scrubbed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An HTTP client that echoes the form body it POSTed spills the
        client secret in plain text — a shape the token-prefix patterns
        cannot see, because an LwA client secret has no prefix."""
        log = tmp_path / "audit.jsonl"
        monkeypatch.setattr(plugin_audit, "_audit_path", lambda: log)
        record_plugin_call(
            tool="t",
            arguments={},
            source="s",
            ok=False,
            error=(
                "POST failed with body grant_type=authorization_code&"
                "code=ANsecretCode123&client_secret=SECRET-CLIENT-VALUE"
            ),
        )
        rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        assert "SECRET-CLIENT-VALUE" not in rec["error"]
        assert "ANsecretCode123" not in rec["error"]
        # The keys survive so the message still says what failed.
        assert "client_secret=***" in rec["error"]
        assert "code=***" in rec["error"]
        assert "grant_type=authorization_code" in rec["error"]


@pytest.mark.unit
class TestScrubFreeText:
    """``_scrub`` must redact credential VALUES without eating the
    diagnostic around them — an over-eager scrubber makes every error
    unactionable, which is its own kind of failure."""

    @pytest.mark.parametrize(
        ("text", "leaked"),
        [
            ("client_secret=amzn1.oa2-cs.v1.abcdef", "amzn1.oa2-cs.v1.abcdef"),
            ("client_secret: amzn1.oa2-cs.v1.abcdef", "amzn1.oa2-cs.v1.abcdef"),
            ("{'client_secret': 'shhhh-value'}", "shhhh-value"),
            ("refresh_token=Atzr-plain-shaped-value", "Atzr-plain-shaped-value"),
            ("access_token = plain-shaped-value", "plain-shaped-value"),
            ("api_key=sk-1234567890", "sk-1234567890"),
            ("api-key=sk-1234567890", "sk-1234567890"),
            ("password=hunter2hunter2", "hunter2hunter2"),
            ("?code=ANabcdefgh12&scope=x", "ANabcdefgh12"),
            ("{'code': 'ANabcdefgh12'}", "ANabcdefgh12"),
            ("Authorization: Bearer Atza|abc", "Atza|abc"),
        ],
    )
    def test_credential_values_are_redacted(self, text: str, leaked: str) -> None:
        scrubbed = plugin_audit._scrub(text)
        assert leaked not in scrubbed
        assert "***" in scrubbed

    @pytest.mark.parametrize(
        "text",
        [
            # ``code`` is the false-positive minefield: ordinary prose
            # about HTTP/errno codes must survive intact.
            "HTTP 400 status code= 400 for the request",
            "response status_code=400 and code=17",
            "error code: 12345678 from upstream",
            "LwA authorization-code exchange failed (HTTP 500, error='server_error')",
            "cannot exchange: no client_secret in amazon_ads credentials",
            "Amazon rejected the authorization code (error='invalid_grant'). "
            "Codes are single-use and expire 5 minutes after consent",
        ],
    )
    def test_ordinary_diagnostics_survive_unchanged(self, text: str) -> None:
        assert plugin_audit._scrub(text) == text
