"""HTTP integration tests for the plugin-credentials routes.

Boots a real :class:`ConfigureWizard` on 127.0.0.1:0 in a daemon
thread and exercises:

- ``GET  /api/credentials/plugins``       — registry walk → JSON list
- ``POST /api/credentials/plugins/save``  — write to a per-test
  ``credentials.json`` via a stubbed :class:`FilesystemSecretStore`
  rooted under ``tmp_path``.

The CSRF and Host-header gates established by ``test_web_handlers.py``
are not re-exercised here — those routes share the same dispatch loop
and the new routes pick up the gates automatically.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core.providers import AccountCredentialField, default_registry
from mureo.core.providers.registry import ProviderEntry
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_class(
    name: str,
    *,
    fields: tuple[AccountCredentialField, ...],
    display_name: str | None = None,
) -> type:
    class _Fake:
        pass

    _Fake.name = name  # type: ignore[attr-defined]
    _Fake.display_name = display_name or name  # type: ignore[attr-defined]
    _Fake.capabilities = frozenset()  # type: ignore[attr-defined]
    _Fake.account_credential_fields = fields  # type: ignore[attr-defined]
    return _Fake


def _entry(
    name: str,
    *,
    fields: tuple[AccountCredentialField, ...],
    display_name: str | None = None,
) -> ProviderEntry:
    return ProviderEntry(
        name=name,
        display_name=display_name or name,
        capabilities=frozenset(),
        provider_class=_make_class(name, fields=fields, display_name=display_name),
        source_distribution=None,
    )


@pytest.fixture
def wizard(tmp_path: Path) -> Iterator[ConfigureWizard]:
    """ConfigureWizard with a writable HOME and a credentials.json
    path under ``tmp_path`` so the save route never touches the
    operator's real file."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
    (home / ".mureo").mkdir()

    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


@pytest.fixture
def credentials_path(wizard: ConfigureWizard) -> Path:
    """Resolved path the handler writes to — derived from the
    wizard's ``host_paths`` (``<home>/.mureo/credentials.json``).
    The handler explicitly passes this path to
    :class:`FilesystemSecretStore` so the save flow stays scoped to
    the test ``tmp_path`` rather than the operator's real HOME."""
    return wizard.host_paths.credentials_path


@pytest.fixture
def registry_two_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the registry to two synthetic plugins for the handler
    smoke tests."""
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {
            "demo_ads": _entry(
                "demo_ads",
                display_name="Demo Ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        required=True,
                        secret=True,
                    ),
                    AccountCredentialField(
                        key="account_id",
                        display_name="Account ID",
                    ),
                ),
            ),
            "noop": _entry("noop", fields=()),
        },
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _url(wiz: ConfigureWizard, path: str) -> str:
    return f"http://127.0.0.1:{wiz.port}{path}"


def _get(wiz: ConfigureWizard, path: str) -> HTTPResponse:
    return urllib.request.urlopen(_url(wiz, path), timeout=2.0)


def _post(
    wiz: ConfigureWizard,
    path: str,
    payload: dict[str, Any],
) -> HTTPResponse:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(_url(wiz, path), data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-CSRF-Token", wiz.session.csrf_token)
    return urllib.request.urlopen(req, timeout=2.0)


# ---------------------------------------------------------------------------
# GET /api/credentials/plugins
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_lists_plugins_with_declared_fields(
    wizard: ConfigureWizard, registry_two_plugins: None
) -> None:
    resp = _get(wizard, "/api/credentials/plugins")
    assert resp.status == 200
    body = json.loads(resp.read())
    assert "plugins" in body
    names = [p["provider_name"] for p in body["plugins"]]
    # The "noop" plugin (no declared fields) is filtered out.
    assert names == ["demo_ads"]
    [demo] = body["plugins"]
    assert demo["display_name"] == "Demo Ads"
    keys = [f["key"] for f in demo["fields"]]
    assert keys == ["api_key", "account_id"]
    api_key_field = next(f for f in demo["fields"] if f["key"] == "api_key")
    assert api_key_field["secret"] is True
    assert api_key_field["required"] is True


@pytest.mark.unit
def test_get_uses_session_locale_for_field_labels(
    wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler must forward ``session.locale`` into the registry
    walk so plugin-declared ``display_name_i18n`` / ``description_i18n``
    entries are resolved against the active operator locale (#186).
    """
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {
            "lineyahoo_ads": _entry(
                "lineyahoo_ads",
                display_name="LINE/Yahoo! Ads",
                fields=(
                    AccountCredentialField(
                        key="business_id",
                        display_name="Business ID",
                        description="Yahoo! JAPAN Business ID.",
                        display_name_i18n={"ja": "ビジネス ID"},
                        description_i18n={"ja": "Yahoo! JAPAN ビジネス ID。"},
                    ),
                ),
            )
        },
    )
    wizard.session.set_locale("ja")

    resp = _get(wizard, "/api/credentials/plugins")
    body = json.loads(resp.read())
    [plugin] = body["plugins"]
    [field] = plugin["fields"]
    assert field["display_name"] == "ビジネス ID"
    assert field["description"] == "Yahoo! JAPAN ビジネス ID。"


@pytest.mark.unit
def test_get_returns_empty_list_when_no_plugins(
    wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(default_registry, "_entries", {})
    resp = _get(wizard, "/api/credentials/plugins")
    assert resp.status == 200
    body = json.loads(resp.read())
    assert body == {"plugins": []}


# ---------------------------------------------------------------------------
# POST /api/credentials/plugins/save
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_post_save_writes_credentials_file(
    wizard: ConfigureWizard,
    registry_two_plugins: None,
    credentials_path: Path,
) -> None:
    resp = _post(
        wizard,
        "/api/credentials/plugins/save",
        {
            "provider_name": "demo_ads",
            "values": {"api_key": "sk-zzzz", "account_id": "acct-1"},
        },
    )
    assert resp.status == 200
    body = json.loads(resp.read())
    assert body["status"] == "ok"
    assert body["provider_name"] == "demo_ads"
    assert sorted(body["accepted_keys"]) == ["account_id", "api_key"]

    # File landed at the wizard-scoped credentials path under tmp_path.
    on_disk = json.loads(credentials_path.read_text())
    assert on_disk == {"demo_ads": {"api_key": "sk-zzzz", "account_id": "acct-1"}}


@pytest.mark.unit
def test_post_save_unknown_provider_returns_400(
    wizard: ConfigureWizard,
    registry_two_plugins: None,
    credentials_path: Path,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(
            wizard,
            "/api/credentials/plugins/save",
            {"provider_name": "ghost", "values": {"api_key": "x"}},
        )
    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read())
    assert body["error"] == "unknown_provider"


@pytest.mark.unit
def test_post_save_missing_provider_name_returns_400(
    wizard: ConfigureWizard,
    registry_two_plugins: None,
    credentials_path: Path,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(
            wizard,
            "/api/credentials/plugins/save",
            {"values": {"api_key": "x"}},
        )
    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read())
    assert body["error"] == "provider_name_required"


@pytest.mark.unit
def test_post_save_non_string_value_returns_400(
    wizard: ConfigureWizard,
    registry_two_plugins: None,
    credentials_path: Path,
) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(
            wizard,
            "/api/credentials/plugins/save",
            {
                "provider_name": "demo_ads",
                "values": {"api_key": {"nested": "no"}},
            },
        )
    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read())
    assert body["error"] == "invalid_field_value"


@pytest.mark.unit
def test_post_save_blank_secret_keeps_existing(
    wizard: ConfigureWizard,
    registry_two_plugins: None,
    credentials_path: Path,
) -> None:
    # Seed an existing entry.
    _post(
        wizard,
        "/api/credentials/plugins/save",
        {
            "provider_name": "demo_ads",
            "values": {"api_key": "previous", "account_id": "old-label"},
        },
    )
    # Submit blank api_key + new label.
    resp = _post(
        wizard,
        "/api/credentials/plugins/save",
        {
            "provider_name": "demo_ads",
            "values": {"api_key": "", "account_id": "new-label"},
        },
    )
    body = json.loads(resp.read())
    assert body["status"] == "ok"
    # Only ``account_id`` was actually changed; the blank-secret-skip
    # path must not list the unchanged secret as accepted.
    assert body["accepted_keys"] == ["account_id"]

    on_disk = json.loads(credentials_path.read_text())
    assert on_disk == {"demo_ads": {"api_key": "previous", "account_id": "new-label"}}


# ---------------------------------------------------------------------------
# #336 — GET /api/credentials/plugins/<provider>/accounts (post-auth picker)
# ---------------------------------------------------------------------------


def _picker_entry(
    lister: Any, *, accounts_field: str | None = "account_id"
) -> ProviderEntry:
    from mureo.core.providers import AccountOAuthConfig

    class _Broker:
        name = "meta_ads_logly"
        display_name = "Logly Meta"
        capabilities = frozenset()
        account_credential_fields = (
            AccountCredentialField(key="client_id", display_name="Client ID"),
            AccountCredentialField(
                key="client_secret", display_name="Client Secret", secret=True
            ),
            AccountCredentialField(
                key="access_token", display_name="Access Token", secret=True
            ),
            AccountCredentialField(key="account_id", display_name="Account"),
        )
        account_oauth = AccountOAuthConfig(
            authorize_url="https://example.test/authorize",
            token_url="https://example.test/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="access_token",
            accounts_field=accounts_field,
        )

    if lister is not None:
        _Broker.list_oauth_accounts = staticmethod(lister)  # type: ignore[attr-defined]
    return ProviderEntry(
        name="meta_ads_logly",
        display_name="Logly Meta",
        capabilities=frozenset(),
        provider_class=_Broker,
        source_distribution=None,
    )


def _store_token(credentials_path: Path) -> None:
    from mureo.core.secret_store import FilesystemSecretStore

    FilesystemSecretStore(path=credentials_path).save(
        "meta_ads_logly", {"access_token": "TKN"}
    )


@pytest.mark.unit
def test_accounts_endpoint_returns_normalised_accounts(
    wizard: ConfigureWizard,
    credentials_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {
            "meta_ads_logly": _picker_entry(
                lambda creds: [{"id": "act_1", "name": "Brand"}]
            )
        },
    )
    _store_token(credentials_path)
    resp = _get(wizard, "/api/credentials/plugins/meta_ads_logly/accounts")
    assert resp.status == 200
    body = json.loads(resp.read())
    assert body["accounts"] == [{"id": "act_1", "name": "Brand"}]


@pytest.mark.unit
def test_accounts_endpoint_409_when_not_authenticated(
    wizard: ConfigureWizard, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {"meta_ads_logly": _picker_entry(lambda creds: [{"id": "act_1"}])},
    )
    # No token stored → 409 not_authenticated.
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard, "/api/credentials/plugins/meta_ads_logly/accounts")
    assert exc.value.code == 409
    assert json.loads(exc.value.read())["error"] == "not_authenticated"


@pytest.mark.unit
def test_accounts_endpoint_404_when_not_supported(
    wizard: ConfigureWizard,
    credentials_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # accounts_field present but no lister hook → accounts_not_supported.
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {"meta_ads_logly": _picker_entry(None)},
    )
    _store_token(credentials_path)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard, "/api/credentials/plugins/meta_ads_logly/accounts")
    assert exc.value.code == 404
    assert json.loads(exc.value.read())["error"] == "accounts_not_supported"


@pytest.mark.unit
def test_accounts_endpoint_404_unknown_provider(wizard: ConfigureWizard) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard, "/api/credentials/plugins/nope/accounts")
    assert exc.value.code == 404
    assert json.loads(exc.value.read())["error"] == "unknown_provider"


@pytest.mark.unit
def test_accounts_endpoint_502_when_hook_fails(
    wizard: ConfigureWizard,
    credentials_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(creds: dict[str, str]) -> list[dict[str, str]]:
        raise RuntimeError("graph down")

    monkeypatch.setattr(
        default_registry,
        "_entries",
        {"meta_ads_logly": _picker_entry(_boom)},
    )
    _store_token(credentials_path)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(wizard, "/api/credentials/plugins/meta_ads_logly/accounts")
    assert exc.value.code == 502
    assert json.loads(exc.value.read())["error"] == "account_listing_failed"
