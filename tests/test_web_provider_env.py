"""Unit tests for ``mureo.web.env_var_writer.build_credentials_env``.

The official upstream MCPs (e.g. ``google-ads-mcp``) read their config
ONLY from environment variables — they never see mureo's
``~/.mureo/credentials.json``. A freshly registered official provider is
therefore unusable unless mureo injects an ``env`` block built from the
credentials the user already has. This module pins that builder:

- reverse of the per-var writer's closed allow-list (env name →
  (section, field)); never produces a name outside it;
- emits one ``{ENV_NAME: str(value)}`` pair per PRESENT, NON-EMPTY field
  in the requested section (ints coerced to str);
- empty / missing values, missing section, and missing file all yield a
  ``{}`` (caller then writes a bare block, exactly the pre-fix shape).

All FS via ``tmp_path``. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.web.env_var_writer import build_credentials_env

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.unit
class TestBuildCredentialsEnv:
    def test_google_ads_full_section_maps_every_field(
        self, tmp_path: Path
    ) -> None:
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "google_ads": {
                    "developer_token": "DT",
                    "client_id": "CID",
                    "client_secret": "CS",
                    "refresh_token": "RT",
                    "login_customer_id": "123",
                    "customer_id": "456",
                }
            },
        )

        env = build_credentials_env("google_ads", credentials_path=creds)

        assert env == {
            "GOOGLE_ADS_DEVELOPER_TOKEN": "DT",
            "GOOGLE_ADS_CLIENT_ID": "CID",
            "GOOGLE_ADS_CLIENT_SECRET": "CS",
            "GOOGLE_ADS_REFRESH_TOKEN": "RT",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123",
            "GOOGLE_ADS_CUSTOMER_ID": "456",
        }

    def test_empty_and_missing_fields_are_skipped(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "google_ads": {
                    "developer_token": "DT",
                    "client_id": "",
                    "client_secret": None,
                    "refresh_token": "RT",
                }
            },
        )

        env = build_credentials_env("google_ads", credentials_path=creds)

        assert env == {
            "GOOGLE_ADS_DEVELOPER_TOKEN": "DT",
            "GOOGLE_ADS_REFRESH_TOKEN": "RT",
        }

    def test_int_value_is_coerced_to_str(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(creds, {"google_ads": {"login_customer_id": 1234567890}})

        env = build_credentials_env("google_ads", credentials_path=creds)

        assert env == {"GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890"}

    def test_ga4_section(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "ga4": {
                    "service_account_path": "/p/sa.json",
                    "project_id": "proj-1",
                }
            },
        )

        env = build_credentials_env("ga4", credentials_path=creds)

        assert env == {
            "GOOGLE_APPLICATION_CREDENTIALS": "/p/sa.json",
            "GOOGLE_PROJECT_ID": "proj-1",
        }

    def test_missing_section_yields_empty(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(creds, {"meta_ads": {"access_token": "T"}})

        assert build_credentials_env("google_ads", credentials_path=creds) == {}

    def test_missing_file_yields_empty(self, tmp_path: Path) -> None:
        creds = tmp_path / "does-not-exist.json"

        assert build_credentials_env("google_ads", credentials_path=creds) == {}

    def test_unknown_section_yields_empty(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(creds, {"google_ads": {"developer_token": "DT"}})

        assert build_credentials_env("nope", credentials_path=creds) == {}

    def test_only_allow_listed_fields_are_emitted(self, tmp_path: Path) -> None:
        """A stray/unknown field in the section is never surfaced as env."""
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "google_ads": {
                    "developer_token": "DT",
                    "totally_unknown_field": "leak?",
                }
            },
        )

        env = build_credentials_env("google_ads", credentials_path=creds)

        assert env == {"GOOGLE_ADS_DEVELOPER_TOKEN": "DT"}
