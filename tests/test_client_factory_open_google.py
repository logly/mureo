"""The one Google Ads client opener shared by MCP, analytics and change import (#875).

:func:`mureo.client_factory.open_google_ads_client` owns the precedence
(credential source → BYOD → credentials file), the workspace scoping, the
numeric id check, the missing-credentials error and the process-wide rate
limiter. These tests pin each of them at the opener; the callers' own suites
pin how they map its failures.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.auth import GoogleAdsCredentials
from mureo.client_factory import (
    GOOGLE_ADS_THROTTLER,
    AccountIdRefused,
    NoCredentialsError,
    open_google_ads_client,
)
from mureo.core.credential_source import CredentialSource, use_credential_source

pytestmark = pytest.mark.unit

_FILE_CREDS = GoogleAdsCredentials(
    client_id="placeholder",
    client_secret="placeholder",
    refresh_token="placeholder",
    customer_id="1112223333",
)
_SOURCE_CREDS = GoogleAdsCredentials(
    client_id="placeholder",
    client_secret="placeholder",
    refresh_token="placeholder",
    customer_id="4445556666",
)


class _GoogleSource:
    def __init__(self, creds: GoogleAdsCredentials | None, oauth: Any) -> None:
        self.creds = creds
        self.oauth = oauth

    def load_credentials(self) -> GoogleAdsCredentials | None:
        return self.creds

    def oauth_credentials(self, credentials: GoogleAdsCredentials) -> Any:
        return self.oauth


@pytest.fixture
def unscoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """No workspace allow-list: ids pass through ``resolve_customer_id``."""
    monkeypatch.setattr(
        "mureo.core.account_scope.runtime_google_ads_customer_ids", lambda: None
    )


@pytest.fixture
def byod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.client_factory.byod_has", lambda platform: True)


@pytest.fixture
def no_byod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.client_factory.byod_has", lambda platform: False)


@pytest.mark.usefixtures("unscoped", "byod")
class TestPrecedence:
    def test_source_wins_over_byod_and_file(self) -> None:
        oauth = object()
        source = _GoogleSource(_SOURCE_CREDS, oauth)
        with (
            patch(
                "mureo.auth.load_google_ads_credentials", return_value=_FILE_CREDS
            ) as load_file,
            patch("mureo.client_factory.get_google_ads_client") as byod_factory,
            patch("mureo.auth.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=source)),
        ):
            client, resolved = open_google_ads_client()
        assert client is factory.return_value
        assert resolved == "4445556666"
        factory.assert_called_once_with(
            _SOURCE_CREDS,
            "4445556666",
            throttler=GOOGLE_ADS_THROTTLER,
            oauth_credentials=oauth,
        )
        load_file.assert_not_called()
        byod_factory.assert_not_called()

    def test_byod_without_an_id_opens_as_byod(self) -> None:
        with (
            patch("mureo.auth.load_google_ads_credentials") as load_file,
            patch("mureo.client_factory.get_google_ads_client") as byod_factory,
        ):
            client, resolved = open_google_ads_client()
        assert client is byod_factory.return_value
        assert resolved == "byod"
        assert byod_factory.call_args.kwargs["creds"] is None
        assert byod_factory.call_args.kwargs["customer_id"] == "byod"
        load_file.assert_not_called()

    def test_byod_with_an_empty_id_opens_as_byod(self) -> None:
        with patch("mureo.client_factory.get_google_ads_client") as byod_factory:
            client, resolved = open_google_ads_client("")
        assert client is byod_factory.return_value
        assert resolved == "byod"
        assert byod_factory.call_args.kwargs["customer_id"] == "byod"

    def test_byod_with_the_byod_id_opens_as_byod(self) -> None:
        """``"byod"`` is the id the BYOD client's ``list_accounts`` returns, so
        an agent passing it back gets the BYOD client, not a format error."""
        with patch("mureo.client_factory.get_google_ads_client") as byod_factory:
            client, resolved = open_google_ads_client("byod")
        assert client is byod_factory.return_value
        assert resolved == "byod"
        assert byod_factory.call_args.kwargs["customer_id"] == "byod"

    def test_byod_with_an_id_opens_with_the_resolved_id(self) -> None:
        with patch("mureo.client_factory.get_google_ads_client") as byod_factory:
            client, resolved = open_google_ads_client("123-456-7890")
        assert client is byod_factory.return_value
        assert resolved == "123-456-7890"
        assert byod_factory.call_args.kwargs["customer_id"] == "123-456-7890"


@pytest.mark.usefixtures("unscoped", "no_byod")
class TestCredentialsFile:
    def test_file_path_uses_the_credentials_default(self) -> None:
        with (
            patch("mureo.auth.load_google_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.create_google_ads_client") as factory,
        ):
            client, resolved = open_google_ads_client()
        assert client is factory.return_value
        assert resolved == "1112223333"
        factory.assert_called_once_with(
            _FILE_CREDS, "1112223333", throttler=GOOGLE_ADS_THROTTLER
        )

    def test_login_customer_id_is_the_fallback_default(self) -> None:
        creds = GoogleAdsCredentials(
            client_id="placeholder",
            client_secret="placeholder",
            refresh_token="placeholder",
            login_customer_id="7778889999",
        )
        with (
            patch("mureo.auth.load_google_ads_credentials", return_value=creds),
            patch("mureo.auth.create_google_ads_client") as factory,
        ):
            _, resolved = open_google_ads_client()
        assert resolved == "7778889999"
        assert factory.call_args.args[1] == "7778889999"

    def test_explicit_id_wins_over_the_default(self) -> None:
        with (
            patch("mureo.auth.load_google_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.create_google_ads_client") as factory,
        ):
            _, resolved = open_google_ads_client("999-888-7777")
        assert resolved == "999-888-7777"
        assert factory.call_args.args[1] == "999-888-7777"

    def test_neither_source_nor_file_raises_no_credentials(self) -> None:
        with (
            patch("mureo.auth.load_google_ads_credentials", return_value=None),
            patch("mureo.auth.create_google_ads_client") as factory,
            pytest.raises(
                NoCredentialsError, match="google_ads credentials are not configured"
            ),
        ):
            open_google_ads_client("1112223333")
        factory.assert_not_called()

    def test_a_source_without_credentials_raises_no_credentials(self) -> None:
        source = _GoogleSource(None, object())
        with (
            patch("mureo.auth.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=source)),
            pytest.raises(NoCredentialsError),
        ):
            open_google_ads_client("1112223333")
        factory.assert_not_called()

    def test_a_non_numeric_id_is_refused(self) -> None:
        with (
            patch("mureo.auth.load_google_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.create_google_ads_client") as factory,
            pytest.raises(AccountIdRefused, match="Invalid customer_id format"),
        ):
            open_google_ads_client("acct-1")
        factory.assert_not_called()

    def test_oauth_is_not_passed_when_the_source_returns_none(self) -> None:
        source = _GoogleSource(_SOURCE_CREDS, None)
        with (
            patch("mureo.auth.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=source)),
        ):
            open_google_ads_client()
        assert factory.call_args.kwargs == {"throttler": GOOGLE_ADS_THROTTLER}


class TestScoping:
    @pytest.fixture(autouse=True)
    def _scoped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mureo.core.account_scope.runtime_google_ads_customer_ids",
            lambda: frozenset({"1112223333"}),
        )

    @pytest.mark.usefixtures("no_byod")
    def test_live_refuses_an_out_of_scope_id(self) -> None:
        with (
            patch("mureo.auth.load_google_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.create_google_ads_client") as factory,
            pytest.raises(AccountIdRefused, match="refused"),
        ):
            open_google_ads_client("2223334444")
        factory.assert_not_called()

    @pytest.mark.usefixtures("byod")
    def test_byod_refuses_an_out_of_scope_id(self) -> None:
        with (
            patch("mureo.client_factory.get_google_ads_client") as byod_factory,
            pytest.raises(AccountIdRefused, match="refused"),
        ):
            open_google_ads_client("2223334444")
        byod_factory.assert_not_called()


def test_one_throttler_for_every_live_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two opens share the same limiter instance, not one each."""
    monkeypatch.setattr(
        "mureo.core.account_scope.runtime_google_ads_customer_ids", lambda: None
    )
    monkeypatch.setattr("mureo.client_factory.byod_has", lambda platform: False)
    factory = MagicMock()
    with (
        patch("mureo.auth.load_google_ads_credentials", return_value=_FILE_CREDS),
        patch("mureo.auth.create_google_ads_client", factory),
    ):
        open_google_ads_client()
        open_google_ads_client("999")
    first, second = (call.kwargs["throttler"] for call in factory.call_args_list)
    assert first is second is GOOGLE_ADS_THROTTLER
