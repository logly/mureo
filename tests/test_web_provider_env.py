"""Unit tests for ``mureo.web.env_var_writer.build_provider_env``.

The official upstream MCPs (e.g. ``google-ads-mcp``) read their config
ONLY from environment variables — they never see mureo's
``~/.mureo/credentials.json``. A freshly registered official provider is
therefore unusable unless mureo injects an ``env`` block built from the
credentials the user already has. This module pins that builder.

Unlike a blanket section dump, ``build_provider_env`` is driven by the
EXACT env var names a provider declares (its catalog ``required_env`` +
``optional_env``), so it emits only what the upstream reads (#102):

- ``google-ads-mcp`` authenticates via ADC, so it needs
  ``GOOGLE_ADS_DEVELOPER_TOKEN`` + ``GOOGLE_APPLICATION_CREDENTIALS`` (the
  service-account path) + optional ``GOOGLE_ADS_LOGIN_CUSTOMER_ID`` — NOT
  the Client-Library trio (client_id/secret/refresh_token), which the
  upstream ignores entirely;
- the resolution is SECTION-AWARE: the shared
  ``GOOGLE_APPLICATION_CREDENTIALS`` name maps to
  ``google_ads.service_account_path`` for the Google Ads provider but to
  ``ga4.service_account_path`` for the GA4 provider;
- emits one ``{ENV_NAME: str(value)}`` pair per PRESENT, NON-EMPTY field
  (ints coerced to str); empty / missing values, names not valid for the
  section, missing section and missing file all yield nothing.

All FS via ``tmp_path``. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.web._helpers import read_json_safe
from mureo.web.env_var_writer import build_provider_env, write_credential_env_var

if TYPE_CHECKING:
    from pathlib import Path

# The Google Ads ADC env the upstream actually reads (catalog
# required_env + optional_env): dev token, service-account path (ADC), and
# the optional login customer id. The Client-Library trio is deliberately
# absent.
_GOOGLE_ADS_ADC_NAMES = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
)
_GA4_NAMES = ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_PROJECT_ID")


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.unit
class TestBuildProviderEnv:
    def test_google_ads_emits_adc_env_not_client_library_trio(
        self, tmp_path: Path
    ) -> None:
        """The Google Ads ADC env is built from the provider's declared
        names — dev token + GOOGLE_APPLICATION_CREDENTIALS (service-account
        path) + optional login customer id. The Client-Library trio stored
        in the same section is NEVER emitted (the upstream ignores it)."""
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "google_ads": {
                    "developer_token": "DT",
                    "service_account_path": "/p/ads-sa.json",
                    "login_customer_id": "123",
                    # Client-Library secrets the upstream ADC client ignores.
                    "client_id": "CID",
                    "client_secret": "CS",
                    "refresh_token": "RT",
                }
            },
        )

        env = build_provider_env(
            _GOOGLE_ADS_ADC_NAMES, "google_ads", credentials_path=creds
        )

        assert env == {
            "GOOGLE_ADS_DEVELOPER_TOKEN": "DT",
            "GOOGLE_APPLICATION_CREDENTIALS": "/p/ads-sa.json",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123",
        }

    def test_google_application_credentials_is_section_aware(
        self, tmp_path: Path
    ) -> None:
        """The shared ``GOOGLE_APPLICATION_CREDENTIALS`` name resolves to
        ``google_ads.service_account_path`` for the Google Ads section —
        NOT the GA4 binding (which is the historical 1:1 mapping)."""
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "google_ads": {"service_account_path": "/p/ads-sa.json"},
                "ga4": {"service_account_path": "/p/ga4-sa.json"},
            },
        )

        env = build_provider_env(
            ("GOOGLE_APPLICATION_CREDENTIALS",), "google_ads", credentials_path=creds
        )

        assert env == {"GOOGLE_APPLICATION_CREDENTIALS": "/p/ads-sa.json"}

    def test_ga4_section_unchanged(self, tmp_path: Path) -> None:
        """ga4-official still resolves GOOGLE_APPLICATION_CREDENTIALS /
        GOOGLE_PROJECT_ID from the ga4 section (no behaviour change)."""
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "ga4": {
                    "service_account_path": "/p/ga4-sa.json",
                    "project_id": "proj-1",
                }
            },
        )

        env = build_provider_env(_GA4_NAMES, "ga4", credentials_path=creds)

        assert env == {
            "GOOGLE_APPLICATION_CREDENTIALS": "/p/ga4-sa.json",
            "GOOGLE_PROJECT_ID": "proj-1",
        }

    def test_empty_and_missing_values_are_skipped(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "google_ads": {
                    "developer_token": "DT",
                    "service_account_path": "",
                    "login_customer_id": None,
                }
            },
        )

        env = build_provider_env(
            _GOOGLE_ADS_ADC_NAMES, "google_ads", credentials_path=creds
        )

        assert env == {"GOOGLE_ADS_DEVELOPER_TOKEN": "DT"}

    def test_int_value_is_coerced_to_str(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(creds, {"google_ads": {"login_customer_id": 1234567890}})

        env = build_provider_env(
            ("GOOGLE_ADS_LOGIN_CUSTOMER_ID",), "google_ads", credentials_path=creds
        )

        assert env == {"GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890"}

    def test_name_not_valid_for_section_is_skipped(self, tmp_path: Path) -> None:
        """A requested name that does not bind to the section (e.g.
        GOOGLE_PROJECT_ID, a GA4-only name, requested for google_ads) is
        silently skipped — never resolved against the wrong section."""
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {"google_ads": {"developer_token": "DT", "project_id": "leak?"}},
        )

        env = build_provider_env(
            ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_PROJECT_ID"),
            "google_ads",
            credentials_path=creds,
        )

        assert env == {"GOOGLE_ADS_DEVELOPER_TOKEN": "DT"}

    def test_requested_but_absent_field_is_skipped(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(creds, {"google_ads": {"developer_token": "DT"}})

        env = build_provider_env(
            _GOOGLE_ADS_ADC_NAMES, "google_ads", credentials_path=creds
        )

        assert env == {"GOOGLE_ADS_DEVELOPER_TOKEN": "DT"}

    def test_missing_section_yields_empty(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        _write(creds, {"meta_ads": {"access_token": "T"}})

        assert (
            build_provider_env(
                _GOOGLE_ADS_ADC_NAMES, "google_ads", credentials_path=creds
            )
            == {}
        )

    def test_missing_file_yields_empty(self, tmp_path: Path) -> None:
        creds = tmp_path / "does-not-exist.json"

        assert (
            build_provider_env(
                _GOOGLE_ADS_ADC_NAMES, "google_ads", credentials_path=creds
            )
            == {}
        )

    def test_only_requested_names_are_emitted(self, tmp_path: Path) -> None:
        """A field present in the section but NOT requested is never
        surfaced — the env block is driven by the provider's declared
        names, not the on-disk section contents."""
        creds = tmp_path / "credentials.json"
        _write(
            creds,
            {
                "google_ads": {
                    "developer_token": "DT",
                    "service_account_path": "/p/sa.json",
                }
            },
        )

        env = build_provider_env(
            ("GOOGLE_ADS_DEVELOPER_TOKEN",), "google_ads", credentials_path=creds
        )

        assert env == {"GOOGLE_ADS_DEVELOPER_TOKEN": "DT"}


@pytest.mark.unit
class TestWriteCredentialEnvVarSectionAware:
    """``write_credential_env_var`` gains an optional ``section`` to
    disambiguate env names SHARED across credentials.json sections (#102 B2).

    The wizard's service-account-path input for ``google-ads-official`` posts
    the shared ``GOOGLE_APPLICATION_CREDENTIALS`` name but must persist into
    ``google_ads.service_account_path`` — NOT the canonical GA4 binding. A
    section-less write keeps the historical 1:1 behaviour byte-for-byte.
    """

    def test_section_none_uses_canonical_binding(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        write_credential_env_var(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/p/ga4-sa.json",
            credentials_path=creds,
        )
        assert read_json_safe(creds) == {
            "ga4": {"service_account_path": "/p/ga4-sa.json"}
        }

    def test_section_routes_shared_name_to_google_ads(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        write_credential_env_var(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/p/ads-sa.json",
            section="google_ads",
            credentials_path=creds,
        )
        assert read_json_safe(creds) == {
            "google_ads": {"service_account_path": "/p/ads-sa.json"}
        }

    def test_explicit_ga4_section_matches_canonical(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        write_credential_env_var(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/p/ga4-sa.json",
            section="ga4",
            credentials_path=creds,
        )
        assert read_json_safe(creds) == {
            "ga4": {"service_account_path": "/p/ga4-sa.json"}
        }

    def test_name_not_bound_to_section_raises(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        # GOOGLE_PROJECT_ID is a GA4-only name; it does not bind to google_ads.
        with pytest.raises(ValueError, match="google_ads"):
            write_credential_env_var(
                "GOOGLE_PROJECT_ID",
                "proj-1",
                section="google_ads",
                credentials_path=creds,
            )
        assert not creds.exists()

    def test_section_write_preserves_sibling_sections(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps({"ga4": {"service_account_path": "/p/ga4-sa.json"}}),
            encoding="utf-8",
        )
        write_credential_env_var(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/p/ads-sa.json",
            section="google_ads",
            credentials_path=creds,
        )
        assert read_json_safe(creds) == {
            "ga4": {"service_account_path": "/p/ga4-sa.json"},
            "google_ads": {"service_account_path": "/p/ads-sa.json"},
        }

    def test_disallowed_name_still_raises(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        with pytest.raises(ValueError, match="not allowed"):
            write_credential_env_var(
                "EVIL_VAR", "x", section="google_ads", credentials_path=creds
            )

    def test_empty_value_still_raises(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        with pytest.raises(ValueError, match="non-empty"):
            write_credential_env_var(
                "GOOGLE_APPLICATION_CREDENTIALS",
                "",
                section="google_ads",
                credentials_path=creds,
            )
