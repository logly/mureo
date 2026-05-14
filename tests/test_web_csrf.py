"""CSRF defense for the configure-UI session layer.

Covers ``mureo.web._helpers.fresh_csrf_token`` /
``mureo.web._helpers.compare_csrf`` and ``mureo.web.session.ConfigureSession``
CSRF / OAuth bookkeeping.

Security invariants asserted here:

* Tokens come from ``secrets.token_urlsafe`` — sufficient entropy,
  URL-safe alphabet.
* Comparison goes through ``secrets.compare_digest`` (constant time)
  to defeat timing attacks.
* Empty / missing tokens compare false.
* The OAuth provider allow-list (`OAUTH_PROVIDERS`) is enforced on
  every mark / query call.
"""

from __future__ import annotations

import ast
import secrets
import string
from pathlib import Path
from unittest.mock import patch

import pytest

from mureo.web import _helpers as helpers_mod
from mureo.web._helpers import compare_csrf, fresh_csrf_token
from mureo.web.session import (
    OAUTH_PROVIDERS,
    SUPPORTED_HOSTS,
    ConfigureSession,
    OAuthState,
)

URL_SAFE_ALPHABET: frozenset[str] = frozenset(
    string.ascii_letters + string.digits + "-_"
)


@pytest.mark.unit
class TestFreshCsrfToken:
    def test_returns_nonempty_string(self) -> None:
        token = fresh_csrf_token()
        assert isinstance(token, str)
        assert token != ""

    def test_token_uses_url_safe_alphabet(self) -> None:
        for _ in range(20):
            token = fresh_csrf_token()
            offenders = [c for c in token if c not in URL_SAFE_ALPHABET]
            assert (
                offenders == []
            ), f"Non-URL-safe characters in CSRF token: {offenders!r}"

    def test_token_has_high_entropy_length(self) -> None:
        token = fresh_csrf_token()
        assert len(token) >= 32, (
            "CSRF token suspiciously short — expected ≥32 chars from "
            "token_urlsafe(32)"
        )

    def test_consecutive_calls_yield_distinct_tokens(self) -> None:
        tokens = {fresh_csrf_token() for _ in range(50)}
        assert len(tokens) == 50, "fresh_csrf_token must not collide"

    def test_uses_stdlib_secrets_module(self) -> None:
        """Mock ``secrets.token_urlsafe`` and ensure the helper goes
        through it, not e.g. ``random``."""
        with patch.object(
            helpers_mod._secrets, "token_urlsafe", return_value="FAKE_TOK"
        ) as mock_token:
            out = fresh_csrf_token()
        assert out == "FAKE_TOK"
        mock_token.assert_called_once()


@pytest.mark.unit
class TestCompareCsrf:
    def test_equal_tokens_compare_true(self) -> None:
        token = fresh_csrf_token()
        assert compare_csrf(token, token) is True

    def test_different_tokens_compare_false(self) -> None:
        assert compare_csrf("abc", "abd") is False

    def test_empty_supplied_returns_false(self) -> None:
        assert compare_csrf("", "expected") is False

    def test_empty_expected_returns_false(self) -> None:
        assert compare_csrf("supplied", "") is False

    def test_both_empty_returns_false(self) -> None:
        """Both-empty must NOT short-circuit to True — that's the
        classic ``if a == b`` bug we explicitly defend against."""
        assert compare_csrf("", "") is False

    def test_uses_secrets_compare_digest(self) -> None:
        """compare_csrf must delegate to ``secrets.compare_digest``
        (constant-time). Verify by intercepting the call."""
        with patch.object(
            helpers_mod._secrets, "compare_digest", wraps=secrets.compare_digest
        ) as mock_cmp:
            compare_csrf("abc", "abc")
        mock_cmp.assert_called_once_with("abc", "abc")

    def test_source_file_does_not_use_naive_equality(self) -> None:
        """AST scan: confirm the implementation of ``compare_csrf`` does
        not contain a bare ``supplied == expected`` comparison — that
        would be a timing-attack regression even if the test above
        passed."""
        source = Path(helpers_mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        target: ast.FunctionDef | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "compare_csrf":
                target = node
                break
        assert target is not None, "compare_csrf not found in _helpers source"
        for sub in ast.walk(target):
            if isinstance(sub, ast.Compare) and any(
                isinstance(op, ast.Eq) for op in sub.ops
            ):
                names: list[str] = []
                if isinstance(sub.left, ast.Name):
                    names.append(sub.left.id)
                for c in sub.comparators:
                    if isinstance(c, ast.Name):
                        names.append(c.id)
                assert not {"supplied", "expected"}.issubset(set(names)), (
                    "compare_csrf uses '==' on supplied/expected — "
                    "timing attack vulnerability"
                )


@pytest.mark.unit
class TestConfigureSessionDefaults:
    def test_default_csrf_token_is_fresh_and_nonempty(self) -> None:
        session = ConfigureSession()
        assert session.csrf_token
        assert all(c in URL_SAFE_ALPHABET for c in session.csrf_token)

    def test_two_sessions_have_distinct_tokens(self) -> None:
        a = ConfigureSession()
        b = ConfigureSession()
        assert a.csrf_token != b.csrf_token

    def test_default_locale_is_english(self) -> None:
        assert ConfigureSession().locale == "en"

    def test_default_host_is_claude_code(self) -> None:
        assert ConfigureSession().host == "claude-code"

    def test_oauth_status_initialised_for_every_provider(self) -> None:
        session = ConfigureSession()
        for provider in OAUTH_PROVIDERS:
            state = session.oauth_status[provider]
            assert isinstance(state, OAuthState)
            assert state.pending is False
            assert state.success is False
            assert state.error is None


@pytest.mark.unit
class TestSetLocale:
    @pytest.mark.parametrize("locale", ["en", "ja"])
    def test_accepts_known_locales(self, locale: str) -> None:
        session = ConfigureSession()
        session.set_locale(locale)
        assert session.locale == locale

    @pytest.mark.parametrize(
        "junk",
        ["", "fr", "zh-CN", "../../etc/passwd", "<script>", " en "],
    )
    def test_ignores_unknown_locales(self, junk: str) -> None:
        session = ConfigureSession()
        before = session.locale
        session.set_locale(junk)
        assert session.locale == before


@pytest.mark.unit
class TestSetHost:
    @pytest.mark.parametrize("host", list(SUPPORTED_HOSTS))
    def test_accepts_known_hosts(self, host: str) -> None:
        session = ConfigureSession()
        session.set_host(host)
        assert session.host == host

    @pytest.mark.parametrize(
        "junk",
        ["", "vscode", "../etc/passwd", "Claude-Code", "claude_code"],
    )
    def test_ignores_unknown_hosts(self, junk: str) -> None:
        session = ConfigureSession()
        before = session.host
        session.set_host(junk)
        assert session.host == before


@pytest.mark.unit
class TestMarkOauthPending:
    def test_pending_for_known_provider_transitions_state(self) -> None:
        session = ConfigureSession()
        session.mark_oauth_pending("google")
        snapshot = session.get_oauth_status("google")
        assert snapshot["pending"] is True
        assert snapshot["success"] is False
        assert snapshot["error"] is None

    def test_pending_resets_previous_error(self) -> None:
        session = ConfigureSession()
        session.mark_oauth_complete("google", success=False, error="boom")
        session.mark_oauth_pending("google")
        snapshot = session.get_oauth_status("google")
        assert snapshot["error"] is None
        assert snapshot["pending"] is True

    def test_pending_rejects_unknown_provider(self) -> None:
        session = ConfigureSession()
        with pytest.raises(ValueError, match="unknown provider"):
            session.mark_oauth_pending("twitter")


@pytest.mark.unit
class TestMarkOauthComplete:
    def test_marks_success(self) -> None:
        session = ConfigureSession()
        session.mark_oauth_pending("meta")
        session.mark_oauth_complete("meta", success=True)
        snapshot = session.get_oauth_status("meta")
        assert snapshot == {"pending": False, "success": True, "error": None}

    def test_marks_failure_with_reason(self) -> None:
        session = ConfigureSession()
        session.mark_oauth_complete("meta", success=False, error="user_denied")
        snapshot = session.get_oauth_status("meta")
        assert snapshot == {
            "pending": False,
            "success": False,
            "error": "user_denied",
        }

    def test_complete_rejects_unknown_provider(self) -> None:
        session = ConfigureSession()
        with pytest.raises(ValueError, match="unknown provider"):
            session.mark_oauth_complete("github", success=True)


@pytest.mark.unit
class TestGetOauthStatus:
    def test_rejects_unknown_provider(self) -> None:
        session = ConfigureSession()
        with pytest.raises(ValueError):
            session.get_oauth_status("twitter")

    def test_status_all_returns_every_provider(self) -> None:
        session = ConfigureSession()
        out = session.get_oauth_status_all()
        assert set(out.keys()) == set(OAUTH_PROVIDERS)
        for entry in out.values():
            assert set(entry.keys()) == {"pending", "success", "error"}

    def test_status_all_reflects_per_provider_state(self) -> None:
        session = ConfigureSession()
        session.mark_oauth_pending("google")
        session.mark_oauth_complete("meta", success=True)
        out = session.get_oauth_status_all()
        assert out["google"]["pending"] is True
        assert out["google"]["success"] is False
        assert out["meta"]["pending"] is False
        assert out["meta"]["success"] is True


@pytest.mark.unit
class TestOauthProviderAllowList:
    def test_only_google_and_meta_are_allowed(self) -> None:
        assert set(OAUTH_PROVIDERS) == {"google", "meta"}

    def test_oauth_providers_is_a_tuple(self) -> None:
        assert isinstance(OAUTH_PROVIDERS, tuple)

    def test_supported_hosts_is_a_tuple(self) -> None:
        assert isinstance(SUPPORTED_HOSTS, tuple)
