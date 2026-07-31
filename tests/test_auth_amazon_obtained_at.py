"""``amazon_ads.refresh_token_obtained_at`` — the re-authorize clock (#121).

Amazon expires refresh tokens issued on/after 2026-07-30 **365 days**
after the advertiser consented (older ones have no fixed expiry). mureo
cannot ask Amazon when a token was issued, so the paste-code wizard
records the moment it obtained one and everything downstream reads that.

Contract pinned here:

- ``save_amazon_access_token`` can write the stamp alongside the tokens,
  under the same lock + atomic write as every other credentials writer,
  and never invents one when not asked;
- the credentials loader ignores the extra metadata key (it is not
  credential material) rather than choking on it;
- the configure UI's generic credential-card save preserves it — a
  region edit from the dashboard must not silently reset the clock.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import pytest

import mureo.auth as auth_mod
from mureo.auth import load_amazon_ads_credentials, save_amazon_access_token

_STAMP = "2026-07-31T00:00:00+00:00"


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.unit
class TestSaveRecordsObtainedAt:
    def test_stamp_is_written_next_to_the_tokens(self, tmp_path: Path) -> None:
        cf = _write(tmp_path, {"amazon_ads": {"client_id": "cid"}})
        save_amazon_access_token(
            "Atza|NEW",
            "Atzr|NEW",
            path=cf,
            refresh_token_obtained_at=_STAMP,
        )
        section = json.loads(cf.read_text())["amazon_ads"]
        assert section["access_token"] == "Atza|NEW"
        assert section["refresh_token"] == "Atzr|NEW"
        assert section["refresh_token_obtained_at"] == _STAMP
        assert section["client_id"] == "cid"

    def test_absent_argument_never_invents_a_stamp(self, tmp_path: Path) -> None:
        """The 60-minute access-token refresh path must not touch the
        refresh token's clock — only a real re-authorization does."""
        cf = _write(tmp_path, {"amazon_ads": {"client_id": "cid"}})
        save_amazon_access_token("Atza|NEW", path=cf)
        assert (
            "refresh_token_obtained_at" not in json.loads(cf.read_text())["amazon_ads"]
        )

    def test_existing_stamp_survives_a_plain_token_refresh(
        self, tmp_path: Path
    ) -> None:
        cf = _write(
            tmp_path,
            {"amazon_ads": {"client_id": "cid", "refresh_token_obtained_at": _STAMP}},
        )
        save_amazon_access_token("Atza|NEW", path=cf)
        section = json.loads(cf.read_text())["amazon_ads"]
        assert section["refresh_token_obtained_at"] == _STAMP

    def test_stamp_write_runs_under_the_credentials_file_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entered: list[Path] = []

        @contextlib.contextmanager
        def _recording_lock(lock_path):  # type: ignore[no-untyped-def]
            entered.append(Path(lock_path))
            yield

        monkeypatch.setattr(auth_mod, "file_lock", _recording_lock)
        cf = _write(tmp_path, {"amazon_ads": {"client_id": "cid"}})
        save_amazon_access_token(
            "Atza|NEW", "Atzr|NEW", path=cf, refresh_token_obtained_at=_STAMP
        )
        assert entered == [tmp_path / "credentials.json.lock"]


@pytest.mark.unit
class TestLoaderIgnoresTheStamp:
    def test_credentials_load_normally_with_the_extra_key(self, tmp_path: Path) -> None:
        cf = _write(
            tmp_path,
            {
                "amazon_ads": {
                    "client_id": "cid",
                    "refresh_token": "Atzr|R",
                    "client_secret": "s",
                    "refresh_token_obtained_at": _STAMP,
                }
            },
        )
        creds = load_amazon_ads_credentials(path=cf)
        assert creds is not None
        assert creds.client_id == "cid"
        # Metadata, not credential material — it must not appear on the
        # frozen dataclass the bridge passes around.
        assert not hasattr(creds, "refresh_token_obtained_at")

    def test_garbage_stamp_does_not_break_the_load(self, tmp_path: Path) -> None:
        cf = _write(
            tmp_path,
            {
                "amazon_ads": {
                    "client_id": "cid",
                    "access_token": "Atza|A",
                    "refresh_token_obtained_at": {"not": "a string"},
                }
            },
        )
        creds = load_amazon_ads_credentials(path=cf)
        assert creds is not None and creds.access_token == "Atza|A"


@pytest.mark.unit
class TestCredentialCardSavePreservesUnknownKeys:
    """The dashboard's Amazon card writes through
    ``save_plugin_credentials``, which merges onto the existing section.
    An operator changing the region must not wipe the re-authorize clock
    the wizard recorded."""

    def test_region_edit_keeps_the_stamp(self, tmp_path: Path) -> None:
        from mureo.amazon_ads.provider import register_amazon_provider
        from mureo.core.secret_store import FilesystemSecretStore
        from mureo.web.plugin_credentials import save_plugin_credentials

        register_amazon_provider()
        cf = _write(
            tmp_path,
            {
                "amazon_ads": {
                    "client_id": "cid",
                    "refresh_token": "Atzr|R",
                    "client_secret": "s",
                    "region": "na",
                    "refresh_token_obtained_at": _STAMP,
                }
            },
        )
        save_plugin_credentials(
            "amazon_ads",
            {"region": "eu"},
            secret_store=FilesystemSecretStore(path=cf),
        )
        section = json.loads(cf.read_text())["amazon_ads"]
        assert section["region"] == "eu"
        assert section["refresh_token_obtained_at"] == _STAMP
        assert section["refresh_token"] == "Atzr|R"
