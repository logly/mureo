"""Static-content guards for the Meta token lifetime surfaces (#726).

Two UI contracts, both grepped out of the bundled assets the way
``tests/test_web_assets_meta_token_card.py`` does (no DOM harness runs this
code):

* the paste card gains OPTIONAL ``app_id`` / ``app_secret`` fields — the
  pair Meta requires to exchange an expiring system-user token
  (``grant_type=fb_exchange_token`` + ``set_token_expires_in_60_days``) —
  and reports the expiry the save response carries;
* the dashboard credential row shows the days remaining and warns inside the
  threshold, driven by the status snapshot's ``meta_token`` row.

The 4-step Business Manager guide is corrected too: the "Never expire"
option it told operators to pick is not what Business settings offers, which
is exactly how installs ended up with an unmonitored 60-day token.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _js() -> str:
    return "\n".join(_read(n) for n in ("auth_wizards_meta.js", "auth_wizards.js"))


_NEW_KEYS = (
    "wizard.auth.meta_token_app_id_label",
    "wizard.auth.meta_token_app_secret_label",
    "wizard.auth.meta_token_app_hint",
    "wizard.auth.meta_token_expires_at",
    "wizard.auth.meta_token_expiry_unknown",
    "wizard.auth.meta_token_warn_inspect_failed",
    "wizard.auth.meta_token_warn_auto_refresh_unavailable",
    "dashboard.meta_token_expires_in",
    "dashboard.meta_token_expired",
)


def test_new_keys_are_referenced_by_the_assets() -> None:
    js = _js()
    for key in _NEW_KEYS:
        assert key in js, f"{key} is defined but never rendered"


def test_new_keys_exist_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    en, ja = data["en"], data["ja"]
    for key in _NEW_KEYS:
        assert key in en and en[key].strip(), f"{key} missing/empty in en"
        assert key in ja and ja[key].strip(), f"{key} missing/empty in ja"
        assert en[key] != ja[key], f"{key} not localized (en == ja)"


class TestOptionalAppCredentialFields:
    def test_card_posts_app_id_and_app_secret(self) -> None:
        js = _js()
        assert "app_id:" in js
        assert "app_secret:" in js

    def test_app_secret_is_password_typed(self) -> None:
        """Same treatment as the token: a secret is never a plain text box."""
        js = _js()
        start = js.index("appSecretInput")
        window = js[start : start + 400]
        assert 'type = "password"' in window


class TestExpiryIsShownOnSave:
    def test_card_reads_the_expiry_off_the_response(self) -> None:
        js = _js()
        assert "token_expires_at" in js

    def test_card_surfaces_the_response_warnings(self) -> None:
        js = _js()
        assert "warnings" in js
        assert "token_inspect_failed" in js
        assert "auto_refresh_unavailable" in js


class TestDashboardCountdown:
    def test_hint_reads_the_new_status_fields(self) -> None:
        js = _js()
        assert "access_token_expiry_warning" in js
        assert "access_token_expires_in_days" in js

    def test_expired_token_gets_its_own_line(self) -> None:
        """ "expires in -3 days" is not a countdown; a token already dead
        needs the past tense, not a negative number."""
        js = _js()
        assert "dashboard.meta_token_expired" in js


class TestGuideNoLongerPromisesANeverExpiringToken:
    def test_english_guide_does_not_say_never_expire(self) -> None:
        en = json.loads(_read("i18n.json"))["en"]["wizard.auth.meta_token_guide_3"]
        assert "never expire" not in en.lower()
        assert "60" in en

    def test_japanese_guide_does_not_say_never_expire(self) -> None:
        ja = json.loads(_read("i18n.json"))["ja"]["wizard.auth.meta_token_guide_3"]
        assert "有効期限なし" not in ja
        assert "60" in ja

    def test_card_intro_does_not_call_the_token_never_expiring(self) -> None:
        """The card's own prose must not restate the assumption the whole
        issue is about."""
        js = _js()
        assert "never-expiring" not in js.lower()


@pytest.mark.parametrize("locale", ["en", "ja"])
def test_expiry_strings_interpolate_days_and_date(locale: str) -> None:
    data = json.loads(_read("i18n.json"))[locale]
    for key in ("wizard.auth.meta_token_expires_at", "dashboard.meta_token_expires_in"):
        assert "{days}" in data[key], f"{key} ({locale}) must show the days left"
        assert "{date}" in data[key], f"{key} ({locale}) must show the expiry date"
