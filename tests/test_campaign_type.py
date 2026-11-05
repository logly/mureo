"""A campaign snapshot's ``campaign_type`` in STATE.json.

The value is the platform's own name for the campaign type, verbatim
(Google Ads ``SEARCH`` / ``PERFORMANCE_MAX``, Meta ``OUTCOME_LEADS``), the
rule ``bidding_strategy_type`` follows. Pinned here:

- it round-trips byte-for-byte, written right after ``bidding_details``;
- a campaign without it parses to ``None`` and gains no key on write, so a
  document written before the field existed stays byte-stable;
- a value that is not a string is carried and written back as found, the
  way the codec treats the other free-form campaign fields;
- a writer puts it in the codec's position, and a campaign kept with
  ``raw`` keeps its on-disk order;
- an upsert that omits it keeps the stored value, one that supplies it
  replaces the stored value.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.models import CampaignSnapshot
from mureo.context.state import read_state_file, upsert_campaign
from mureo.context.state_codec import parse_state, render_state

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _campaign(**extra: Any) -> dict[str, Any]:
    """A campaign entry in the codec's own key order."""
    entry: dict[str, Any] = {
        "campaign_id": "c1",
        "campaign_name": "Brand Search",
        "status": "ENABLED",
        "bidding_strategy_type": "TARGET_CPA",
        "bidding_details": {"target_cpa": 5000},
    }
    entry.update(extra.pop("after_bidding", {}))
    entry.update(
        {
            "daily_budget": 8000.0,
            "device_targeting": None,
            "campaign_goal": None,
            "notes": None,
        }
    )
    entry.update(extra)
    return entry


def _document(campaign: dict[str, Any]) -> str:
    """A v2 document with one platform, formatted as ``render_state`` does."""
    data = {
        "version": "2",
        "last_synced_at": None,
        "customer_id": None,
        "campaigns": [],
        "platforms": {"google_ads": {"account_id": "123", "campaigns": [campaign]}},
        "action_log": [],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _only_campaign(text: str) -> CampaignSnapshot:
    doc = parse_state(text)
    assert doc.platforms is not None
    return doc.platforms["google_ads"].campaigns[0]


class TestCampaignTypeRoundTrip:
    def test_a_set_value_round_trips_byte_for_byte(self) -> None:
        text = _document(_campaign(after_bidding={"campaign_type": "SEARCH"}))

        campaign = _only_campaign(text)

        assert campaign.campaign_type == "SEARCH"
        assert campaign.raw is None
        assert render_state(parse_state(text)) == text

    def test_a_campaign_without_it_gains_no_key(self) -> None:
        text = _document(_campaign())

        campaign = _only_campaign(text)
        rendered = render_state(parse_state(text))

        assert campaign.campaign_type is None
        assert rendered == text
        campaign_out = json.loads(rendered)["platforms"]["google_ads"]["campaigns"][0]
        assert "campaign_type" not in campaign_out

    @pytest.mark.parametrize("value", [7, ["SEARCH", "DISPLAY"], {"type": "SEARCH"}])
    def test_a_non_string_value_is_written_back_as_found(self, value: Any) -> None:
        text = _document(_campaign(after_bidding={"campaign_type": value}))

        assert _only_campaign(text).campaign_type == value
        assert render_state(parse_state(text)) == text

    def test_a_kept_campaign_keeps_its_on_disk_order(self) -> None:
        """An unknown key makes the codec keep ``raw``; ``campaign_type``
        written last by hand stays last."""
        text = _document(_campaign(hand_note="x", campaign_type="DISPLAY"))

        campaign = _only_campaign(text)

        assert campaign.raw is not None
        assert campaign.campaign_type == "DISPLAY"
        assert render_state(parse_state(text)) == text

    def test_the_default_is_none(self) -> None:
        snapshot = CampaignSnapshot(campaign_id="c1", campaign_name="A", status="X")

        assert snapshot.campaign_type is None


class TestCampaignTypeWriters:
    def test_upsert_writes_it_after_bidding_details(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="Leads",
                status="ACTIVE",
                campaign_type="OUTCOME_LEADS",
            ),
            platform="meta_ads",
            account_id="act_1",
        )

        on_disk = json.loads(path.read_text(encoding="utf-8"))
        keys = list(on_disk["platforms"]["meta_ads"]["campaigns"][0])
        assert keys.index("campaign_type") == keys.index("bidding_details") + 1
        doc = read_state_file(path)
        assert doc.platforms is not None
        assert doc.platforms["meta_ads"].campaigns[0].campaign_type == "OUTCOME_LEADS"

    def test_an_upsert_without_it_keeps_the_stored_value(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        first = CampaignSnapshot(
            campaign_id="c1",
            campaign_name="Brand",
            status="ENABLED",
            campaign_type="SEARCH",
        )
        upsert_campaign(path, first, platform="google_ads", account_id="1")

        upsert_campaign(
            path,
            CampaignSnapshot(campaign_id="c1", campaign_name="Brand", status="PAUSED"),
            platform="google_ads",
            account_id="1",
        )

        doc = read_state_file(path)
        assert doc.platforms is not None
        stored = doc.platforms["google_ads"].campaigns[0]
        assert stored.status == "PAUSED"
        assert stored.campaign_type == "SEARCH"

    def test_a_supplied_value_replaces_the_stored_one(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        for campaign_type in ("DISPLAY", "SEARCH"):
            upsert_campaign(
                path,
                CampaignSnapshot(
                    campaign_id="c1",
                    campaign_name="Brand",
                    status="ENABLED",
                    campaign_type=campaign_type,
                ),
                platform="google_ads",
                account_id="1",
            )

        doc = read_state_file(path)
        assert doc.platforms is not None
        assert doc.platforms["google_ads"].campaigns[0].campaign_type == "SEARCH"
