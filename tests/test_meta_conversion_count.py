"""Tests for the canonical Meta conversion counter (#340).

``count_conversions_from_actions`` replaces the old substring scan that
double-counted aggregate+component aliases and swept in custom-conversion
slugs. It counts only the deduped generic action_types.
"""

from __future__ import annotations

import pytest

from mureo.meta_ads._conversion_count import (
    CONVERSION_ACTION_TYPES,
    count_conversions_from_actions,
)


@pytest.mark.unit
def test_counts_generic_conversion_types() -> None:
    actions = [
        {"action_type": "purchase", "value": "5"},
        {"action_type": "lead", "value": "3"},
        {"action_type": "complete_registration", "value": "1"},
        {"action_type": "link_click", "value": "100"},
    ]
    assert count_conversions_from_actions(actions) == 9.0


@pytest.mark.unit
def test_does_not_double_count_aggregate_plus_component() -> None:
    """#340 core fix: the generic ``lead`` aggregate already includes its
    ``offsite_conversion.fb_pixel_lead`` / ``onsite_conversion.lead_grouped``
    components, so the components must NOT be added on top."""
    actions = [
        {"action_type": "lead", "value": "10"},
        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "7"},
        {"action_type": "onsite_conversion.lead_grouped", "value": "3"},
        {"action_type": "purchase", "value": "4"},
        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "4"},
    ]
    # Old substring scan: 10+7+3 + 4+4 = 28. Canonical: 10 (lead) + 4 (purchase).
    assert count_conversions_from_actions(actions) == 14.0


@pytest.mark.unit
def test_ignores_custom_conversion_slug_containing_lead() -> None:
    """#340 false-positive fix: an operator-named custom conversion whose
    slug happens to contain 'lead'/'purchase' must not be counted."""
    actions = [
        {"action_type": "offsite_conversion.custom.my_lead_magnet", "value": "99"},
        {
            "action_type": "offsite_conversion.custom.black_friday_purchase",
            "value": "50",
        },
        {"action_type": "lead", "value": "2"},
    ]
    assert count_conversions_from_actions(actions) == 2.0


@pytest.mark.unit
def test_ignores_view_and_engagement_types() -> None:
    actions = [
        {"action_type": "offsite_conversion.fb_pixel_view_content", "value": "200"},
        {"action_type": "post_engagement", "value": "50"},
        {"action_type": "video_view", "value": "300"},
    ]
    assert count_conversions_from_actions(actions) == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("bad", [None, "invalid", 42, {}, []])
def test_non_list_or_empty_is_zero(bad: object) -> None:
    assert count_conversions_from_actions(bad) == 0.0


@pytest.mark.unit
def test_skips_non_mapping_and_junk_values() -> None:
    actions = [
        "garbage",
        {"action_type": "lead", "value": "not_a_number"},
        {"action_type": "purchase", "value": None},
        {"action_type": "purchase", "value": "5"},
    ]
    assert count_conversions_from_actions(actions) == 5.0


@pytest.mark.unit
def test_canonical_set_is_the_deduped_generics() -> None:
    assert CONVERSION_ACTION_TYPES == frozenset(
        {"lead", "purchase", "complete_registration"}
    )


@pytest.mark.unit
def test_matches_extract_cv_byte_for_byte() -> None:
    """The two live counters must agree — _extract_cv now delegates here."""
    from mureo.meta_ads._analysis import _extract_cv

    rows = [
        {"actions": [{"action_type": "lead", "value": "3"}]},
        {
            "actions": [
                {"action_type": "purchase", "value": "5"},
                {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "5"},
            ]
        },
        {"actions": None},
        {},
    ]
    for row in rows:
        assert _extract_cv(row) == count_conversions_from_actions(row.get("actions"))


@pytest.mark.unit
def test_override_replaces_default_set() -> None:
    """#342 — when an override is given, EXACTLY those action_types count."""
    actions = [
        {"action_type": "lead", "value": "5"},
        {"action_type": "offsite_conversion.custom.123", "value": "9"},
    ]
    # Default: only the generic 'lead'.
    assert count_conversions_from_actions(actions) == 5.0
    # Override: only the custom event.
    assert (
        count_conversions_from_actions(
            actions, conversion_action_types={"offsite_conversion.custom.123"}
        )
        == 9.0
    )


@pytest.mark.unit
def test_empty_override_falls_back_to_default() -> None:
    """An empty/cleared override must NOT zero every conversion — it means
    'use the default set'."""
    actions = [{"action_type": "purchase", "value": "4"}]
    assert count_conversions_from_actions(actions, conversion_action_types=[]) == 4.0
    assert count_conversions_from_actions(actions, conversion_action_types=None) == 4.0


@pytest.mark.unit
def test_override_counts_component_only_account() -> None:
    """A component-only account (no generic aggregate) is counted once the
    operator declares the component as their conversion (#342)."""
    actions = [{"action_type": "offsite_conversion.fb_pixel_lead", "value": "7"}]
    assert count_conversions_from_actions(actions) == 0.0  # default misses it
    assert (
        count_conversions_from_actions(
            actions, conversion_action_types=("offsite_conversion.fb_pixel_lead",)
        )
        == 7.0
    )
