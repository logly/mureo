"""Tests for ``mureo.core.providers.credentials.AccountCredentialField``.

The dataclass is declarative metadata only: it carries no behaviour,
so the test surface is small — construction, immutability, defaults,
and JSON-friendliness via ``dataclasses.asdict``.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict

import pytest

from mureo.core.providers.credentials import AccountCredentialField


@pytest.mark.unit
def test_construct_with_required_and_optional_fields() -> None:
    field = AccountCredentialField(
        key="customer_id",
        display_name="Customer ID",
        placeholder="123-456-7890",
        required=True,
        description="10-digit Google Ads customer ID",
    )
    assert field.key == "customer_id"
    assert field.display_name == "Customer ID"
    assert field.placeholder == "123-456-7890"
    assert field.required is True
    assert field.description == "10-digit Google Ads customer ID"


@pytest.mark.unit
def test_optional_fields_default_to_documented_values() -> None:
    """``placeholder``, ``required``, ``description``, ``secret`` are
    optional with well-defined defaults so a provider can declare a
    single line."""
    field = AccountCredentialField(key="account_id", display_name="Account ID")
    assert field.placeholder == ""
    assert field.required is False
    assert field.description == ""
    assert field.secret is False


@pytest.mark.unit
def test_secret_flag_can_be_set_to_true() -> None:
    """``secret=True`` lets a provider declare an API-key-shaped field
    so consumers (configure wizards, third-party setup UIs) can render
    a masked input and choose tighter storage permissions."""
    field = AccountCredentialField(
        key="api_key",
        display_name="API Key",
        placeholder="advertiser_api_key_xxxx",
        required=True,
        secret=True,
        description="Per-account API key sent in the X-API-Key header.",
    )
    assert field.secret is True
    assert field.required is True


@pytest.mark.unit
def test_secret_flag_serialises_in_asdict() -> None:
    """``secret`` must round-trip through ``dataclasses.asdict`` so
    consumers receiving the field over an HTTP / JSON boundary can
    react to the flag without reflection."""
    field = AccountCredentialField(
        key="api_key",
        display_name="API Key",
        required=True,
        secret=True,
    )
    payload = asdict(field)
    assert payload["secret"] is True
    # Public identifiers default to ``secret=False`` so existing
    # built-in declarations stay non-secret without a code change.
    other = AccountCredentialField(key="customer_id", display_name="Customer ID")
    assert asdict(other)["secret"] is False


@pytest.mark.unit
def test_is_frozen() -> None:
    field = AccountCredentialField(key="x", display_name="X")
    with pytest.raises(FrozenInstanceError):
        field.key = "y"  # type: ignore[misc]


@pytest.mark.unit
def test_asdict_is_json_friendly() -> None:
    """Tooling that surfaces fields over an HTTP / JSON boundary uses
    ``dataclasses.asdict``; the result must be a plain ``dict`` with
    primitive values only (no nested dataclasses, no enums)."""
    field = AccountCredentialField(
        key="account_id",
        display_name="Account ID",
        placeholder="act_123",
        required=True,
        description="hint",
    )
    payload = asdict(field)
    assert payload == {
        "key": "account_id",
        "display_name": "Account ID",
        "placeholder": "act_123",
        "required": True,
        "description": "hint",
        "secret": False,
    }
    # Verify no exotic types slipped in.
    for value in payload.values():
        assert isinstance(value, (str, bool))
