"""Tests for the canonical report-flag vocabulary and normalization.

A daily / weekly / goal report's ``flags`` list drives the coloured chips on
the read-only Reports dashboard. Historically each flag was a free-form
snake_case string with its detail baked in
(``adspot_4311492_invalid_traffic_spike_115740yen_0cv_ctr4.66pct``), which the
frontend could only render verbatim — cramming detail into a tag and never
localizing it. :func:`normalize_flags` lets a skill author a STRUCTURED flag
(``{code, severity, params}``) drawn from a fixed vocabulary so the chip shows a
coarse, localizable label while the detail moves into ``params`` (rendered on
drill-down) and the narrative.

Backward compatibility is a hard requirement: a bare string flag is passed
through untouched so existing STATE.json / skills keep working.
"""

from __future__ import annotations

import pytest

from mureo.analysis.report_flags import FLAG_SEVERITY, SEVERITIES, normalize_flags

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Vocabulary contract
# ---------------------------------------------------------------------------


def test_severities_are_the_four_buckets() -> None:
    """The severity axis is exactly action / watch / info / positive — the
    four visual buckets the dashboard colours (danger / warn / neutral /
    success). Nothing else is a valid severity."""
    assert set(SEVERITIES) == {"action", "watch", "info", "positive"}


def test_vocabulary_covers_the_v1_codes() -> None:
    """The v1 vocabulary includes the newly-introduced codes plus the ones the
    dashboard already understood, each mapped to a default severity that is a
    member of :data:`SEVERITIES`."""
    expected = {
        "cpa_over_target": "watch",
        "cpa_under_target": "positive",
        "cv_below_target": "watch",
        "cv_above_target": "positive",
        "goals_met": "positive",
        "spend_spike": "watch",
        "cpa_spike": "watch",
        "invalid_traffic_suspected": "action",
        "zero_cv_adspots": "watch",
        "budget_overspend": "action",
        "budget_drift": "watch",
        "tracking_suspect": "action",
        "zero_conversions": "action",
        "supply_tools_unconfigured": "info",
        "anomaly_baseline_insufficient": "info",
        "pending_observations": "info",
        "search_console_no_property": "info",
        "ga4_not_configured": "info",
    }
    assert expected == FLAG_SEVERITY
    assert set(FLAG_SEVERITY.values()) <= set(SEVERITIES)
    # ``custom`` is the escape hatch — deliberately NOT a canonical code (it
    # requires an author-supplied label + severity instead of a default).
    assert "custom" not in FLAG_SEVERITY


# ---------------------------------------------------------------------------
# None / list shape
# ---------------------------------------------------------------------------


def test_none_passes_through() -> None:
    assert normalize_flags(None) is None


def test_empty_list_is_empty_list() -> None:
    assert normalize_flags([]) == []


def test_non_list_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_flags({"code": "goals_met"})  # a bare object, not a list
    with pytest.raises(ValueError):
        normalize_flags("goals_met")


# ---------------------------------------------------------------------------
# Legacy string flags (backward compatibility)
# ---------------------------------------------------------------------------


def test_legacy_string_flag_passes_through_unchanged() -> None:
    """A bare snake_case string is preserved verbatim — the frontend still
    humanizes it. This is what keeps existing STATE.json / skills working."""
    assert normalize_flags(["cpa_over_target"]) == ["cpa_over_target"]
    # Even an unknown/detail-laden legacy string is preserved (not rejected):
    raw = "adspot_4311492_invalid_traffic_spike_115740yen_0cv_ctr4.66pct"
    assert normalize_flags([raw]) == [raw]


def test_mixed_legacy_and_structured_flags() -> None:
    out = normalize_flags(["cpa_over_target", {"code": "goals_met"}])
    assert out[0] == "cpa_over_target"
    assert out[1] == {"code": "goals_met", "severity": "positive"}


# ---------------------------------------------------------------------------
# Structured object flags — canonical codes
# ---------------------------------------------------------------------------


def test_known_code_fills_default_severity() -> None:
    """A known code with no explicit severity is stamped with the vocabulary's
    default severity for that code."""
    out = normalize_flags([{"code": "invalid_traffic_suspected"}])
    assert out == [{"code": "invalid_traffic_suspected", "severity": "action"}]


def test_known_code_keeps_explicit_severity_override() -> None:
    """An author may override the default severity with any valid one."""
    out = normalize_flags([{"code": "budget_drift", "severity": "action"}])
    assert out == [{"code": "budget_drift", "severity": "action"}]


def test_params_object_is_preserved() -> None:
    """``params`` carries the detail (adspot / yen / ctr) rendered on
    drill-down, and is preserved as-is."""
    params = {"adspot": "4311492", "spend": 115740, "cv": 0, "ctr": 0.0466}
    out = normalize_flags([{"code": "invalid_traffic_suspected", "params": params}])
    assert out[0]["params"] == params
    assert out[0]["severity"] == "action"


def test_author_extra_fields_are_preserved() -> None:
    """Unknown author fields survive normalization (trusted-writer content);
    only code / severity / params are validated."""
    out = normalize_flags([{"code": "goals_met", "note": "both goals on trailing 30d"}])
    assert out[0]["note"] == "both goals on trailing 30d"


def test_input_is_not_mutated() -> None:
    """Normalization returns new objects and never mutates the caller's dict
    (immutability — no hidden side effects)."""
    original = {"code": "goals_met"}
    normalize_flags([original])
    assert original == {"code": "goals_met"}  # no severity injected in place


def test_unknown_code_is_rejected() -> None:
    """A non-``custom`` code outside the vocabulary is an error — this is what
    keeps the vocabulary honest and forces authors to either use a canonical
    code or the explicit ``custom`` escape hatch."""
    with pytest.raises(ValueError):
        normalize_flags([{"code": "totally_made_up"}])


def test_missing_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_flags([{"severity": "watch"}])
    with pytest.raises(ValueError):
        normalize_flags([{"code": ""}])


def test_invalid_severity_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_flags([{"code": "goals_met", "severity": "purple"}])


def test_non_dict_params_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_flags([{"code": "goals_met", "params": "not-an-object"}])


def test_flag_that_is_neither_string_nor_object_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_flags([123])
    with pytest.raises(ValueError):
        normalize_flags([None])


# ---------------------------------------------------------------------------
# Structured object flags — the ``custom`` escape hatch
# ---------------------------------------------------------------------------


def test_custom_flag_with_string_label() -> None:
    out = normalize_flags(
        [{"code": "custom", "severity": "watch", "label": "Novel finding"}]
    )
    assert out == [{"code": "custom", "severity": "watch", "label": "Novel finding"}]


def test_custom_flag_with_localized_label_map() -> None:
    out = normalize_flags(
        [
            {
                "code": "custom",
                "severity": "info",
                "label": {"ja": "新種の所見", "en": "Novel finding"},
            }
        ]
    )
    assert out[0]["label"] == {"ja": "新種の所見", "en": "Novel finding"}


def test_custom_flag_requires_label() -> None:
    with pytest.raises(ValueError):
        normalize_flags([{"code": "custom", "severity": "watch"}])


def test_custom_flag_requires_severity() -> None:
    """``custom`` has no default severity, so it must be supplied."""
    with pytest.raises(ValueError):
        normalize_flags([{"code": "custom", "label": "x"}])


def test_custom_flag_rejects_empty_or_bad_label() -> None:
    with pytest.raises(ValueError):
        normalize_flags([{"code": "custom", "severity": "watch", "label": "  "}])
    with pytest.raises(ValueError):
        normalize_flags([{"code": "custom", "severity": "watch", "label": 42}])
    with pytest.raises(ValueError):
        normalize_flags([{"code": "custom", "severity": "watch", "label": {"ja": 1}}])
