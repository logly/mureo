"""Meta access-token expiry signalling in the status snapshot (#579).

Meta's long-lived user tokens live ~60 days from issue, and mureo hands
them back to Graph's ``fb_exchange_token`` endpoint at 53 days
(:data:`mureo.auth._TOKEN_REFRESH_THRESHOLD_DAYS`) — but only when
``app_id`` **and** ``app_secret`` are stored alongside the token. So:

- token stored WITH the app pair → an integer age plus an "expiring"
  flag once it passes the refresh threshold, because a token still that
  old on disk is one the automatic refresh has not renewed;
- token stored WITHOUT the app pair → mureo cannot exchange it, so its
  *age* is never a warning (``auth._should_refresh`` short-circuits on
  exactly this condition). Note the save path stamps
  ``token_obtained_at`` on these too, so "has a stamp" alone says
  nothing about expiry;
- no stamp at all (a hand-entered token, #578) → unknown age and **no**
  warning. A missing stamp means "off the refresh clock", never
  "infinitely old".

#726 adds the other half. A Business Manager system-user token does NOT
live forever — it is minted with a 60-day life — so the paste route now
asks Graph ``debug_token`` when it dies and stores the answer as
``token_expires_at``. That date, when present, drives a second and
independent signal: the days remaining, and a warning below
:data:`META_ACCESS_TOKEN_EXPIRY_WARN_DAYS`. It needs no app pair, because
"this credential dies on Tuesday" is worth saying whether or not mureo
can do anything about it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core import clock
from mureo.web.status_collector import (
    META_ACCESS_TOKEN_EXPIRY_WARN_DAYS,
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


def _expiry(days_ahead: float) -> str:
    return (_NOW + timedelta(days=days_ahead)).isoformat(timespec="seconds")


#: The row a credentials file with nothing knowable produces.
_UNKNOWN_ROW = {
    "access_token_age_days": None,
    "access_token_never_expires": False,
    "access_token_expiring": False,
    "access_token_expires_at": None,
    "access_token_expires_in_days": None,
    "access_token_expiry_warning": False,
}


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
        assert row == _UNKNOWN_ROW

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
        assert _detect_meta_token(path) == _UNKNOWN_ROW


@pytest.mark.unit
class TestStoredExpiry:
    """#726 — the token's own ``expires_at``, independent of its age."""

    def test_no_stored_expiry_reports_unknown(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, _app_backed(10))
        row = _detect_meta_token(path)
        assert row["access_token_expires_at"] is None
        assert row["access_token_expires_in_days"] is None
        assert row["access_token_expiry_warning"] is False

    def test_distant_expiry_reports_days_without_warning(self, tmp_path: Path) -> None:
        section = _app_backed(2)
        section["token_expires_at"] = _expiry(45)
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expires_in_days"] == 45
        assert row["access_token_expires_at"] == _expiry(45)
        assert row["access_token_expiry_warning"] is False

    def test_exactly_at_the_threshold_does_not_warn(self, tmp_path: Path) -> None:
        section = _app_backed(2)
        section["token_expires_at"] = _expiry(META_ACCESS_TOKEN_EXPIRY_WARN_DAYS)
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expires_in_days"] == META_ACCESS_TOKEN_EXPIRY_WARN_DAYS
        assert row["access_token_expiry_warning"] is False

    def test_inside_the_threshold_warns(self, tmp_path: Path) -> None:
        section = _app_backed(2)
        section["token_expires_at"] = _expiry(META_ACCESS_TOKEN_EXPIRY_WARN_DAYS - 1)
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expiry_warning"] is True

    def test_an_expired_token_reports_negative_days_and_warns(
        self, tmp_path: Path
    ) -> None:
        """Clamping to zero here would render "0 days left" for a credential
        that died a week ago — the one state that is not a countdown."""
        section = _app_backed(70)
        section["token_expires_at"] = _expiry(-7)
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expires_in_days"] == -7
        assert row["access_token_expiry_warning"] is True

    def test_expiry_warning_needs_no_app_pair(self, tmp_path: Path) -> None:
        """A pasted token with no app credentials is exactly the case that
        cannot be auto-extended, so it is the case that most needs the
        warning."""
        path = _credentials(
            tmp_path,
            {
                "access_token": "EAA-token",
                "token_obtained_at": _stamp(50),
                "token_expires_at": _expiry(3),
            },
        )
        row = _detect_meta_token(path)
        assert row["access_token_expiry_warning"] is True
        assert row["access_token_expiring"] is False

    @pytest.mark.parametrize("raw", ["", "last tuesday", 1234567890, None])
    def test_unparseable_expiry_is_unknown_not_a_warning(
        self, tmp_path: Path, raw: Any
    ) -> None:
        section = _app_backed(2)
        section["token_expires_at"] = raw
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expires_at"] is None
        assert row["access_token_expires_in_days"] is None
        assert row["access_token_expiry_warning"] is False

    def test_zulu_suffix_is_accepted(self, tmp_path: Path) -> None:
        section = _app_backed(2)
        section["token_expires_at"] = (_NOW + timedelta(days=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expires_in_days"] == 5
        assert row["access_token_expiry_warning"] is True


@pytest.mark.unit
class TestPermanentTokenSilencesBothWarnings:
    """#740: Graph reports a permanent token as ``expires_at: 0`` and the
    paste route records that as ``token_never_expires``. A token with no end
    date cannot be expiring — and mureo will not exchange it either, so the
    age clock is measuring a life that does not run out."""

    def test_the_row_reports_the_verdict(self, tmp_path: Path) -> None:
        section = _app_backed(2)
        section["token_never_expires"] = True
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_never_expires"] is True

    def test_absent_verdict_reads_as_false(self, tmp_path: Path) -> None:
        row = _detect_meta_token(_credentials(tmp_path, _app_backed(2)))
        assert row["access_token_never_expires"] is False

    @pytest.mark.parametrize("raw", ["false", "true", "yes", 1, 0, []])
    def test_a_non_boolean_verdict_is_refused(self, tmp_path: Path, raw: Any) -> None:
        """Same boundary as the loader: only a JSON boolean is a verdict.

        ``bool("false")`` is ``True``, so a hand-edited or third-party value
        that reads as "no" would otherwise have silenced the expiry warning
        on the dashboard as well as disabling the refresh."""

        section = _app_backed(2)
        section["token_never_expires"] = raw
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_never_expires"] is False

    def test_a_refused_verdict_does_not_suppress_the_expiry_warning(
        self, tmp_path: Path
    ) -> None:
        """The whole point of refusing it: the warning that a real "never"
        silences must come back for a value mureo does not trust."""

        section = _app_backed(2)
        section["token_never_expires"] = "false"
        section["token_expires_at"] = _expiry(1)
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expiry_warning"] is True

    def test_age_past_the_threshold_is_not_expiring(self, tmp_path: Path) -> None:
        """The app pair is stored and the token is far past the refresh
        threshold, which is exactly the state that used to nag — and, worse,
        used to fire the exchange."""

        section = _app_backed(META_ACCESS_TOKEN_WARN_DAYS + 30)
        section["token_never_expires"] = True
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expiring"] is False
        assert row["access_token_never_expires"] is True

    def test_a_stale_stored_expiry_does_not_warn(self, tmp_path: Path) -> None:
        """Contradictory records: the flag is Graph's own verdict, so it
        wins over a date left behind by an earlier token."""

        section = _app_backed(2)
        section["token_never_expires"] = True
        section["token_expires_at"] = _expiry(1)
        row = _detect_meta_token(_credentials(tmp_path, section))
        assert row["access_token_expiry_warning"] is False
        # The date is still echoed — the row states facts; it just does not
        # raise them as a warning.
        assert row["access_token_expires_in_days"] == 1


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
            "access_token_never_expires": False,
            "access_token_expiring": True,
            "access_token_expires_at": None,
            "access_token_expires_in_days": None,
            "access_token_expiry_warning": False,
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
