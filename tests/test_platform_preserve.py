"""Hand-authored platform / campaign / ad entries are kept, never refused (#881).

The same failure #859 removed for ``action_log``, one level over: an entry
written straight into STATE.json — not through the upsert / metrics tools —
may lack a required key (``campaign_id``, ``ad_id``, ``account_id``), carry
keys mureo does not know, or hold a value the model cannot represent (a
``campaigns`` that is a string). Such an entry used to raise inside the strict
read every writer performs, so ONE hand-authored entry blocked every write of
the whole document; and a whole-document write dropped the unknown keys of
every entry it re-emitted.

The contract pinned here:

- a platform / campaign / ad entry that is an object is read with its missing
  or non-string required keys as ``""`` and keeps its on-disk dict as ``raw``;
  it is written back in its on-disk shape (key order, unknown keys, absent
  required keys stay absent) with mureo's own changes on top;
- a ``campaigns`` / ``ads`` value that is not a list, or holds a non-object
  entry, is written back verbatim — the enclosing entry keeps it in ``raw``
  and its parsed tuple holds the object entries — unless a mureo writer
  replaces that list;
- both read modes build the same document;
- an id read as ``""`` is unknown: it matches no upsert and joins no account.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from mureo.context._platform_codec import parse_platform, platform_state_to_dict
from mureo.context.models import ActionLogEntry, AdState, CampaignSnapshot
from mureo.context.platform_accounts import duplicate_account_entries
from mureo.context.platform_guards import warn_on_duplicate_accounts
from mureo.context.settings_store import set_ops_history_enabled
from mureo.context.state import (
    append_action_log,
    read_state_file,
    upsert_campaign,
    write_state_file,
)
from mureo.context.state_codec import parse_state, render_state

# The two shapes observed in real workspaces (#881). Values are synthetic.
_STRING_CAMPAIGNS: dict[str, Any] = {
    "account_id": "111-222-3333",
    "campaigns": "see the weekly sheet",
    "totals": {"spend": 1200.0},
}
_HAND_CAMPAIGN: dict[str, Any] = {
    "campaign_id": "72804",
    "name": "E2E",
    "status": "paused",
    "budget_note": "raised on Monday",
}
_NO_ACCOUNT_ID: dict[str, Any] = {
    "campaigns": [_HAND_CAMPAIGN],
    "metrics_period": "LAST_30_DAYS",
    "owner": "ops team",
}


def _document() -> dict[str, Any]:
    """A document in the codec's own key order, so it round-trips as-is."""
    return {
        "version": "2",
        "last_synced_at": None,
        "customer_id": None,
        "campaigns": [],
        "platforms": {
            "google_ads": _STRING_CAMPAIGNS,
            "logly_ads": _NO_ACCOUNT_ID,
        },
        "action_log": [],
    }


def _text(data: dict[str, Any]) -> str:
    """Formatted exactly as ``render_state`` formats a document."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _with_platforms(platforms: dict[str, Any]) -> str:
    data = _document()
    data["platforms"] = platforms
    return _text(data)


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(_text(_document()), encoding="utf-8")
    return path


def _on_disk(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _assert_observed_shapes_kept(path: Path) -> None:
    platforms = _on_disk(path)["platforms"]
    assert platforms["google_ads"] == _STRING_CAMPAIGNS
    assert platforms["google_ads"]["campaigns"] == "see the weekly sheet"
    assert platforms["logly_ads"] == _NO_ACCOUNT_ID
    assert "account_id" not in platforms["logly_ads"]
    assert list(platforms["logly_ads"]) == list(_NO_ACCOUNT_ID), "key order changed"
    assert list(platforms["logly_ads"]["campaigns"][0]) == list(_HAND_CAMPAIGN)


def _campaign(**extra: Any) -> dict[str, Any]:
    """A conforming campaign in the codec's own shape, plus ``extra``."""
    return {
        "campaign_id": "c1",
        "campaign_name": "A",
        "status": "ENABLED",
        "bidding_strategy_type": None,
        "bidding_details": None,
        "daily_budget": None,
        "device_targeting": None,
        "campaign_goal": None,
        "notes": None,
        **extra,
    }


#: Every nonconforming shape, one platform each. Round-trips byte-identically.
_SHAPES: dict[str, dict[str, Any]] = {
    "string-campaigns": _STRING_CAMPAIGNS,
    "null-campaigns": {"account_id": "1", "campaigns": None},
    "object-campaigns": {"account_id": "2", "campaigns": {"c1": "x"}},
    "no-account_id": _NO_ACCOUNT_ID,
    "unknown-platform-key": {"account_id": "3", "campaigns": [], "region": "JP"},
    "mixed-campaigns": {
        "account_id": "4",
        "campaigns": [_campaign(), "paused the rest by hand"],
    },
    "campaign-null-and-numeric-ids": {
        "account_id": "5",
        "campaigns": [
            {"campaign_id": None, "campaign_name": "A", "status": "ENABLED"},
            {"campaign_id": 123, "campaign_name": 456, "status": True},
        ],
    },
    "campaign-string-ads": {
        "account_id": "6",
        "campaigns": [_campaign(ads="three RSAs")],
    },
    "campaign-mixed-ads": {
        "account_id": "7",
        "campaigns": [_campaign(ads=[{"ad_id": "a1"}, 42])],
    },
    "ad-without-ad_id": {
        "account_id": "8",
        "campaigns": [
            _campaign(ads=[{"name": "no id", "headline": "Spring"}, {"ad_id": 9}])
        ],
    },
    "campaign-and-ad-unknown-keys-only": {
        "account_id": "10",
        "campaigns": [
            _campaign(
                ads=[{"ad_id": "a1", "headline": "Spring"}],
                owner="ops team",
            )
        ],
    },
    "no-campaigns-key": {"account_id": "11", "owner": "ops team"},
    "string-device_targeting": {
        "account_id": "9",
        "campaigns": [_campaign(device_targeting="mobile only")],
    },
}


@pytest.mark.unit
class TestObservedShapesDoNotBlockWrites:
    def test_strict_read_succeeds(self, state_file: Path) -> None:
        doc = read_state_file(state_file, strict=True)

        assert doc.platforms is not None
        assert doc.platforms["google_ads"].campaigns == ()
        # ``raw`` keeps the key order, the values mureo cannot hold and the
        # unknown keys; a value the fields carry is only a placeholder.
        assert doc.platforms["google_ads"].raw == {
            "account_id": "111-222-3333",
            "campaigns": "see the weekly sheet",
            "totals": None,
        }
        assert doc.platforms["logly_ads"].account_id == ""
        assert doc.platforms["logly_ads"].raw == {
            "campaigns": [],
            "metrics_period": None,
            "owner": "ops team",
        }
        campaign = doc.platforms["logly_ads"].campaigns[0]
        assert (campaign.campaign_id, campaign.campaign_name, campaign.status) == (
            "72804",
            "",
            "paused",
        )
        assert campaign.raw == _HAND_CAMPAIGN

    def test_set_ops_history_enabled(self, state_file: Path) -> None:
        set_ops_history_enabled(state_file, True)

        _assert_observed_shapes_kept(state_file)
        settings = read_state_file(state_file).settings
        assert settings is not None and settings.ops_history_enabled is True

    def test_append_action_log(self, state_file: Path) -> None:
        append_action_log(
            state_file,
            ActionLogEntry(
                timestamp="2026-10-21T09:00:00+09:00",
                action="google_ads_budget_update",
                platform="google_ads",
            ),
        )

        _assert_observed_shapes_kept(state_file)
        assert _on_disk(state_file)["action_log"][-1]["action"] == (
            "google_ads_budget_update"
        )

    def test_upsert_into_a_different_platform(self, state_file: Path) -> None:
        upsert_campaign(
            state_file,
            CampaignSnapshot(campaign_id="M-1", campaign_name="Meta", status="ACTIVE"),
            platform="meta_ads",
            account_id="act_999",
        )

        _assert_observed_shapes_kept(state_file)
        meta = _on_disk(state_file)["platforms"]["meta_ads"]
        assert [c["campaign_id"] for c in meta["campaigns"]] == ["M-1"]


@pytest.mark.unit
class TestRoundTrip:
    @pytest.mark.parametrize("shape", list(_SHAPES))
    def test_each_shape_renders_as_found(self, shape: str) -> None:
        text = _with_platforms({"p": _SHAPES[shape]})

        assert json.loads(render_state(parse_state(text))) == json.loads(text)
        assert render_state(parse_state(text)) == text

    @pytest.mark.parametrize("shape", list(_SHAPES))
    def test_both_modes_build_the_same_document(self, shape: str) -> None:
        text = _with_platforms({"p": _SHAPES[shape]})

        assert parse_state(text, strict=True) == parse_state(text, strict=False)

    def test_every_shape_in_one_document(self) -> None:
        text = _with_platforms(dict(_SHAPES))

        assert render_state(parse_state(text)) == text

    def test_a_conforming_entry_keeps_no_raw(self) -> None:
        conforming = {
            "account_id": "1",
            "campaigns": [_campaign(ads=[{"ad_id": "a1"}])],
        }
        text = _with_platforms({"p": conforming})

        doc = parse_state(text)

        assert doc.platforms is not None
        platform = doc.platforms["p"]
        assert platform.raw is None
        assert platform.campaigns[0].raw is None
        assert platform.campaigns[0].ads is not None
        assert platform.campaigns[0].ads[0].raw is None
        assert render_state(doc) == text

    def test_a_missing_optional_campaign_key_is_still_added_on_a_conforming_entry(
        self,
    ) -> None:
        """Unchanged from main: a conforming entry is emitted canonically."""
        conforming = {
            "account_id": "1",
            "campaigns": [{"campaign_id": "c1", "campaign_name": "A", "status": "X"}],
        }

        rendered = json.loads(
            render_state(parse_state(_with_platforms({"p": conforming})))
        )

        assert rendered["platforms"]["p"]["campaigns"][0]["notes"] is None

    def test_a_top_level_campaign_is_kept_as_found(self) -> None:
        data = _document()
        data["campaigns"] = [_HAND_CAMPAIGN]
        text = _text(data)

        doc = parse_state(text, strict=True)

        assert doc.campaigns[0].campaign_name == ""
        assert doc.campaigns[0].raw == _HAND_CAMPAIGN
        assert render_state(doc) == text
        assert parse_state(text, strict=False) == doc

    def test_non_string_required_values_read_as_empty(self) -> None:
        doc = parse_state(_with_platforms(dict(_SHAPES)))

        assert doc.platforms is not None
        null_id, numeric = doc.platforms["campaign-null-and-numeric-ids"].campaigns
        assert null_id.campaign_id == ""
        assert (numeric.campaign_id, numeric.campaign_name, numeric.status) == (
            "",
            "",
            "",
        )
        ads = doc.platforms["ad-without-ad_id"].campaigns[0].ads
        assert ads is not None
        assert [a.ad_id for a in ads] == ["", ""]

    def test_a_list_with_non_object_entries_parses_the_objects(self) -> None:
        doc = parse_state(_with_platforms(dict(_SHAPES)))

        assert doc.platforms is not None
        assert [c.campaign_id for c in doc.platforms["mixed-campaigns"].campaigns] == [
            "c1"
        ]
        ads = doc.platforms["campaign-mixed-ads"].campaigns[0].ads
        assert ads is not None
        assert [a.ad_id for a in ads] == ["a1"]
        assert doc.platforms["campaign-string-ads"].campaigns[0].ads is None
        assert (
            doc.platforms["string-device_targeting"].campaigns[0].device_targeting
            is None
        )

    def test_raw_is_isolated_from_the_source_and_the_rendered_dict(self) -> None:
        source = {"account_id": "1", "campaigns": [], "note": {"tags": ["a"]}}

        entry = parse_platform("p", source)
        source["note"]["tags"].append("b")
        source["extra"] = 1
        rendered = platform_state_to_dict(entry)
        rendered["note"]["tags"].append("c")

        assert entry.raw == {
            "account_id": "1",
            "campaigns": [],
            "note": {"tags": ["a"]},
        }
        assert platform_state_to_dict(entry)["note"] == {"tags": ["a"]}

    def test_an_unknown_key_alone_keeps_raw(self) -> None:
        doc = parse_state(_with_platforms(dict(_SHAPES)))

        assert doc.platforms is not None
        assert doc.platforms["unknown-platform-key"].raw is not None
        campaign = doc.platforms["campaign-and-ad-unknown-keys-only"].campaigns[0]
        assert campaign.raw is not None
        assert campaign.ads is not None
        assert campaign.ads[0].raw == {"ad_id": "a1", "headline": "Spring"}

    @pytest.mark.parametrize("model", [AdState, CampaignSnapshot])
    def test_raw_must_be_an_object(self, model: type) -> None:
        required = (
            {"ad_id": "a"}
            if model is AdState
            else {
                "campaign_id": "c",
                "campaign_name": "n",
                "status": "s",
            }
        )

        with pytest.raises(ValueError, match="raw must be an object"):
            model(**required, raw=["not", "an", "object"])


@pytest.mark.unit
class TestMureoChangesLand:
    def test_upsert_onto_a_preserved_campaign(self, state_file: Path) -> None:
        upsert_campaign(
            state_file,
            CampaignSnapshot(
                campaign_id="72804", campaign_name="E2E", status="ENABLED"
            ),
            platform="logly_ads",
            account_id="555",
        )

        platform = _on_disk(state_file)["platforms"]["logly_ads"]
        stored = platform["campaigns"]
        assert len(stored) == 1
        assert stored[0]["status"] == "ENABLED"
        assert stored[0]["budget_note"] == "raised on Monday"
        assert stored[0]["name"] == "E2E"
        assert list(stored[0])[: len(_HAND_CAMPAIGN)] == list(_HAND_CAMPAIGN)
        assert stored[0]["campaign_name"] == "E2E"
        # The platform's own unknown key survives; the id mureo set lands.
        assert platform["owner"] == "ops team"
        assert platform["account_id"] == "555"
        assert list(platform)[: len(_NO_ACCOUNT_ID)] == list(_NO_ACCOUNT_ID)

    def test_upsert_into_a_string_campaigns_platform_replaces_the_value(
        self, state_file: Path
    ) -> None:
        upsert_campaign(
            state_file,
            CampaignSnapshot(campaign_id="G-1", campaign_name="G", status="ENABLED"),
            platform="google_ads",
            account_id="111-222-3333",
        )

        platform = _on_disk(state_file)["platforms"]["google_ads"]
        assert [c["campaign_id"] for c in platform["campaigns"]] == ["G-1"]
        assert platform["totals"] == {"spend": 1200.0}

    def test_a_field_mureo_sets_lands_and_the_rest_is_kept(self) -> None:
        text = _with_platforms({"p": _SHAPES["campaign-string-ads"]})
        doc = parse_state(text)
        assert doc.platforms is not None
        platform = doc.platforms["p"]
        campaign = dataclasses.replace(platform.campaigns[0], notes="checked")
        changed = dataclasses.replace(
            doc,
            platforms={"p": dataclasses.replace(platform, campaigns=(campaign,))},
        )

        stored = json.loads(render_state(changed))["platforms"]["p"]["campaigns"][0]

        assert stored["notes"] == "checked"
        assert stored["ads"] == "three RSAs"

    def test_replaced_ads_are_written_from_the_model(self) -> None:
        text = _with_platforms({"p": _SHAPES["campaign-string-ads"]})
        doc = parse_state(text)
        assert doc.platforms is not None
        platform = doc.platforms["p"]
        campaign = dataclasses.replace(
            platform.campaigns[0], ads=(AdState(ad_id="a1"),)
        )
        changed = dataclasses.replace(
            doc,
            platforms={"p": dataclasses.replace(platform, campaigns=(campaign,))},
        )

        stored = json.loads(render_state(changed))["platforms"]["p"]["campaigns"][0]

        assert stored["ads"] == [{"ad_id": "a1"}]

    def test_an_empty_id_never_matches_an_upsert(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        path.write_text(
            _with_platforms(
                {"logly_ads": {"account_id": "1", "campaigns": [{"name": "x"}]}}
            ),
            encoding="utf-8",
        )

        upsert_campaign(
            path,
            CampaignSnapshot(campaign_id="c9", campaign_name="N", status="ENABLED"),
            platform="logly_ads",
            account_id="1",
        )

        stored = _on_disk(path)["platforms"]["logly_ads"]["campaigns"]
        assert stored[0] == {"name": "x"}
        assert stored[1]["campaign_id"] == "c9"


@pytest.mark.unit
class TestUnknownAccountIds:
    def test_two_missing_account_ids_are_not_duplicates(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        text = _with_platforms(
            {
                "google_ads": {"campaigns": [], "totals": {"spend": 1.0}},
                "logly_ads": {"campaigns": [], "totals": {"spend": 2.0}},
            }
        )
        doc = parse_state(text)

        assert duplicate_account_entries(doc.platforms) == ()
        with caplog.at_level(logging.WARNING):
            warn_on_duplicate_accounts(tmp_path / "STATE.json", doc)
        assert "double-counted" not in caplog.text

    def test_a_numeric_account_id_is_read_as_found(self) -> None:
        """Unchanged from main: present means read as is, so it still joins."""
        text = _with_platforms(
            {
                "google_ads": {"account_id": 1234567890, "campaigns": []},
                "google_ads_2": {"account_id": "1234567890", "campaigns": []},
            }
        )

        doc = parse_state(text)

        assert doc.platforms is not None
        assert doc.platforms["google_ads"].raw is None
        assert len(duplicate_account_entries(doc.platforms)) == 1
        assert render_state(doc) == text


@pytest.mark.unit
class TestLogging:
    def test_parsing_a_nonconforming_document_warns_about_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            parse_state(_with_platforms(dict(_SHAPES)), strict=True)

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_a_whole_document_write_is_byte_stable(self, state_file: Path) -> None:
        before = state_file.read_text(encoding="utf-8")

        write_state_file(state_file, read_state_file(state_file))

        assert state_file.read_text(encoding="utf-8") == before
