"""Unit tests for ``mureo.core.ga4_adc`` (#938).

The Google authorization becomes an ``authorized_user`` ADC file the
official GA4 MCP reads, but only when Google granted ``analytics.readonly``
and only over a ``ga4`` section that is absent, has no credential file path,
or already points at the managed file: a section naming any other file
always wins.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from mureo.core.ga4_adc import (
    ANALYTICS_READONLY_SCOPE,
    drop_managed_ga4_section,
    ga4_section_usable,
    is_managed_ga4_section,
    managed_adc_path,
    oauth_client_project_number,
    refresh_managed_ga4_adc,
    store_has_managed_ga4,
    sync_ga4_adc_from_google,
    unlink_managed_ga4_adc,
)

pytestmark = pytest.mark.unit

_PROJECT = "123456789012"
_CLIENT_ID = f"{_PROJECT}-abc123def.apps.googleusercontent.com"
_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"


@pytest.fixture
def creds(tmp_path: Path) -> Path:
    return tmp_path / "store" / "credentials.json"


def _sync(existing: dict[str, Any], creds: Path, **overrides: Any) -> bool:
    kwargs: dict[str, Any] = {
        "client_id": _CLIENT_ID,
        "client_secret": "SECRET",
        "refresh_token": "1//REFRESH",
        "granted_scopes": [_ADS_SCOPE, ANALYTICS_READONLY_SCOPE],
        "credentials_path": creds,
    }
    kwargs.update(overrides)
    return sync_ga4_adc_from_google(existing, **kwargs)


def _read_adc(creds: Path) -> dict[str, Any]:
    return json.loads(managed_adc_path(creds).read_text(encoding="utf-8"))


class TestManagedPath:
    def test_is_named_after_the_store_beside_it(self, tmp_path: Path) -> None:
        store = tmp_path / "credentials.json"

        assert managed_adc_path(store) == tmp_path / "credentials-ga4-adc.json"

    def test_two_stores_in_one_directory_never_share_it(self, tmp_path: Path) -> None:
        one = managed_adc_path(tmp_path / "credentials.json")
        other = managed_adc_path(tmp_path / "client-a.json")

        assert one != other
        assert other == tmp_path / "client-a-ga4-adc.json"


class TestSync:
    def test_writes_the_adc_and_points_the_section_at_it(
        self, creds: Path, tmp_path: Path
    ) -> None:
        existing: dict[str, Any] = {}

        assert _sync(existing, creds) is True

        adc = tmp_path / "store" / "credentials-ga4-adc.json"
        assert adc == managed_adc_path(creds)
        assert json.loads(adc.read_text(encoding="utf-8")) == {
            "type": "authorized_user",
            "client_id": _CLIENT_ID,
            "client_secret": "SECRET",
            "refresh_token": "1//REFRESH",
            "quota_project_id": _PROJECT,
        }
        if os.name == "posix":
            assert stat.S_IMODE(adc.stat().st_mode) == 0o600
        assert existing["ga4"] == {
            "service_account_path": str(adc),
            "project_id": _PROJECT,
        }

    def test_skips_without_the_analytics_scope(self, creds: Path) -> None:
        existing: dict[str, Any] = {"google_ads": {"client_id": _CLIENT_ID}}

        assert _sync(existing, creds, granted_scopes=[_ADS_SCOPE]) is False

        assert not managed_adc_path(creds).exists()
        assert existing == {"google_ads": {"client_id": _CLIENT_ID}}

    def test_skips_a_client_id_without_a_project_number(self, creds: Path) -> None:
        existing: dict[str, Any] = {}

        assert _sync(existing, creds, client_id="custom-client-id") is False

        assert not managed_adc_path(creds).exists()
        assert existing == {}

    def test_keeps_the_operators_own_file(self, creds: Path, tmp_path: Path) -> None:
        own = {"service_account_path": str(tmp_path / "sa.json"), "project_id": "p"}
        existing: dict[str, Any] = {"ga4": dict(own)}

        assert _sync(existing, creds) is False

        assert not managed_adc_path(creds).exists()
        assert existing == {"ga4": own}

    def test_keeps_an_operator_path_without_a_project(
        self, creds: Path, tmp_path: Path
    ) -> None:
        own = {"service_account_path": str(tmp_path / "sa.json")}
        existing: dict[str, Any] = {"ga4": dict(own)}

        assert _sync(existing, creds) is False

        assert not managed_adc_path(creds).exists()
        assert existing == {"ga4": own}

    def test_fills_a_section_without_a_path(self, creds: Path) -> None:
        existing: dict[str, Any] = {"ga4": {"project_id": "half-written"}}

        assert _sync(existing, creds) is True

        assert existing["ga4"]["project_id"] == _PROJECT
        assert is_managed_ga4_section(existing["ga4"], creds)

    def test_rewrites_a_managed_section_with_the_rotated_token(
        self, creds: Path
    ) -> None:
        existing: dict[str, Any] = {}
        _sync(existing, creds)

        assert _sync(existing, creds, refresh_token="1//ROTATED") is True

        assert _read_adc(creds)["refresh_token"] == "1//ROTATED"
        assert is_managed_ga4_section(existing["ga4"], creds)

    def test_keeps_a_project_set_on_a_managed_section(self, creds: Path) -> None:
        existing: dict[str, Any] = {}
        _sync(existing, creds)
        existing["ga4"]["project_id"] = "my-quota-project"

        assert _sync(existing, creds, refresh_token="1//ROTATED") is True

        assert existing["ga4"]["project_id"] == "my-quota-project"
        assert _read_adc(creds)["quota_project_id"] == "my-quota-project"

    def test_fills_an_emptied_project_on_a_managed_section(self, creds: Path) -> None:
        existing: dict[str, Any] = {}
        _sync(existing, creds)
        existing["ga4"]["project_id"] = ""

        assert _sync(existing, creds) is True

        assert existing["ga4"]["project_id"] == _PROJECT

    def test_a_failed_write_leaves_the_section_alone(
        self, creds: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(payload: dict[str, Any], path: Path) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr("mureo.core.ga4_adc.atomic_write_json", _boom)
        existing: dict[str, Any] = {}

        assert _sync(existing, creds) is False

        assert "ga4" not in existing


def _managed_store(creds: Path) -> dict[str, Any]:
    existing: dict[str, Any] = {
        "google_ads": {
            "client_id": _CLIENT_ID,
            "client_secret": "SECRET",
            "refresh_token": "1//REFRESH",
        }
    }
    _sync(existing, creds)
    return existing


class TestRefresh:
    def test_rewrites_the_file_from_the_google_section(self, creds: Path) -> None:
        existing = _managed_store(creds)
        existing["google_ads"]["refresh_token"] = "1//EDITED"
        existing["ga4"]["project_id"] = "my-quota-project"

        assert refresh_managed_ga4_adc(existing, creds) is True

        assert _read_adc(creds) == {
            "type": "authorized_user",
            "client_id": _CLIENT_ID,
            "client_secret": "SECRET",
            "refresh_token": "1//EDITED",
            "quota_project_id": "my-quota-project",
        }

    def test_leaves_a_section_pointing_elsewhere(
        self, creds: Path, tmp_path: Path
    ) -> None:
        existing = _managed_store(creds)
        unlink_managed_ga4_adc(creds)
        existing["ga4"] = {"service_account_path": str(tmp_path / "sa.json")}

        assert refresh_managed_ga4_adc(existing, creds) is False

        assert not managed_adc_path(creds).exists()

    def test_skips_when_a_google_value_is_missing(self, creds: Path) -> None:
        existing = _managed_store(creds)
        del existing["google_ads"]["client_secret"]

        assert refresh_managed_ga4_adc(existing, creds) is False

        assert _read_adc(creds)["client_secret"] == "SECRET"

    def test_skips_when_the_project_id_is_missing(self, creds: Path) -> None:
        existing = _managed_store(creds)
        existing["google_ads"]["refresh_token"] = "1//EDITED"
        del existing["ga4"]["project_id"]

        assert refresh_managed_ga4_adc(existing, creds) is False

        assert _read_adc(creds)["refresh_token"] == "1//REFRESH"

    def test_a_failed_write_returns_false(
        self, creds: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing = _managed_store(creds)

        def _boom(payload: dict[str, Any], path: Path) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr("mureo.core.ga4_adc.atomic_write_json", _boom)

        assert refresh_managed_ga4_adc(existing, creds) is False


class TestSyncDropsAStaleManagedFile:
    """A new grant that can no longer back the managed file removes it and
    the section pointing at it; an operator's own section is left alone."""

    def test_a_grant_without_the_analytics_scope(
        self, creds: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        existing = _managed_store(creds)

        with caplog.at_level(logging.INFO, logger="mureo.core.ga4_adc"):
            assert _sync(existing, creds, granted_scopes=[_ADS_SCOPE]) is False

        assert "ga4" not in existing
        assert not managed_adc_path(creds).exists()
        assert "GA4 credential file removed: analytics.readonly was not granted" in [
            r.getMessage() for r in caplog.records
        ]

    def test_a_client_id_without_a_project_number(self, creds: Path) -> None:
        existing = _managed_store(creds)

        assert _sync(existing, creds, client_id="custom-client-id") is False

        assert "ga4" not in existing
        assert not managed_adc_path(creds).exists()

    def test_leaves_the_operators_own_section(
        self, creds: Path, tmp_path: Path
    ) -> None:
        _managed_store(creds)
        own = {"service_account_path": str(tmp_path / "sa.json"), "project_id": "p"}
        existing: dict[str, Any] = {"ga4": dict(own)}

        assert _sync(existing, creds, granted_scopes=[_ADS_SCOPE]) is False

        assert existing == {"ga4": own}
        assert managed_adc_path(creds).exists()


class TestStoreHasManaged:
    def test_reads_the_ga4_section_of_the_store(
        self, creds: Path, tmp_path: Path
    ) -> None:
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text(json.dumps(_managed_store(creds)), encoding="utf-8")
        assert store_has_managed_ga4(creds) is True

        own = {"ga4": {"service_account_path": str(tmp_path / "sa.json")}}
        creds.write_text(json.dumps(own), encoding="utf-8")
        assert store_has_managed_ga4(creds) is False

    def test_a_missing_store_has_none(self, creds: Path) -> None:
        assert store_has_managed_ga4(creds) is False


class TestDropSection:
    def test_pops_the_managed_section_only(self, creds: Path) -> None:
        existing = _managed_store(creds)

        assert drop_managed_ga4_section(existing, creds) is True

        assert "ga4" not in existing
        assert "google_ads" in existing
        assert managed_adc_path(creds).exists()

    def test_leaves_the_operators_own_section(
        self, creds: Path, tmp_path: Path
    ) -> None:
        own = {"service_account_path": str(tmp_path / "sa.json"), "project_id": "p"}
        existing: dict[str, Any] = {"ga4": dict(own)}

        assert drop_managed_ga4_section(existing, creds) is False

        assert existing == {"ga4": own}


class TestUnlink:
    def test_deletes_the_file(self, creds: Path) -> None:
        _managed_store(creds)

        assert unlink_managed_ga4_adc(creds) is True

        assert not managed_adc_path(creds).exists()

    def test_is_idempotent(self, creds: Path) -> None:
        assert unlink_managed_ga4_adc(creds) is False

    def test_a_failed_delete_is_logged_and_returns_false(
        self,
        creds: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _managed_store(creds)

        def _deny(self: Path, missing_ok: bool = False) -> None:
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "unlink", _deny)

        with caplog.at_level(logging.WARNING, logger="mureo.core.ga4_adc"):
            assert unlink_managed_ga4_adc(creds) is False

        assert [r.getMessage() for r in caplog.records] == [
            "GA4 credential file not removed (PermissionError)"
        ]


class TestIsManaged:
    def test_reads_only_dict_sections_with_the_managed_path(self, creds: Path) -> None:
        managed = str(managed_adc_path(creds))

        assert is_managed_ga4_section({"service_account_path": managed}, creds)
        assert not is_managed_ga4_section({"service_account_path": "/x.json"}, creds)
        assert not is_managed_ga4_section({}, creds)
        assert not is_managed_ga4_section("not-a-dict", creds)
        assert not is_managed_ga4_section(None, creds)

    def test_matches_a_home_relative_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        store = tmp_path / "store" / "credentials.json"
        section = {"service_account_path": "~/store/credentials-ga4-adc.json"}

        assert is_managed_ga4_section(section, store)

    def test_matches_a_path_with_a_dot_segment(self, creds: Path) -> None:
        dotted = os.path.join(str(creds.parent), ".", "credentials-ga4-adc.json")

        assert is_managed_ga4_section({"service_account_path": dotted}, creds)


class TestSectionUsable:
    @pytest.mark.parametrize(
        ("section", "expected"),
        [
            ({"service_account_path": "/a.json", "project_id": "p"}, True),
            ({"service_account_path": "/a.json"}, False),
            ({"project_id": "p"}, False),
            ({"service_account_path": "", "project_id": "p"}, False),
            ({}, False),
            (None, False),
            ("not-a-dict", False),
        ],
    )
    def test_needs_both_values(self, section: object, expected: bool) -> None:
        assert ga4_section_usable(section) is expected


@pytest.mark.parametrize(
    ("client_id", "expected"),
    [
        (_CLIENT_ID, _PROJECT),
        (f"  {_CLIENT_ID}\n", _PROJECT),
        ("abc-123.apps.googleusercontent.com", None),
        (f"{_PROJECT}-abc123.apps.example.com", None),
        (f"{_PROJECT}-abc123.apps.googleusercontent.com.evil", None),
        ("", None),
    ],
)
def test_oauth_client_project_number(client_id: str, expected: str | None) -> None:
    assert oauth_client_project_number(client_id) == expected
