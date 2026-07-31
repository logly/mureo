"""Amazon refresh-token expiry signalling in the status snapshot (#121).

Amazon expires refresh tokens issued **on/after 2026-07-30** 365 days
after the advertiser consented; tokens issued earlier have no fixed
expiry. mureo can only know an issue date it recorded itself
(``amazon_ads.refresh_token_obtained_at``, written by the paste-code
authorization wizard), so:

- stamp present and parseable → an integer age plus an "expiring" flag
  once it passes the 335-day warning threshold (30 days of headroom);
- stamp absent (legacy setup) or unparseable → unknown age and **no**
  warning. Warning on an unknown age would nag every pre-2026-07-30
  advertiser about an expiry that does not apply to them.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core import clock
from mureo.web.status_collector import _detect_amazon_token

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "server_now", lambda: _NOW)


def _credentials(tmp_path: Path, section: Any) -> Path:
    path = tmp_path / "credentials.json"
    payload = {} if section is None else {"amazon_ads": section}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stamp(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


@pytest.mark.unit
class TestAmazonRefreshTokenAge:
    def test_no_credentials_file_is_unknown_and_not_expiring(
        self, tmp_path: Path
    ) -> None:
        row = _detect_amazon_token(tmp_path / "missing.json")
        assert row == {
            "refresh_token_age_days": None,
            "refresh_token_expiring": False,
        }

    def test_legacy_section_without_a_stamp_is_unknown(self, tmp_path: Path) -> None:
        """A pre-wizard setup has no recorded consent date, and Amazon's
        older refresh tokens have no fixed expiry — say nothing."""
        path = _credentials(tmp_path, {"client_id": "cid", "refresh_token": "Atzr|R"})
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] is None
        assert row["refresh_token_expiring"] is False

    def test_fresh_stamp_reports_its_age_without_warning(self, tmp_path: Path) -> None:
        path = _credentials(
            tmp_path, {"client_id": "cid", "refresh_token_obtained_at": _stamp(10.4)}
        )
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] == 10
        assert row["refresh_token_expiring"] is False

    def test_just_below_the_threshold_does_not_warn(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, {"refresh_token_obtained_at": _stamp(335)})
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] == 335
        assert row["refresh_token_expiring"] is False

    def test_past_the_threshold_warns(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, {"refresh_token_obtained_at": _stamp(336)})
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] == 336
        assert row["refresh_token_expiring"] is True

    def test_beyond_the_full_year_still_warns(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, {"refresh_token_obtained_at": _stamp(400)})
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] == 400
        assert row["refresh_token_expiring"] is True

    def test_unparseable_stamp_is_unknown_not_expiring(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, {"refresh_token_obtained_at": "yesterday-ish"})
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] is None
        assert row["refresh_token_expiring"] is False

    def test_non_string_stamp_is_unknown(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, {"refresh_token_obtained_at": 1234567890})
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] is None

    def test_zulu_suffix_is_accepted(self, tmp_path: Path) -> None:
        """``datetime.fromisoformat`` rejects ``Z`` before 3.11, and a
        hand-edited file may well carry one."""
        stamp = (_NOW - timedelta(days=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = _credentials(tmp_path, {"refresh_token_obtained_at": stamp})
        assert _detect_amazon_token(path)["refresh_token_age_days"] == 12

    def test_future_stamp_clamps_to_zero(self, tmp_path: Path) -> None:
        """Clock skew must not render as a negative age."""
        path = _credentials(tmp_path, {"refresh_token_obtained_at": _stamp(-5)})
        row = _detect_amazon_token(path)
        assert row["refresh_token_age_days"] == 0
        assert row["refresh_token_expiring"] is False

    def test_malformed_section_is_tolerated(self, tmp_path: Path) -> None:
        path = _credentials(tmp_path, "not-a-dict")
        assert _detect_amazon_token(path)["refresh_token_age_days"] is None


@pytest.mark.unit
class TestSnapshotCarriesTheRow:
    def test_collect_status_exposes_amazon_token(self, tmp_path: Path) -> None:
        from mureo.web.status_collector import collect_status

        home = tmp_path / "home"
        (home / ".mureo").mkdir(parents=True)
        (home / ".mureo" / "credentials.json").write_text(
            json.dumps({"amazon_ads": {"refresh_token_obtained_at": _stamp(350)}}),
            encoding="utf-8",
        )
        snapshot = collect_status("claude-code", home=home)
        assert snapshot.amazon_token == {
            "refresh_token_age_days": 350,
            "refresh_token_expiring": True,
        }
        assert snapshot.as_dict()["amazon_token"]["refresh_token_expiring"] is True

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
        assert snapshot.as_dict()["amazon_token"] == {}
