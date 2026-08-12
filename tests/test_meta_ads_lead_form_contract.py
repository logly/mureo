"""Contract tests for two Meta Graph API v21.0 lead-form defects (2026-08-12).

1. ``follow_up_action_url`` was typed optional, but Meta requires it.
   Creating a form without it always fails with HTTP 400
   ``error_subcode 1892085`` / "Missing field(s): FollowUpActionURL", so
   every caller that followed mureo's schema hit a server round-trip
   failure. It is now a required parameter that fails at the call site.

2. The intro card's cover photo is write/read asymmetric. Create accepts
   ``context_card.cover_photo_id``, but Meta reads it back as
   ``context_card.cover_photo.id`` (``{id, created_time}``) — and asking
   for ``context_card{cover_photo_id}`` is rejected with
   ``(#100) Tried accessing nonexisting field (cover_photo_id)``. So
   ``duplicate_lead_form`` must normalize the read-back shape before
   re-posting it, or the duplicate loses its cover photo (or 400s).
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.meta_ads._leads import LeadsMixin


def _make_mock_client() -> LeadsMixin:
    """Build a LeadsMixin instance with mocked _get/_post/_ad_account_id."""

    class MockClient(LeadsMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})

    return MockClient()


def _import_meta_ads_tools():
    from mureo.mcp import tools_meta_ads

    return tools_meta_ads


def _import_handlers():
    from mureo.mcp import _handlers_meta_ads

    return _handlers_meta_ads


@pytest.fixture(autouse=True)
def _standalone_meta_ads():
    """Pin the handler test below to STANDALONE (untenanted) Meta Ads.

    Same reason as ``tests/test_meta_ads_leads.py``: a dev box carrying a
    ``mureo.runtime_context_factory`` plugin with a shared-auth
    multi-account store would fail-close every account_id and break the
    assertion for reasons unrelated to this contract.
    """
    with patch(
        "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
        return_value=None,
    ):
        yield


# ===========================================================================
# Defect 1 — follow_up_action_url is required by Meta
# ===========================================================================


@pytest.mark.unit
class TestFollowUpActionUrlRequired:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    def test_signature_has_no_default(self) -> None:
        """The parameter must have no default at all.

        A default (even ``None``) means a caller can omit it and only
        learn about ``error_subcode 1892085`` after a Meta round-trip.
        """
        param = inspect.signature(LeadsMixin.create_lead_form).parameters[
            "follow_up_action_url"
        ]
        assert param.default is inspect.Parameter.empty

    @pytest.mark.asyncio
    async def test_omitting_it_raises_type_error(self, client: LeadsMixin) -> None:
        """Omitting it fails at the call site, not at Meta."""
        with pytest.raises(TypeError):
            await client.create_lead_form(  # type: ignore[call-arg]
                page_id="page_123",
                name="no follow-up",
                questions=[{"type": "EMAIL"}],
                privacy_policy_url="https://example.com/privacy",
            )
        client._post.assert_not_called()

    @pytest.mark.asyncio
    async def test_always_emitted_into_payload(self, client: LeadsMixin) -> None:
        """A normal create always sends the field Meta demands."""
        await client.create_lead_form(
            page_id="page_123",
            name="basic",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/privacy",
            follow_up_action_url="https://example.com/thanks",
        )
        data = client._post.call_args[0][1]
        assert data["follow_up_action_url"] == "https://example.com/thanks"

    def test_tool_schema_lists_it_as_required(self) -> None:
        """The MCP schema must not advertise an optional field Meta rejects."""
        mod = _import_meta_ads_tools()
        tool = next(t for t in mod.TOOLS if t.name == "meta_ads_lead_forms_create")
        assert "follow_up_action_url" in tool.inputSchema["required"]

    async def test_handler_rejects_missing_follow_up_action_url(self) -> None:
        """``_require`` raises ValueError, which ``api_error_handler``
        re-raises untouched, so the caller sees a named-parameter error
        instead of a Meta 400."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        client = AsyncMock()
        creds = MagicMock()

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
            pytest.raises(ValueError, match="follow_up_action_url"),
        ):
            await mod.handle_tool(
                "meta_ads_lead_forms_create",
                {
                    "account_id": "act_123",
                    "page_id": "page_456",
                    "name": "contract form",
                    "questions": [{"type": "EMAIL"}],
                    "privacy_policy_url": "https://example.com/privacy",
                },
            )

        client.create_lead_form.assert_not_awaited()


# ===========================================================================
# Defect 1 (duplicate path) — a source form without the field cannot be copied
# ===========================================================================


@pytest.mark.unit
class TestDuplicateRequiresFollowUpActionUrl:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_missing_follow_up_action_url_raises(
        self, client: LeadsMixin
    ) -> None:
        """Mirrors the existing ``privacy_policy.url`` fail-fast: Meta
        requires the field at creation time, so the duplicate would 400
        server-side anyway."""
        source = {
            "id": "form_1",
            "name": "source form",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
        }
        client._get = AsyncMock(return_value=source)

        with pytest.raises(ValueError) as excinfo:
            await client.duplicate_lead_form(
                "form_1", page_id="page_123", new_name="Copy"
            )
        message = str(excinfo.value)
        assert "follow_up_action_url" in message
        assert "requires" in message
        client._post.assert_not_called()


# ===========================================================================
# Defect 2 — context_card cover photo write/read asymmetry
# ===========================================================================


@pytest.mark.unit
class TestDuplicateNormalizesContextCard:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @staticmethod
    def _source_with_cover() -> dict:
        return {
            "id": "form_1",
            "name": "source form",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
            "follow_up_action_url": "https://example.com/thanks",
            "context_card": {
                "title": "t",
                "content": "c",
                "style": "PARAGRAPH_STYLE",
                "cover_photo": {
                    "id": "122104778757409237",
                    "created_time": "2026-08-12T00:00:00+0000",
                },
                "id": "999",
            },
        }

    @pytest.mark.asyncio
    async def test_cover_photo_converted_to_cover_photo_id(
        self, client: LeadsMixin
    ) -> None:
        """Meta reads back ``cover_photo: {id, ...}`` but only accepts
        ``cover_photo_id`` on write."""
        client._get = AsyncMock(return_value=self._source_with_cover())
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form("form_1", page_id="page_123", new_name="Copy")

        card = json.loads(client._post.call_args[0][1]["context_card"])
        assert card["cover_photo_id"] == "122104778757409237"
        assert "cover_photo" not in card
        # The server-assigned card id is read-only — re-posting it 400s.
        assert "id" not in card
        assert card["title"] == "t"
        assert card["content"] == "c"
        assert card["style"] == "PARAGRAPH_STYLE"

    @pytest.mark.asyncio
    async def test_source_dict_is_not_mutated(self, client: LeadsMixin) -> None:
        """The normalization returns a new dict — the caller's read-back
        record stays exactly as Meta returned it."""
        source = self._source_with_cover()
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form("form_1", page_id="page_123", new_name="Copy")

        assert source["context_card"] == {
            "title": "t",
            "content": "c",
            "style": "PARAGRAPH_STYLE",
            "cover_photo": {
                "id": "122104778757409237",
                "created_time": "2026-08-12T00:00:00+0000",
            },
            "id": "999",
        }

    @pytest.mark.asyncio
    async def test_card_without_cover_photo_still_copied(
        self, client: LeadsMixin
    ) -> None:
        """No cover photo on the source means no ``cover_photo_id`` key —
        the rest of the card still travels."""
        source = {
            "id": "form_1",
            "name": "source form",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
            "follow_up_action_url": "https://example.com/thanks",
            "context_card": {
                "title": "t",
                "content": "c",
                "style": "LIST_STYLE",
                "id": "999",
            },
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form("form_1", page_id="page_123", new_name="Copy")

        card = json.loads(client._post.call_args[0][1]["context_card"])
        assert card == {"title": "t", "content": "c", "style": "LIST_STYLE"}
        assert "cover_photo_id" not in card
