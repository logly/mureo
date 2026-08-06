"""The shared one-account-one-platform-key join (#533 / #534).

This is the single source of the rule for THREE consumers — the STATE.json
write guards, the read-only Reports view that surfaces an existing conflict,
and out-of-tree writers (mureo-agency) that assemble a whole ``StateDocument``
themselves. Reimplementing the join in any of them would let it drift, and
drift here re-creates the double-counting bug, so its public surface is pinned
here.
"""

from __future__ import annotations

import pytest

from mureo.context.models import PlatformState
from mureo.context.platform_accounts import (
    DuplicateAccountEntry,
    account_ids_match,
    duplicate_account_entries,
    normalize_account_id,
    platform_keys_for_account,
)

pytestmark = pytest.mark.unit


def _platforms(**pairs: str) -> dict[str, PlatformState]:
    return {key: PlatformState(account_id=acct) for key, acct in pairs.items()}


# ---------------------------------------------------------------------------
# normalize_account_id / account_ids_match
# ---------------------------------------------------------------------------


def test_normalize_folds_the_act_prefix_and_surrounding_space() -> None:
    assert normalize_account_id("act_123") == "123"
    assert normalize_account_id("123") == "123"
    assert normalize_account_id("  act_123  ") == "123"


def test_normalize_of_an_unknown_id_is_empty() -> None:
    """An empty / whitespace-only id means UNKNOWN, not a value."""
    assert normalize_account_id("") == ""
    assert normalize_account_id("   ") == ""


def test_match_is_tolerant_of_the_act_prefix() -> None:
    assert account_ids_match("act_123", "123")
    assert account_ids_match("123", "act_123")
    assert not account_ids_match("123", "456")


def test_an_unknown_id_never_matches_anything_including_another_unknown() -> None:
    assert not account_ids_match("", "")
    assert not account_ids_match("", "act_1")
    assert not account_ids_match("act_1", "")
    assert not account_ids_match("   ", "   ")


# ---------------------------------------------------------------------------
# platform_keys_for_account
# ---------------------------------------------------------------------------


def test_platform_keys_for_account_finds_every_key_in_document_order() -> None:
    platforms = _platforms(meta_ads="act_1", google_ads="999")
    platforms["plugin:mureo-logly-bridge"] = PlatformState(account_id="1")
    assert platform_keys_for_account(platforms, "act_1") == (
        "meta_ads",
        "plugin:mureo-logly-bridge",
    )


def test_platform_keys_for_account_ignores_unknown_ids() -> None:
    platforms = _platforms(legacy="", meta_ads="act_1")
    assert platform_keys_for_account(platforms, "") == ()
    assert platform_keys_for_account(platforms, "act_1") == ("meta_ads",)


def test_platform_keys_for_account_accepts_none() -> None:
    assert platform_keys_for_account(None, "act_1") == ()


# ---------------------------------------------------------------------------
# duplicate_account_entries
# ---------------------------------------------------------------------------


def test_no_duplicates_yields_nothing() -> None:
    assert duplicate_account_entries(_platforms(meta_ads="act_1", ga="999")) == ()
    assert duplicate_account_entries(None) == ()
    assert duplicate_account_entries({}) == ()


def test_two_keys_for_one_account_are_grouped() -> None:
    platforms = _platforms(meta_ads="act_1")
    platforms["plugin:mureo-logly-bridge"] = PlatformState(account_id="1")
    groups = duplicate_account_entries(platforms)
    assert groups == (
        DuplicateAccountEntry(
            account_id="act_1",
            platform_keys=("meta_ads", "plugin:mureo-logly-bridge"),
        ),
    )
    # The reported account_id is the one AS STORED on the first key, so an
    # operator can find it in the file.
    assert groups[0].account_id == "act_1"


def test_three_keys_for_one_account_form_one_group() -> None:
    platforms = _platforms(a="act_1", b="1", c="act_1")
    groups = duplicate_account_entries(platforms)
    assert len(groups) == 1
    assert groups[0].platform_keys == ("a", "b", "c")


def test_unknown_ids_are_never_grouped_with_each_other() -> None:
    """Two entries that both omitted account_id are not "the same account"."""
    platforms = _platforms(legacy_one="", legacy_two="", blank="   ")
    assert duplicate_account_entries(platforms) == ()


def test_the_group_is_hashable_so_it_can_latch_a_warn_once() -> None:
    platforms = _platforms(meta_ads="act_1", other="act_1")
    (group,) = duplicate_account_entries(platforms)
    assert {group, group} == {group}


# ---------------------------------------------------------------------------
# Hostile input — this module is consumed out-of-tree
# ---------------------------------------------------------------------------


def test_a_non_string_id_is_folded_textually_not_raised_on() -> None:
    """A hand-edited ``"account_id": 12345`` (a JSON number) must not blow up
    a detection helper.

    mureo-agency assembles ``PlatformState`` from loosely-typed sources, so a
    non-``str`` id is a question of when, not if. Coercing textually keeps the
    duplicate DETECTABLE — raising from inside a write guard would surface as
    the wrong exception type from an unrelated call.
    """
    assert normalize_account_id(12345) == "12345"  # type: ignore[arg-type]
    assert account_ids_match(12345, "12345")  # type: ignore[arg-type]
    assert account_ids_match("act_12345", 12345)  # type: ignore[arg-type]


def test_none_is_unknown_not_the_string_none() -> None:
    """``str(None)`` would join every id-less entry under a bogus "None"."""
    assert normalize_account_id(None) == ""  # type: ignore[arg-type]
    assert not account_ids_match(None, None)  # type: ignore[arg-type]


def test_a_non_string_id_in_a_document_is_grouped_not_raised_on() -> None:
    platforms = {
        "meta_ads": PlatformState(account_id=12345),  # type: ignore[arg-type]
        "plugin:x": PlatformState(account_id="12345"),
    }
    (group,) = duplicate_account_entries(platforms)
    assert group.platform_keys == ("meta_ads", "plugin:x")


# ---------------------------------------------------------------------------
# Case sensitivity
# ---------------------------------------------------------------------------


def test_the_act_prefix_folds_case_insensitively() -> None:
    """Only the PREFIX folds — a hand-typed ``ACT_1`` is the same account."""
    assert normalize_account_id("ACT_1") == "1"
    assert normalize_account_id("Act_1") == "1"
    assert account_ids_match("ACT_1", "act_1")
    assert account_ids_match("ACT_1", "1")


def test_the_id_body_stays_case_sensitive() -> None:
    """Deliberate: real ad account ids are numeric, but a plugin platform may
    use a case-significant alphanumeric id, and folding the whole string would
    join two genuinely different accounts."""
    assert normalize_account_id("AbC") == "AbC"
    assert not account_ids_match("AbC", "abc")
