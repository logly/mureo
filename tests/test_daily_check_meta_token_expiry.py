"""/daily-check reports a Meta token that is about to expire (#726).

An expired token already surfaces as ``auth_cause: token_invalid`` (#580) —
but that is the report AFTER the outage. A Business Manager system-user
token is minted with a 60-day life, mureo now records when it dies, and the
daily run is where a countdown belongs: the operator reads it every morning,
and renewing a Meta token is not something that can be done in the five
minutes after a report fails.

Pinned in BOTH the packaged copy and the repo-root mirror, kept
byte-identical.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills" / "daily-check" / "SKILL.md"
_MIRROR = _ROOT / "skills" / "daily-check" / "SKILL.md"


def _body() -> str:
    return _PACKAGED.read_text(encoding="utf-8")


def test_copies_are_byte_identical() -> None:
    assert _PACKAGED.read_bytes() == _MIRROR.read_bytes()


def test_names_the_threshold() -> None:
    body = _body()
    assert "token_expires_at" in body
    assert "14 days" in body


def test_the_skill_and_the_status_card_count_the_same_days() -> None:
    """The prompt hard-codes the number — it is prose, not code — so it is
    pinned to the collector's constant here. A threshold moved in one place
    and not the other would have the dashboard warning on a day the morning
    report calls fine."""

    from mureo.web.status_collector import META_ACCESS_TOKEN_EXPIRY_WARN_DAYS

    assert META_ACCESS_TOKEN_EXPIRY_WARN_DAYS == 14
    assert f"{META_ACCESS_TOKEN_EXPIRY_WARN_DAYS} days" in _body()


def test_classifies_the_finding() -> None:
    """A countdown with no verdict attached is a note nobody acts on."""
    lines = [ln for ln in _body().splitlines() if "token_expires_at" in ln]
    assert lines, "no Meta token-expiry step in the skill"
    joined = " ".join(lines).lower()
    assert "watch" in joined
    assert "action needed" in joined


def test_says_how_to_renew() -> None:
    lines = " ".join(ln for ln in _body().splitlines() if "token_expires_at" in ln)
    lowered = lines.lower()
    assert "system-user token" in lowered
    assert "app id" in lowered or "app_id" in lowered
