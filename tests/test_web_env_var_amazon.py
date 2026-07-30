"""Amazon Ads parity in the configure UI's credential write paths.

Google Ads / Meta Ads / GA4 / Creative Studio each bind their env-var
names to a ``credentials.json`` section through the closed allow-list in
``mureo.web.env_var_writer`` and each expose a per-section Remove button.
Amazon shipped its credential card without either, so:

- the single-field write path (``POST /api/credentials/env-var``) refused
  every ``AMAZON_ADS_*`` name, and
- the status snapshot's ``env_vars`` row (built from the same allow-list)
  never reported the Amazon fields, and
- the dashboard's Remove button had no allow-listed section to post.

The allow-list entries are asserted against the loader's own env-var
names (``mureo.auth._load_amazon_ads_from_env``) so the write path and
the read path cannot drift.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.amazon_ads.bridge import AmazonAdsBridge
from mureo.auth import load_amazon_ads_credentials
from mureo.core.providers import get_account_credential_fields
from mureo.web.env_var_writer import (
    allowed_env_var_names,
    get_env_var_target,
    removable_credential_sections,
    remove_credential_section,
    write_credential_env_var,
)
from mureo.web.host_paths import HostPaths
from mureo.web.status_collector import collect_status

if TYPE_CHECKING:
    from pathlib import Path

#: Every ``amazon_ads`` field the bridge declares — the single source the
#: env-var allow-list must mirror one-for-one.
_AMAZON_FIELDS = tuple(f.key for f in get_account_credential_fields(AmazonAdsBridge))


def _env_name(field: str) -> str:
    """``client_secret`` → ``AMAZON_ADS_CLIENT_SECRET`` (loader convention)."""
    return "AMAZON_ADS_" + field.upper()


def _paths(tmp_path: Path) -> HostPaths:
    return HostPaths(
        host="claude-code",
        settings_path=tmp_path / "settings.json",
        skills_dir=tmp_path / "skills",
        commands_dir=tmp_path / "commands",
        credentials_path=tmp_path / "credentials.json",
        mcp_registry_path=tmp_path / ".claude.json",
    )


@pytest.mark.unit
class TestAmazonEnvVarAllowList:
    def test_every_declared_field_has_an_allow_listed_env_var(self) -> None:
        names = allowed_env_var_names()
        for field in _AMAZON_FIELDS:
            assert _env_name(field) in names, f"{_env_name(field)} not allow-listed"

    def test_each_name_targets_the_amazon_ads_section_and_field(self) -> None:
        for field in _AMAZON_FIELDS:
            target = get_env_var_target(_env_name(field))
            assert target is not None
            assert target.section == "amazon_ads"
            assert target.field == field

    def test_no_stray_amazon_names_beyond_the_declared_fields(self) -> None:
        """The allow-list must not carry an Amazon name the loader ignores."""
        listed = {n for n in allowed_env_var_names() if n.startswith("AMAZON_ADS_")}
        assert listed == {_env_name(f) for f in _AMAZON_FIELDS}


@pytest.mark.unit
class TestAmazonEnvVarWriteRoundTrip:
    def test_written_values_load_back_as_usable_credentials(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "credentials.json"
        write_credential_env_var(
            "AMAZON_ADS_CLIENT_ID", "amzn1.app.cid", credentials_path=path
        )
        write_credential_env_var(
            "AMAZON_ADS_REFRESH_TOKEN", "Atzr|refresh", credentials_path=path
        )
        write_credential_env_var(
            "AMAZON_ADS_CLIENT_SECRET", "shh", credentials_path=path
        )
        write_credential_env_var("AMAZON_ADS_REGION", "eu", credentials_path=path)

        creds = load_amazon_ads_credentials(path)
        assert creds is not None
        assert creds.client_id == "amzn1.app.cid"
        assert creds.refresh_token == "Atzr|refresh"
        assert creds.client_secret == "shh"
        assert creds.region == "eu"

    def test_write_does_not_disturb_other_sections(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        path.write_text(
            json.dumps({"google_ads": {"developer_token": "keep"}}), encoding="utf-8"
        )
        write_credential_env_var(
            "AMAZON_ADS_ACCESS_TOKEN", "Atza|tok", credentials_path=path
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["google_ads"] == {"developer_token": "keep"}
        assert payload["amazon_ads"] == {"access_token": "Atza|tok"}


@pytest.mark.unit
class TestAmazonSectionIsRemovable:
    def test_amazon_ads_is_allow_listed_for_removal(self) -> None:
        assert "amazon_ads" in removable_credential_sections()

    def test_remove_drops_only_the_amazon_section(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        path.write_text(
            json.dumps(
                {
                    "amazon_ads": {"client_id": "cid", "access_token": "Atza|tok"},
                    "meta_ads": {"access_token": "meta"},
                }
            ),
            encoding="utf-8",
        )
        assert remove_credential_section("amazon_ads", credentials_path=path) is True
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "amazon_ads" not in payload
        assert payload["meta_ads"] == {"access_token": "meta"}

    def test_remove_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        path.write_text(json.dumps({"meta_ads": {}}), encoding="utf-8")
        assert remove_credential_section("amazon_ads", credentials_path=path) is False


@pytest.mark.unit
class TestAmazonEnvVarsInStatusSnapshot:
    def test_snapshot_reports_amazon_fields_with_secrets_masked(
        self, tmp_path: Path
    ) -> None:
        paths = _paths(tmp_path)
        paths.credentials_path.write_text(
            json.dumps(
                {
                    "amazon_ads": {
                        "client_id": "amzn1.app.cid",
                        "access_token": "Atza|super-secret-1234",
                        "region": "fe",
                    }
                }
            ),
            encoding="utf-8",
        )
        snapshot = collect_status("claude-code", paths=paths)

        # Secret-named field: masked preview only.
        token = snapshot.env_vars["AMAZON_ADS_ACCESS_TOKEN"]
        assert token["set"] is True
        assert "super-secret" not in token["value_preview"]
        assert token["value_preview"].endswith("1234")

        # Non-secret identifiers surface verbatim so the operator can check them.
        assert snapshot.env_vars["AMAZON_ADS_REGION"]["value_preview"] == "fe"
        assert snapshot.env_vars["AMAZON_ADS_CLIENT_ID"]["set"] is True
        assert snapshot.env_vars["AMAZON_ADS_PROFILE_ID"]["set"] is False
