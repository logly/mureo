"""Meta access-token expiry signalling in the status snapshot (#579).

Meta's long-lived user tokens live ~60 days from issue, and mureo hands
them back to Graph's ``fb_exchange_token`` endpoint at 53 days
(:data:`mureo.auth._TOKEN_REFRESH_THRESHOLD_DAYS`) — but only when
``app_id`` **and** ``app_secret`` are stored alongside the token. So:

- token stored WITH the app pair → an integer age plus an "expiring"
  flag once it passes the refresh threshold, because a token still that
  old on disk is one the automatic refresh has not renewed;
- token stored WITHOUT the app pair → a Business Manager system-user
  token, which never expires (``auth._should_refresh`` short-circuits on
  exactly this condition). Its age is reported but never warned about —
  an expiry notice on a token that cannot expire is noise. Note the save
  path stamps ``token_obtained_at`` on these too, so "has a stamp" alone
  says nothing about expiry;
- no stamp at all (a hand-entered token, #578) → unknown age and **no**
  warning. A missing stamp means "off the refresh clock", never
  "infinitely old".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core import clock
from mureo.web.status_collector import (
    META_ACCESS_TOKEN_WARN_DAYS,
    _detect_meta_token,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "server_now", lambda: _NOW)


def _credentials(tmp_path: Path, section: Any) -> Path:
    path = tmp_path / "credentials.json"
    payload = {} if section is None else {"meta_ads": section}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stamp(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _app_backed(days_ago: float) -> dict[str, Any]:
    """A token on the refresh clock: app pair present plus a stamp."""
    return {
        "access_token": "EAA-token",
        "app_id": "123",
        "app_secret": "s3cr3t",
        "token_obtained_at": _stamp(days_ago),
    }


@pytest.mark.unit
class TestWarnThreshold:
    def test_threshold_tracks_the_refresh_clock(self) -> None:
        """The warning fires exactly where the automatic refresh should
        have: a divergence here would nag about a token mureo itself is
        about to replace, or stay silent past the point of no return."""
        from mureo.auth import _TOKEN_REFRESH_THRESHOLD_DAYS

        assert META_ACCESS_TOKEN_WARN_DAYS == _TOKEN_REFRESH_THRESHOLD_DAYS


@pytest.mark.unit
class TestMetaAccessTokenAge:
    def test_no_credentials_file_is_unknown_and_not_expiring(
        self, tmp_path: Path
    ) -> None:
        row = _detect_meta_token(tmp_path / "missing.json")
        assert row == {
            "access_token_age_days": None,
            "access_token_expiring": False,
        }

    def test_fresh_app_backed_token_reports_its_age_without_warning(
        self, tmp_path: Path
    ) -> None:
        path = _credentials(tmp_path, _app_backed(10.9))
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] == 10
        assert row["access_token_expiring"] is False

    def test_just_below_the_threshold_does_not_warn(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, _app_backed(META_ACCESS_TOKEN_WARN_DAYS))
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] == META_ACCESS_TOKEN_WARN_DAYS
        assert row["access_token_expiring"] is False

    def test_past_the_threshold_warns(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, _app_backed(META_ACCESS_TOKEN_WARN_DAYS + 1))
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] == META_ACCESS_TOKEN_WARN_DAYS + 1
        assert row["access_token_expiring"] is True

    def test_beyond_the_full_lifetime_still_warns(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, _app_backed(400))
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] == 400
        assert row["access_token_expiring"] is True


@pytest.mark.unit
class TestSystemUserTokensAreNeverWarnedAbout:
    def test_token_without_the_app_pair_is_not_expiring(self, tmp_path: Path) -> None:
        """The paste card saves a system-user token WITHOUT app_id /
        app_secret precisely because it never expires — but it does stamp
        token_obtained_at, so age alone must not drive the warning."""
        path = _credentials(
            tmp_path,
            {"access_token": "EAA-token", "token_obtained_at": _stamp(400)},
        )
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] == 400
        assert row["access_token_expiring"] is False

    def test_app_id_without_app_secret_cannot_refresh_so_never_warns(
        self, tmp_path: Path
    ) -> None:
        path = _credentials(
            tmp_path,
            {
                "access_token": "EAA-token",
                "app_id": "123",
                "token_obtained_at": _stamp(400),
            },
        )
        assert _detect_meta_token(path)["access_token_expiring"] is False

    def test_app_secret_without_app_id_never_warns(self, tmp_path: Path) -> None:
        path = _credentials(
            tmp_path,
            {
                "access_token": "EAA-token",
                "app_secret": "s3cr3t",
                "token_obtained_at": _stamp(400),
            },
        )
        assert _detect_meta_token(path)["access_token_expiring"] is False

    def test_blank_app_pair_never_warns(self, tmp_path: Path) -> None:
        """Empty strings are what an advanced-form clear leaves behind, and
        auth._should_refresh treats them as absent too."""
        path = _credentials(
            tmp_path,
            {
                "access_token": "EAA-token",
                "app_id": "",
                "app_secret": "",
                "token_obtained_at": _stamp(400),
            },
        )
        assert _detect_meta_token(path)["access_token_expiring"] is False


@pytest.mark.unit
class TestUnknownAgeIsNeverAWarning:
    def test_missing_stamp_is_unknown_not_infinitely_old(self, tmp_path: Path) -> None:
        """#578: writing META_ADS_ACCESS_TOKEN by hand CLEARS the stamp to
        keep the token off the refresh clock. Reading that as an ancient
        token would warn about the one credential that is freshest."""
        path = _credentials(
            tmp_path,
            {"access_token": "EAA-token", "app_id": "123", "app_secret": "s3cr3t"},
        )
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] is None
        assert row["access_token_expiring"] is False

    def test_unparseable_stamp_is_unknown_not_expiring(self, tmp_path: Path) -> None:
        path = _credentials(
            tmp_path,
            {
                "access_token": "EAA-token",
                "app_id": "123",
                "app_secret": "s3cr3t",
                "token_obtained_at": "last tuesday",
            },
        )
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] is None
        assert row["access_token_expiring"] is False

    def test_non_string_stamp_is_unknown(self, tmp_path: Path) -> None:
        path = _credentials(
            tmp_path,
            {"access_token": "EAA-token", "token_obtained_at": 1234567890},
        )
        assert _detect_meta_token(path)["access_token_age_days"] is None

    def test_zulu_suffix_is_accepted(self, tmp_path: Path) -> None:
        stamp = (_NOW - timedelta(days=54)).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = _credentials(
            tmp_path,
            {
                "access_token": "EAA-token",
                "app_id": "123",
                "app_secret": "s3cr3t",
                "token_obtained_at": stamp,
            },
        )
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] == 54
        assert row["access_token_expiring"] is True

    def test_future_stamp_clamps_to_zero(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, _app_backed(-5))
        row = _detect_meta_token(path)
        assert row["access_token_age_days"] == 0
        assert row["access_token_expiring"] is False

    def test_malformed_section_is_tolerated(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, "not-a-dict")
        assert _detect_meta_token(path) == {
            "access_token_age_days": None,
            "access_token_expiring": False,
        }


@pytest.mark.unit
class TestSnapshotCarriesTheRow:
    def test_collect_status_exposes_meta_token(self, tmp_path: Path) -> None:
        from mureo.web.status_collector import collect_status

        home = tmp_path / "home"
        (home / ".mureo").mkdir(parents=True)
        (home / ".mureo" / "credentials.json").write_text(
            json.dumps({"meta_ads": _app_backed(60)}),
            encoding="utf-8",
        )
        snapshot = collect_status("claude-code", home=home)
        assert snapshot.meta_token == {
            "access_token_age_days": 60,
            "access_token_expiring": True,
        }
        assert snapshot.as_dict()["meta_token"]["access_token_expiring"] is True

    def test_default_snapshot_construction_still_works(self) -> None:
        """Direct constructions (tests, alternate callers) must not break."""
        from mureo.web.setup_state import SetupParts
        from mureo.web.status_collector import StatusSnapshot

        snapshot = StatusSnapshot(
            host="claude-code",
            setup_parts=SetupParts(),
            providers_installed={},
            credentials_present={},
            credentials_oauth={},
            env_vars={},
            legacy_commands_present=False,
            mureo_disable={},
        )
        assert snapshot.as_dict()["meta_token"] == {}
