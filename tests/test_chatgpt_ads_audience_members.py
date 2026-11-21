"""The ChatGPT Ads audience membership add and remove tools (#995).

The identifiers are personal data, so they come from a local file, never a
tool argument, and leave the process only as SHA-256 digests (email, phone)
or as the raw advertising id the API requires. Pinned here: the request body,
the file rules (path checks shared with the image upload, UTF-8, size, 1 to
10,000 distinct values), that one invalid line refuses the whole call without
quoting any line, the ``Idempotency-Key`` handling and its failure sentence,
that no reversal is recorded, and what the audit trail sees of a call.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mureo.chatgpt_ads import handlers
from mureo.chatgpt_ads._api import MAX_IDENTIFIER_FILE_BYTES, MAX_INLINE_IDENTIFIERS
from mureo.chatgpt_ads._errors import (
    MAY_HAVE_BEEN_APPLIED,
    REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY,
    REPEAT_WITH_IDEMPOTENCY_KEY,
    ChatGPTAdsAPIError,
)
from mureo.chatgpt_ads._hashing import sha256_hex
from mureo.chatgpt_ads.handlers_audiences import _file_lines
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.core.auth_failure import PlatformAuthError
from mureo.mcp.plugin_audit import mask_arguments
from tests._chatgpt_ads_fakes import (
    FakeAPI,
    call_tool,
    fail_tool,
    install_fake_api,
    sent_body,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_ADD = "chatgpt_ads_audiences_members_add"
_REMOVE = "chatgpt_ads_audiences_members_remove"
_OPERATION = {"operation_id": "caudop_1", "status": "processing"}
#: A value no message, log record or result may ever contain.
_SENTINEL = "SENTINEL-PII-9c41"
_JAMIE_SHA = "057a0fff4c78ae3e14236c36b611061cbdd54ccd72a34b23f77d7a8c4bca4963"


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = install_fake_api(monkeypatch)
    for action in ("add", "remove"):
        fake.add(f"/custom_audiences/caud_1/{action}", body=_OPERATION)
    return fake


def _file(tmp_path: Path, text: str, name: str = "list.txt") -> str:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _args(
    file_path: str, identifier_type: str = "email", **extra: Any
) -> dict[str, Any]:
    return {
        "audience_id": "caud_1",
        "file_path": file_path,
        "identifier_type": identifier_type,
        **extra,
    }


async def _refused(arguments: dict[str, Any], name: str = _ADD) -> str:
    with pytest.raises(ValueError) as info:
        await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
    return str(info.value)


class TestBody:
    @pytest.mark.parametrize(("name", "action"), [(_ADD, "add"), (_REMOVE, "remove")])
    async def test_emails_are_hashed_and_returned_unchanged(
        self, api: FakeAPI, tmp_path: Path, name: str, action: str
    ) -> None:
        path = _file(
            tmp_path, "  Jamie@Example.com \n\njamie@example.com\nb.c+x@example.com\n"
        )
        assert await call_tool(name, _args(path)) == _OPERATION
        request = api.requests[0]
        assert request.url.path == f"/v1/custom_audiences/caud_1/{action}"
        assert sent_body(request) == {
            "identifiers": [
                {"identifier_type": "email_sha256", "identifier": _JAMIE_SHA},
                {
                    "identifier_type": "email_sha256",
                    "identifier": sha256_hex("b.c+x@example.com"),
                },
            ]
        }

    async def test_phones_are_hashed_with_the_plus(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        path = _file(tmp_path, "+1 (555) 010-0000\r\n+1.555.010.0000\r\n", "p.csv")
        await call_tool(_ADD, _args(path, "phone"))
        assert sent_body(api.requests[0]) == {
            "identifiers": [
                {
                    "identifier_type": "phone_number_sha256",
                    "identifier": sha256_hex("+15550100000"),
                }
            ]
        }

    async def test_gaids_are_sent_raw_and_digests_as_given(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        gaid = "38400000-8CF0-11BD-B23E-10B96E40000D"
        await call_tool(_ADD, _args(_file(tmp_path, gaid), "gaid"))
        await call_tool(
            _ADD, _args(_file(tmp_path, _JAMIE_SHA.upper(), "h.txt"), "email_sha256")
        )
        bodies = [sent_body(r)["identifiers"] for r in api.requests]
        assert bodies == [
            [{"identifier_type": "gaid", "identifier": gaid.lower()}],
            [{"identifier_type": "email_sha256", "identifier": _JAMIE_SHA}],
        ]

    @pytest.mark.parametrize(
        ("identifier_type", "text"),
        [
            ("email", "jamie@example.com\nalex@example.com"),
            ("phone", "+15550100000\n+15550100001"),
            ("gaid", "38400000-8cf0-11bd-b23e-10b96e40000d"),
            ("email_sha256", _JAMIE_SHA),
            ("phone_number_sha256", _JAMIE_SHA),
        ],
    )
    async def test_no_plaintext_type_or_value_is_ever_sent(
        self, api: FakeAPI, tmp_path: Path, identifier_type: str, text: str
    ) -> None:
        await call_tool(_ADD, _args(_file(tmp_path, text), identifier_type))
        body = sent_body(api.requests[0])
        assert set(body) == {"identifiers"}
        types = {item["identifier_type"] for item in body["identifiers"]}
        assert types <= {"email_sha256", "phone_number_sha256", "gaid"}
        if identifier_type in ("email", "phone"):
            assert not any(
                line in api.requests[0].content.decode() for line in text.split("\n")
            )

    async def test_a_byte_order_mark_is_accepted(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        path = tmp_path / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbfjamie@example.com\n")
        await call_tool(_ADD, _args(str(path)))
        assert sent_body(api.requests[0])["identifiers"][0]["identifier"] == _JAMIE_SHA

    async def test_exactly_the_inline_limit_is_sent(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        lines = "\n".join(f"user{i}@example.com" for i in range(MAX_INLINE_IDENTIFIERS))
        await call_tool(_ADD, _args(_file(tmp_path, lines)))
        assert len(sent_body(api.requests[0])["identifiers"]) == MAX_INLINE_IDENTIFIERS


class TestRefusals:
    @pytest.mark.parametrize("text", ["", "\n\n   \n"], ids=["empty", "blank-lines"])
    async def test_no_identifier(self, api: FakeAPI, tmp_path: Path, text: str) -> None:
        message = await _refused(_args(_file(tmp_path, text)))
        assert message == "file_path holds no identifiers; give one per line"
        assert api.requests == []

    async def test_one_over_the_inline_limit_says_to_split(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        count = MAX_INLINE_IDENTIFIERS + 1
        lines = "\n".join(f"user{i}@example.com" for i in range(count))
        message = await _refused(_args(_file(tmp_path, lines)))
        assert f"{count:,}" in message and "split the file" in message
        assert api.requests == []

    async def test_duplicates_count_once_toward_the_limit(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        lines = "\n".join(
            f"user{i % MAX_INLINE_IDENTIFIERS}@example.com"
            for i in range(MAX_INLINE_IDENTIFIERS + 5)
        )
        await call_tool(_ADD, _args(_file(tmp_path, lines)))
        assert len(sent_body(api.requests[0])["identifiers"]) == MAX_INLINE_IDENTIFIERS

    async def test_an_invalid_line_names_numbers_and_never_content(
        self,
        api: FakeAPI,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        text = f"jamie@example.com\n{_SENTINEL}\n\nalex@example.com\n{_SENTINEL} x\n"
        arguments = _args(_file(tmp_path, text))
        with caplog.at_level(logging.DEBUG):
            message = await _refused(arguments)
        assert "2 line(s)" in message and "line 2, 5" in message
        assert _SENTINEL not in message
        assert all(_SENTINEL not in r.getMessage() for r in caplog.records)
        assert api.requests == []

    async def test_at_most_ten_line_numbers_are_named(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        text = "\n".join(f"{_SENTINEL}-{i}" for i in range(12))
        message = await _refused(_args(_file(tmp_path, text), "phone"))
        assert "12 line(s)" in message
        assert "line 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 (the first 10 shown)" in message
        assert _SENTINEL not in message

    async def test_a_number_without_country_code_is_invalid(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        message = await _refused(_args(_file(tmp_path, "555-010-0000"), "phone"))
        assert "line 1" in message
        assert "555" not in message.split("line 1", 1)[1]

    async def test_bytes_that_are_not_utf8_quote_nothing(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        path = tmp_path / "latin.txt"
        path.write_bytes(b"jamie@example.com\n" + _SENTINEL.encode() + b"\xff\xfe\n")
        message = await _refused(_args(str(path)))
        assert message == "file_path must be a UTF-8 text file"
        assert api.requests == []

    def test_the_decode_error_carries_no_file_bytes(self) -> None:
        with pytest.raises(ValueError) as info:
            _file_lines(_SENTINEL.encode() + b"\xff")
        assert info.value.__cause__ is None
        assert info.value.__context__ is None

    async def test_a_spreadsheet_row_is_refused(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        text = "jamie@example.com,+15550100000\n"
        message = await _refused(_args(_file(tmp_path, text, "export.csv")))
        assert "1 line(s)" in message and "line 1" in message
        assert api.requests == []

    @pytest.mark.parametrize(
        ("arguments", "match"),
        [
            ({"identifier_type": "md5"}, "identifier_type"),
            ({"identifier_type": None}, "identifier_type"),
            ({"audience_id": "../x"}, "audience_id"),
            ({"file_path": ""}, "file_path"),
            ({"file_path": "x" * 4097}, "file_path"),
            ({"idempotency_key": "has space"}, "idempotency_key"),
        ],
        ids=["type", "no-type", "audience", "empty-path", "long-path", "key"],
    )
    async def test_bad_arguments_send_nothing(
        self, api: FakeAPI, tmp_path: Path, arguments: dict[str, Any], match: str
    ) -> None:
        base = _args(_file(tmp_path, "jamie@example.com"))
        message = await _refused({**base, **arguments})
        assert match in message
        assert api.requests == []


class TestFileRules:
    async def test_an_unsupported_extension(self, api: FakeAPI, tmp_path: Path) -> None:
        path = _file(tmp_path, "jamie@example.com", "list.json")
        with pytest.raises(ValueError, match="Unsupported"):
            await ChatGPTAdsProvider().handle_mcp_tool(_ADD, _args(path))
        assert api.requests == []

    async def test_a_missing_file(self, api: FakeAPI, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                _ADD, _args(str(tmp_path / "absent.txt"))
            )
        assert api.requests == []

    async def test_a_directory(self, api: FakeAPI, tmp_path: Path) -> None:
        folder = tmp_path / "d.txt"
        folder.mkdir()
        with pytest.raises(ValueError, match="not a regular file"):
            await ChatGPTAdsProvider().handle_mcp_tool(_ADD, _args(str(folder)))
        assert api.requests == []

    async def test_a_traversing_path(self, api: FakeAPI, tmp_path: Path) -> None:
        path = str(tmp_path / ".." / tmp_path.name / "list.txt")
        with pytest.raises(ValueError, match="must not contain '..'"):
            await ChatGPTAdsProvider().handle_mcp_tool(_ADD, _args(path))
        assert api.requests == []

    async def test_a_file_over_the_cap(self, api: FakeAPI, tmp_path: Path) -> None:
        path = tmp_path / "big.txt"
        path.write_bytes(b"a" * (MAX_IDENTIFIER_FILE_BYTES + 1))
        with pytest.raises(ValueError, match="2 MiB"):
            await ChatGPTAdsProvider().handle_mcp_tool(_ADD, _args(str(path)))
        assert api.requests == []


def _key(request: httpx.Request) -> str | None:
    return request.headers.get("Idempotency-Key")


class TestIdempotency:
    async def test_a_key_is_generated_when_absent(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        path = _file(tmp_path, "jamie@example.com")
        await call_tool(_ADD, _args(path))
        await call_tool(_ADD, _args(path))
        first, second = (_key(r) for r in api.requests)
        assert first and second and first != second

    async def test_the_given_key_is_sent(self, api: FakeAPI, tmp_path: Path) -> None:
        await call_tool(
            _REMOVE,
            _args(_file(tmp_path, "jamie@example.com"), idempotency_key="rm-1"),
        )
        assert _key(api.requests[0]) == "rm-1"
        assert "idempotency_key" not in sent_body(api.requests[0])

    async def test_a_5xx_is_retried_with_the_same_key_and_body(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        api = install_fake_api(monkeypatch)
        api.add("/custom_audiences/caud_1/add", 503, {"error": {"message": "busy"}})
        api.add("/custom_audiences/caud_1/add", body=_OPERATION)
        await call_tool(_ADD, _args(_file(tmp_path, "jamie@example.com")))
        first, second = api.requests
        assert _key(first) == _key(second) is not None
        assert first.content == second.content

    async def test_a_final_5xx_names_the_key_and_the_operation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        api = install_fake_api(monkeypatch)
        api.add("/custom_audiences/caud_1/add", 502, {"error": {"message": "down"}})
        failure = await fail_tool(
            _ADD, _args(_file(tmp_path, "jamie@example.com"), idempotency_key="k1")
        )
        assert len(api.requests) == 3
        sentence = REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY.format(key="k1")
        assert failure.detail.endswith(sentence)
        assert "same file" in sentence
        assert MAY_HAVE_BEEN_APPLIED not in failure.detail

    async def test_a_transport_error_names_the_generated_key(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        api.raise_on["/v1/custom_audiences/caud_1/add"] = httpx.ConnectError("refused")
        failure = await fail_tool(_ADD, _args(_file(tmp_path, "jamie@example.com")))
        key = _key(api.requests[0])
        assert key is not None and {_key(r) for r in api.requests} == {key}
        assert failure.detail.endswith(
            REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY.format(key=key)
        )

    async def test_the_deadline_names_the_operation_sentence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def _hang(_client: Any, _arguments: dict[str, Any]) -> Any:
            await asyncio.sleep(10)

        monkeypatch.setitem(handlers.HANDLERS, _REMOVE, _hang)
        monkeypatch.setattr(handlers, "_open_client", lambda _k: FakeAPI().client())
        arguments = _args(_file(tmp_path, "a@example.com"), idempotency_key="late-1")
        with pytest.raises(ChatGPTAdsAPIError) as info:
            await handlers.run_tool(_REMOVE, arguments, "k", deadline=0.01)
        text = str(info.value)
        assert text.endswith(REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY.format(key="late-1"))
        assert REPEAT_WITH_IDEMPOTENCY_KEY.format(key="late-1") not in text

    async def test_a_direct_call_without_a_key_is_refused(self) -> None:
        client = FakeAPI().client()
        async with client:
            with pytest.raises(ValueError, match="idempotency_key"):
                await client.post_operation(
                    "/custom_audiences/caud_1/add",
                    {"identifiers": []},
                    idempotency_key="",
                )


_GAID = "38400000-8CF0-11BD-B23E-10B96E40000D"
_ALEX_SHA = sha256_hex("alex@example.com")
#: A caller's key shaped like a UUID: masked if the platform echoed it, but
#: the note naming it is appended after the masking.
_UUID_KEY = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"

#: (identifier_type, file text, values sent, platform message echoing them).
_ECHOES = [
    pytest.param(
        "email",
        "jamie@example.com",
        [_JAMIE_SHA],
        f"invalid identifier {_JAMIE_SHA}",
        id="one-digest",
    ),
    pytest.param(
        "email",
        "jamie@example.com\nalex@example.com",
        [_JAMIE_SHA, _ALEX_SHA],
        f"invalid identifiers {_JAMIE_SHA}, {_ALEX_SHA}",
        id="two-digests",
    ),
    pytest.param(
        "email",
        "jamie@example.com",
        [_JAMIE_SHA],
        f"invalid identifier {_JAMIE_SHA.upper()}",
        id="upper-case-digest",
    ),
    pytest.param("gaid", _GAID, [_GAID.lower()], f"unknown device {_GAID}", id="gaid"),
    pytest.param(
        "email",
        "jamie@example.com",
        [_JAMIE_SHA],
        f"{'x' * 150} {_JAMIE_SHA} {'y' * 300}",
        id="digest-across-the-cut",
    ),
    pytest.param(
        "email",
        "jamie@example.com\nalex@example.com",
        [_JAMIE_SHA, _ALEX_SHA],
        f"invalid identifiers {_JAMIE_SHA}{_ALEX_SHA}",
        id="joined-digests",
    ),
]


def _assert_no_sent_value(text: str, sent: list[str]) -> None:
    lowered = text.lower()
    for value in sent:
        assert value.lower()[:16] not in lowered


class TestPlatformEcho:
    @pytest.mark.parametrize("name", [_ADD, _REMOVE])
    @pytest.mark.parametrize("status", [400, 403, 500])
    @pytest.mark.parametrize(("identifier_type", "text", "sent", "message"), _ECHOES)
    async def test_an_echoed_identifier_never_comes_back(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        name: str,
        status: int,
        identifier_type: str,
        text: str,
        sent: list[str],
        message: str,
    ) -> None:
        api = install_fake_api(monkeypatch)
        action = "add" if name == _ADD else "remove"
        api.add(
            f"/custom_audiences/caud_1/{action}",
            status,
            {"error": {"message": message}},
        )
        arguments = _args(_file(tmp_path, text), identifier_type)
        result = await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
        _assert_no_sent_value(" ".join(part.text for part in result), sent)
        with pytest.raises((ChatGPTAdsAPIError, PlatformAuthError)) as info:
            await handlers.run_tool(name, arguments, "k")
        _assert_no_sent_value(str(info.value), sent)
        assert "***" in str(info.value)

    @pytest.mark.parametrize("code", [_JAMIE_SHA, _GAID], ids=["digest", "gaid"])
    async def test_an_identifier_echoed_as_the_error_code_is_masked(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: str
    ) -> None:
        api = install_fake_api(monkeypatch)
        api.add(
            "/custom_audiences/caud_1/add",
            400,
            {"error": {"message": "invalid identifier", "code": code}},
        )
        failure = await fail_tool(_ADD, _args(_file(tmp_path, "jamie@example.com")))
        _assert_no_sent_value(failure.detail, [code])
        assert "HTTP 400 (***)" in failure.detail

    @pytest.mark.parametrize("key", [None, _UUID_KEY], ids=["generated", "uuid"])
    async def test_the_key_is_still_named_after_a_5xx(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str | None
    ) -> None:
        api = install_fake_api(monkeypatch)
        echo = {"error": {"message": f"retry {_JAMIE_SHA} {_UUID_KEY}"}}
        api.add("/custom_audiences/caud_1/add", 502, echo)
        extra = {} if key is None else {"idempotency_key": key}
        failure = await fail_tool(
            _ADD, _args(_file(tmp_path, "jamie@example.com"), **extra)
        )
        sent_key = _key(api.requests[0])
        assert sent_key is not None and (key is None or sent_key == key)
        assert failure.detail.endswith(
            REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY.format(key=sent_key)
        )
        _assert_no_sent_value(failure.detail, [_JAMIE_SHA])

    async def test_an_audience_read_is_quoted_as_before(self, api: FakeAPI) -> None:
        api.add("/custom_audiences/caud_1", 400, {"error": {"message": _JAMIE_SHA}})
        failure = await fail_tool(
            "chatgpt_ads_audiences_get", {"audience_id": "caud_1"}
        )
        assert _JAMIE_SHA in failure.detail


class TestTrail:
    @pytest.mark.parametrize("name", [_ADD, _REMOVE])
    async def test_no_reversal_and_no_request(
        self, api: FakeAPI, tmp_path: Path, name: str
    ) -> None:
        arguments = _args(_file(tmp_path, "jamie@example.com"))
        assert await ChatGPTAdsProvider().capture_reversal(name, arguments) is None
        assert api.requests == []

    def test_the_audit_view_holds_the_path_and_no_identifier(
        self, tmp_path: Path
    ) -> None:
        path = _file(tmp_path, f"{_SENTINEL}@example.com")
        recorded = mask_arguments(_args(path))
        # Compared as a value: a serialised Windows path doubles its
        # backslashes, so the path is not a substring of the JSON text.
        assert recorded["file_path"] == path
        assert _SENTINEL not in json.dumps(recorded)
