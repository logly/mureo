"""Amazon Ads credential loading (TDD: RED → GREEN → IMPROVE).

Phase 1 of #113: ``amazon_ads`` section in ~/.mureo/credentials.json,
mirroring the Google/Meta loaders in ``mureo.auth``. credentials.json
only (no env fallback in Phase 1 — documented).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from pathlib import Path

import pytest

import mureo.auth as auth_mod
from mureo.auth import (
    load_amazon_ads_credentials,
    save_amazon_access_token,
)
from mureo.providers.config_writer import ConfigWriteError


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


@pytest.mark.unit
class TestSaveAmazonAccessToken:
    def test_updates_section_preserving_others(self, tmp_path: Path) -> None:
        cf = _write(
            tmp_path,
            {
                "google_ads": {"developer_token": "keep"},
                "amazon_ads": {
                    "client_id": "cid",
                    "access_token": "OLD",
                    "region": "eu",
                },
            },
        )
        save_amazon_access_token("Atza|NEW", "Atzr|NEW", path=cf)
        doc = json.loads(cf.read_text())
        assert doc["amazon_ads"]["access_token"] == "Atza|NEW"
        assert doc["amazon_ads"]["refresh_token"] == "Atzr|NEW"
        assert doc["amazon_ads"]["client_id"] == "cid"  # preserved
        assert doc["amazon_ads"]["region"] == "eu"  # preserved
        assert doc["google_ads"]["developer_token"] == "keep"  # untouched

    def test_creates_section_when_absent(self, tmp_path: Path) -> None:
        cf = _write(tmp_path, {"meta_ads": {"access_token": "m"}})
        save_amazon_access_token("Atza|NEW", path=cf)
        doc = json.loads(cf.read_text())
        assert doc["amazon_ads"]["access_token"] == "Atza|NEW"
        assert "refresh_token" not in doc["amazon_ads"]
        assert doc["meta_ads"]["access_token"] == "m"

    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        cf = tmp_path / "credentials.json"
        save_amazon_access_token("Atza|NEW", path=cf)
        assert json.loads(cf.read_text())["amazon_ads"]["access_token"] == "Atza|NEW"

    def test_written_file_is_0600(self, tmp_path: Path) -> None:
        import stat

        cf = tmp_path / "credentials.json"
        save_amazon_access_token("Atza|NEW", path=cf)
        assert stat.S_IMODE(cf.stat().st_mode) == 0o600

    def test_round_trips_with_loader(self, tmp_path: Path) -> None:
        cf = _write(
            tmp_path,
            {"amazon_ads": {"client_id": "cid", "access_token": "OLD"}},
        )
        save_amazon_access_token("Atza|NEW", path=cf)
        c = load_amazon_ads_credentials(path=cf)
        assert c is not None and c.access_token == "Atza|NEW"

    def test_malformed_file_raises_and_leaves_it_untouched(
        self, tmp_path: Path
    ) -> None:
        """A slightly-corrupt credentials.json must NOT be overwritten.

        Same contract as ``_save_meta_token``: ``_load_existing`` raises
        ``ConfigWriteError`` rather than resetting to ``{}``, which would
        silently erase every other provider's section.
        """
        cf = tmp_path / "credentials.json"
        original = '{"google_ads": {"developer_token": "keep"}, "meta_ads": {,}'
        cf.write_text(original, encoding="utf-8")

        with pytest.raises(ConfigWriteError):
            save_amazon_access_token("Atza|NEW", "Atzr|NEW", path=cf)

        assert cf.read_text(encoding="utf-8") == original  # byte-for-byte

    def test_read_modify_write_runs_under_the_credentials_file_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole cycle is serialised by the shared credentials lock.

        A true concurrency test lives in ``test_credentials_concurrency``;
        here we only pin that this writer contends on the SAME sidecar
        lock every other credentials.json writer uses, so it cannot
        last-writer-wins away a concurrent wizard save.
        """
        entered: list[Path] = []

        @contextlib.contextmanager
        def _recording_lock(lock_path):  # type: ignore[no-untyped-def]
            entered.append(Path(lock_path))
            yield

        monkeypatch.setattr(auth_mod, "file_lock", _recording_lock)

        cf = _write(tmp_path, {"amazon_ads": {"client_id": "cid"}})
        save_amazon_access_token("Atza|NEW", path=cf)

        assert entered == [tmp_path / "credentials.json.lock"]
