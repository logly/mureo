"""Amazon Ads credential loading (TDD: RED → GREEN → IMPROVE).

Phase 1 of #113: ``amazon_ads`` section in ~/.mureo/credentials.json,
mirroring the Google/Meta loaders in ``mureo.auth``. credentials.json
only (no env fallback in Phase 1 — documented).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from mureo.auth import AmazonAdsCredentials, load_amazon_ads_credentials


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "credentials.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


@pytest.mark.unit
class TestLoadAmazonAdsCredentials:
    def test_full_section_parsed(self, tmp_path: Path) -> None:
        cf = _write(
            tmp_path,
            {
                "amazon_ads": {
                    "client_id": "amzn1.application-oa2-client.abc",
                    "access_token": "Atza|secret-access",
                    "refresh_token": "Atzr|secret-refresh",
                    "client_secret": "lwa-client-secret",
                    "region": "EU",
                    "account_mode": "fixed",
                    "profile_id": "111",
                    "account_id": "222",
                    "manager_account_id": "333",
                }
            },
        )
        c = load_amazon_ads_credentials(path=cf)
        assert c is not None
        assert c.client_id == "amzn1.application-oa2-client.abc"
        assert c.access_token == "Atza|secret-access"
        assert c.refresh_token == "Atzr|secret-refresh"
        assert c.client_secret == "lwa-client-secret"
        assert c.region == "eu"  # normalized lower
        assert c.account_mode == "fixed"
        assert c.profile_id == "111"
        assert c.account_id == "222"
        assert c.manager_account_id == "333"

    def test_minimal_uses_safe_defaults(self, tmp_path: Path) -> None:
        cf = _write(
            tmp_path,
            {"amazon_ads": {"client_id": "cid", "access_token": "tok"}},
        )
        c = load_amazon_ads_credentials(path=cf)
        assert c is not None
        assert c.region == "na"  # default
        assert c.account_mode == "dynamic"  # default
        assert c.refresh_token is None
        assert c.client_secret is None
        assert c.profile_id is None

    def test_invalid_region_and_mode_fall_back_to_defaults(
        self, tmp_path: Path
    ) -> None:
        cf = _write(
            tmp_path,
            {
                "amazon_ads": {
                    "client_id": "cid",
                    "access_token": "tok",
                    "region": "antarctica",
                    "account_mode": "bogus",
                }
            },
        )
        c = load_amazon_ads_credentials(path=cf)
        assert c is not None
        assert c.region == "na"
        assert c.account_mode == "dynamic"

    def test_missing_required_returns_none(self, tmp_path: Path) -> None:
        for section in ({}, {"client_id": "cid"}, {"access_token": "tok"}):
            cf = _write(tmp_path, {"amazon_ads": section})
            assert load_amazon_ads_credentials(path=cf) is None

    def test_no_section_returns_none(self, tmp_path: Path) -> None:
        cf = _write(tmp_path, {"google_ads": {"x": 1}})
        assert load_amazon_ads_credentials(path=cf) is None

    def test_file_not_found_returns_none(self, tmp_path: Path) -> None:
        assert load_amazon_ads_credentials(path=tmp_path / "nope.json") is None

    def test_credentials_are_immutable(self, tmp_path: Path) -> None:
        cf = _write(
            tmp_path,
            {"amazon_ads": {"client_id": "cid", "access_token": "tok"}},
        )
        c = load_amazon_ads_credentials(path=cf)
        assert c is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.access_token = "mutated"  # type: ignore[misc]
