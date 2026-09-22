"""Which shapes the scrubber treats as a secret (#528, #758, #779).

Split out of ``tests/test_mcp_plugin_audit.py``. The patterns themselves:
the token prefixes, the ``key=value`` roots, the key coverage the
argument masker already had, the ordinary diagnostics that must survive
unchanged, and the linear-time guarantee on a 2 MB input.
"""

from __future__ import annotations

import json
import time

import pytest

from mureo.mcp import plugin_audit


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
        # Explicit ids: without them pytest names each case after its
        # 2 MB payload, and a 2 MB node id is what CI chokes on, not the
        # scrub — the hosted runner spent an hour streaming each line of
        # ``-v`` output, and Windows failed at setup with the id inside a
        # path. Locally the same six cases run in seconds.
        ids=["x", "space", "quote", "secret_", "token ", "private_ke"],
    )
    def test_a_two_megabyte_input_stays_linear(self, payload: str) -> None:
        """The ``_CODE_KEY_VALUE`` comment records a 2 MB error body that
        hung this suite. A quadratic pattern does not finish in seconds, so
        a generous ceiling still catches one."""
        start = time.perf_counter()
        plugin_audit._scrub(payload)
        assert time.perf_counter() - start < 5.0
