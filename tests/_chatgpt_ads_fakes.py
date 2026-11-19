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

from mureo.chatgpt_ads.client import ChatGPTAdsClient

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


def sent_body(request: httpx.Request) -> Any:
    """The decoded JSON body of ``request``, or ``None`` when it sent none."""
    return json.loads(request.content) if request.content else None


def assert_matches_contract(request: httpx.Request) -> None:
    """Fail unless the request's path, query names and body keys are in the
    fixture. An operation the fixture lists without ``body`` takes none."""
    for op in openapi_operations():
        if op["method"] == request.method and _template_regex(op["path"]).match(
            request.url.path
        ):
            unknown = {k for k, _ in request.url.params.multi_items()} - set(
                op["query"]
            )
            assert not unknown, f"{request.url.path}: undocumented params {unknown}"
            body = sent_body(request)
            if body is not None:
                assert isinstance(body, dict), f"{request.url.path}: body not an object"
                extra = set(body) - set(op.get("body", ()))
                assert not extra, f"{request.url.path}: undocumented body keys {extra}"
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
