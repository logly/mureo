"""Unit tests for ``mureo.web.plugin_credentials``.

This module bridges the registered providers' declarative
``account_credential_fields`` and the configure-UI persistence layer
(``~/.mureo/credentials.json`` via ``FilesystemSecretStore``):

- :func:`list_plugin_credential_fields` walks the registry, returns a
  JSON-serialisable description of each provider that declares
  non-empty ``account_credential_fields`` — the wizard JS reads this
  to render the form.
- :func:`save_plugin_credentials` writes one provider's values to the
  secret store. It validates the provider exists, drops unknown field
  keys (so a stale UI cannot inject arbitrary keys), and treats a
  blank ``secret=True`` field as "keep the existing value" so an edit
  form does not require re-entering the API key on every save.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.core.providers import (
    AccountCredentialField,
    default_registry,
)
from mureo.core.providers.registry import ProviderEntry
from mureo.core.secret_store import FilesystemSecretStore

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers — synthesise providers without touching real entry points.
# ---------------------------------------------------------------------------


def _make_class(
    name: str,
    *,
    fields: tuple[AccountCredentialField, ...] = (),
    display_name: str | None = None,
    oauth: Any = None,
) -> type:
    """Build a minimal provider class with the requested credential fields.

    ``oauth`` (an ``AccountOAuthConfig``) is attached as
    ``account_oauth`` only when supplied, so a manual-entry provider keeps
    no such attribute (``get_account_oauth_config`` → ``None``).
    """

    class _Fake:
        pass

    _Fake.name = name  # type: ignore[attr-defined]
    _Fake.display_name = display_name or name  # type: ignore[attr-defined]
    _Fake.capabilities = frozenset()  # type: ignore[attr-defined]
    _Fake.account_credential_fields = fields  # type: ignore[attr-defined]
    if oauth is not None:
        _Fake.account_oauth = oauth  # type: ignore[attr-defined]
    return _Fake


def _register(
    monkeypatch: pytest.MonkeyPatch,
    entries: list[ProviderEntry],
) -> None:
    """Replace ``default_registry._entries`` with the supplied entries.

    A monkeypatch keeps the override scoped to one test — the global
    registry is restored automatically.
    """
    new_map = {e.name: e for e in entries}
    monkeypatch.setattr(default_registry, "_entries", new_map)


def _entry(
    name: str,
    *,
    fields: tuple[AccountCredentialField, ...] = (),
    display_name: str | None = None,
    oauth: Any = None,
) -> ProviderEntry:
    cls = _make_class(name, fields=fields, display_name=display_name, oauth=oauth)
    return ProviderEntry(
        name=name,
        display_name=display_name or name,
        capabilities=frozenset(),
        provider_class=cls,
        source_distribution=None,
    )


# ---------------------------------------------------------------------------
# list_plugin_credential_fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_returns_empty_when_no_providers_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(monkeypatch, [])
    assert list_plugin_credential_fields() == []


@pytest.mark.unit
def test_list_skips_providers_without_account_credential_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers that declare no per-account fields are not in the UI —
    they have nothing for the operator to fill in."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry("noop", fields=()),
            _entry(
                "with_fields",
                fields=(
                    AccountCredentialField(key="account_id", display_name="Account ID"),
                ),
            ),
        ],
    )

    result = list_plugin_credential_fields()
    names = [r["provider_name"] for r in result]
    assert names == ["with_fields"]


@pytest.mark.unit
def test_list_includes_full_field_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every documented attribute round-trips so the wizard JS can
    render placeholder, description, required + secret without a
    second round-trip."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                display_name="Demo Ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        placeholder="advertiser_api_key_xxxx",
                        required=True,
                        secret=True,
                        description="Per-account API key.",
                    ),
                    AccountCredentialField(
                        key="account_id",
                        display_name="Account ID",
                        placeholder="acct-123",
                        required=False,
                        secret=False,
                        description="Optional scope label.",
                    ),
                ),
            )
        ],
    )

    [entry] = list_plugin_credential_fields()
    assert entry["provider_name"] == "demo_ads"
    assert entry["display_name"] == "Demo Ads"
    assert entry["fields"] == [
        {
            "key": "api_key",
            "display_name": "API Key",
            "placeholder": "advertiser_api_key_xxxx",
            "required": True,
            "secret": True,
            "description": "Per-account API key.",
        },
        {
            "key": "account_id",
            "display_name": "Account ID",
            "placeholder": "acct-123",
            "required": False,
            "secret": False,
            "description": "Optional scope label.",
        },
    ]


@pytest.mark.unit
def test_account_credential_field_has_empty_i18n_dicts_by_default() -> None:
    """Backwards compatibility for plugins that don't declare i18n.

    Plugins that predate locale support keep working unchanged — the
    new ``display_name_i18n`` / ``description_i18n`` attributes default
    to empty mappings, so the fallback chain (i18n[locale] →
    i18n["en"] → display_name) lands on the legacy single-string
    value when no translation is declared.
    """
    f = AccountCredentialField(key="api_key", display_name="API Key")
    assert f.display_name_i18n == {}
    assert f.description_i18n == {}


@pytest.mark.unit
def test_list_uses_locale_when_field_declares_i18n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``locale="ja"`` resolves to the JA entry declared by the plugin."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
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
        ],
    )

    [entry] = list_plugin_credential_fields(locale="ja")
    [field] = entry["fields"]
    assert field["display_name"] == "ビジネス ID"
    assert field["description"] == "Yahoo! JAPAN ビジネス ID。"


@pytest.mark.unit
def test_list_falls_back_to_en_when_requested_locale_not_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown locale falls back to ``en`` if declared, then ``display_name``."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        description="Per-account API key.",
                        # JA omitted; EN declared explicitly.
                        display_name_i18n={"en": "API Key (EN)"},
                        description_i18n={"en": "Per-account API key. (EN)"},
                    ),
                ),
            )
        ],
    )

    [entry] = list_plugin_credential_fields(locale="ja")
    [field] = entry["fields"]
    assert field["display_name"] == "API Key (EN)"
    assert field["description"] == "Per-account API key. (EN)"


@pytest.mark.unit
def test_list_falls_back_to_display_name_when_no_i18n_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither locale nor ``en`` i18n is declared, the bare
    ``display_name`` / ``description`` strings come through."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        description="Per-account API key.",
                    ),
                ),
            )
        ],
    )

    [entry] = list_plugin_credential_fields(locale="ja")
    [field] = entry["fields"]
    assert field["display_name"] == "API Key"
    assert field["description"] == "Per-account API key."


@pytest.mark.unit
def test_list_locale_en_with_only_ja_declared_returns_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``locale="en"`` + only ``display_name_i18n={"ja": "..."}`` must
    NOT leak the JA entry into the EN locale. The chain is
    ``i18n[locale] → i18n["en"] → display_name`` — with no ``"en"``
    declared either, the bare ``display_name`` wins.
    """
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        description="Per-account API key.",
                        display_name_i18n={"ja": "API キー"},
                        description_i18n={"ja": "アカウント単位の API キー。"},
                    ),
                ),
            )
        ],
    )

    [entry] = list_plugin_credential_fields(locale="en")
    [field] = entry["fields"]
    assert field["display_name"] == "API Key"
    assert field["description"] == "Per-account API key."


@pytest.mark.unit
def test_list_empty_string_i18n_entry_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty-string i18n entry must be treated as "not declared",
    not "render an empty label". A mistakenly-empty translation should
    fall through to the next layer (``en`` → ``display_name``) rather
    than blank the form. Regression guard against a refactor that
    flips the truthiness check to ``is not None``.
    """
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        description="Per-account API key.",
                        display_name_i18n={"ja": "", "en": "API Key (EN)"},
                        description_i18n={"ja": ""},
                    ),
                ),
            )
        ],
    )

    [entry] = list_plugin_credential_fields(locale="ja")
    [field] = entry["fields"]
    # Empty JA → falls through to EN-declared entry.
    assert field["display_name"] == "API Key (EN)"
    # Empty JA + no EN declared → falls through to bare description.
    assert field["description"] == "Per-account API key."


@pytest.mark.unit
def test_list_default_locale_is_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling without a locale keeps the pre-#186 behaviour: EN."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        display_name_i18n={
                            "en": "API Key (EN)",
                            "ja": "API キー",
                        },
                    ),
                ),
            )
        ],
    )

    [entry] = list_plugin_credential_fields()
    [field] = entry["fields"]
    assert field["display_name"] == "API Key (EN)"


@pytest.mark.unit
def test_list_sorts_providers_alphabetically_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stable rendering order — operators see the same list every time
    regardless of registry insertion order."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    field = (AccountCredentialField(key="k", display_name="K"),)
    _register(
        monkeypatch,
        [
            _entry("zeta", fields=field),
            _entry("alpha", fields=field),
            _entry("mu", fields=field),
        ],
    )

    names = [r["provider_name"] for r in list_plugin_credential_fields()]
    assert names == ["alpha", "mu", "zeta"]


# ---------------------------------------------------------------------------
# save_plugin_credentials
# ---------------------------------------------------------------------------


def _store(tmp_path: Path) -> FilesystemSecretStore:
    return FilesystemSecretStore(path=tmp_path / "credentials.json")


@pytest.mark.unit
def test_save_writes_fields_to_secret_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key", display_name="API Key", secret=True
                    ),
                    AccountCredentialField(key="account_id", display_name="Account ID"),
                ),
            )
        ],
    )
    store = _store(tmp_path)

    result = save_plugin_credentials(
        "demo_ads",
        {"api_key": "sk-xxxx", "account_id": "acct-1"},
        secret_store=store,
    )

    assert store.load("demo_ads") == {"api_key": "sk-xxxx", "account_id": "acct-1"}
    # The returned envelope reports both the merged state and which
    # keys the call actually changed.
    assert result["merged"] == {"api_key": "sk-xxxx", "account_id": "acct-1"}
    assert sorted(result["accepted_keys"]) == ["account_id", "api_key"]


@pytest.mark.unit
def test_save_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale UI must not be able to inject arbitrary keys into the
    credential file by POSTing under an unrecognised provider name."""
    from mureo.web.plugin_credentials import (
        UnknownProviderError,
        save_plugin_credentials,
    )

    _register(monkeypatch, [])
    store = _store(tmp_path)

    with pytest.raises(UnknownProviderError):
        save_plugin_credentials("ghost", {"api_key": "x"}, secret_store=store)
    # No file written.
    assert not (tmp_path / "credentials.json").exists()


@pytest.mark.unit
def test_save_drops_unknown_field_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fields not declared by the provider are silently dropped — the
    UI may legitimately fall behind the plugin's declared schema after
    an upgrade, but we never persist unknown keys."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(AccountCredentialField(key="api_key", display_name="API Key"),),
            )
        ],
    )
    store = _store(tmp_path)

    save_plugin_credentials(
        "demo_ads",
        {"api_key": "kept", "stale_field": "dropped"},
        secret_store=store,
    )

    assert store.load("demo_ads") == {"api_key": "kept"}


@pytest.mark.unit
def test_save_merges_with_existing_unrelated_providers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Saving plugin credentials must not clobber other providers'
    entries in the same credentials file (Google Ads, Meta Ads, etc.)."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(AccountCredentialField(key="api_key", display_name="API"),),
            )
        ],
    )
    store = _store(tmp_path)
    # Pre-populate an unrelated entry.
    store.save("google_ads", {"developer_token": "preserved"})

    save_plugin_credentials("demo_ads", {"api_key": "x"}, secret_store=store)

    assert store.load("google_ads") == {"developer_token": "preserved"}
    assert store.load("demo_ads") == {"api_key": "x"}


@pytest.mark.unit
def test_save_blank_secret_keeps_existing_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty string for a ``secret=True`` field means "keep the
    existing value" so an edit form does not force the operator to
    re-enter the API key on every save."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key", display_name="API Key", secret=True
                    ),
                    AccountCredentialField(
                        key="label", display_name="Label", secret=False
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    store.save("demo_ads", {"api_key": "previous-secret", "label": "old-label"})

    result = save_plugin_credentials(
        "demo_ads",
        {"api_key": "", "label": "new-label"},
        secret_store=store,
    )

    assert store.load("demo_ads") == {
        "api_key": "previous-secret",
        "label": "new-label",
    }
    # Only ``label`` was actually changed — the blank-secret skip
    # path must not surface ``api_key`` as "saved".
    assert result["accepted_keys"] == ["label"]


@pytest.mark.unit
def test_save_blank_secret_on_empty_store_for_optional_field_is_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blank optional ``secret=True`` field with no existing value
    is silently a no-op — the operator simply did not fill it in. No
    new key is written."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        secret=True,
                        required=False,
                    ),
                    AccountCredentialField(
                        key="label", display_name="Label", required=False
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    result = save_plugin_credentials(
        "demo_ads",
        {"api_key": "", "label": "L1"},
        secret_store=store,
    )
    assert store.load("demo_ads") == {"label": "L1"}
    assert result["accepted_keys"] == ["label"]


@pytest.mark.unit
def test_save_blank_non_secret_optional_overwrites_with_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blank ``secret=False`` field is taken literally — the operator
    explicitly cleared the value. Only ``secret=True`` has the
    "blank = keep existing" carve-out. Required fields get the
    separate :class:`RequiredFieldMissingError` treatment exercised
    below."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="label", display_name="Label", required=False
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    store.save("demo_ads", {"label": "old"})

    save_plugin_credentials("demo_ads", {"label": ""}, secret_store=store)

    assert store.load("demo_ads") == {"label": ""}


@pytest.mark.unit
def test_save_rejects_blank_required_non_secret_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A required non-secret field cannot be blanked — the operator
    would otherwise silently land in a state the plugin will reject
    at runtime."""
    from mureo.web.plugin_credentials import (
        RequiredFieldMissingError,
        save_plugin_credentials,
    )

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="label",
                        display_name="Label",
                        required=True,
                        secret=False,
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    with pytest.raises(RequiredFieldMissingError):
        save_plugin_credentials("demo_ads", {"label": ""}, secret_store=store)


@pytest.mark.unit
def test_save_rejects_blank_required_secret_when_no_existing_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A required secret field on an empty store cannot be left blank —
    there is no existing value to keep, so the "blank means keep"
    rule does not apply."""
    from mureo.web.plugin_credentials import (
        RequiredFieldMissingError,
        save_plugin_credentials,
    )

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        required=True,
                        secret=True,
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    with pytest.raises(RequiredFieldMissingError):
        save_plugin_credentials("demo_ads", {"api_key": ""}, secret_store=store)


@pytest.mark.unit
def test_save_accepts_blank_required_secret_when_value_already_stored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The "blank means keep" rule still applies when a required
    secret has a previously-stored value — this is the everyday edit
    case (operator updates one non-secret field without retyping the
    API key)."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        required=True,
                        secret=True,
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    store.save("demo_ads", {"api_key": "kept"})
    save_plugin_credentials("demo_ads", {"api_key": ""}, secret_store=store)
    assert store.load("demo_ads") == {"api_key": "kept"}


@pytest.mark.unit
def test_save_rejects_required_field_absent_from_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A required field absent from the payload (rather than blank)
    is also rejected when no value is currently stored — the operator
    submitted an incomplete form."""
    from mureo.web.plugin_credentials import (
        RequiredFieldMissingError,
        save_plugin_credentials,
    )

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key",
                        display_name="API Key",
                        required=True,
                    ),
                    AccountCredentialField(
                        key="label", display_name="Label", required=False
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    with pytest.raises(RequiredFieldMissingError):
        save_plugin_credentials("demo_ads", {"label": "L1"}, secret_store=store)


@pytest.mark.unit
def test_save_rejects_non_string_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Per-account fields are flat strings — a JSON payload that ships
    nested objects or numbers is rejected so a downstream consumer
    doesn't have to defend against shape drift."""
    from mureo.web.plugin_credentials import (
        InvalidFieldValueError,
        save_plugin_credentials,
    )

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(AccountCredentialField(key="api_key", display_name="API"),),
            )
        ],
    )
    store = _store(tmp_path)

    with pytest.raises(InvalidFieldValueError):
        save_plugin_credentials(
            "demo_ads", {"api_key": {"nested": "no"}}, secret_store=store
        )
    assert not (tmp_path / "credentials.json").exists()


@pytest.mark.unit
def test_save_does_not_log_secret_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Secret values must never appear in mureo's own log output —
    ``secret=True`` is the consumer's contract that the value is
    sensitive, so the helper redacts it from its info log."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [
            _entry(
                "demo_ads",
                fields=(
                    AccountCredentialField(
                        key="api_key", display_name="API Key", secret=True
                    ),
                    AccountCredentialField(
                        key="label", display_name="Label", secret=False
                    ),
                ),
            )
        ],
    )
    store = _store(tmp_path)
    sentinel = "super-secret-token-xyz"

    import logging

    with caplog.at_level(logging.DEBUG, logger="mureo.web.plugin_credentials"):
        save_plugin_credentials(
            "demo_ads",
            {"api_key": sentinel, "label": "visible-label"},
            secret_store=store,
        )

    log_text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert sentinel not in log_text


# ---------------------------------------------------------------------------
# #217 — an account_oauth provider's target_field is acquired via
# Authenticate, never typed into Save, so it must not be required-enforced
# here (else first-time setup deadlocks: Save wants the token, Authenticate
# wants Save). Defense-in-depth in save_plugin_credentials, UI-independent.
# ---------------------------------------------------------------------------


def _yahoo_oauth() -> Any:
    from mureo.core.providers import AccountOAuthConfig

    return AccountOAuthConfig(
        authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
        scopes=("scopeA",),
    )


def _yahoo_fields() -> tuple[AccountCredentialField, ...]:
    return (
        AccountCredentialField(key="client_id", display_name="Client ID"),
        AccountCredentialField(key="client_secret", display_name="Secret", secret=True),
        # The OAuth target — declared required (the plugin needs it at
        # runtime) but obtained via Authenticate, not the Save form.
        AccountCredentialField(
            key="refresh_token",
            display_name="Refresh token",
            required=True,
            secret=True,
        ),
    )


@pytest.mark.unit
def test_save_does_not_require_oauth_target_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Saving client creds without the (required) OAuth target_field on an
    empty store must NOT raise — the token comes from Authenticate."""
    from mureo.web.plugin_credentials import save_plugin_credentials

    _register(
        monkeypatch,
        [_entry("yahoo_ads", fields=_yahoo_fields(), oauth=_yahoo_oauth())],
    )
    store = _store(tmp_path)
    result = save_plugin_credentials(
        "yahoo_ads",
        {"client_id": "CID", "client_secret": "SECRET"},
        secret_store=store,
    )
    assert store.load("yahoo_ads") == {"client_id": "CID", "client_secret": "SECRET"}
    # The token field is not persisted as a blank, and no error was raised.
    assert "refresh_token" not in result["merged"]


@pytest.mark.unit
def test_save_still_requires_non_oauth_required_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The exemption is scoped to the OAuth target_field only — a *different*
    required field on the same provider is still enforced."""
    from mureo.web.plugin_credentials import (
        RequiredFieldMissingError,
        save_plugin_credentials,
    )

    fields = (
        *_yahoo_fields(),
        AccountCredentialField(
            key="base_account_id", display_name="Base account", required=True
        ),
    )
    _register(
        monkeypatch,
        [_entry("yahoo_ads", fields=fields, oauth=_yahoo_oauth())],
    )
    store = _store(tmp_path)
    with pytest.raises(RequiredFieldMissingError):
        save_plugin_credentials(
            "yahoo_ads",
            {"client_id": "CID", "client_secret": "SECRET"},
            secret_store=store,
        )


# ---------------------------------------------------------------------------
# #220 — a provider that declares a fixed callback_port surfaces the
# canonical loopback callback URL in its oauth block, so the dashboard
# pre-fills the exact URL the operator must register provider-side.
# ---------------------------------------------------------------------------


def _yahoo_oauth_with_port(port: int) -> Any:
    from mureo.core.providers import AccountOAuthConfig

    return AccountOAuthConfig(
        authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
        scopes=("scopeA",),
        callback_port=port,
    )


@pytest.mark.unit
def test_list_oauth_block_includes_default_callback_url_when_port_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "yahoo_ads",
                fields=_yahoo_fields(),
                oauth=_yahoo_oauth_with_port(8765),
            )
        ],
    )
    [plugin] = list_plugin_credential_fields()
    assert (
        plugin["oauth"]["default_callback_url"]
        == "http://127.0.0.1:8765/oauth/callback"
    )


@pytest.mark.unit
def test_list_oauth_block_omits_default_callback_url_without_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider without callback_port (the #216 default) carries no
    default_callback_url — the dashboard uses its generic fallback. The
    oauth block keeps its original three keys."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [_entry("yahoo_ads", fields=_yahoo_fields(), oauth=_yahoo_oauth())],
    )
    [plugin] = list_plugin_credential_fields()
    assert "default_callback_url" not in plugin["oauth"]
