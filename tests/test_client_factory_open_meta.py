"""The one Meta Ads client opener shared by MCP and analytics (#875).

:func:`mureo.client_factory.open_meta_ads_client` owns the precedence
(credential source → BYOD → credentials file), the workspace scoping, the
``act_`` canonicalization, the file-token refresh, the missing-credentials
error and the process-wide rate limiter. These tests pin each of them at the
opener; the callers' own suites pin how they map its failures.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth import MetaAdsCredentials
from mureo.client_factory import (
    META_ADS_THROTTLER,
    AccountIdRefused,
    NoCredentialsError,
    open_meta_ads_client,
)
from mureo.core.credential_source import CredentialSource, use_credential_source

pytestmark = pytest.mark.unit

_FILE_CREDS = MetaAdsCredentials(access_token="placeholder", account_id="act_111")
_REFRESHED_CREDS = MetaAdsCredentials(
    access_token="placeholder-refreshed", account_id="act_111"
)
_SOURCE_CREDS = MetaAdsCredentials(access_token="placeholder", account_id="act_444")


class _MetaSource:
    def __init__(self, creds: MetaAdsCredentials | None) -> None:
        self.creds = creds

    def load_credentials(self) -> MetaAdsCredentials | None:
        return self.creds


def _refresh_spy() -> AsyncMock:
    return AsyncMock(return_value=_REFRESHED_CREDS)


@pytest.fixture
def unscoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """No workspace allow-list: ids pass through ``resolve_account_id``."""
    monkeypatch.setattr(
        "mureo.core.account_scope.runtime_meta_account_ids", lambda: None
    )


@pytest.fixture
def byod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.client_factory.byod_has", lambda platform: True)


@pytest.fixture
def no_byod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.client_factory.byod_has", lambda platform: False)


@pytest.mark.usefixtures("unscoped", "byod")
class TestPrecedence:
    async def test_source_wins_over_byod_and_file(self) -> None:
        refresh = _refresh_spy()
        with (
            patch(
                "mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS
            ) as load_file,
            patch("mureo.auth.refresh_meta_token_if_needed", refresh),
            patch("mureo.client_factory.get_meta_ads_client") as byod_factory,
            patch("mureo.auth.create_meta_ads_client") as factory,
            use_credential_source(
                CredentialSource(meta_ads=_MetaSource(_SOURCE_CREDS))
            ),
        ):
            client, resolved = await open_meta_ads_client()
        assert client is factory.return_value
        assert resolved == "act_444"
        factory.assert_called_once_with(
            _SOURCE_CREDS, "act_444", throttler=META_ADS_THROTTLER
        )
        load_file.assert_not_called()
        byod_factory.assert_not_called()

    async def test_source_credentials_reach_the_factory_unrefreshed(self) -> None:
        """The source owns the token lifecycle (#821): no refresh, and the
        credentials it returned are the ones the client gets."""
        refresh = _refresh_spy()
        with (
            patch("mureo.auth.refresh_meta_token_if_needed", refresh),
            patch("mureo.auth.create_meta_ads_client") as factory,
            use_credential_source(
                CredentialSource(meta_ads=_MetaSource(_SOURCE_CREDS))
            ),
        ):
            await open_meta_ads_client("act_444")
        refresh.assert_not_awaited()
        assert factory.call_args.args[0] is _SOURCE_CREDS

    async def test_byod_without_an_id_opens_as_act_byod(self) -> None:
        refresh = _refresh_spy()
        with (
            patch("mureo.auth.load_meta_ads_credentials") as load_file,
            patch("mureo.auth.refresh_meta_token_if_needed", refresh),
            patch("mureo.client_factory.get_meta_ads_client") as byod_factory,
        ):
            client, resolved = await open_meta_ads_client()
        assert client is byod_factory.return_value
        assert resolved == "act_byod"
        assert byod_factory.call_args.kwargs["creds"] is None
        assert byod_factory.call_args.kwargs["account_id"] == "act_byod"
        assert byod_factory.call_args.kwargs["throttler"] is META_ADS_THROTTLER
        load_file.assert_not_called()
        refresh.assert_not_awaited()

    async def test_byod_with_an_empty_id_opens_as_act_byod(self) -> None:
        with patch("mureo.client_factory.get_meta_ads_client") as byod_factory:
            client, resolved = await open_meta_ads_client("")
        assert client is byod_factory.return_value
        assert resolved == "act_byod"
        assert byod_factory.call_args.kwargs["account_id"] == "act_byod"

    async def test_byod_with_the_byod_id_opens_as_act_byod(self) -> None:
        with patch("mureo.client_factory.get_meta_ads_client") as byod_factory:
            client, resolved = await open_meta_ads_client("act_byod")
        assert client is byod_factory.return_value
        assert resolved == "act_byod"
        assert byod_factory.call_args.kwargs["account_id"] == "act_byod"

    async def test_byod_with_an_id_opens_with_the_canonical_id(self) -> None:
        with patch("mureo.client_factory.get_meta_ads_client") as byod_factory:
            client, resolved = await open_meta_ads_client("222")
        assert client is byod_factory.return_value
        assert resolved == "act_222"
        assert byod_factory.call_args.kwargs["account_id"] == "act_222"


@pytest.mark.usefixtures("unscoped", "no_byod")
class TestCredentialsFile:
    async def test_file_path_uses_the_credentials_default(self) -> None:
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.refresh_meta_token_if_needed", _refresh_spy()),
            patch("mureo.auth.create_meta_ads_client") as factory,
        ):
            client, resolved = await open_meta_ads_client()
        assert client is factory.return_value
        assert resolved == "act_111"
        factory.assert_called_once_with(
            _REFRESHED_CREDS, "act_111", throttler=META_ADS_THROTTLER
        )

    async def test_file_token_is_refreshed_before_the_client_is_built(self) -> None:
        refresh = _refresh_spy()
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.refresh_meta_token_if_needed", refresh),
            patch("mureo.auth.create_meta_ads_client") as factory,
        ):
            await open_meta_ads_client()
        refresh.assert_awaited_once_with(_FILE_CREDS)
        assert factory.call_args.args[0] is _REFRESHED_CREDS

    async def test_explicit_id_wins_over_the_default(self) -> None:
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.refresh_meta_token_if_needed", _refresh_spy()),
            patch("mureo.auth.create_meta_ads_client") as factory,
        ):
            _, resolved = await open_meta_ads_client("act_999")
        assert resolved == "act_999"
        assert factory.call_args.args[1] == "act_999"

    async def test_a_bare_id_is_prefixed(self) -> None:
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.refresh_meta_token_if_needed", _refresh_spy()),
            patch("mureo.auth.create_meta_ads_client") as factory,
        ):
            _, resolved = await open_meta_ads_client("999")
        assert resolved == "act_999"
        assert factory.call_args.args[1] == "act_999"

    async def test_neither_source_nor_file_raises_no_credentials(self) -> None:
        refresh = _refresh_spy()
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=None),
            patch("mureo.auth.refresh_meta_token_if_needed", refresh),
            patch("mureo.auth.create_meta_ads_client") as factory,
            pytest.raises(
                NoCredentialsError, match="meta_ads credentials are not configured"
            ),
        ):
            await open_meta_ads_client("act_111")
        factory.assert_not_called()
        refresh.assert_not_awaited()

    async def test_a_source_without_credentials_raises_no_credentials(self) -> None:
        with (
            patch("mureo.auth.create_meta_ads_client") as factory,
            use_credential_source(CredentialSource(meta_ads=_MetaSource(None))),
            pytest.raises(NoCredentialsError),
        ):
            await open_meta_ads_client("act_111")
        factory.assert_not_called()


class TestScoping:
    @pytest.fixture(autouse=True)
    def _scoped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mureo.core.account_scope.runtime_meta_account_ids",
            lambda: frozenset({"act_111"}),
        )

    @pytest.mark.usefixtures("no_byod")
    async def test_live_refuses_an_out_of_scope_id(self) -> None:
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.refresh_meta_token_if_needed", _refresh_spy()),
            patch("mureo.auth.create_meta_ads_client") as factory,
            pytest.raises(AccountIdRefused, match="refused"),
        ):
            await open_meta_ads_client("act_222")
        factory.assert_not_called()

    @pytest.mark.usefixtures("byod")
    async def test_byod_refuses_an_out_of_scope_id(self) -> None:
        with (
            patch("mureo.client_factory.get_meta_ads_client") as byod_factory,
            pytest.raises(AccountIdRefused, match="refused"),
        ):
            await open_meta_ads_client("act_222")
        byod_factory.assert_not_called()

    @pytest.mark.usefixtures("no_byod")
    async def test_live_opens_a_bare_in_scope_id_as_act(self) -> None:
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.refresh_meta_token_if_needed", _refresh_spy()),
            patch("mureo.auth.create_meta_ads_client") as factory,
        ):
            _, resolved = await open_meta_ads_client("111")
        assert resolved == "act_111"
        assert factory.call_args.args[1] == "act_111"

    @pytest.mark.usefixtures("no_byod")
    async def test_live_refuses_a_bare_out_of_scope_id(self) -> None:
        """Prefixing a bare id never widens the scope: ``"222"`` is still
        checked against the allow-list and refused."""
        with (
            patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
            patch("mureo.auth.refresh_meta_token_if_needed", _refresh_spy()),
            patch("mureo.auth.create_meta_ads_client") as factory,
            pytest.raises(AccountIdRefused, match="refused"),
        ):
            await open_meta_ads_client("222")
        factory.assert_not_called()

    @pytest.mark.usefixtures("byod")
    async def test_byod_opens_the_byod_id_unchecked(self) -> None:
        """The one exemption: ``"act_byod"`` in BYOD mode is not in the
        allow-list but opens anyway (no credentials to scope against)."""
        with patch("mureo.client_factory.get_meta_ads_client") as byod_factory:
            client, resolved = await open_meta_ads_client("act_byod")
        assert client is byod_factory.return_value
        assert resolved == "act_byod"
        assert byod_factory.call_args.kwargs["account_id"] == "act_byod"


async def test_one_throttler_for_every_live_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two opens share the same limiter instance, not one each."""
    monkeypatch.setattr(
        "mureo.core.account_scope.runtime_meta_account_ids", lambda: None
    )
    monkeypatch.setattr("mureo.client_factory.byod_has", lambda platform: False)
    factory = MagicMock()
    with (
        patch("mureo.auth.load_meta_ads_credentials", return_value=_FILE_CREDS),
        patch("mureo.auth.refresh_meta_token_if_needed", _refresh_spy()),
        patch("mureo.auth.create_meta_ads_client", factory),
    ):
        await open_meta_ads_client()
        await open_meta_ads_client("act_999")
    first, second = (call.kwargs["throttler"] for call in factory.call_args_list)
    assert first is second is META_ADS_THROTTLER
