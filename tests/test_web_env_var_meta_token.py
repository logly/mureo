"""A Meta token pasted into the advanced form must not enter the refresh clock.

Regression tests for #578. The advanced "mureo Credentials (advanced)" form
writes one field at a time through :func:`write_credential_env_var`, which
merges field-wise. For ``META_ADS_ACCESS_TOKEN`` that merge used to leave the
previous token's ``token_obtained_at`` in place, so the very next Meta call saw
a brand-new token as an aged one, handed it to the Graph token-exchange
endpoint under the stale ``app_id``/``app_secret``, and wrote the result over
it (or failed silently).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from mureo.auth import _should_refresh, load_meta_ads_credentials
from mureo.web.env_var_writer import write_credential_env_var

if TYPE_CHECKING:
    from pathlib import Path

#: Older than ``mureo.auth._TOKEN_REFRESH_THRESHOLD_DAYS`` (53) by a margin, so
#: the surviving stamp is unambiguously past the refresh threshold.
_STALE_STAMP = (datetime.now(tz=timezone.utc) - timedelta(days=90)).isoformat()

#: The expiry #726 stores next to the stamp. It describes the token being
#: replaced just as the stamp does, and it drives both the status card's
#: countdown and (since #726) the refresh threshold — so a surviving copy
#: would nag about a token that is gone AND re-arm the very exchange #578
#: disarmed, this time on the expiry branch rather than the age branch.
_STALE_EXPIRY = (datetime.now(tz=timezone.utc) - timedelta(days=30)).isoformat()


def _write_stale_meta_section(path: Path) -> None:
    """Seed the on-disk state an operator with an expired token actually has."""
    path.write_text(
        json.dumps(
            {
                "meta_ads": {
                    "access_token": "EXPIRED-USER-TOKEN",
                    "app_id": "111111111111111",
                    "app_secret": "stale-app-secret",
                    "account_id": "act_222",
                    "token_obtained_at": _STALE_STAMP,
                    "token_expires_at": _STALE_EXPIRY,
                    "token_type": "SYSTEM_USER",
                    "token_never_expires": True,
                },
                # A second provider must survive the single-field write.
                "google_ads": {"developer_token": "dev-token"},
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.unit
class TestMetaAccessTokenLeavesRefreshClock:
    def test_pasted_token_is_not_due_for_refresh(self, tmp_path: Path) -> None:
        """The exact assertion #578 asks for: no refresh after a hand paste."""
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCESS_TOKEN", "SYSTEM-USER-TOKEN", credentials_path=path
        )

        creds = load_meta_ads_credentials(path)
        assert creds is not None
        assert creds.access_token == "SYSTEM-USER-TOKEN"
        assert _should_refresh(creds) is False

    def test_stale_token_obtained_at_is_dropped(self, tmp_path: Path) -> None:
        """The stamp belongs to the token being replaced, so it must not survive."""
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCESS_TOKEN", "SYSTEM-USER-TOKEN", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert "token_obtained_at" not in meta

    def test_stale_token_expires_at_is_dropped(self, tmp_path: Path) -> None:
        """#726: the expiry describes the replaced token too. Left behind it
        would show a countdown for a credential that no longer exists, and
        would put the new hand-pasted token straight back on the refresh
        clock through the expiry branch."""
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCESS_TOKEN", "SYSTEM-USER-TOKEN", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert "token_expires_at" not in meta
        creds = load_meta_ads_credentials(path)
        assert creds is not None
        assert _should_refresh(creds) is False

    def test_stale_token_type_is_dropped(self, tmp_path: Path) -> None:
        """#726: Graph's verdict describes the replaced token. Inherited by
        a hand-pasted token of a different kind, it would put a
        system-user-only parameter on the user-token exchange — the exact
        confusion the field exists to end."""
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCESS_TOKEN", "SYSTEM-USER-TOKEN", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert "token_type" not in meta
        creds = load_meta_ads_credentials(path)
        assert creds is not None
        assert creds.token_type is None

    def test_stale_never_expires_verdict_is_dropped(self, tmp_path: Path) -> None:
        """#740: Graph's "this one is permanent" verdict describes the
        replaced token. Inherited, a hand-entered 60-day token would sit
        ahead of every refresh clock and expire without a single warning."""
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCESS_TOKEN", "SYSTEM-USER-TOKEN", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert "token_never_expires" not in meta
        creds = load_meta_ads_credentials(path)
        assert creds is not None
        assert creds.token_never_expires is False

    def test_writing_another_meta_field_keeps_the_never_expires_verdict(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCOUNT_ID", "act_999", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert meta["token_never_expires"] is True

    def test_writing_another_meta_field_keeps_the_token_type(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCOUNT_ID", "act_999", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert meta["token_type"] == "SYSTEM_USER"

    def test_writing_another_meta_field_keeps_the_expiry(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCOUNT_ID", "act_999", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert meta["token_expires_at"] == _STALE_EXPIRY

    def test_app_credentials_and_account_are_preserved(self, tmp_path: Path) -> None:
        """Only the refresh clock is cleared — no other field is destroyed.

        Dropping ``app_secret`` would make an operator who only meant to
        refresh a token re-fetch it from Meta, so the fix clears the stamp
        instead: ``_should_refresh`` already short-circuits without one.
        """
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCESS_TOKEN", "SYSTEM-USER-TOKEN", credentials_path=path
        )

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["meta_ads"]["app_id"] == "111111111111111"
        assert payload["meta_ads"]["app_secret"] == "stale-app-secret"
        assert payload["meta_ads"]["account_id"] == "act_222"
        assert payload["google_ads"] == {"developer_token": "dev-token"}

    def test_writing_another_meta_field_keeps_the_stamp(self, tmp_path: Path) -> None:
        """Only the token write clears the clock.

        Saving ``META_ADS_ACCOUNT_ID`` does not replace the token, so the
        stamp still describes the token on disk and must be left alone.
        """
        path = tmp_path / "credentials.json"
        _write_stale_meta_section(path)

        write_credential_env_var(
            "META_ADS_ACCOUNT_ID", "act_999", credentials_path=path
        )

        meta = json.loads(path.read_text(encoding="utf-8"))["meta_ads"]
        assert meta["token_obtained_at"] == _STALE_STAMP
        assert meta["account_id"] == "act_999"

    def test_no_stamp_to_clear_is_not_an_error(self, tmp_path: Path) -> None:
        """A first-time paste has no prior section; the write still succeeds."""
        path = tmp_path / "credentials.json"

        write_credential_env_var(
            "META_ADS_ACCESS_TOKEN", "SYSTEM-USER-TOKEN", credentials_path=path
        )

        creds = load_meta_ads_credentials(path)
        assert creds is not None
        assert creds.access_token == "SYSTEM-USER-TOKEN"
        assert _should_refresh(creds) is False
