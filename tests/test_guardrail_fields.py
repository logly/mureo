"""The Guardrails field catalog and its labels (#843).

:mod:`mureo.policy.guardrail_fields` is the one table the configure UI and
its API describe ``## Guardrails`` from. Two drifts are pinned here, both
of which would ship silently otherwise:

- a field added to :class:`~mureo.policy.strategy_gate.Guardrails` without
  a catalog row (the card would not offer it, the API would not report it);
- a catalog row without an operator-readable label and description in both
  locales of ``i18n.json``.
"""

from __future__ import annotations

import dataclasses
import json
from importlib import resources
from typing import Any

import pytest

from mureo.policy.guardrail_fields import (
    GUARDRAIL_FIELDS,
    GUARDRAIL_KINDS,
    GuardrailField,
    guardrail_field,
)
from mureo.policy.strategy_gate import Guardrails


def _i18n() -> dict[str, Any]:
    ref = resources.files("mureo") / "_data" / "web" / "i18n.json"
    with resources.as_file(ref) as path:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.mark.unit
class TestCatalogMatchesTheDataclass:
    def test_every_dataclass_field_has_exactly_one_row(self) -> None:
        dataclass_keys = [f.name for f in dataclasses.fields(Guardrails)]
        catalog_keys = [f.key for f in GUARDRAIL_FIELDS]
        assert sorted(catalog_keys) == sorted(dataclass_keys)
        assert len(catalog_keys) == len(set(catalog_keys))

    def test_the_catalog_follows_the_dataclass_order(self) -> None:
        """One order everywhere: the card lists rules the way the gate's
        own definition does, so a reader can map one onto the other."""
        dataclass_keys = [f.name for f in dataclasses.fields(Guardrails)]
        assert [f.key for f in GUARDRAIL_FIELDS] == dataclass_keys

    def test_every_kind_is_a_known_kind(self) -> None:
        assert set(GUARDRAIL_KINDS) == {
            "money",
            "percent",
            "integer_days",
            "bool",
            "currency",
            "string_set",
            "metric_set",
        }
        for item in GUARDRAIL_FIELDS:
            assert item.kind in GUARDRAIL_KINDS, item.key

    def test_kinds_agree_with_the_dataclass_types(self) -> None:
        defaults = Guardrails()
        for item in GUARDRAIL_FIELDS:
            default = getattr(defaults, item.key)
            if item.kind == "bool":
                assert default is False, item.key
            elif item.kind in ("string_set", "metric_set"):
                assert len(default) == 0, item.key
            else:
                assert default is None, item.key

    def test_the_label_key_is_derived_from_the_field_key(self) -> None:
        for item in GUARDRAIL_FIELDS:
            assert item.label_key == f"guardrails.field.{item.key}.label"
            assert item.desc_key == f"guardrails.field.{item.key}.desc"

    def test_rows_are_immutable(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            GUARDRAIL_FIELDS[0].key = "other"  # type: ignore[misc]

    def test_lookup_by_key(self) -> None:
        found = guardrail_field("max_total_daily_budget")
        assert isinstance(found, GuardrailField)
        assert found.kind == "money"
        assert guardrail_field("no_such_rule") is None


@pytest.mark.unit
class TestRanges:
    def test_money_is_never_negative_and_has_a_sanity_ceiling(self) -> None:
        """No account's cap is a trillion units; past that it is a typo."""
        for item in GUARDRAIL_FIELDS:
            if item.kind == "money":
                assert item.minimum == 0, item.key
                assert item.maximum == 1e12, item.key

    def test_delivery_shares_are_percentages_of_a_whole(self) -> None:
        for key in (
            "max_delivery_share_removed_pct",
            "max_cumulative_delivery_share_removed_pct",
        ):
            item = guardrail_field(key)
            assert item is not None
            assert (item.kind, item.minimum, item.maximum) == ("percent", 0, 100)

    def test_a_budget_increase_may_exceed_one_hundred_percent(self) -> None:
        item = guardrail_field("max_daily_budget_increase_pct")
        assert item is not None
        assert (item.kind, item.minimum, item.maximum) == ("percent", 0, 1e6)

    def test_the_window_matches_the_rule_resolver_clamp(self) -> None:
        """The resolver clamps out-of-range windows silently; the editor
        refuses them instead, so the two bounds must be the same numbers."""
        from mureo.analysis.exclusion_impact.rules import MAX_WINDOW_DAYS

        item = guardrail_field("exclusion_impact_window_days")
        assert item is not None
        assert item.kind == "integer_days"
        assert (item.minimum, item.maximum) == (1, MAX_WINDOW_DAYS)

    def test_units(self) -> None:
        for item in GUARDRAIL_FIELDS:
            expected = {
                "money": "currency",
                "percent": "%",
                "integer_days": "days",
            }.get(item.kind)
            assert item.unit == expected, item.key


@pytest.mark.unit
class TestLabelsInBothLocales:
    @pytest.mark.parametrize("locale", ["en", "ja"])
    def test_every_field_has_a_label_and_a_description(self, locale: str) -> None:
        catalog = _i18n()[locale]
        for item in GUARDRAIL_FIELDS:
            for key in (item.label_key, item.desc_key):
                assert key in catalog, f"{key} missing from i18n.json {locale!r}"
                value = catalog[key]
                assert isinstance(value, str)
                assert value.strip() != ""
                assert value != key

    def test_japanese_is_really_japanese(self) -> None:
        data = _i18n()
        for item in GUARDRAIL_FIELDS:
            assert data["en"][item.label_key] != data["ja"][item.label_key]
            assert data["en"][item.desc_key] != data["ja"][item.desc_key]

    def test_the_field_names_are_not_the_raw_keys(self) -> None:
        """The whole point: an operator reads a name, not an identifier."""
        data = _i18n()
        for locale in ("en", "ja"):
            for item in GUARDRAIL_FIELDS:
                label = data[locale][item.label_key]
                assert label != item.key
                assert "_" not in label, f"{item.key}: {label!r} reads as an identifier"

    def test_descriptions_are_one_sentence(self) -> None:
        data = _i18n()
        for item in GUARDRAIL_FIELDS:
            en = data["en"][item.desc_key]
            ja = data["ja"][item.desc_key]
            assert en.endswith(".") and ". " not in en, item.key
            assert ja.endswith("。") and ja.count("。") == 1, item.key

    def test_the_named_examples(self) -> None:
        data = _i18n()
        assert (
            data["en"]["guardrails.field.max_daily_budget_increase_pct.label"]
            == "Max daily budget increase per change (%)"
        )
        assert (
            data["ja"]["guardrails.field.max_daily_budget_increase_pct.label"]
            == "1 回の変更で許す日予算の増加率(%)"
        )
        assert (
            data["ja"][
                "guardrails.field.max_cumulative_delivery_share_removed_pct.label"
            ]
            == "除外で削ってよい配信量の累計上限(%)"
        )
