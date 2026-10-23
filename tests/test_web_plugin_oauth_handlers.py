"""#201 — configure-handler endpoints for the generic plugin OAuth flow.

Covers ``POST /api/credentials/plugins/<p>/oauth/start`` and
``GET  …/oauth/status`` plus the ``oauth`` descriptor block surfaced by
``GET /api/credentials/plugins``. The OAuth bridge is patched so no real
wizard binds; these tests pin the handler's policy: a provider must be
registered and declare ``account_oauth``, the saved client id/secret are
loaded before the flow starts (else ``400 client_credentials_missing``),
and the descriptor exposes only field *keys*, never secret values.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from mureo.core.providers import AccountCredentialField, AccountOAuthConfig
from mureo.core.providers.registry import ProviderEntry, default_registry
from mureo.web.oauth_bridge import OAuthHandoffResult
from mureo.web.server import ConfigureWizard
from tests.web_support import get, post

_OAUTH = AccountOAuthConfig(
    authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
    token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
    client_id_field="client_id",
    client_secret_field="client_secret",
    target_field="refresh_token",
    scopes=("scopeA",),
)
_FIELDS = (
    AccountCredentialField(key="client_id", display_name="Client ID"),
    AccountCredentialField(key="client_secret", display_name="Secret", secret=True),
    AccountCredentialField(key="refresh_token", display_name="Refresh", secret=True),
)


def _oauth_class() -> type:
    class _Yahoo:
        name = "yahoo_ads"
        display_name = "Yahoo! JAPAN Ads"
        capabilities = frozenset()
        account_credential_fields = _FIELDS
        account_oauth = _OAUTH

    return _Yahoo


def _plain_class() -> type:
    class _Demo:
        name = "demo_ads"
        display_name = "Demo Ads"
        capabilities = frozenset()
        account_credential_fields = (
            AccountCredentialField(key="api_key", display_name="API Key", secret=True),
        )

    return _Demo


def _entry(cls: type) -> ProviderEntry:
    return ProviderEntry(
        name=cls.name,  # type: ignore[attr-defined]
        display_name=cls.display_name,  # type: ignore[attr-defined]
        capabilities=frozenset(),
        provider_class=cls,
        source_distribution=None,
    )


@pytest.fixture
def _two_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {"yahoo_ads": _entry(_oauth_class()), "demo_ads": _entry(_plain_class())},
    )


@pytest.fixture
def wizard(_two_plugins: None, wizard: ConfigureWizard) -> ConfigureWizard:
    """The shared wizard, booted only once the registry holds the two plugins."""
    return wizard


_CALLBACK_URL = "http://127.0.0.1:8765/oauth/callback"


def _authenticate_payload() -> dict:
    """Form values a dashboard Authenticate click submits (#217): client
    creds + the operator-registered loopback callback URL (#216), with no
    prior Save on disk."""
    return {
        "values": {
            "client_id": "CID",
            "client_secret": "SECRET",
            "oauth_callback_url": _CALLBACK_URL,
        }
    }


# ---------------------------------------------------------------------------
# GET /api/credentials/plugins — oauth descriptor block (#201 / Batch 6)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_plugin_list_exposes_oauth_block(wizard: ConfigureWizard) -> None:
    status, body = get(wizard, "/api/credentials/plugins")
    assert status == 200, body
    by_name = {p["provider_name"]: p for p in body["plugins"]}
    assert by_name["yahoo_ads"]["oauth"] == {
        "target_field": "refresh_token",
        "client_id_field": "client_id",
        "client_secret_field": "client_secret",
    }
    # A manual-entry provider declares no oauth → null (no Authenticate button).
    assert by_name["demo_ads"]["oauth"] is None
    # The descriptor leaks no endpoints/secrets.
    assert "authorize_url" not in json.dumps(by_name["yahoo_ads"]["oauth"])


@pytest.mark.unit
def test_plugin_list_surfaces_saved_callback_url(wizard: ConfigureWizard) -> None:
    """#216: a previously-saved (non-secret) ``oauth_callback_url`` is
    surfaced in the list payload so the dashboard can pre-fill it on
    re-auth instead of resetting to the well-known default."""
    path = wizard.host_paths.credentials_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "yahoo_ads": {
                    "client_id": "CID",
                    "oauth_callback_url": "http://127.0.0.1:9000/cb",
                }
            }
        )
    )
    status, body = get(wizard, "/api/credentials/plugins")
    assert status == 200, body
    by_name = {p["provider_name"]: p for p in body["plugins"]}
    assert by_name["yahoo_ads"]["oauth_callback_url"] == "http://127.0.0.1:9000/cb"
    # Manual provider never gets the key.
    assert "oauth_callback_url" not in by_name["demo_ads"]


@pytest.mark.unit
def test_plugin_list_surfaces_field_current_state(wizard: ConfigureWizard) -> None:
    """#224: each declared field carries a ``configured`` flag; a non-secret
    field also ships its stored value verbatim for pre-fill, while a secret
    field NEVER ships its value (only the flag)."""
    path = wizard.host_paths.credentials_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"yahoo_ads": {"client_id": "CID", "client_secret": "SECRET"}})
    )
    status, body = get(wizard, "/api/credentials/plugins")
    assert status == 200, body
    fields = {
        f["key"]: f
        for p in body["plugins"]
        if p["provider_name"] == "yahoo_ads"
        for f in p["fields"]
    }
    # Non-secret, stored → configured + value verbatim.
    assert fields["client_id"]["configured"] is True
    assert fields["client_id"]["value"] == "CID"
    # Secret, stored → configured True but NO value shipped to the browser.
    assert fields["client_secret"]["configured"] is True
    assert "value" not in fields["client_secret"]
    # Unset field → not configured, no value.
    assert fields["refresh_token"]["configured"] is False
    assert "value" not in fields["refresh_token"]
    # Defense in depth: the secret value never appears anywhere in payload.
    assert "SECRET" not in json.dumps(body)


# ---------------------------------------------------------------------------
# POST …/oauth/start
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_start_400_when_client_credentials_missing(wizard: ConfigureWizard) -> None:
    # No form values submitted → no client id/secret → 400 (#217: creds
    # come from the request body, not disk).
    status, body = post(wizard, "/api/credentials/plugins/yahoo_ads/oauth/start")
    assert status == 400
    assert body["error"] == "client_credentials_missing"


@pytest.mark.unit
def test_start_success_uses_form_values_no_prior_save(
    wizard: ConfigureWizard,
) -> None:
    """#217: Authenticate succeeds with the submitted form values and NO
    prior Save on disk; the bridge receives the client creds, the operator
    callback URL (#216), and persist_values for the atomic write."""
    fake = OAuthHandoffResult(
        url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize?x=1",
        state="pending",
        provider="yahoo_ads",
    )
    # Nothing on disk — the credentials file does not exist yet.
    assert not wizard.host_paths.credentials_path.exists()
    with patch.object(
        wizard.oauth_bridge, "start_plugin_oauth", return_value=fake
    ) as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _authenticate_payload(),
        )
        assert status == 200, body
    assert body["url"].startswith("https://biz-oauth.yahoo.co.jp/oauth/v1/authorize")
    kwargs = mock_start.call_args.kwargs
    assert kwargs["provider"] == "yahoo_ads"
    assert kwargs["client_id"] == "CID"
    assert kwargs["client_secret"] == "SECRET"
    assert kwargs["callback_url"] == _CALLBACK_URL
    assert kwargs["oauth_config"].target_field == "refresh_token"
    # persist_values carries the operator's values (restricted to declared
    # field keys) + the callback URL, for the bridge's atomic save.
    persist = kwargs["persist_values"]
    assert persist["client_id"] == "CID"
    assert persist["client_secret"] == "SECRET"
    assert persist["oauth_callback_url"] == _CALLBACK_URL
    # The required-but-unfilled target_field is never persisted as blank.
    assert "refresh_token" not in persist


def _store_section(wiz: ConfigureWizard, section: dict) -> None:
    """Pre-populate the provider's credentials section on disk, as an
    earlier Save or an installer would have."""
    path = wiz.host_paths.credentials_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"yahoo_ads": section}))


def _blank_creds_payload(**overrides: str) -> dict:
    """An Authenticate POST whose client creds are blank, as the dashboard
    sends them when the secret is stored but never pre-filled."""
    values = {
        "client_id": "",
        "client_secret": "  ",
        "oauth_callback_url": _CALLBACK_URL,
    }
    values.update(overrides)
    return {"values": values}


def _fake_handoff() -> OAuthHandoffResult:
    return OAuthHandoffResult(
        url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize?x=1",
        state="pending",
        provider="yahoo_ads",
    )


@pytest.mark.unit
def test_start_reuses_stored_client_credentials_when_form_blank(
    wizard: ConfigureWizard,
) -> None:
    """Stored client id/secret + blank form values: the flow starts with
    the stored values, and persist_values carries them (not ``""``) so the
    callback's atomic write cannot blank a stored secret."""
    _store_section(wizard, {"client_id": "STORED_CID", "client_secret": "STORED_S"})
    with patch.object(
        wizard.oauth_bridge, "start_plugin_oauth", return_value=_fake_handoff()
    ) as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _blank_creds_payload(),
        )
        assert status == 200
    kwargs = mock_start.call_args.kwargs
    assert kwargs["client_id"] == "STORED_CID"
    assert kwargs["client_secret"] == "STORED_S"
    persist = kwargs["persist_values"]
    assert persist["client_id"] == "STORED_CID"
    assert persist["client_secret"] == "STORED_S"
    assert persist["oauth_callback_url"] == _CALLBACK_URL


@pytest.mark.unit
def test_start_posted_client_secret_wins_over_stored(
    wizard: ConfigureWizard,
) -> None:
    """A non-blank posted value is used verbatim; storage is only a
    fallback for blanks."""
    _store_section(wizard, {"client_id": "STORED_CID", "client_secret": "STORED_S"})
    with patch.object(
        wizard.oauth_bridge, "start_plugin_oauth", return_value=_fake_handoff()
    ) as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _blank_creds_payload(client_secret="POSTED_S"),
        )
        assert status == 200, body
    kwargs = mock_start.call_args.kwargs
    assert kwargs["client_secret"] == "POSTED_S"
    assert kwargs["persist_values"]["client_secret"] == "POSTED_S"
    # The blank client id still falls back to storage.
    assert kwargs["client_id"] == "STORED_CID"


@pytest.mark.unit
def test_start_400_when_blank_form_and_nothing_stored(
    wizard: ConfigureWizard,
) -> None:
    with patch.object(wizard.oauth_bridge, "start_plugin_oauth") as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _blank_creds_payload(),
        )
    assert status == 400
    assert body["error"] == "client_credentials_missing"
    mock_start.assert_not_called()


@pytest.mark.unit
def test_start_400_when_only_client_id_stored(wizard: ConfigureWizard) -> None:
    """One of the pair stored, the other blank in the form and absent from
    storage (or stored empty) -> still 400."""
    _store_section(wizard, {"client_id": "STORED_CID", "client_secret": ""})
    with patch.object(wizard.oauth_bridge, "start_plugin_oauth") as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _blank_creds_payload(),
        )
    assert status == 400
    assert body["error"] == "client_credentials_missing"
    mock_start.assert_not_called()


@pytest.mark.unit
def test_start_400_when_only_client_secret_stored(wizard: ConfigureWizard) -> None:
    _store_section(wizard, {"client_secret": "STORED_S"})
    with patch.object(wizard.oauth_bridge, "start_plugin_oauth") as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _blank_creds_payload(),
        )
    assert status == 400
    assert body["error"] == "client_credentials_missing"
    mock_start.assert_not_called()


@pytest.mark.unit
def test_start_never_fills_target_field_from_storage(
    wizard: ConfigureWizard,
) -> None:
    """The consent-obtained token is never copied from storage into
    persist_values, even when one is stored and the form posts it blank;
    the callback writes the new token itself."""
    _store_section(
        wizard,
        {
            "client_id": "STORED_CID",
            "client_secret": "STORED_S",
            "refresh_token": "OLD_TOKEN",
        },
    )
    with patch.object(
        wizard.oauth_bridge, "start_plugin_oauth", return_value=_fake_handoff()
    ) as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _blank_creds_payload(refresh_token=""),
        )
        assert status == 200, body
    persist = mock_start.call_args.kwargs["persist_values"]
    assert "refresh_token" not in persist
    assert "OLD_TOKEN" not in json.dumps(mock_start.call_args.kwargs, default=str)


@pytest.mark.unit
def test_start_does_not_echo_stored_credentials_in_response(
    wizard: ConfigureWizard,
) -> None:
    """Neither the 400 envelope nor the success body carries a stored
    credential value."""
    _store_section(wizard, {"client_id": "STORED_CID", "client_secret": "STORED_S"})
    with patch.object(
        wizard.oauth_bridge, "start_plugin_oauth", return_value=_fake_handoff()
    ):
        status, body = post(
            wizard,
            "/api/credentials/plugins/yahoo_ads/oauth/start",
            _blank_creds_payload(),
        )
    assert status == 200, body
    raw = json.dumps(body, ensure_ascii=False)
    assert "STORED_S" not in raw
    assert "STORED_CID" not in raw


@pytest.mark.unit
def test_start_400_when_callback_url_invalid(wizard: ConfigureWizard) -> None:
    """A non-loopback / missing callback URL (#216) is rejected with a
    specific code before the bridge is touched."""
    payload = {
        "values": {
            "client_id": "CID",
            "client_secret": "SECRET",
            "oauth_callback_url": "https://example.com/oauth/callback",
        }
    }
    with patch.object(wizard.oauth_bridge, "start_plugin_oauth") as mock_start:
        status, body = post(
            wizard, "/api/credentials/plugins/yahoo_ads/oauth/start", payload
        )
    assert status == 400
    assert body["error"] == "callback_url_invalid"
    mock_start.assert_not_called()


@pytest.mark.unit
def test_start_400_when_token_headers_invalid(
    wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider declaring a reserved ``token_headers`` name fails the
    reader's validation, so start answers the existing clean 400 before
    the bridge is touched."""

    class _BadHeaders:
        name = "broker_ads"
        display_name = "Broker Ads"
        capabilities = frozenset()
        account_credential_fields = _FIELDS
        account_oauth = AccountOAuthConfig(
            authorize_url="https://broker.example.com/oauth/authorize",
            token_url="https://broker.example.com/oauth/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="refresh_token",
            token_headers=(("Authorization", "Bearer x"),),
        )

    monkeypatch.setitem(default_registry._entries, "broker_ads", _entry(_BadHeaders))
    with patch.object(wizard.oauth_bridge, "start_plugin_oauth") as mock_start:
        status, body = post(
            wizard,
            "/api/credentials/plugins/broker_ads/oauth/start",
            _authenticate_payload(),
        )
    assert status == 400
    assert body["error"] == "invalid_oauth_config"
    mock_start.assert_not_called()


@pytest.mark.unit
def test_start_404_for_unknown_provider(wizard: ConfigureWizard) -> None:
    status, body = post(wizard, "/api/credentials/plugins/nope_ads/oauth/start")
    assert status == 404


@pytest.mark.unit
def test_start_404_when_provider_has_no_oauth(wizard: ConfigureWizard) -> None:
    status, body = post(wizard, "/api/credentials/plugins/demo_ads/oauth/start")
    assert status == 404
    assert body["error"] == "oauth_not_supported"


# ---------------------------------------------------------------------------
# GET …/oauth/status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_status_idle_before_start(wizard: ConfigureWizard) -> None:
    status, body = get(wizard, "/api/credentials/plugins/yahoo_ads/oauth/status")
    assert status == 200, body
    assert body == {
        "pending": False,
        "success": False,
        "error": None,
    }


@pytest.mark.unit
def test_status_404_for_unknown_provider(wizard: ConfigureWizard) -> None:
    status, _ = get(wizard, "/api/credentials/plugins/nope_ads/oauth/status")
    assert status == 404
