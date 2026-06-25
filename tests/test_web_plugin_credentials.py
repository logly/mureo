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
    display_name_i18n: dict[str, str] | None = None,
    oauth: Any = None,
    lister: Any = None,
) -> type:
    """Build a minimal provider class with the requested credential fields.

    ``oauth`` (an ``AccountOAuthConfig``) is attached as
    ``account_oauth`` only when supplied, so a manual-entry provider keeps
    no such attribute (``get_account_oauth_config`` → ``None``).
    ``display_name_i18n`` (#236) is attached only when supplied, so a
    provider that omits it keeps no such attribute (heading falls back to
    ``display_name``).
    """

    class _Fake:
        pass

    _Fake.name = name  # type: ignore[attr-defined]
    _Fake.display_name = display_name or name  # type: ignore[attr-defined]
    _Fake.capabilities = frozenset()  # type: ignore[attr-defined]
    _Fake.account_credential_fields = fields  # type: ignore[attr-defined]
    if display_name_i18n is not None:
        _Fake.display_name_i18n = display_name_i18n  # type: ignore[attr-defined]
    if oauth is not None:
        _Fake.account_oauth = oauth  # type: ignore[attr-defined]
    if lister is not None:
        # #336 — the post-auth account picker hook. ``staticmethod`` so it
        # is callable off the class without instantiation (registry only
        # ever holds the class).
        _Fake.list_oauth_accounts = staticmethod(lister)  # type: ignore[attr-defined]
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
    display_name_i18n: dict[str, str] | None = None,
    oauth: Any = None,
    lister: Any = None,
) -> ProviderEntry:
    cls = _make_class(
        name,
        fields=fields,
        display_name=display_name,
        display_name_i18n=display_name_i18n,
        oauth=oauth,
        lister=lister,
    )
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
def test_heading_localized_when_provider_declares_display_name_i18n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#236 — a provider declaring ``display_name_i18n`` gets a locale-
    resolved section heading (same fallback as field labels, #186)."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "yahoo_search",
                display_name="Yahoo! JAPAN Ads (Search)",
                display_name_i18n={"ja": "Yahoo! JAPAN 広告（検索）"},
                fields=(
                    AccountCredentialField(key="account_id", display_name="Account ID"),
                ),
            ),
        ],
    )

    ja = list_plugin_credential_fields(locale="ja")
    assert ja[0]["display_name"] == "Yahoo! JAPAN 広告（検索）"
    en = list_plugin_credential_fields(locale="en")
    assert en[0]["display_name"] == "Yahoo! JAPAN Ads (Search)"


@pytest.mark.unit
def test_heading_falls_back_to_display_name_without_i18n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that omits ``display_name_i18n`` keeps the bare
    ``display_name`` in every locale (regression-free)."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "plain",
                display_name="Plain Ads",
                fields=(
                    AccountCredentialField(key="account_id", display_name="Account ID"),
                ),
            ),
        ],
    )

    assert list_plugin_credential_fields(locale="ja")[0]["display_name"] == "Plain Ads"
    assert list_plugin_credential_fields(locale="en")[0]["display_name"] == "Plain Ads"


@pytest.mark.unit
def test_heading_unknown_locale_falls_back_to_en_then_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown locale resolves ``i18n['en']`` if present, else the bare
    ``display_name`` — matching the field-label fallback chain (#186)."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "with_en",
                display_name="Bare",
                display_name_i18n={"en": "English Heading"},
                fields=(
                    AccountCredentialField(key="account_id", display_name="Account ID"),
                ),
            ),
            _entry(
                "ja_only",
                display_name="Bare JA-only",
                display_name_i18n={"ja": "日本語のみ"},
                fields=(
                    AccountCredentialField(key="account_id", display_name="Account ID"),
                ),
            ),
        ],
    )

    result = {
        r["provider_name"]: r["display_name"]
        for r in list_plugin_credential_fields(locale="fr")
    }
    assert result["with_en"] == "English Heading"
    assert result["ja_only"] == "Bare JA-only"


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


# ---------------------------------------------------------------------------
# #336 — post-auth account picker: list_oauth_accounts + _oauth_to_dict
# surfacing of accounts_field / has_account_lister.
# ---------------------------------------------------------------------------


def _broker_fields() -> tuple[AccountCredentialField, ...]:
    return (
        AccountCredentialField(key="client_id", display_name="Client ID"),
        AccountCredentialField(
            key="client_secret", display_name="Client Secret", secret=True
        ),
        AccountCredentialField(
            key="access_token", display_name="Access Token", secret=True
        ),
        AccountCredentialField(key="account_id", display_name="Ad Account"),
    )


def _broker_oauth(accounts_field: str | None = "account_id") -> Any:
    from mureo.core.providers import AccountOAuthConfig

    return AccountOAuthConfig(
        authorize_url="https://example.test/authorize",
        token_url="https://example.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="access_token",
        accounts_field=accounts_field,
    )


@pytest.mark.unit
def test_oauth_block_surfaces_accounts_field_and_lister(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A picker provider exposes ``accounts_field`` + ``has_account_lister``
    so the dashboard renders a picker; a manual-id OAuth provider does not."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [
            _entry(
                "meta_ads_logly",
                fields=_broker_fields(),
                oauth=_broker_oauth(),
                lister=lambda creds: [{"id": "act_1", "name": "Brand"}],
            ),
        ],
    )
    [plugin] = list_plugin_credential_fields()
    assert plugin["oauth"]["accounts_field"] == "account_id"
    assert plugin["oauth"]["has_account_lister"] is True


@pytest.mark.unit
def test_oauth_block_lister_false_when_hook_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """accounts_field declared but no hook → has_account_lister False, so the
    UI keeps the plain input rather than a dead picker."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch,
        [_entry("broker", fields=_broker_fields(), oauth=_broker_oauth())],
    )
    [plugin] = list_plugin_credential_fields()
    assert plugin["oauth"]["accounts_field"] == "account_id"
    assert plugin["oauth"]["has_account_lister"] is False


@pytest.mark.unit
def test_oauth_block_omits_accounts_keys_without_accounts_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-picker OAuth provider keeps the original block (no picker keys)."""
    from mureo.web.plugin_credentials import list_plugin_credential_fields

    _register(
        monkeypatch, [_entry("yahoo_ads", fields=_yahoo_fields(), oauth=_yahoo_oauth())]
    )
    [plugin] = list_plugin_credential_fields()
    assert "accounts_field" not in plugin["oauth"]
    assert "has_account_lister" not in plugin["oauth"]


@pytest.mark.unit
def test_list_oauth_accounts_returns_normalised_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.web.plugin_credentials import list_oauth_accounts

    def _lister(creds: dict[str, str]) -> list[dict[str, str]]:
        assert creds["access_token"] == "TKN"
        return [
            {"id": "act_1", "name": "Brand A"},
            {"id": "act_2"},  # name falls back to id
            {"name": "no id — dropped"},  # no id → dropped
            "garbage",  # non-mapping → dropped
        ]

    _register(
        monkeypatch,
        [
            _entry(
                "broker", fields=_broker_fields(), oauth=_broker_oauth(), lister=_lister
            )
        ],
    )
    store = _store(tmp_path)
    store.save("broker", {"access_token": "TKN"})
    accounts = list_oauth_accounts("broker", secret_store=store)
    assert accounts == [
        {"id": "act_1", "name": "Brand A"},
        {"id": "act_2", "name": "act_2"},
    ]


@pytest.mark.unit
def test_list_oauth_accounts_supports_async_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.web.plugin_credentials import list_oauth_accounts

    async def _lister(creds: dict[str, str]) -> list[dict[str, str]]:
        return [{"id": "act_9", "name": "Async"}]

    _register(
        monkeypatch,
        [
            _entry(
                "broker", fields=_broker_fields(), oauth=_broker_oauth(), lister=_lister
            )
        ],
    )
    store = _store(tmp_path)
    store.save("broker", {"access_token": "TKN"})
    assert list_oauth_accounts("broker", secret_store=store) == [
        {"id": "act_9", "name": "Async"}
    ]


@pytest.mark.unit
def test_list_oauth_accounts_unknown_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.web.plugin_credentials import (
        UnknownProviderError,
        list_oauth_accounts,
    )

    _register(monkeypatch, [])
    with pytest.raises(UnknownProviderError):
        list_oauth_accounts("nope", secret_store=_store(tmp_path))


@pytest.mark.unit
def test_list_oauth_accounts_not_supported_without_accounts_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.web.plugin_credentials import (
        OAuthAccountsNotSupportedError,
        list_oauth_accounts,
    )

    _register(
        monkeypatch,
        [_entry("yahoo_ads", fields=_yahoo_fields(), oauth=_yahoo_oauth())],
    )
    with pytest.raises(OAuthAccountsNotSupportedError):
        list_oauth_accounts("yahoo_ads", secret_store=_store(tmp_path))


@pytest.mark.unit
def test_list_oauth_accounts_not_supported_without_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.web.plugin_credentials import (
        OAuthAccountsNotSupportedError,
        list_oauth_accounts,
    )

    _register(
        monkeypatch,
        [_entry("broker", fields=_broker_fields(), oauth=_broker_oauth())],
    )
    store = _store(tmp_path)
    store.save("broker", {"access_token": "TKN"})
    with pytest.raises(OAuthAccountsNotSupportedError):
        list_oauth_accounts("broker", secret_store=store)


@pytest.mark.unit
def test_list_oauth_accounts_requires_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mureo.web.plugin_credentials import (
        OAuthNotAuthenticatedError,
        list_oauth_accounts,
    )

    _register(
        monkeypatch,
        [
            _entry(
                "broker",
                fields=_broker_fields(),
                oauth=_broker_oauth(),
                lister=lambda creds: [{"id": "act_1"}],
            )
        ],
    )
    # No access_token stored → must refuse to list (nothing to enumerate with).
    with pytest.raises(OAuthNotAuthenticatedError):
        list_oauth_accounts("broker", secret_store=_store(tmp_path))


@pytest.mark.unit
def test_list_oauth_accounts_wraps_hook_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from mureo.web.plugin_credentials import AccountListingError, list_oauth_accounts

    def _boom(creds: dict[str, str]) -> list[dict[str, str]]:
        raise RuntimeError("token expired: SECRET-TKN")

    _register(
        monkeypatch,
        [
            _entry(
                "broker", fields=_broker_fields(), oauth=_broker_oauth(), lister=_boom
            )
        ],
    )
    store = _store(tmp_path)
    store.save("broker", {"access_token": "SECRET-TKN"})
    with caplog.at_level("WARNING"):
        with pytest.raises(AccountListingError):
            list_oauth_accounts("broker", secret_store=store)
    # The underlying exception detail (and token) must not leak into logs.
    assert "SECRET-TKN" not in caplog.text


# ---------------------------------------------------------------------------
# #337 — multi_account_picker_scope hides the picker field per OAuth provider.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_multi_account_picker_scope_excludes_accounts_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.web.plugin_credentials import multi_account_picker_scope

    _register(
        monkeypatch,
        [
            _entry("meta_ads_logly", fields=_broker_fields(), oauth=_broker_oauth()),
            _entry("yahoo_ads", fields=_yahoo_fields(), oauth=_yahoo_oauth()),
            _entry(
                "manual", fields=(AccountCredentialField(key="k", display_name="K"),)
            ),
        ],
    )
    scope = multi_account_picker_scope()
    # Picker provider: allow-list keeps everything EXCEPT account_id.
    assert "meta_ads_logly" in scope
    assert "account_id" not in scope["meta_ads_logly"]
    assert "client_id" in scope["meta_ads_logly"]
    # Non-picker providers are absent (all their fields kept).
    assert "yahoo_ads" not in scope
    assert "manual" not in scope


@pytest.mark.unit
def test_list_oauth_accounts_non_iterable_return_is_wrapped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hook returning a non-iterable (a typo'd ``return 42``) must collapse
    to AccountListingError → 502, never escape as a raw 500."""
    from mureo.web.plugin_credentials import AccountListingError, list_oauth_accounts

    _register(
        monkeypatch,
        [
            _entry(
                "broker",
                fields=_broker_fields(),
                oauth=_broker_oauth(),
                lister=lambda creds: 42,  # not iterable
            )
        ],
    )
    store = _store(tmp_path)
    store.save("broker", {"access_token": "TKN"})
    with pytest.raises(AccountListingError):
        list_oauth_accounts("broker", secret_store=store)


@pytest.mark.unit
def test_list_oauth_accounts_async_hook_from_running_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The async-bridge worker-thread fallback runs an async hook even when a
    loop is already running (no 'asyncio.run() cannot be called from a running
    event loop')."""
    import asyncio

    from mureo.web.plugin_credentials import list_oauth_accounts

    async def _lister(creds: dict[str, str]) -> list[dict[str, str]]:
        return [{"id": "act_loop", "name": "Loop"}]

    _register(
        monkeypatch,
        [
            _entry(
                "broker", fields=_broker_fields(), oauth=_broker_oauth(), lister=_lister
            )
        ],
    )
    store = _store(tmp_path)
    store.save("broker", {"access_token": "TKN"})

    async def _drive() -> list[dict[str, str]]:
        # Called from inside a running loop → exercises the ThreadPool branch.
        return list_oauth_accounts("broker", secret_store=store)

    assert asyncio.run(_drive()) == [{"id": "act_loop", "name": "Loop"}]
