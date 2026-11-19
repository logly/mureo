"""ChatGPT Ads rides the plugin collect/dispatch path of the MCP server.

The bundled provider is served like any entry-point plugin: all its tools
are listed, a call reaches the provider (and the plugin audit), a read never
lands in ``STATE.json``'s ``action_log``, and ``MUREO_DISABLE_CHATGPT_ADS=1``
removes every tool. How a mutation lands in ``action_log`` is pinned in
``test_chatgpt_ads_reversal.py``.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools_mutations import MUTATION_TOOLS
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI
from tests._server_reload import reloaded_server

pytestmark = pytest.mark.unit

_NAMES = {
    "chatgpt_ads_account_get",
    "chatgpt_ads_campaigns_list",
    "chatgpt_ads_campaigns_get",
    "chatgpt_ads_ad_groups_list",
    "chatgpt_ads_ad_groups_get",
    "chatgpt_ads_ads_list",
    "chatgpt_ads_ads_get",
    "chatgpt_ads_insights_report",
    "chatgpt_ads_change_history_list",
    *(t.name for t in MUTATION_TOOLS),
}


def _no_thirdparty(**_kw: Any) -> tuple[()]:
    return ()


@contextlib.contextmanager
def _server(env: dict[str, str | None] | None = None):  # type: ignore[no-untyped-def]
    with reloaded_server(
        _no_thirdparty,
        patches={"mureo.core.providers.default_registry._entries": {}},
        env=env,
    ) as mod:
        yield mod


async def test_every_tool_is_listed_and_owned_by_the_provider() -> None:
    with _server() as mod:
        listed = {t.name for t in await mod.handle_list_tools()}
        assert listed >= _NAMES
        for name in _NAMES:
            assert isinstance(mod._PLUGIN_DISPATCH[name], ChatGPTAdsProvider)
        assert {
            n for n, o in mod._plugin_tool_owners().items() if o == "chatgpt_ads"
        } == _NAMES


async def test_dispatch_reaches_the_provider_and_is_not_promoted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.context.models import StateDocument
    from mureo.context.state import read_state_file, write_state_file
    from mureo.mcp import plugin_audit

    write_state_file(tmp_path / "STATE.json", StateDocument())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: tmp_path / "audit.jsonl")
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)
    api = FakeAPI().add("/ad_account", body={"id": "adacct_1"})
    monkeypatch.setattr(handlers, "_open_client", lambda _key: api.client())
    with _server() as mod:
        out = await mod.handle_call_tool("chatgpt_ads_account_get", {})
    assert json.loads(out[0].text) == {"id": "adacct_1"}
    audit = [
        json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()
    ]
    assert audit[-1]["source"] == "mureo-chatgpt-ads"
    assert read_state_file(tmp_path / "STATE.json").action_log == ()
    assert SENTINEL_KEY not in (tmp_path / "audit.jsonl").read_text()


async def test_the_disable_switch_removes_every_tool() -> None:
    with _server(env={"MUREO_DISABLE_CHATGPT_ADS": "1"}) as mod:
        listed = {t.name for t in await mod.handle_list_tools()}
        assert not (listed & _NAMES)
