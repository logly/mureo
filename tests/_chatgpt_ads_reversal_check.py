"""Proof that a recorded ChatGPT Ads reversal can run and restores the prior state.

Not a test module (no ``test_`` prefix). A reversal is only worth recording if
``rollback_apply`` can execute it: :func:`assert_reversal_restores` checks the
reversal's params against the named tool's ``inputSchema`` (what an MCP
client validates) and then runs the tool through
:func:`~mureo.chatgpt_ads.handlers.run_tool` against a fresh fake API (what the
handler validates and sends), comparing the one POST it makes with the prior
state the test read back.
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads.handlers import ALL_TOOLS
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from tests._chatgpt_ads_fakes import SENTINEL_KEY, FakeAPI, sent_body

_SCHEMAS = {t.name: t.inputSchema for t in ALL_TOOLS}

_ID_PATHS = (
    ("campaign_id", "/campaigns"),
    ("ad_group_id", "/ad_groups"),
    ("ad_id", "/ads"),
)


def _fake_for(params: dict[str, Any], prior_body: Any) -> FakeAPI:
    """A fake that answers every read a reversal's tool makes before its POST
    with the prior state, so a pre-write check sees what the capture saw."""
    fake = FakeAPI()
    for key, prefix in _ID_PATHS:
        if key in params:
            entity = f"{prefix}/{params[key]}"
            prior = prior_body if isinstance(prior_body, dict) else {}
            fake.add(entity, body={"id": params[key], **prior})
            fake.add(entity, body={"id": params[key]})
            for action in ("pause", "activate"):
                fake.add(f"{entity}/{action}", body={"id": params[key]})
    fake.add("/ad_account/spend_limit_windows", body={"object": "list"})
    fake.add("/ad_account/daily_spend_limit", body={"spend_limits": {}})
    return fake


async def assert_reversal_restores(found: dict[str, Any], prior_body: Any) -> None:
    """Fail unless ``found`` passes its tool's schema and, run, sends exactly
    one POST whose body is ``prior_body`` (``None`` = a POST without one)."""
    operation, params = found["operation"], found["params"]
    jsonschema.Draft202012Validator(_SCHEMAS[operation]).validate(params)
    fake = _fake_for(params, prior_body)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(handlers, "_open_client", lambda _key: fake.client())
        await handlers.run_tool(operation, params, SENTINEL_KEY)
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 1, [(r.method, r.url.path) for r in fake.requests]
    assert sent_body(posts[0]) == prior_body


_UNSET: Any = object()


async def capture_checked(
    name: str, arguments: dict[str, Any], restores: Any = _UNSET
) -> dict[str, Any] | None:
    """``capture_reversal(name, arguments)``, checked.

    A test that obtains a reversal names the request body that restores the
    prior state (``None`` = a POST without a body), and the reversal is run to
    prove it sends exactly that.
    """
    found = await ChatGPTAdsProvider().capture_reversal(name, arguments)
    if found is not None:
        # Every reversal names one of this provider's tools and carries only
        # that tool's top-level schema properties: the planner refuses
        # anything else.
        assert found["operation"] in _SCHEMAS
        assert set(found["params"]) <= set(_SCHEMAS[found["operation"]]["properties"])
        assert "caveats" not in found or found["caveats"]
        assert restores is not _UNSET, "state the body that restores the prior"
        await assert_reversal_restores(found, restores)
    return found
