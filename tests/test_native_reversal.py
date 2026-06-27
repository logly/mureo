"""Unit tests for native mutation before-state recording (#274).

Covers the pure reversal builder plus the best-effort STATE.json capture
and action_log promotion for native status toggles.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.mcp import native_reversal as nr


def _seed_state(d) -> None:
    from mureo.context.models import StateDocument
    from mureo.context.state import write_state_file

    write_state_file(d / "STATE.json", StateDocument())


# ---------------------------------------------------------------------------
# is_reversible_native_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsReversibleNativeTool:
    @pytest.mark.parametrize(
        "name",
        [
            "meta_ads_campaigns_pause",
            "meta_ads_campaigns_enable",
            "meta_ads_ad_sets_pause",
            "meta_ads_ad_sets_enable",
            "meta_ads_ads_pause",
            "meta_ads_ads_enable",
            "google_ads_campaigns_update_status",
            "google_ads_ads_update_status",
        ],
    )
    def test_status_toggles_are_reversible(self, name: str) -> None:
        assert nr.is_reversible_native_tool(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "meta_ads_campaigns_create",
            "meta_ads_ad_sets_update",
            "google_ads_budget_update",
            "meta_ads_campaigns_get",
            "google_ads_keywords_add",
        ],
    )
    def test_other_tools_are_not_reversible(self, name: str) -> None:
        assert nr.is_reversible_native_tool(name) is False


# ---------------------------------------------------------------------------
# build_reversal — Meta (dedicated pause/enable tools)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildReversalMeta:
    def test_prior_active_reverses_to_enable(self) -> None:
        rp = nr.build_reversal(
            "meta_ads_campaigns_pause", {"campaign_id": "c1"}, "ACTIVE"
        )
        assert rp == {
            "operation": "meta_ads_campaigns_enable",
            "params": {"campaign_id": "c1"},
        }

    def test_prior_paused_reverses_to_pause(self) -> None:
        rp = nr.build_reversal("meta_ads_ads_enable", {"ad_id": "a1"}, "PAUSED")
        assert rp == {
            "operation": "meta_ads_ads_pause",
            "params": {"ad_id": "a1"},
        }

    def test_ad_set_uses_ad_set_id(self) -> None:
        rp = nr.build_reversal("meta_ads_ad_sets_pause", {"ad_set_id": "s1"}, "ACTIVE")
        assert rp["operation"] == "meta_ads_ad_sets_enable"
        assert rp["params"] == {"ad_set_id": "s1"}

    def test_unrestorable_prior_status_yields_none(self) -> None:
        assert (
            nr.build_reversal(
                "meta_ads_campaigns_pause", {"campaign_id": "c1"}, "ARCHIVED"
            )
            is None
        )

    def test_missing_prior_status_yields_none(self) -> None:
        assert (
            nr.build_reversal("meta_ads_campaigns_pause", {"campaign_id": "c1"}, None)
            is None
        )

    def test_missing_id_arg_yields_none(self) -> None:
        assert nr.build_reversal("meta_ads_campaigns_pause", {}, "ACTIVE") is None


# ---------------------------------------------------------------------------
# build_reversal — Google (single update_status tool)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildReversalGoogle:
    def test_campaign_status_restores_prior(self) -> None:
        rp = nr.build_reversal(
            "google_ads_campaigns_update_status",
            {"campaign_id": "c1", "status": "PAUSED"},
            "ENABLED",
        )
        assert rp == {
            "operation": "google_ads_campaigns_update_status",
            "params": {"campaign_id": "c1", "status": "ENABLED"},
        }

    def test_ad_status_includes_ad_group_and_ad(self) -> None:
        rp = nr.build_reversal(
            "google_ads_ads_update_status",
            {"ad_group_id": "ag1", "ad_id": "a1", "status": "PAUSED"},
            "ENABLED",
        )
        assert rp == {
            "operation": "google_ads_ads_update_status",
            "params": {"ad_group_id": "ag1", "ad_id": "a1", "status": "ENABLED"},
        }

    def test_removed_prior_status_yields_none(self) -> None:
        assert (
            nr.build_reversal(
                "google_ads_campaigns_update_status",
                {"campaign_id": "c1", "status": "PAUSED"},
                "REMOVED",
            )
            is None
        )


# ---------------------------------------------------------------------------
# capture_before_state — best-effort GET before the mutation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCaptureBeforeState:
    async def test_non_reversible_tool_skips_capture(
        self, tmp_path, monkeypatch
    ) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert await nr.capture_before_state("meta_ads_campaigns_create", {}) is None

    async def test_no_state_file_skips_capture(self, tmp_path, monkeypatch) -> None:
        # STATE.json absent ⇒ no GET, no capture.
        monkeypatch.chdir(tmp_path)
        called = AsyncMock()
        monkeypatch.setattr("mureo.mcp._handlers_meta_ads._get_client", called)
        result = await nr.capture_before_state(
            "meta_ads_campaigns_pause", {"campaign_id": "c1"}
        )
        assert result is None
        called.assert_not_called()

    async def test_meta_capture_reads_status(self, tmp_path, monkeypatch) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)

        client = AsyncMock()
        client.get_campaign = AsyncMock(return_value={"id": "c1", "status": "ACTIVE"})
        monkeypatch.setattr(
            "mureo.mcp._handlers_meta_ads._get_client",
            AsyncMock(return_value=client),
        )
        status = await nr.capture_before_state(
            "meta_ads_campaigns_pause", {"campaign_id": "c1"}
        )
        assert status == "ACTIVE"
        client.get_campaign.assert_awaited_once_with("c1")

    async def test_google_ad_capture_finds_row(self, tmp_path, monkeypatch) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)

        client = AsyncMock()
        client.list_ads = AsyncMock(
            return_value=[
                {"id": "other", "status": "ENABLED"},
                {"id": "a1", "status": "PAUSED"},
            ]
        )
        monkeypatch.setattr(
            "mureo.mcp._handlers_google_ads._get_client",
            lambda args: client,
        )
        status = await nr.capture_before_state(
            "google_ads_ads_update_status",
            {"ad_group_id": "ag1", "ad_id": "a1", "status": "ENABLED"},
        )
        assert status == "PAUSED"

    async def test_capture_swallows_get_errors(self, tmp_path, monkeypatch) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)

        client = AsyncMock()
        client.get_campaign = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(
            "mureo.mcp._handlers_meta_ads._get_client",
            AsyncMock(return_value=client),
        )
        assert (
            await nr.capture_before_state(
                "meta_ads_campaigns_pause", {"campaign_id": "c1"}
            )
            is None
        )


# ---------------------------------------------------------------------------
# record_native_mutation — action_log promotion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordNativeMutation:
    def test_records_reversible_entry(self, tmp_path, monkeypatch) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        nr.record_native_mutation(
            "meta_ads_campaigns_pause", {"campaign_id": "c1"}, "ACTIVE"
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        entry = doc.action_log[0]
        assert entry.action == "meta_ads_campaigns_pause"
        assert entry.platform == "meta_ads"
        assert entry.observation_due is not None
        assert entry.reversible_params == {
            "operation": "meta_ads_campaigns_enable",
            "params": {"campaign_id": "c1"},
        }

    def test_records_audit_only_when_status_unknown(
        self, tmp_path, monkeypatch
    ) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        # No prior status captured ⇒ honest non-reversible audit entry.
        nr.record_native_mutation(
            "meta_ads_campaigns_pause", {"campaign_id": "c1"}, None
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        assert doc.action_log[0].reversible_params is None

    def test_no_state_file_is_noop(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        # Must not raise despite the absent STATE.json.
        nr.record_native_mutation(
            "meta_ads_campaigns_pause", {"campaign_id": "c1"}, "ACTIVE"
        )
        assert not (tmp_path / "STATE.json").exists()

    def test_non_status_tool_is_noop(self, tmp_path, monkeypatch) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        nr.record_native_mutation("meta_ads_campaigns_create", {"name": "X"}, None)
        doc = read_state_file(tmp_path / "STATE.json")
        assert doc.action_log == ()

    def test_skips_recording_on_api_error_result(self, tmp_path, monkeypatch) -> None:
        from mcp.types import TextContent

        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        # A failed mutation (api_error_handler envelope) must not be logged —
        # platform state did not change.
        nr.record_native_mutation(
            "meta_ads_campaigns_pause",
            {"campaign_id": "c1"},
            "ACTIVE",
            [TextContent(type="text", text="API error: permission denied")],
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert doc.action_log == ()

    def test_records_on_success_result(self, tmp_path, monkeypatch) -> None:
        from mcp.types import TextContent

        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        nr.record_native_mutation(
            "meta_ads_campaigns_pause",
            {"campaign_id": "c1"},
            "ACTIVE",
            [TextContent(type="text", text='{"id": "c1", "status": "PAUSED"}')],
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1


# ---------------------------------------------------------------------------
# shared is_error_result helper (one source of truth in _helpers)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSharedIsErrorResult:
    def test_native_alias_delegates_to_helper(self) -> None:
        # nr._is_error_result is a thin alias for the shared helper.
        from mcp.types import TextContent

        from mureo.mcp._helpers import is_error_result

        envelope = [TextContent(type="text", text="API error: boom")]
        assert is_error_result(envelope) is True
        assert nr._is_error_result(envelope) is True

    def test_empty_and_none_are_not_errors(self) -> None:
        from mureo.mcp._helpers import is_error_result

        assert is_error_result(None) is False
        assert is_error_result([]) is False

    def test_non_error_text_is_not_an_error(self) -> None:
        from mcp.types import TextContent

        from mureo.mcp._helpers import is_error_result

        assert is_error_result([TextContent(type="text", text="ok")]) is False
        # "Error:" alone is NOT the api_error_handler envelope — only the exact
        # "API error:" prefix counts, so plugin data starting with "Error" is
        # not mistaken for a failed mutation.
        assert is_error_result([TextContent(type="text", text="Error: data")]) is False

    def test_api_error_prefix_constant_matches_handler_output(self) -> None:
        # Pin the producer/detector contract: the prefix the handler stamps is
        # the prefix the detector keys off.
        from mureo.mcp._helpers import API_ERROR_PREFIX

        assert API_ERROR_PREFIX == "API error:"


# ---------------------------------------------------------------------------
# server.handle_call_tool wiring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDispatchWiring:
    async def test_status_toggle_captures_before_then_records_after(
        self, monkeypatch
    ) -> None:
        from mcp.types import TextContent

        from mureo.mcp import server as server_mod

        calls: list[Any] = []

        async def fake_capture(name: str, args: dict[str, Any]) -> str | None:
            calls.append(("capture", name))
            return "ACTIVE"

        async def fake_dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
            calls.append(("dispatch", name))
            return [TextContent(type="text", text="ok")]

        def fake_record(
            name: str,
            args: dict[str, Any],
            before: str | None,
            result: list[Any] | None = None,
        ) -> None:
            calls.append(("record", name, before))

        monkeypatch.setattr(server_mod, "capture_before_state", fake_capture)
        monkeypatch.setattr(server_mod, "handle_meta_ads_tool", fake_dispatch)
        monkeypatch.setattr(server_mod, "record_native_mutation", fake_record)
        monkeypatch.setattr(server_mod, "_evaluate_policy_gates", lambda n, a: None)

        out = await server_mod.handle_call_tool(
            "meta_ads_campaigns_pause", {"campaign_id": "c1"}
        )
        # Before-state is captured *before* dispatch; recording happens
        # *after* a successful dispatch, with the captured status.
        assert calls == [
            ("capture", "meta_ads_campaigns_pause"),
            ("dispatch", "meta_ads_campaigns_pause"),
            ("record", "meta_ads_campaigns_pause", "ACTIVE"),
        ]
        assert out[0].text == "ok"
