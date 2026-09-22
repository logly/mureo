"""Unit tests for the plugin audit trail (mureo.mcp.plugin_audit).

Phase 1 of #114: every plugin tool call is recorded to a dedicated
append-only JSONL log; secrets are masked; auditing never raises.
"""

from __future__ import annotations

import json
import time
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

    @pytest.mark.parametrize(
        "key",
        [
            # The field name in a Google service-account JSON; the value is
            # a PEM private key. No root matched it — ``api[_-]?key`` needs
            # the literal ``api``.
            "private_key",
            "privateKey",
            "private-key",
            # ``passwd`` was a root, ``pwd`` is not a substring of it.
            "pwd",
            "signature",
        ],
    )
    def test_remaining_credential_key_names_are_redacted(self, key: str) -> None:
        """#779 — three spellings the KEY path did not recognise."""
        assert _mask({key: "SENSITIVE_VALUE_HERE"})[key] == "***"

    @pytest.mark.parametrize(
        "key",
        [
            # ``_SENSITIVE_KEY`` matches as a SUBSTRING, so ``sig`` as a root
            # would collapse all three of these — value and all.
            "design",
            "assign",
            "signal",
            # ``key`` alone would take these, for the same reason.
            "keyword",
            "monkey",
            # Ordinary arguments, pinned so the wider root list cannot start
            # swallowing the trail it exists to record.
            "campaign_id",
            "final_url",
        ],
    )
    def test_ordinary_argument_names_are_not_redacted(self, key: str) -> None:
        assert _mask({key: "ordinary-value"})[key] == "ordinary-value"

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
class TestMaskScrubsStringValues:
    """#779 — a secret pasted into an ordinary free-text argument.

    Masking by KEY name alone left it verbatim in ``JOURNAL.jsonl`` and in
    the plugin audit log, while the very same sentence WAS scrubbed on its
    way into ``STATE.json``: two stores, two rules. Every surviving string
    now goes through ``scrub_text`` as well.
    """

    def test_secret_in_a_nested_string_value_is_scrubbed(self) -> None:
        out = _mask({"entry": {"reason": "rotating after api_key=SHHH_SECRET leaked"}})
        reason = out["entry"]["reason"]
        assert "SHHH_SECRET" not in reason
        # The key and its separator survive, so the record still reads.
        assert reason == "rotating after api_key=*** leaked"

    def test_secret_in_a_string_inside_a_list_is_scrubbed(self) -> None:
        out = _mask({"notes": ["harmless", "client_secret=SECRET-CLIENT-VALUE"]})
        assert out["notes"] == ["harmless", "client_secret=***"]

    def test_bearer_token_in_a_plain_string_value_is_scrubbed(self) -> None:
        out = _mask({"note": "retrying with Authorization: Bearer Atza|SECRET.abc"})
        assert "SECRET.abc" not in out["note"]
        assert out["note"] == "retrying with Authorization: ***"

    def test_a_secret_is_scrubbed_before_the_string_is_truncated(self) -> None:
        """Order matters — and only ``Basic <base64>`` proves it.

        A secret that STRADDLES the cut is the whole case for paying the
        scrub cost first. ``api_key=…`` does not make it: its value class
        happily eats ``…<truncated>``, so truncating first still produces a
        match. ``Basic``'s value class is base64 only, so a truncated
        credential is unrecognisable and would be written in cleartext.
        """
        out = _mask("x" * 484 + "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==")
        assert "QWxhZGRpbj" not in out
        assert out.endswith("***")
        assert len(out) <= plugin_audit._MAX_STR  # hard cap unchanged

    def test_the_hard_cap_still_applies_after_scrubbing(self) -> None:
        out = _mask("api_key=SHHH_SECRET " + "x" * 2000)
        assert "SHHH_SECRET" not in out
        assert out.startswith("api_key=*** ")
        assert out.endswith(plugin_audit._TRUNC)
        assert len(out) == plugin_audit._MAX_STR

    def test_an_argument_url_keeps_its_query_string(self) -> None:
        """#779 review — ``code=`` is a rule for error PROSE, not arguments.

        ``final_url`` is a real argument of ad creation and of sitelinks, and
        a query string is full of ordinary ``…_code=`` parameters. Rewriting
        the landing page an agent submitted defeats the reason the journal
        exists.
        """
        url = "https://example.com/lp?utm_source=x&promo_code=SUMMER2026&ref=1"
        out = _mask({"final_url": url, "name": "Q4 promo code=BLACKFRIDAY24"})
        assert out["final_url"] == url
        assert out["name"] == "Q4 promo code=BLACKFRIDAY24"

    def test_the_code_rule_still_applies_to_free_text(self) -> None:
        """The exemption is scoped to ``mask_arguments``: a ``reason`` or a
        ``rationale`` goes through ``scrub_text`` directly and still loses an
        authorization code."""
        assert "ANabcdefgh12" not in plugin_audit._scrub("?code=ANabcdefgh12&scope=x")

    def test_the_scrubber_never_sees_more_than_the_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cost per value is a constant, not O(len(value)).

        ``mask_arguments`` runs on the asyncio event loop for every tool
        call — twice for a plugin call — and MCP puts no bound on argument
        size. Everything past the window is truncated away regardless.
        """
        seen: list[int] = []

        def _spy(text: str, **kwargs: object) -> str:
            seen.append(len(text))
            return text

        monkeypatch.setattr(plugin_audit, "scrub_text", _spy)
        out = _mask("x" * 5_000_000)

        assert seen == [plugin_audit.SCRUB_WINDOW]
        assert len(out) == plugin_audit._MAX_STR


@pytest.mark.unit
class TestArgumentValuesAreNotAdCopy:
    """#779 review 2 — the bare roots were eating advertising copy.

    A root like ``secret`` or ``cookie`` matched on a space-padded colon,
    which is how English punctuates a sentence and how nobody writes a
    credential. ``headline``, ``description``, ``primary_text`` and a
    campaign ``name`` are the most-written arguments in this product, and
    the journal exists to record what the agent actually submitted.

    The fix is the separator, not the root list: in ``argument`` mode an
    ambiguous root needs the shape ``_CODE_KEY_VALUE`` already requires —
    ``key=value`` with no space before the ``=``, or the quoted dict-key
    form — so every machine-generated leak still matches.
    """

    @pytest.mark.parametrize(
        "copy",
        [
            "The secret: better ROAS in 30 days",
            "Trade secret: how we cut CPA 40%",
            "Cookie: the new flavour drop",
            "Signature: our chef's tasting menu",
            "Credential: ISO 27001 certified",
            "Password: freedom — a thriller",
            # Judged with the six above: ``authorization`` is an ordinary
            # English word in exactly the same way.
            "Landing page authorization: pending review",
        ],
    )
    def test_ad_copy_survives_the_argument_path(self, copy: str) -> None:
        assert _mask({"headline": copy}) == {"headline": copy}

    @pytest.mark.parametrize(
        ("text", "leaked"),
        [
            # ``=`` with no space: every form-encoded and query-string leak.
            ("app_secret=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("cookie=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("password=hunter2hunter2", "hunter2hunter2"),
            ("authorization=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            # A signed GCS URL — the real reason these roots are here.
            (
                "https://storage.googleapis.com/b/o.png?X-Goog-Credential="
                "svc%40p.iam&X-Goog-Signature=abc123def456",
                "abc123def456",
            ),
            # The quoted dict-key form an exception repr produces.
            ('{"appSecret": "SHHH_SECRET_VALUE"}', "SHHH_SECRET_VALUE"),
            ("{'cookie': 'SHHH_SECRET_VALUE'}", "SHHH_SECRET_VALUE"),
            # Unambiguous compounds keep the loose separator: they do not
            # occur in an English sentence, so a spaced colon is safe.
            ("developer-token: abc123XYZ", "abc123XYZ"),
            ("private_key: SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            # Spelled out as a compound for exactly this reason: the bare
            # ``secret`` root would otherwise hand it the strict separator.
            ("client_secret: amzn1.oa2-cs.v1.abcdef", "amzn1.oa2-cs.v1.abcdef"),
        ],
    )
    def test_real_leak_shapes_still_match_in_an_argument(
        self, text: str, leaked: str
    ) -> None:
        out = _mask({"note": text})["note"]
        assert leaked not in out
        assert "***" in out

    @pytest.mark.parametrize(
        "copy",
        [
            "The secret: better ROAS in 30 days",
            "Cookie: the new flavour drop",
            "Password: freedom — a thriller",
            "Landing page authorization: pending review",
        ],
    )
    def test_prose_mode_is_deliberately_unchanged(self, copy: str) -> None:
        """The tightening is scoped to arguments. An error string, a
        ``reason`` and a ``rationale`` keep today's wider rule — prose is
        where a spaced colon really can introduce a credential, and where
        over-masking costs legibility rather than the record itself."""
        assert plugin_audit._scrub(copy) != copy


@pytest.mark.unit
class TestSensitiveKeysShortCircuit:
    """Step 1 of ``mask_arguments``: a secret-shaped KEY means the value is
    never inspected at all — not scrubbed, not recursed into, not truncated.
    That is both the strongest redaction available and the reason a 10 MB
    blob under ``api_key`` costs nothing."""

    def test_a_huge_value_under_a_sensitive_key_is_not_inspected(self) -> None:
        assert _mask({"api_key": "s" * 5_000_000}) == {"api_key": "***"}

    def test_a_container_under_a_sensitive_key_is_not_recursed_into(self) -> None:
        out = _mask(
            {
                "credentials": {"nested": "value", "deeper": [1, 2, 3]},
                "tokens": ["one", "two"],
            }
        )
        assert out == {"credentials": "***", "tokens": "***"}


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

    def test_platform_failure_is_recorded_beside_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#528 — a call that returned an error envelope did not raise.

        ``ok`` keeps meaning "the call did not raise", so a platform-side
        refusal is recorded as ``platform_ok: false``; the operator trail must
        not read as a success for a call that changed nothing. Written only
        when a failure is detected, so an ordinary record is unchanged.
        """
        log = tmp_path / "audit.jsonl"
        monkeypatch.setattr(plugin_audit, "_audit_path", lambda: log)

        record_plugin_call(tool="t", arguments={}, source="s", ok=True)
        record_plugin_call(
            tool="t",
            arguments={},
            source="s",
            ok=True,
            platform_ok=False,
            error="API error: FIELD_VALUE_IS_INVALID: bad id",
        )

        first, second = (
            json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()
        )
        assert "platform_ok" not in first  # unchanged for a plain success
        assert second["ok"] is True
        assert second["platform_ok"] is False
        assert "FIELD_VALUE_IS_INVALID" in second["error"]

    def test_tool_and_source_are_capped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No field of an append-only line may be unbounded, and ``args``
        and ``error`` were the only two that were capped."""
        log = tmp_path / "audit.jsonl"
        monkeypatch.setattr(plugin_audit, "_audit_path", lambda: log)
        record_plugin_call(tool="t" * 5000, arguments={}, source="s" * 5000, ok=True)
        rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        assert len(rec["tool"]) == plugin_audit._MAX_STR
        assert len(rec["source"]) == plugin_audit._MAX_STR

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
            # #528 — the rule must not key on the WHOLE key being ``code``:
            # a differently-named field holding the same material leaks.
            (
                '{"authorizationCode": "AQABAAABBBCCCDDDauthcode123456"}',
                "AQABAAABBBCCCDDDauthcode123456",
            ),
            ("authCode=AQABAAABBBCCCDDDauthcode123456", "AQABAAABBBCCCDDD"),
            ("&oauth_code=AQABAAABBBCCCDDDauthcode123456", "AQABAAABBBCCCDDD"),
            # #528 — camelCase spellings of EVERY credential family. Amazon's
            # surface is camelCase throughout (``advertiserAccountId``,
            # ``adProductFilter``), so a snake_case-only rule leaks in exactly
            # the payloads this scrubber exists for.
            (
                '{"clientSecret": "amzn1.oa2-cs.v1.SUPERSECRETVALUE"}',
                "amzn1.oa2-cs.v1.SUPERSECRETVALUE",
            ),
            ('{"refreshToken": "abcdefgh12345678"}', "abcdefgh12345678"),
            ('{"accessToken": "abcdefgh12345678"}', "abcdefgh12345678"),
            ('{"apiKey": "sk-abcdefgh12345678"}', "sk-abcdefgh12345678"),
            ("clientSecret=amzn1.oa2-cs.v1.SUPERSECRETVALUE", "SUPERSECRETVALUE"),
            ("refreshToken=Atzr-plain-shaped-value", "Atzr-plain-shaped-value"),
            ("accessToken: plain-shaped-value", "plain-shaped-value"),
            # ...and the hyphenated spellings, for the same reason.
            ("client-secret=amzn1.oa2-cs.v1.SUPERSECRETVALUE", "SUPERSECRETVALUE"),
            ("refresh-token=Atzr-plain-shaped-value", "Atzr-plain-shaped-value"),
            # #758 — Google's request metadata spells its credential
            # ``developer-token``, and a gRPC debug string prints the metadata
            # verbatim. All three spellings, like every other key family.
            ("developer-token: abc123XYZ", "abc123XYZ"),
            ("developer_token=abc123XYZ", "abc123XYZ"),
            ('{"developerToken": "abc123XYZ"}', "abc123XYZ"),
            # ``authorization`` as a key. A Bearer value is already caught by
            # the token pass above; this pins that the key form is masked too.
            ("authorization: Bearer abc.def", "abc.def"),
            # A Basic scheme: the key pass masks the scheme word, the value
            # pass masks the base64 credential that follows it.
            ("Authorization=Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA=="),
            ("HTTP 401 with Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA=="),
        ],
    )
    def test_credential_values_are_redacted(self, text: str, leaked: str) -> None:
        scrubbed = plugin_audit._scrub(text)
        assert leaked not in scrubbed
        assert "***" in scrubbed

    def test_a_bearer_token_does_not_swallow_the_closing_quote(self) -> None:
        """The token pattern must stop at a quote, like the ``Atza|`` ones do.

        ``Bearer\\s+\\S+`` ate the closing ``"`` and everything after it,
        leaving structurally broken JSON for whoever reads the record. No leak,
        but a bearer token cannot contain a quote, so narrowing is free.
        """
        text = '{"code":"BAD","message":"bad header Bearer sometoken.jwt.here"}'
        scrubbed = plugin_audit._scrub(text)

        assert "sometoken.jwt.here" not in scrubbed
        assert json.loads(scrubbed) == {"code": "BAD", "message": "bad header ***"}

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
            # ``Basic`` as a word, not a scheme: short or non-base64 values
            # after it are prose and must survive.
            "Basic plan does not include this report",
            "Basic auth failed for user",
        ],
    )
    def test_ordinary_diagnostics_survive_unchanged(self, text: str) -> None:
        assert plugin_audit._scrub(text) == text


@pytest.mark.unit
class TestKeyCoverageMatchesTheKeyPath:
    """#779 — the KEY path and the VALUE path recognised different keys.

    ``_SENSITIVE_KEY`` masks an argument whose key merely CONTAINS ``token``
    / ``secret`` / ``password`` / ``credential`` / ``cookie``; the value
    path knew seven exact spellings. So the same credential was redacted
    when it arrived as an argument key and written in cleartext when it
    arrived inside a string — and ``app_secret`` is mureo's own Meta
    credential field name.
    """

    @pytest.mark.parametrize(
        ("text", "leaked"),
        [
            # mureo's own Meta credential field (``mureo/auth.py``).
            ("app_secret=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ('{"appSecret": "SHHH_SECRET_VALUE"}', "SHHH_SECRET_VALUE"),
            # ``…_key`` tails. ``key`` is NOT a root of its own — see
            # ``monkey=`` below — so each compound is spelled out.
            ("secret_key=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ('{"secretKey": "SHHH_SECRET_VALUE"}', "SHHH_SECRET_VALUE"),
            ("private_key=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ('{"privateKey": "SHHH_SECRET_VALUE"}', "SHHH_SECRET_VALUE"),
            ("aws_secret_access_key=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            # ``token`` in every prefix a platform picked, plus the bare key.
            ("auth_token=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ('{"authToken": "SHHH_SECRET_VALUE"}', "SHHH_SECRET_VALUE"),
            ("id_token=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("session_token=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("client_token=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("token=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            # The remaining ``_SENSITIVE_KEY`` roots.
            ("passwd=hunter2hunter2", "hunter2hunter2"),
            ("pwd=hunter2hunter2", "hunter2hunter2"),
            ("credential=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("credentials=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("bearer=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("Set-Cookie: sid=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
            ("signature=SHHH_SECRET_VALUE", "SHHH_SECRET_VALUE"),
        ],
    )
    def test_the_value_path_now_sees_what_the_key_path_sees(
        self, text: str, leaked: str
    ) -> None:
        scrubbed = plugin_audit._scrub(text)
        assert leaked not in scrubbed
        assert "***" in scrubbed

    def test_the_key_prefix_survives_so_the_diagnostic_still_reads(self) -> None:
        """Only the tail WORD is matched; the prefix is never consumed —
        the same technique ``_CODE_KEY_VALUE`` uses for
        ``authorizationCode``, and the reason no ``[\\w-]*secret`` wildcard
        is needed."""
        assert plugin_audit._scrub("app_secret=SHHH") == "app_secret=***"
        assert plugin_audit._scrub("privateKey=SHHH") == "privateKey=***"
        assert (
            plugin_audit._scrub("aws_secret_access_key=SHHH")
            == "aws_secret_access_key=***"
        )

    @pytest.mark.parametrize(
        "text",
        [
            # ``key`` alone is not a root; adding it would eat these.
            "monkey=x",
            "turkey=y",
            "keyword=running shoes",
            # ``sig`` is not a root either, for exactly this reason.
            "design=modern",
            # ``token`` is the one ambiguous root: in ordinary prose it is a
            # UNIT, not a credential, so it carries a minimum value length.
            "max_tokens=4096",
            "token: 5",
            "token limit: 128000",
            # Unchanged by this commit, pinned here so the wider key list
            # cannot quietly start matching them.
            "status code = 400",
            "error code: 17",
        ],
    )
    def test_ordinary_words_ending_in_a_root_are_not_masked(self, text: str) -> None:
        assert plugin_audit._scrub(text) == text

    @pytest.mark.parametrize(
        "payload",
        [
            "x" * 2_000_000,
            " " * 2_000_000,
            "'" * 2_000_000,
            # Near-miss: every root reached, every separator absent. This is
            # the shape a ``[\\w-]*secret`` prefix wildcard hangs on.
            "secret_" * 285_000,
            "token " * 333_000,
            "private_ke" * 200_000,
        ],
    )
    def test_a_two_megabyte_input_stays_linear(self, payload: str) -> None:
        """The ``_CODE_KEY_VALUE`` comment records a 2 MB error body that
        hung this suite. A quadratic pattern does not finish in seconds, so
        a generous ceiling still catches one."""
        start = time.perf_counter()
        plugin_audit._scrub(payload)
        assert time.perf_counter() - start < 5.0
