"""MCP surface for Performance Max asset-group assets (#590, #626).

Tool schemas, handler wiring, and the two classification seams a new tool
has to land on the right side of: the strategy-reminder mutation
classifier (a write that reads as a read gets no reminder) and the
rollback planner's report-only vocabulary (a read that reads as a write is
reported as un-revertible).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_LIST_TOOL = "google_ads_asset_group_assets_list"
_REPLACE_TOOL = "google_ads_asset_group_assets_replace"
_REPLACE_IMAGE_TOOL = "google_ads_asset_group_images_replace"


def _import_google_ads_tools():
    from mureo.mcp import tools_google_ads

    return tools_google_ads


def _import_handlers():
    from mureo.mcp import _handlers_google_ads

    return _handlers_google_ads


def _tool(name: str) -> Any:
    mod = _import_google_ads_tools()
    return next(t for t in mod.TOOLS if t.name == name)


@pytest.fixture(autouse=True)
def _standalone_google_ads():
    """Pin these handler tests to STANDALONE (untenanted) Google Ads (#411)."""
    with patch(
        "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
        return_value=None,
    ):
        yield


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssetGroupToolDefinitions:
    def test_all_three_tools_are_registered(self) -> None:
        names = {t.name for t in _import_google_ads_tools().TOOLS}
        assert {_LIST_TOOL, _REPLACE_TOOL, _REPLACE_IMAGE_TOOL} <= names

    def test_list_takes_no_required_parameter(self) -> None:
        schema = _tool(_LIST_TOOL).inputSchema
        assert schema["required"] == []
        assert set(schema["properties"]) == {
            "customer_id",
            "asset_group_id",
            "campaign_id",
        }

    def test_replace_requires_the_full_swap(self) -> None:
        schema = _tool(_REPLACE_TOOL).inputSchema
        assert set(schema["required"]) == {
            "asset_group_id",
            "field_type",
            "old_asset_id",
            "new_text",
        }

    def test_field_type_is_enum_locked_to_the_three_text_types(self) -> None:
        from mureo.google_ads._asset_groups import PMAX_TEXT_FIELD_TYPES

        enum = _tool(_REPLACE_TOOL).inputSchema["properties"]["field_type"]["enum"]
        assert set(enum) == set(PMAX_TEXT_FIELD_TYPES)

    def test_new_text_is_bounded_by_the_widest_field_limit(self) -> None:
        """The schema cannot vary the cap by field_type, so it carries the
        widest one and the client layer enforces the per-type width."""
        from mureo.google_ads._asset_groups import PMAX_TEXT_FIELD_TYPES

        prop = _tool(_REPLACE_TOOL).inputSchema["properties"]["new_text"]
        assert prop["maxLength"] == max(PMAX_TEXT_FIELD_TYPES.values())
        assert prop["minLength"] == 1

    def test_the_read_points_at_the_write_and_back(self) -> None:
        """An agent that found one tool must be able to find the other."""
        assert _REPLACE_TOOL in _tool(_LIST_TOOL).description
        assert _LIST_TOOL in _tool(_REPLACE_TOOL).description


@pytest.mark.unit
class TestImageToolDefinition:
    """#626: the image half of the same surface."""

    def test_image_field_type_is_enum_locked_to_the_five_image_types(self) -> None:
        from mureo.google_ads._asset_groups import PMAX_IMAGE_FIELD_TYPES

        schema = _tool(_REPLACE_IMAGE_TOOL).inputSchema
        assert set(schema["properties"]["field_type"]["enum"]) == set(
            PMAX_IMAGE_FIELD_TYPES
        )

    def test_neither_image_source_is_required_but_both_are_offered(self) -> None:
        """ "Exactly one of" is not expressible in ``required``; the client
        enforces it so every caller gets the rule, not just this schema."""
        schema = _tool(_REPLACE_IMAGE_TOOL).inputSchema
        assert set(schema["required"]) == {
            "asset_group_id",
            "field_type",
            "old_asset_id",
        }
        assert {"new_asset_id", "new_image_path"} <= set(schema["properties"])

    def test_one_tool_covers_both_situations(self) -> None:
        """The operator must not have to work out whether the account
        already holds the image in order to pick a tool name."""
        description = _tool(_REPLACE_IMAGE_TOOL).description
        assert "new_asset_id" in description
        assert "new_image_path" in description
        assert "exactly one" in description.lower()

    def test_the_description_names_the_shape_of_every_slot(self) -> None:
        """An agent that cannot see the rule will offer an image that gets
        refused."""
        description = _tool(_REPLACE_IMAGE_TOOL).description
        for rule in ("1.91:1", "1:1", "4:5", "4:1"):
            assert rule in description
        assert "resize" in description

    def test_the_read_and_the_two_writes_point_at_each_other(self) -> None:
        assert _REPLACE_IMAGE_TOOL in _tool(_LIST_TOOL).description
        assert _LIST_TOOL in _tool(_REPLACE_IMAGE_TOOL).description
        assert _REPLACE_TOOL in _tool(_REPLACE_IMAGE_TOOL).description

    def test_the_read_advertises_the_image_columns(self) -> None:
        """#591's defect in reverse: describing the read as text-only now
        hides half of what it returns."""
        description = _tool(_LIST_TOOL).description
        for column in ("asset_name", "url", "width_pixels", "height_pixels"):
            assert column in description
        assert "MARKETING_IMAGE" in description


# ---------------------------------------------------------------------------
# Name-shape classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolNameClassification:
    def test_replace_is_classified_as_a_mutation(self) -> None:
        """A write the classifier reads as a read gets no STRATEGY.md
        reminder and no batch reminder."""
        from mureo.core.strategy_reminder import is_mutating_builtin_tool

        assert is_mutating_builtin_tool(_REPLACE_TOOL) is True

    def test_list_is_not_classified_as_a_mutation(self) -> None:
        from mureo.core.strategy_reminder import is_mutating_builtin_tool

        assert is_mutating_builtin_tool(_LIST_TOOL) is False

    def test_list_reads_as_report_only_to_the_rollback_planner(self) -> None:
        from mureo.core.tool_names import reads_as_a_report_only_action

        assert reads_as_a_report_only_action(_LIST_TOOL) is True

    def test_replace_does_not_read_as_report_only(self) -> None:
        from mureo.core.tool_names import reads_as_a_report_only_action

        assert reads_as_a_report_only_action(_REPLACE_TOOL) is False

    def test_the_image_replace_is_classified_as_a_mutation(self) -> None:
        """#590 found `_replace` missing from the classifier's suffixes the
        hard way. The image tool's name has to land on the same entry."""
        from mureo.core.strategy_reminder import is_mutating_builtin_tool

        assert is_mutating_builtin_tool(_REPLACE_IMAGE_TOOL) is True

    def test_the_image_replace_does_not_read_as_report_only(self) -> None:
        from mureo.core.tool_names import reads_as_a_report_only_action

        assert reads_as_a_report_only_action(_REPLACE_IMAGE_TOOL) is False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _mock_google_ads_context() -> tuple[Any, Any]:
    return MagicMock(), AsyncMock()


@pytest.mark.unit
class TestAssetGroupHandlers:
    async def test_list_forwards_both_filters(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_asset_group_assets.return_value = [
            {"asset_id": "111", "text": "Old", "field_type": "HEADLINE"},
            {"asset_id": "555", "url": "https://x/555", "field_type": "LOGO"},
        ]

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                _LIST_TOOL,
                {
                    "customer_id": "1234567890",
                    "asset_group_id": "4242",
                    "campaign_id": "900",
                },
            )

        client.list_asset_group_assets.assert_awaited_once_with(
            asset_group_id="4242", campaign_id="900"
        )
        parsed = json.loads(result[0].text)
        assert parsed[0]["asset_id"] == "111"
        assert parsed[1]["url"] == "https://x/555"

    async def test_list_without_filters_passes_none(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.list_asset_group_assets.return_value = []

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            await mod.handle_tool(_LIST_TOOL, {"customer_id": "1234567890"})

        client.list_asset_group_assets.assert_awaited_once_with(
            asset_group_id=None, campaign_id=None
        )

    async def test_replace_forwards_the_swap(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.replace_asset_group_text_asset.return_value = {
            "asset_group_id": "4242",
            "field_type": "HEADLINE",
            "added": {"asset_id": "777", "text": "New copy"},
            "removed": {"asset_id": "111", "text": "Old copy"},
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                _REPLACE_TOOL,
                {
                    "customer_id": "1234567890",
                    "asset_group_id": "4242",
                    "field_type": "HEADLINE",
                    "old_asset_id": "111",
                    "new_text": "New copy",
                },
            )

        client.replace_asset_group_text_asset.assert_awaited_once_with(
            {
                "asset_group_id": "4242",
                "field_type": "HEADLINE",
                "old_asset_id": "111",
                "new_text": "New copy",
            }
        )
        parsed = json.loads(result[0].text)
        assert parsed["added"]["text"] == "New copy"
        assert parsed["removed"]["asset_id"] == "111"

    @pytest.mark.parametrize(
        "missing", ["asset_group_id", "field_type", "old_asset_id", "new_text"]
    )
    async def test_replace_requires_every_swap_parameter(self, missing: str) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        args = {
            "customer_id": "1234567890",
            "asset_group_id": "4242",
            "field_type": "HEADLINE",
            "old_asset_id": "111",
            "new_text": "New copy",
        }
        args.pop(missing)

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
            pytest.raises(ValueError, match=missing),
        ):
            await mod.handle_tool(_REPLACE_TOOL, args)

        client.replace_asset_group_text_asset.assert_not_awaited()


@pytest.mark.unit
class TestAssetGroupImageHandlers:
    async def test_forwards_an_existing_asset_swap(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.replace_asset_group_image_asset.return_value = {
            "asset_group_id": "4242",
            "field_type": "MARKETING_IMAGE",
            "added": {"asset_id": "777", "source": "existing_asset"},
            "removed": {"asset_id": "555"},
        }

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                _REPLACE_IMAGE_TOOL,
                {
                    "customer_id": "1234567890",
                    "asset_group_id": "4242",
                    "field_type": "MARKETING_IMAGE",
                    "old_asset_id": "555",
                    "new_asset_id": "777",
                },
            )

        client.replace_asset_group_image_asset.assert_awaited_once_with(
            {
                "asset_group_id": "4242",
                "field_type": "MARKETING_IMAGE",
                "old_asset_id": "555",
                "new_asset_id": "777",
            }
        )
        assert json.loads(result[0].text)["added"]["asset_id"] == "777"

    async def test_forwards_an_upload_swap_with_its_name(self) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.replace_asset_group_image_asset.return_value = {"added": {}}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            await mod.handle_tool(
                _REPLACE_IMAGE_TOOL,
                {
                    "customer_id": "1234567890",
                    "asset_group_id": "4242",
                    "field_type": "LOGO",
                    "old_asset_id": "555",
                    "new_image_path": "/tmp/logo.png",
                    "new_image_name": "Autumn logo",
                },
            )

        client.replace_asset_group_image_asset.assert_awaited_once_with(
            {
                "asset_group_id": "4242",
                "field_type": "LOGO",
                "old_asset_id": "555",
                "new_image_path": "/tmp/logo.png",
                "new_image_name": "Autumn logo",
            }
        )

    async def test_an_absent_source_is_not_forwarded_as_none(self) -> None:
        """The client decides "exactly one of"; a ``None`` sitting in the
        params would make an absent argument look supplied."""
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        client.replace_asset_group_image_asset.return_value = {"added": {}}

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
        ):
            await mod.handle_tool(
                _REPLACE_IMAGE_TOOL,
                {
                    "customer_id": "1234567890",
                    "asset_group_id": "4242",
                    "field_type": "LOGO",
                    "old_asset_id": "555",
                    "new_asset_id": "777",
                },
            )

        params = client.replace_asset_group_image_asset.await_args.args[0]
        assert "new_image_path" not in params
        assert "new_image_name" not in params

    @pytest.mark.parametrize(
        "missing", ["asset_group_id", "field_type", "old_asset_id"]
    )
    async def test_requires_every_targeting_parameter(self, missing: str) -> None:
        mod = _import_google_ads_tools()
        creds, client = _mock_google_ads_context()
        args = {
            "customer_id": "1234567890",
            "asset_group_id": "4242",
            "field_type": "MARKETING_IMAGE",
            "old_asset_id": "555",
            "new_asset_id": "777",
        }
        args.pop(missing)

        h = _import_handlers()
        with (
            patch.object(h, "load_google_ads_credentials", return_value=creds),
            patch.object(h, "create_google_ads_client", return_value=client),
            pytest.raises(ValueError, match=missing),
        ):
            await mod.handle_tool(_REPLACE_IMAGE_TOOL, args)

        client.replace_asset_group_image_asset.assert_not_awaited()


# ---------------------------------------------------------------------------
# BYOD
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    ["replace_asset_group_text_asset", "replace_asset_group_image_asset"],
)
def test_the_swaps_are_refused_in_byod_read_only_mode(
    tmp_path: Any, method: str
) -> None:
    """A BYOD client answers unknown READS with an empty list; a write must
    not take that path and read as a swap that quietly did nothing."""
    import asyncio

    from mureo.byod.clients import ByodGoogleAdsClient

    client = ByodGoogleAdsClient(data_dir=tmp_path / "google_ads")
    result = asyncio.run(getattr(client, method)({"a": 1}))
    assert result["status"] == "skipped_in_byod_readonly"
    assert result["operation"] == method
