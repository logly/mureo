"""Every ChatGPT Ads tool that sends an ``Idempotency-Key`` ends a lost
answer with one sentence, whichever way the answer was lost.

The sentence is chosen in two places: the client picks it from the request's
policy after an exhausted 5xx, and ``handlers.run_tool`` picks it by tool name
when the call deadline fires (the deadline runs outside the client, so it
cannot read the request's policy). This module holds the two to the same
sentence naming the same key, for every tool offering ``idempotency_key``, so
a new key-bearing tool is covered without editing it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError
from tests._chatgpt_ads_fakes import FakeAPI, fail_tool, install_fake_api

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_KEY = "same-key_01"
#: Stands for the identifier file a membership change reads.
_FILE = "<file>"
_AUDIENCE = {"audience_id": "caud_1", "file_path": _FILE, "identifier_type": "email"}

#: Key-bearing tool → (the path it posts to, minimal valid arguments).
_CALLS: dict[str, tuple[str, dict[str, Any]]] = {
    "chatgpt_ads_campaigns_create": (
        "/campaigns",
        {
            "name": "Spring sale",
            "budget": {"daily_spend_limit_micros": 50_000_000},
            "bidding_type": "clicks",
        },
    ),
    "chatgpt_ads_ad_groups_create": (
        "/ad_groups",
        {
            "campaign_id": "c_1",
            "name": "Running shoes",
            "bidding_config": {
                "billing_event_type": "click",
                "strategy": "maximize_clicks",
            },
        },
    ),
    "chatgpt_ads_ads_create": (
        "/ads",
        {
            "ad_group_id": "g_1",
            "name": "Card one",
            "creative": {
                "type": "chat_card",
                "title": "Trail shoes",
                "body": "Light shoes for long runs.",
                "target_url": "https://example.com/shoes",
            },
        },
    ),
    "chatgpt_ads_audiences_members_add": ("/custom_audiences/caud_1/add", _AUDIENCE),
    "chatgpt_ads_audiences_members_remove": (
        "/custom_audiences/caud_1/remove",
        _AUDIENCE,
    ),
}


def _arguments(name: str, tmp_path: Path) -> dict[str, Any]:
    assert name in _CALLS, (
        f"{name} offers idempotency_key: add its path and minimal valid "
        "arguments to _CALLS in this module"
    )
    arguments = dict(_CALLS[name][1])
    if arguments.get("file_path") == _FILE:
        path = tmp_path / "list.txt"
        path.write_text("jamie@example.com\n", encoding="utf-8")
        arguments["file_path"] = str(path)
    return {**arguments, "idempotency_key": _KEY}


async def _deadline_sentence(
    monkeypatch: pytest.MonkeyPatch, name: str, arguments: dict[str, Any]
) -> str:
    async def _hang(_client: Any, _arguments: dict[str, Any]) -> Any:
        await asyncio.sleep(10)

    monkeypatch.setitem(handlers.HANDLERS, name, _hang)
    monkeypatch.setattr(handlers, "_open_client", lambda _k: FakeAPI().client())
    with pytest.raises(ChatGPTAdsAPIError) as info:
        await handlers.run_tool(name, arguments, "k", deadline=0.01)
    return str(info.value).split(" seconds ", 1)[1]


@pytest.mark.parametrize("name", sorted(handlers._IDEMPOTENT_TOOL_NAMES))
async def test_the_5xx_and_the_deadline_end_with_one_sentence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    arguments = _arguments(name, tmp_path)
    api = install_fake_api(monkeypatch)
    api.add(_CALLS[name][0], 502, {"error": {"message": "bad gateway"}})
    failure = await fail_tool(name, arguments)
    sentence = await _deadline_sentence(monkeypatch, name, arguments)
    assert f'idempotency_key="{_KEY}"' in sentence
    assert failure.detail.endswith(sentence)


def test_every_key_bearing_tool_has_a_row() -> None:
    assert set(_CALLS) == handlers._IDEMPOTENT_TOOL_NAMES
