"""Shared fakes for the ``tests/test_chatgpt_ads_*`` modules.

Not a test module (no ``test_`` prefix). HTTP is faked with
``httpx.MockTransport``: every request is recorded, answered from a route
table, and nothing reaches the network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
from mcp.types import Tool

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads.client import ChatGPTAdsClient
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.core.tool_failure import Failure, failure_of
from mureo.mcp import server as mcp_server
from mureo.mcp.plugin_semantics import derive_semantics
from mureo.policy.strategy_gate import StrategyPolicyGate

#: An obvious stand-in for the operator's API key. Every hygiene test asserts
#: this string appears in no log record, exception text or tool result.
SENTINEL_KEY = "sk-ads-SENTINEL-DO-NOT-LEAK-0123456789"

_FIXTURE = Path(__file__).parent / "fixtures" / "chatgpt_ads_openapi_subset.json"

#: One routed answer: status, JSON (or raw text) body, optional headers.
Answer = tuple[int, Any, dict[str, str]]


def openapi_operations() -> list[dict[str, Any]]:
    """The contract fixture's operations, cut from the OpenAPI document."""
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["operations"]


def openapi_fixture_version() -> str:
    """The ``info.version`` of the OpenAPI document the fixture was cut from."""
    return str(json.loads(_FIXTURE.read_text(encoding="utf-8"))["openapi_version"])


def _template_regex(template: str) -> re.Pattern[str]:
    return re.compile("^/v1" + re.sub(r"\{[^}]+\}", "[^/]+", template) + "$")


#: Request headers every call carries, which no operation lists.
_COMMON_HEADERS = frozenset(
    {
        "host",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
        "authorization",
        "content-length",
        "content-type",
    }
)


def is_multipart(request: httpx.Request) -> bool:
    return request.headers.get("content-type", "").startswith("multipart/form-data")


def sent_body(request: httpx.Request) -> Any:
    """The decoded JSON body of ``request``, or ``None`` when it sent none."""
    return json.loads(request.content) if request.content else None


def multipart_parts(request: httpx.Request) -> dict[str, dict[str, Any]]:
    """Each form field of a multipart ``request``: its headers and its bytes."""
    boundary = request.headers["content-type"].split("boundary=", 1)[1].encode()
    parts: dict[str, dict[str, Any]] = {}
    for chunk in request.content.split(b"--" + boundary)[1:-1]:
        head, _, data = chunk.strip(b"\r\n").partition(b"\r\n\r\n")
        headers = dict(
            line.split(": ", 1) for line in head.decode().split("\r\n") if line
        )
        name = re.search(r'name="([^"]*)"', headers["Content-Disposition"])
        assert name is not None, headers
        parts[name.group(1)] = {"headers": headers, "content": data}
    return parts


def _paths(value: Any, prefix: str = "") -> set[str]:
    """Every dotted property path inside ``value`` (``[]`` = array item)."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            found |= {path, *_paths(item, path)}
    elif isinstance(value, list):
        for item in value:
            found |= _paths(item, f"{prefix}[]")
    return found


def _check_body(op: dict[str, Any], request: httpx.Request) -> None:
    where = request.url.path
    if is_multipart(request):
        extra = set(multipart_parts(request)) - set(op.get("multipart", ()))
        assert not extra, f"{where}: undocumented form fields {extra}"
        return
    body = sent_body(request)
    if body is None:
        return
    assert isinstance(body, dict), f"{where}: body not an object"
    extra = set(body) - set(op.get("body", ()))
    assert not extra, f"{where}: undocumented body keys {extra}"
    if "fields" in op:
        nested = _paths(body) - set(op["fields"])
        assert not nested, f"{where}: undocumented body fields {nested}"


def assert_matches_contract(request: httpx.Request) -> None:
    """Fail unless the request's path, query names, extra headers and body
    keys (nested ones too, where the fixture lists ``fields``) are in the
    fixture. An operation the fixture lists without ``body`` takes none."""
    for op in openapi_operations():
        if op["method"] == request.method and _template_regex(op["path"]).match(
            request.url.path
        ):
            unknown = {k for k, _ in request.url.params.multi_items()} - set(
                op["query"]
            )
            assert not unknown, f"{request.url.path}: undocumented params {unknown}"
            headers = set(request.headers) - _COMMON_HEADERS
            allowed = {h.lower() for h in op.get("headers", ())}
            assert headers <= allowed, f"{request.url.path}: headers {headers}"
            _check_body(op, request)
            return
    raise AssertionError(f"{request.method} {request.url.path} is not in the fixture")


@dataclass
class FakeAPI:
    """Route table + request log behind an ``httpx.MockTransport``.

    ``routes`` maps a URL path (``/v1/campaigns``) to a list of answers,
    consumed in order whatever the method (a ``GET`` and a ``POST`` on the same
    path share one list); the last answer repeats once the list runs out.
    """

    routes: dict[str, list[Answer]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    raise_on: dict[str, Exception] = field(default_factory=dict)

    def add(
        self,
        path: str,
        status: int = 200,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> FakeAPI:
        self.routes.setdefault(f"/v1{path}", []).append((status, body, headers or {}))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert_matches_contract(request)
        if request.url.path in self.raise_on:
            raise self.raise_on[request.url.path]
        answers = self.routes.get(request.url.path)
        if not answers:
            return httpx.Response(404, json={"error": {"message": "Not found"}})
        status, body, headers = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(body, str):
            return httpx.Response(status, text=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    def client(self, sleeps: list[float] | None = None) -> ChatGPTAdsClient:
        record = sleeps if sleeps is not None else []

        async def _sleep(seconds: float) -> None:
            record.append(seconds)

        return ChatGPTAdsClient(
            SENTINEL_KEY,
            transport=httpx.MockTransport(self.handler),
            sleep=_sleep,
        )

    def params(self, index: int = -1) -> list[tuple[str, str]]:
        return list(self.requests[index].url.params.multi_items())


def page(rows: list[dict[str, Any]], *, has_more: bool) -> dict[str, Any]:
    """A list page in the API's envelope."""
    return {
        "object": "list",
        "data": rows,
        "first_id": rows[0]["id"] if rows else None,
        "last_id": rows[-1]["id"] if rows else None,
        "has_more": has_more,
    }


def rows(prefix: str, start: int, count: int) -> list[dict[str, Any]]:
    return [
        {"id": f"{prefix}_{i}", "name": f"n{i}"} for i in range(start, start + count)
    ]


def install_fake_api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    """A :class:`FakeAPI` behind every tool call, with the sentinel key set."""
    fake = FakeAPI()
    monkeypatch.setenv("CHATGPT_ADS_API_KEY", SENTINEL_KEY)
    monkeypatch.setattr(handlers, "_open_client", lambda _key: fake.client())
    return fake


async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Run ``name`` through the provider; its JSON result, asserted a success."""
    result = await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
    assert failure_of(result) is None, result[0].text
    return json.loads(result[0].text)


async def fail_tool(name: str, arguments: dict[str, Any]) -> Failure:
    """Run ``name`` through the provider; its failure, asserted present."""
    result = await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
    failure = failure_of(result)
    assert failure is not None, result[0].text
    return failure


def by_name(tools: tuple[Tool, ...]) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


def schema_errors(tool: Tool, arguments: dict[str, Any]) -> list[Any]:
    """What the tool's input schema refuses in ``arguments``."""
    validator = jsonschema.Draft202012Validator(tool.inputSchema)
    return list(validator.iter_errors(arguments))


def strategy_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tools: tuple[Tool, ...],
    guardrails: str,
) -> StrategyPolicyGate:
    """The real STRATEGY.md gate over ``tools``' declarations and ``guardrails``.

    Registers into the process-global declaration registries, so the caller
    resets them first (the ``_clean_registries`` fixture).
    """
    semantics = {tool.name: derive_semantics(tool) for tool in tools}
    mcp_server._register_plugin_budget_declarations(semantics)
    mcp_server._register_plugin_bid_declarations(semantics)
    mcp_server._register_plugin_pattern_fallbacks(semantics)
    (tmp_path / "STRATEGY.md").write_text(guardrails, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return StrategyPolicyGate()
