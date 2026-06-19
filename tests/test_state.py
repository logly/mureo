"""STATE.json related tests (parsing, rendering, file I/O, v1/v2 compat)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mureo.context.errors import ContextFileError
from mureo.context.models import (
    ActionLogEntry,
    CampaignSnapshot,
    PlatformState,
    StateDocument,
)
from mureo.context.state import (
    append_action_log,
    get_campaign,
    parse_state,
    read_state_file,
    render_state,
    set_platform_metrics,
    set_report,
    upsert_campaign,
    write_state_file,
)


class TestParseState:
    """STATE.json parse tests."""

    @pytest.mark.unit
    def test_parse_state_empty(self) -> None:
        """Empty JSON parse."""
        result = parse_state("{}")
        assert result.version == "1"
        assert result.campaigns == ()

    @pytest.mark.unit
    def test_parse_state_with_campaigns(self) -> None:
        """Parse with campaigns."""
        data = {
            "version": "1",
            "last_synced_at": "2024-03-29T10:30:00Z",
            "customer_id": "1234567890",
            "campaigns": [
                {
                    "campaign_id": "123456",
                    "campaign_name": "Search - Brand",
                    "status": "ENABLED",
                    "bidding_strategy_type": "TARGET_CPA",
                    "bidding_details": {"target_cpa": 3000},
                    "daily_budget": 10000.0,
                    "device_targeting": [
                        {
                            "device_type": "MOBILE",
                            "enabled": True,
                            "bid_modifier": 1.2,
                        }
                    ],
                    "campaign_goal": "コンバージョン最大化",
                    "notes": None,
                }
            ],
        }
        result = parse_state(json.dumps(data))
        assert result.version == "1"
        assert result.customer_id == "1234567890"
        assert len(result.campaigns) == 1
        c = result.campaigns[0]
        assert c.campaign_id == "123456"
        assert c.campaign_name == "Search - Brand"
        assert c.status == "ENABLED"
        assert c.bidding_strategy_type == "TARGET_CPA"
        assert c.daily_budget == 10000.0


class TestRenderState:
    """STATE.json rendering tests."""

    @pytest.mark.unit
    def test_render_state(self) -> None:
        """Generate JSON from StateDocument."""
        doc = StateDocument(
            version="1",
            last_synced_at="2024-03-29T10:30:00Z",
            customer_id="123",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1",
                    campaign_name="Test",
                    status="ENABLED",
                ),
            ),
        )
        text = render_state(doc)
        parsed = json.loads(text)
        assert parsed["version"] == "1"
        assert parsed["customer_id"] == "123"
        assert len(parsed["campaigns"]) == 1

    @pytest.mark.unit
    def test_render_parse_roundtrip(self) -> None:
        """render -> parse -> render preserves content."""
        original = StateDocument(
            version="1",
            last_synced_at="2024-03-29T10:30:00Z",
            customer_id="123",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1",
                    campaign_name="Test",
                    status="ENABLED",
                    bidding_strategy_type="TARGET_CPA",
                    bidding_details={"target_cpa": 3000},
                    daily_budget=10000.0,
                ),
            ),
        )
        text = render_state(original)
        restored = parse_state(text)
        assert restored.version == original.version
        assert restored.customer_id == original.customer_id
        assert len(restored.campaigns) == len(original.campaigns)
        assert restored.campaigns[0].campaign_id == "1"
        assert restored.campaigns[0].daily_budget == 10000.0


class TestStateFile:
    """STATE.json file I/O tests."""

    @pytest.mark.unit
    def test_read_state_file(self, tmp_path: Path) -> None:
        """Read from file."""
        fp = tmp_path / "STATE.json"
        data = {
            "version": "1",
            "customer_id": "123",
            "campaigns": [
                {
                    "campaign_id": "1",
                    "campaign_name": "Test",
                    "status": "ENABLED",
                }
            ],
        }
        fp.write_text(json.dumps(data), encoding="utf-8")
        result = read_state_file(fp)
        assert len(result.campaigns) == 1

    @pytest.mark.unit
    def test_write_state_file(self, tmp_path: Path) -> None:
        """Write to file."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(
            version="1",
            customer_id="123",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1",
                    campaign_name="Test",
                    status="ENABLED",
                ),
            ),
        )
        write_state_file(fp, doc)
        assert fp.exists()
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["customer_id"] == "123"

    @pytest.mark.unit
    def test_read_state_file_not_exists(self, tmp_path: Path) -> None:
        """Missing file returns default."""
        fp = tmp_path / "STATE.json"
        result = read_state_file(fp)
        assert result.version == "1"
        assert result.campaigns == ()

    @pytest.mark.unit
    def test_upsert_campaign(self, tmp_path: Path) -> None:
        """Update existing campaign (upsert)."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1",
                    campaign_name="Old Name",
                    status="ENABLED",
                    daily_budget=5000.0,
                ),
            ),
        )
        write_state_file(fp, doc)

        updated = CampaignSnapshot(
            campaign_id="1",
            campaign_name="New Name",
            status="PAUSED",
            daily_budget=10000.0,
        )
        new_doc = upsert_campaign(
            fp, updated, platform="google_ads", account_id="123-456-7890"
        )
        assert len(new_doc.campaigns) == 1
        assert new_doc.campaigns[0].campaign_name == "New Name"
        assert new_doc.campaigns[0].status == "PAUSED"
        assert new_doc.campaigns[0].daily_budget == 10000.0

        # v2 platforms section is populated with the required account_id +
        # the campaign, and last_synced_at is stamped (without these the
        # dashboard renders the client as inactive).
        assert new_doc.platforms is not None
        assert new_doc.platforms["google_ads"].account_id == "123-456-7890"
        assert new_doc.platforms["google_ads"].campaigns[0].campaign_name == "New Name"
        assert new_doc.last_synced_at is not None

        # Verify persisted to file
        reloaded = read_state_file(fp)
        assert reloaded.campaigns[0].campaign_name == "New Name"
        assert reloaded.platforms["google_ads"].account_id == "123-456-7890"
        assert reloaded.last_synced_at is not None

    @pytest.mark.unit
    def test_upsert_campaign_preserves_platform_rollup(self, tmp_path: Path) -> None:
        """A campaign upsert must NOT wipe the platform's totals/metrics_period.

        Those have no upsert input, so the read-modify-write must inherit them
        — otherwise every sync-state campaign upsert silently destroys the
        dashboard KPIs (regression guard for the rollup-preservation fix).
        """
        fp = tmp_path / "STATE.json"
        doc = StateDocument(
            platforms={
                "google_ads": PlatformState(
                    account_id="123",
                    campaigns=(
                        CampaignSnapshot(
                            campaign_id="1", campaign_name="A", status="ENABLED"
                        ),
                    ),
                    totals={"spend": 100, "conversions": 5},
                    metrics_period="LAST_30_DAYS",
                )
            },
        )
        write_state_file(fp, doc)

        new_doc = upsert_campaign(
            fp,
            CampaignSnapshot(campaign_id="2", campaign_name="B", status="ENABLED"),
            platform="google_ads",
            account_id="123",
        )

        ga = new_doc.platforms["google_ads"]
        assert ga.totals == {"spend": 100, "conversions": 5}
        assert ga.metrics_period == "LAST_30_DAYS"
        assert {c.campaign_id for c in ga.campaigns} == {"1", "2"}
        # And it survives the round-trip to disk.
        reloaded = read_state_file(fp).platforms["google_ads"]
        assert reloaded.totals == {"spend": 100, "conversions": 5}
        assert reloaded.metrics_period == "LAST_30_DAYS"

    @pytest.mark.unit
    def test_upsert_campaign_new(self, tmp_path: Path) -> None:
        """Add new campaign."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1",
                    campaign_name="Existing",
                    status="ENABLED",
                ),
            ),
        )
        write_state_file(fp, doc)

        new_campaign = CampaignSnapshot(
            campaign_id="2",
            campaign_name="New Campaign",
            status="ENABLED",
        )
        new_doc = upsert_campaign(
            fp, new_campaign, platform="google_ads", account_id="123-456-7890"
        )
        assert len(new_doc.campaigns) == 2
        assert new_doc.campaigns[0].campaign_id == "1"
        assert new_doc.campaigns[1].campaign_id == "2"
        # New campaign lands under the platform with its account_id.
        assert new_doc.platforms["google_ads"].account_id == "123-456-7890"
        assert new_doc.platforms["google_ads"].campaigns[0].campaign_id == "2"
        assert new_doc.last_synced_at is not None

    @pytest.mark.unit
    def test_get_campaign(self) -> None:
        """Search by campaign_id."""
        doc = StateDocument(
            campaigns=(
                CampaignSnapshot(campaign_id="1", campaign_name="A", status="ENABLED"),
                CampaignSnapshot(campaign_id="2", campaign_name="B", status="PAUSED"),
            ),
        )
        found = get_campaign(doc, "2")
        assert found is not None
        assert found.campaign_name == "B"

        not_found = get_campaign(doc, "999")
        assert not_found is None


class TestCampaignSnapshotImmutability:
    """CampaignSnapshot mutable field defensive copy tests."""

    @pytest.mark.unit
    def test_bidding_details_deepcopy_on_init(self) -> None:
        """Mutating the original dict after init does not affect snapshot."""
        original_details: dict[str, Any] = {"target_cpa": 3000, "nested": {"a": 1}}
        snapshot = CampaignSnapshot(
            campaign_id="1",
            campaign_name="Test",
            status="ENABLED",
            bidding_details=original_details,
        )
        # Mutate external dict
        original_details["target_cpa"] = 9999
        original_details["nested"]["a"] = 999

        # Snapshot unaffected
        assert snapshot.bidding_details is not None
        assert snapshot.bidding_details["target_cpa"] == 3000
        assert snapshot.bidding_details["nested"]["a"] == 1

    @pytest.mark.unit
    def test_device_targeting_is_tuple(self) -> None:
        """device_targeting is converted to tuple."""
        devices = [{"device_type": "MOBILE", "enabled": True}]
        snapshot = CampaignSnapshot(
            campaign_id="1",
            campaign_name="Test",
            status="ENABLED",
            device_targeting=devices,  # type: ignore[arg-type]
        )
        assert isinstance(snapshot.device_targeting, tuple)

    @pytest.mark.unit
    def test_device_targeting_deepcopy_on_init(self) -> None:
        """Mutating the original list after init does not affect snapshot."""
        devices = [{"device_type": "MOBILE", "enabled": True}]
        snapshot = CampaignSnapshot(
            campaign_id="1",
            campaign_name="Test",
            status="ENABLED",
            device_targeting=devices,  # type: ignore[arg-type]
        )
        # Mutate external list
        devices[0]["enabled"] = False

        assert snapshot.device_targeting is not None
        assert snapshot.device_targeting[0]["enabled"] is True


class TestStateFileErrorHandling:
    """State file I/O error tests."""

    @pytest.mark.unit
    def test_read_state_file_invalid_json(self, tmp_path: Path) -> None:
        """Invalid JSON raises ContextFileError."""
        fp = tmp_path / "STATE.json"
        fp.write_text("{invalid json content", encoding="utf-8")
        with pytest.raises(ContextFileError):
            read_state_file(fp)

    @pytest.mark.unit
    def test_read_state_file_permission_error(self, tmp_path: Path) -> None:
        """Permission error raises ContextFileError."""
        fp = tmp_path / "STATE.json"
        fp.write_text("{}", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with pytest.raises(ContextFileError):
                read_state_file(fp)

    @pytest.mark.unit
    def test_parse_state_missing_required_field_campaign_id(self) -> None:
        """Missing campaign_id raises ValueError."""
        data = {"campaigns": [{"campaign_name": "Test", "status": "ENABLED"}]}
        with pytest.raises(ValueError, match="campaign_id"):
            parse_state(json.dumps(data))

    @pytest.mark.unit
    def test_parse_state_missing_required_field_campaign_name(self) -> None:
        """Missing campaign_name raises ValueError."""
        data = {"campaigns": [{"campaign_id": "1", "status": "ENABLED"}]}
        with pytest.raises(ValueError, match="campaign_name"):
            parse_state(json.dumps(data))

    @pytest.mark.unit
    def test_parse_state_missing_required_field_status(self) -> None:
        """Missing status raises ValueError."""
        data = {"campaigns": [{"campaign_id": "1", "campaign_name": "Test"}]}
        with pytest.raises(ValueError, match="status"):
            parse_state(json.dumps(data))


class TestAtomicWrite:
    """Atomic write tests."""

    @pytest.mark.unit
    def test_write_state_file_atomic(self, tmp_path: Path) -> None:
        """File has correct content after write."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(
            version="1",
            customer_id="123",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1",
                    campaign_name="Test",
                    status="ENABLED",
                ),
            ),
        )
        write_state_file(fp, doc)
        assert fp.exists()
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["customer_id"] == "123"
        assert len(data["campaigns"]) == 1

    @pytest.mark.unit
    def test_write_state_file_creates_parent_dir(self, tmp_path: Path) -> None:
        """Parent directory is auto-created."""
        fp = tmp_path / "subdir" / "deep" / "STATE.json"
        doc = StateDocument(version="1", customer_id="456")
        write_state_file(fp, doc)
        assert fp.exists()
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["customer_id"] == "456"

    @pytest.mark.unit
    def test_write_state_file_atomic_failure_no_corrupt(self, tmp_path: Path) -> None:
        """Write failure does not corrupt existing file."""
        fp = tmp_path / "STATE.json"
        original_doc = StateDocument(version="1", customer_id="original")
        write_state_file(fp, original_doc)

        new_doc = StateDocument(version="1", customer_id="new")
        with patch("mureo.context.state.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                write_state_file(fp, new_doc)

        # Original file is intact
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["customer_id"] == "original"


class TestInitExports:
    """__init__.py export tests."""

    @pytest.mark.unit
    def test_context_file_error_exported(self) -> None:
        """ContextFileError is exported from __init__.py."""
        import mureo.context as context_mod

        assert hasattr(context_mod, "ContextFileError")
        assert context_mod.ContextFileError is ContextFileError


class TestStateV2Models:
    """Immutability tests for v2 models."""

    @pytest.mark.unit
    def test_action_log_entry_frozen(self) -> None:
        """ActionLogEntry is immutable (frozen dataclass)."""
        entry = ActionLogEntry(
            timestamp="2026-04-03T09:30:00Z",
            action="negative_keywords.add",
            platform="google_ads",
        )
        with pytest.raises(AttributeError):
            entry.action = "something_else"  # type: ignore[misc]

    @pytest.mark.unit
    def test_action_log_entry_with_metrics_and_observation(self) -> None:
        """ActionLogEntry supports metrics_at_action and observation_due."""
        entry = ActionLogEntry(
            timestamp="2026-04-01T10:30:00+09:00",
            action="Added 15 negative keywords",
            platform="google_ads",
            metrics_at_action={"cpa": 5200, "conversions": 45},
            observation_due="2026-04-15",
        )
        assert entry.metrics_at_action == {"cpa": 5200, "conversions": 45}
        assert entry.observation_due == "2026-04-15"

    @pytest.mark.unit
    def test_action_log_entry_metrics_defaults_to_none(self) -> None:
        """New fields default to None for backwards compatibility."""
        entry = ActionLogEntry(
            timestamp="t",
            action="a",
            platform="p",
        )
        assert entry.metrics_at_action is None
        assert entry.observation_due is None

    @pytest.mark.unit
    def test_action_log_entry_metrics_defensive_copy(self) -> None:
        """metrics_at_action dict is defensively copied."""
        original = {"cpa": 5200}
        entry = ActionLogEntry(
            timestamp="t",
            action="a",
            platform="p",
            metrics_at_action=original,
        )
        original["cpa"] = 9999
        assert entry.metrics_at_action["cpa"] == 5200

    @pytest.mark.unit
    def test_platform_state_frozen(self) -> None:
        """PlatformState is immutable (frozen dataclass)."""
        ps = PlatformState(account_id="1234567890")
        with pytest.raises(AttributeError):
            ps.account_id = "other"  # type: ignore[misc]

    @pytest.mark.unit
    def test_platform_state_campaigns_defensive_copy(self) -> None:
        """PlatformState takes a defensive copy of campaigns tuple."""
        campaigns = [
            CampaignSnapshot(campaign_id="1", campaign_name="C1", status="ENABLED"),
        ]
        ps = PlatformState(account_id="123", campaigns=tuple(campaigns))
        assert isinstance(ps.campaigns, tuple)
        assert len(ps.campaigns) == 1


class TestParseStateV1Compat:
    """Backward compatibility: v1 format still parses correctly."""

    @pytest.mark.unit
    def test_parse_v1_format_still_works(self) -> None:
        """Old v1 format with top-level customer_id and campaigns parses fine."""
        data = {
            "version": "1",
            "last_synced_at": "2024-03-29T10:30:00Z",
            "customer_id": "1234567890",
            "campaigns": [
                {
                    "campaign_id": "123",
                    "campaign_name": "Search - Brand",
                    "status": "ENABLED",
                }
            ],
        }
        doc = parse_state(json.dumps(data))
        assert doc.version == "1"
        assert doc.customer_id == "1234567890"
        assert len(doc.campaigns) == 1
        assert doc.campaigns[0].campaign_id == "123"
        # v2 fields should have defaults
        assert doc.platforms is None
        assert doc.action_log == ()


class TestParseStateV2:
    """Parsing v2 format with platforms and action_log."""

    @pytest.mark.unit
    def test_parse_v2_with_platforms(self) -> None:
        """Parse v2 format with platforms dict."""
        data = {
            "version": "2",
            "last_synced_at": "2026-04-03T10:00:00Z",
            "platforms": {
                "google_ads": {
                    "account_id": "1234567890",
                    "campaigns": [
                        {
                            "campaign_id": "111",
                            "campaign_name": "Google Campaign",
                            "status": "ENABLED",
                        }
                    ],
                },
                "meta_ads": {
                    "account_id": "act_123456789",
                    "campaigns": [
                        {
                            "campaign_id": "222",
                            "campaign_name": "Meta Campaign",
                            "status": "PAUSED",
                        }
                    ],
                },
            },
            "customer_id": "1234567890",
            "campaigns": [
                {
                    "campaign_id": "111",
                    "campaign_name": "Google Campaign",
                    "status": "ENABLED",
                }
            ],
        }
        doc = parse_state(json.dumps(data))
        assert doc.version == "2"
        assert doc.platforms is not None
        assert "google_ads" in doc.platforms
        assert "meta_ads" in doc.platforms
        assert doc.platforms["google_ads"].account_id == "1234567890"
        assert len(doc.platforms["google_ads"].campaigns) == 1
        assert doc.platforms["google_ads"].campaigns[0].campaign_id == "111"
        assert doc.platforms["meta_ads"].account_id == "act_123456789"
        assert len(doc.platforms["meta_ads"].campaigns) == 1
        # Backward compat fields still present
        assert doc.customer_id == "1234567890"
        assert len(doc.campaigns) == 1

    @pytest.mark.unit
    def test_parse_v2_with_action_log(self) -> None:
        """Parse v2 format with action_log."""
        data = {
            "version": "2",
            "action_log": [
                {
                    "timestamp": "2026-04-03T09:30:00Z",
                    "action": "negative_keywords.add",
                    "platform": "google_ads",
                    "campaign_id": "111222333",
                    "summary": "Added 5 negative keywords",
                    "command": "/search-term-cleanup",
                },
                {
                    "timestamp": "2026-04-03T10:00:00Z",
                    "action": "budget.update",
                    "platform": "meta_ads",
                },
            ],
            "campaigns": [],
        }
        doc = parse_state(json.dumps(data))
        assert len(doc.action_log) == 2
        assert doc.action_log[0].timestamp == "2026-04-03T09:30:00Z"
        assert doc.action_log[0].action == "negative_keywords.add"
        assert doc.action_log[0].platform == "google_ads"
        assert doc.action_log[0].campaign_id == "111222333"
        assert doc.action_log[0].summary == "Added 5 negative keywords"
        assert doc.action_log[0].command == "/search-term-cleanup"
        # Second entry has optional fields as None
        assert doc.action_log[1].campaign_id is None
        assert doc.action_log[1].summary is None
        assert doc.action_log[1].command is None
        # New fields default to None when absent from JSON
        assert doc.action_log[0].metrics_at_action is None
        assert doc.action_log[0].observation_due is None

    @pytest.mark.unit
    def test_parse_v2_action_log_with_metrics(self) -> None:
        """Parse action_log entries with metrics_at_action and observation_due."""
        data = {
            "version": "2",
            "action_log": [
                {
                    "timestamp": "2026-04-01T10:30:00+09:00",
                    "action": "Added 15 negative keywords",
                    "platform": "google_ads",
                    "campaign_id": "12345",
                    "metrics_at_action": {"cpa": 5200, "conversions": 45},
                    "observation_due": "2026-04-15",
                },
            ],
            "campaigns": [],
        }
        doc = parse_state(json.dumps(data))
        entry = doc.action_log[0]
        assert entry.metrics_at_action == {"cpa": 5200, "conversions": 45}
        assert entry.observation_due == "2026-04-15"

    @pytest.mark.unit
    def test_render_action_log_with_metrics_roundtrip(self) -> None:
        """Render and re-parse action_log with metrics_at_action."""
        doc = StateDocument(
            version="2",
            action_log=(
                ActionLogEntry(
                    timestamp="2026-04-01T10:30:00+09:00",
                    action="budget change",
                    platform="google_ads",
                    metrics_at_action={"cpa": 5200, "cost": 234000},
                    observation_due="2026-04-08",
                ),
            ),
        )
        rendered = render_state(doc)
        reparsed = parse_state(rendered)
        assert reparsed.action_log[0].metrics_at_action == {"cpa": 5200, "cost": 234000}
        assert reparsed.action_log[0].observation_due == "2026-04-08"

    @pytest.mark.unit
    def test_render_action_log_with_reversible_params_roundtrip(self) -> None:
        """Render and re-parse action_log carrying reversible_params."""
        hint = {
            "operation": "google_ads_budget_update",
            "params": {"budget_id": "456", "amount_micros": 10_000_000_000},
            "caveats": ["does not refund already-spent budget"],
        }
        doc = StateDocument(
            version="2",
            action_log=(
                ActionLogEntry(
                    timestamp="2026-04-15T10:00:00",
                    action="update_budget",
                    platform="google_ads",
                    reversible_params=hint,
                ),
            ),
        )
        rendered = render_state(doc)
        reparsed = parse_state(rendered)
        assert reparsed.action_log[0].reversible_params == hint

    @pytest.mark.unit
    def test_render_action_log_omits_none_reversible_params(self) -> None:
        """reversible_params is omitted from JSON when None."""
        doc = StateDocument(
            version="2",
            action_log=(
                ActionLogEntry(
                    timestamp="t",
                    action="update_budget",
                    platform="google_ads",
                ),
            ),
        )
        rendered = render_state(doc)
        assert "reversible_params" not in rendered

    @pytest.mark.unit
    def test_render_action_log_with_rollback_of_roundtrip(self) -> None:
        """Render and re-parse action_log carrying rollback_of."""
        doc = StateDocument(
            version="2",
            action_log=(
                ActionLogEntry(
                    timestamp="2026-04-16T10:00:00",
                    action="google_ads_budget_update",
                    platform="google_ads",
                    summary="Rolled back #3",
                    rollback_of=3,
                ),
            ),
        )
        rendered = render_state(doc)
        assert '"rollback_of": 3' in rendered
        reparsed = parse_state(rendered)
        assert reparsed.action_log[0].rollback_of == 3

    @pytest.mark.unit
    def test_render_action_log_omits_none_rollback_of(self) -> None:
        """rollback_of is omitted from JSON when None."""
        doc = StateDocument(
            version="2",
            action_log=(
                ActionLogEntry(
                    timestamp="t",
                    action="update_budget",
                    platform="google_ads",
                ),
            ),
        )
        rendered = render_state(doc)
        assert "rollback_of" not in rendered

    @pytest.mark.unit
    def test_parse_state_without_rollback_of_defaults_none(self) -> None:
        """Legacy STATE.json without rollback_of parses cleanly."""
        data = {
            "version": "2",
            "action_log": [
                {
                    "timestamp": "t",
                    "action": "update_budget",
                    "platform": "google_ads",
                }
            ],
        }
        result = parse_state(json.dumps(data))
        assert result.action_log[0].rollback_of is None

    @pytest.mark.unit
    def test_render_action_log_omits_none_metrics(self) -> None:
        """Render omits metrics_at_action and observation_due when None."""
        doc = StateDocument(
            version="2",
            action_log=(
                ActionLogEntry(
                    timestamp="t",
                    action="a",
                    platform="p",
                ),
            ),
        )
        rendered = render_state(doc)
        parsed_data = json.loads(rendered)
        entry_dict = parsed_data["action_log"][0]
        assert "metrics_at_action" not in entry_dict
        assert "observation_due" not in entry_dict

    @pytest.mark.unit
    def test_parse_v2_empty_platforms_and_log(self) -> None:
        """Parse v2 with empty platforms dict and empty action_log."""
        data = {
            "version": "2",
            "platforms": {},
            "action_log": [],
            "campaigns": [],
        }
        doc = parse_state(json.dumps(data))
        assert doc.platforms == {}
        assert doc.action_log == ()


class TestRenderStateV2:
    """Render v2 format."""

    @pytest.mark.unit
    def test_render_v2(self) -> None:
        """Render includes platforms and action_log."""
        google_platform = PlatformState(
            account_id="1234567890",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="111",
                    campaign_name="Google Campaign",
                    status="ENABLED",
                ),
            ),
        )
        entry = ActionLogEntry(
            timestamp="2026-04-03T09:30:00Z",
            action="negative_keywords.add",
            platform="google_ads",
            campaign_id="111",
            summary="Added 5 negative keywords",
            command="/search-term-cleanup",
        )
        doc = StateDocument(
            version="2",
            last_synced_at="2026-04-03T10:00:00Z",
            customer_id="1234567890",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="111",
                    campaign_name="Google Campaign",
                    status="ENABLED",
                ),
            ),
            platforms={"google_ads": google_platform},
            action_log=(entry,),
        )
        text = render_state(doc)
        parsed = json.loads(text)
        assert parsed["version"] == "2"
        assert "platforms" in parsed
        assert "google_ads" in parsed["platforms"]
        assert parsed["platforms"]["google_ads"]["account_id"] == "1234567890"
        assert len(parsed["platforms"]["google_ads"]["campaigns"]) == 1
        assert "action_log" in parsed
        assert len(parsed["action_log"]) == 1
        assert parsed["action_log"][0]["action"] == "negative_keywords.add"
        # Backward compat fields
        assert parsed["customer_id"] == "1234567890"
        assert len(parsed["campaigns"]) == 1

    @pytest.mark.unit
    def test_render_v2_no_platforms(self) -> None:
        """Render v2 with no platforms omits the key."""
        doc = StateDocument(version="2", campaigns=())
        text = render_state(doc)
        parsed = json.loads(text)
        assert parsed.get("platforms") is None

    @pytest.mark.unit
    def test_render_v2_empty_action_log(self) -> None:
        """Render v2 with empty action_log still includes the key."""
        doc = StateDocument(version="2", campaigns=(), action_log=())
        text = render_state(doc)
        parsed = json.loads(text)
        assert parsed["action_log"] == []


class TestBackwardCompatV1ToV2:
    """Parse v1 format then render as v2 roundtrip."""

    @pytest.mark.unit
    def test_backward_compat_v1_to_v2(self) -> None:
        """v1 format parsed, then rendered, preserves data."""
        v1_data = {
            "version": "1",
            "last_synced_at": "2024-03-29T10:30:00Z",
            "customer_id": "1234567890",
            "campaigns": [
                {
                    "campaign_id": "123",
                    "campaign_name": "Test",
                    "status": "ENABLED",
                }
            ],
        }
        doc = parse_state(json.dumps(v1_data))
        text = render_state(doc)
        restored = json.loads(text)
        assert restored["version"] == "1"
        assert restored["customer_id"] == "1234567890"
        assert len(restored["campaigns"]) == 1
        assert restored["campaigns"][0]["campaign_id"] == "123"


class TestAppendActionLog:
    """Test append_action_log helper."""

    @pytest.mark.unit
    def test_append_action_log(self, tmp_path: Path) -> None:
        """Append an action log entry to existing STATE.json."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(version="2", customer_id="123", campaigns=())
        write_state_file(fp, doc)

        entry = ActionLogEntry(
            timestamp="2026-04-03T09:30:00Z",
            action="negative_keywords.add",
            platform="google_ads",
            campaign_id="111",
            summary="Added 5 negative keywords",
            command="/search-term-cleanup",
        )
        updated = append_action_log(fp, entry)
        assert len(updated.action_log) == 1
        assert updated.action_log[0].action == "negative_keywords.add"

        # Verify persisted to file
        reloaded = read_state_file(fp)
        assert len(reloaded.action_log) == 1
        assert reloaded.action_log[0].timestamp == "2026-04-03T09:30:00Z"

    @pytest.mark.unit
    def test_append_action_log_multiple(self, tmp_path: Path) -> None:
        """Append multiple entries preserves order."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(version="2", campaigns=())
        write_state_file(fp, doc)

        entry1 = ActionLogEntry(
            timestamp="2026-04-03T09:00:00Z",
            action="budget.update",
            platform="google_ads",
        )
        entry2 = ActionLogEntry(
            timestamp="2026-04-03T10:00:00Z",
            action="negative_keywords.add",
            platform="meta_ads",
        )
        append_action_log(fp, entry1)
        updated = append_action_log(fp, entry2)
        assert len(updated.action_log) == 2
        assert updated.action_log[0].action == "budget.update"
        assert updated.action_log[1].action == "negative_keywords.add"

    @pytest.mark.unit
    def test_append_action_log_to_nonexistent_file(self, tmp_path: Path) -> None:
        """Append to a non-existent file creates it."""
        fp = tmp_path / "STATE.json"
        entry = ActionLogEntry(
            timestamp="2026-04-03T09:30:00Z",
            action="budget.update",
            platform="google_ads",
        )
        updated = append_action_log(fp, entry)
        assert fp.exists()
        assert len(updated.action_log) == 1


class TestSetReport:
    """Stage c: set_report writes a structured analysis summary into the
    STATE.json ``reports`` section so a read-only dashboard can render the
    latest report without re-running the agent."""

    @pytest.mark.unit
    def test_set_report_writes_new_report_key(self, tmp_path: Path) -> None:
        """set_report stores the summary under reports[report]."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(version="2")
        write_state_file(fp, doc)

        summary = {
            "generated_at": "2026-06-17T00:00:00+00:00",
            "period": "2026-06-17",
            "kpis": {"google_ads": {"cpa": 4800}},
            "flags": ["cpa_over_target"],
            "narrative": "One campaign is over the CPA target.",
        }
        updated = set_report(fp, "daily", summary)
        assert updated.reports is not None
        assert updated.reports["daily"] == summary

        reloaded = read_state_file(fp)
        assert reloaded.reports is not None
        assert reloaded.reports["daily"]["flags"] == ["cpa_over_target"]

    @pytest.mark.unit
    def test_set_report_preserves_other_report_keys(self, tmp_path: Path) -> None:
        """Writing one report kind does not clobber the others."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(version="2", reports={"weekly": {"narrative": "ok"}})
        write_state_file(fp, doc)

        updated = set_report(fp, "daily", {"narrative": "healthy"})
        assert updated.reports is not None
        # New key added.
        assert updated.reports["daily"] == {"narrative": "healthy"}
        # Pre-existing key untouched.
        assert updated.reports["weekly"] == {"narrative": "ok"}

    @pytest.mark.unit
    def test_set_report_overwrites_same_report_key(self, tmp_path: Path) -> None:
        """Re-writing the same report kind replaces its summary."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(version="2", reports={"daily": {"narrative": "old"}})
        write_state_file(fp, doc)

        updated = set_report(fp, "daily", {"narrative": "new"})
        assert updated.reports is not None
        assert updated.reports["daily"] == {"narrative": "new"}

    @pytest.mark.unit
    def test_set_report_preserves_campaigns_and_action_log(
        self, tmp_path: Path
    ) -> None:
        """The rest of the document (campaigns, action_log, platforms) survives
        a report write."""
        fp = tmp_path / "STATE.json"
        ps = PlatformState(
            account_id="123",
            campaigns=(
                CampaignSnapshot(campaign_id="1", campaign_name="C", status="ENABLED"),
            ),
        )
        entry = ActionLogEntry(
            timestamp="2026-06-17T09:00:00Z",
            action="budget.update",
            platform="google_ads",
        )
        doc = StateDocument(
            version="2",
            campaigns=(
                CampaignSnapshot(campaign_id="1", campaign_name="C", status="ENABLED"),
            ),
            platforms={"google_ads": ps},
            action_log=(entry,),
        )
        write_state_file(fp, doc)

        updated = set_report(fp, "goal", {"narrative": "on track"})
        assert updated.reports is not None
        assert updated.reports["goal"] == {"narrative": "on track"}
        # Untouched sections.
        assert len(updated.campaigns) == 1
        assert updated.campaigns[0].campaign_id == "1"
        assert len(updated.action_log) == 1
        assert updated.action_log[0].action == "budget.update"
        assert updated.platforms is not None
        assert updated.platforms["google_ads"].account_id == "123"

    @pytest.mark.unit
    def test_set_report_restamps_last_synced_at(self, tmp_path: Path) -> None:
        """last_synced_at is re-stamped to now on a report write."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(version="2", last_synced_at="2020-01-01T00:00:00+00:00")
        write_state_file(fp, doc)

        updated = set_report(fp, "daily", {"narrative": "fresh"})
        assert updated.last_synced_at is not None
        assert updated.last_synced_at != "2020-01-01T00:00:00+00:00"

    @pytest.mark.unit
    def test_set_report_starts_from_none_reports(self, tmp_path: Path) -> None:
        """Backward compat: a doc whose reports is None gains a {} that the new
        report key is merged into."""
        fp = tmp_path / "STATE.json"
        doc = StateDocument(version="2")
        assert doc.reports is None
        write_state_file(fp, doc)

        updated = set_report(fp, "weekly", {"narrative": "watch"})
        assert updated.reports == {"weekly": {"narrative": "watch"}}

    @pytest.mark.unit
    def test_set_report_to_nonexistent_file_creates_it(self, tmp_path: Path) -> None:
        """Writing a report to an absent STATE.json creates the file."""
        fp = tmp_path / "STATE.json"
        updated = set_report(fp, "daily", {"narrative": "first run"})
        assert fp.exists()
        assert updated.reports == {"daily": {"narrative": "first run"}}

    @pytest.mark.unit
    def test_set_report_roundtrips_to_disk(self, tmp_path: Path) -> None:
        """The persisted summary round-trips through a fresh read."""
        fp = tmp_path / "STATE.json"
        summary = {
            "generated_at": "2026-06-17T00:00:00+00:00",
            "period": "LAST_7_DAYS",
            "kpis": {"totals": {"spend": 12345.0, "conversions": 12}},
            "flags": [],
            "narrative": "Spend steady week over week.",
        }
        set_report(fp, "weekly", summary)
        reloaded = read_state_file(fp)
        assert reloaded.reports is not None
        assert reloaded.reports["weekly"] == summary


class TestStatePerformanceMetrics:
    """Stage a+b: optional performance metrics on snapshots / platforms /
    document. All fields are OPTIONAL with safe defaults so old STATE.json
    files (without them) parse unchanged and emit no extra keys."""

    @pytest.mark.unit
    def test_campaign_metrics_defaults_to_none(self) -> None:
        """CampaignSnapshot.metrics defaults to None."""
        snap = CampaignSnapshot(campaign_id="1", campaign_name="C", status="ENABLED")
        assert snap.metrics is None

    @pytest.mark.unit
    def test_campaign_metrics_defensive_copy(self) -> None:
        """metrics dict is defensively deep-copied on init."""
        original: dict[str, Any] = {"spend": 1000, "nested": {"cpa": 5200}}
        snap = CampaignSnapshot(
            campaign_id="1",
            campaign_name="C",
            status="ENABLED",
            metrics=original,
        )
        original["spend"] = 9999
        original["nested"]["cpa"] = 1
        assert snap.metrics is not None
        assert snap.metrics["spend"] == 1000
        assert snap.metrics["nested"]["cpa"] == 5200

    @pytest.mark.unit
    def test_platform_state_metrics_defaults(self) -> None:
        """PlatformState.totals / metrics_period default to None."""
        ps = PlatformState(account_id="123")
        assert ps.totals is None
        assert ps.metrics_period is None

    @pytest.mark.unit
    def test_platform_state_totals_defensive_copy(self) -> None:
        """PlatformState.totals dict is defensively deep-copied on init."""
        totals: dict[str, Any] = {"spend": 5000, "nested": {"clicks": 12}}
        ps = PlatformState(account_id="123", totals=totals)
        totals["spend"] = 1
        totals["nested"]["clicks"] = 0
        assert ps.totals is not None
        assert ps.totals["spend"] == 5000
        assert ps.totals["nested"]["clicks"] == 12

    @pytest.mark.unit
    def test_state_document_reports_defaults_to_none(self) -> None:
        """StateDocument.reports defaults to None."""
        doc = StateDocument()
        assert doc.reports is None

    @pytest.mark.unit
    def test_state_document_reports_defensive_copy(self) -> None:
        """StateDocument.reports dict is defensively deep-copied on init."""
        reports: dict[str, Any] = {"daily": {"summary": "ok"}}
        doc = StateDocument(reports=reports)
        reports["daily"]["summary"] = "changed"
        assert doc.reports is not None
        assert doc.reports["daily"]["summary"] == "ok"

    @pytest.mark.unit
    def test_parse_campaign_metrics(self) -> None:
        """Parse a campaign carrying a metrics object."""
        data = {
            "campaigns": [
                {
                    "campaign_id": "1",
                    "campaign_name": "C",
                    "status": "ENABLED",
                    "metrics": {
                        "spend": 12345.0,
                        "impressions": 10000,
                        "clicks": 250,
                        "conversions": 12,
                        "cpa": 1028.75,
                        "ctr": 0.025,
                        "result_indicator": "leads",
                        "period": "LAST_30_DAYS",
                        "fetched_at": "2026-06-17T00:00:00+00:00",
                    },
                }
            ]
        }
        doc = parse_state(json.dumps(data))
        metrics = doc.campaigns[0].metrics
        assert metrics is not None
        assert metrics["spend"] == 12345.0
        assert metrics["result_indicator"] == "leads"
        assert metrics["period"] == "LAST_30_DAYS"

    @pytest.mark.unit
    def test_parse_campaign_without_metrics_defaults_none(self) -> None:
        """A campaign with no metrics key parses to None (backward compat)."""
        data = {
            "campaigns": [
                {"campaign_id": "1", "campaign_name": "C", "status": "ENABLED"}
            ]
        }
        doc = parse_state(json.dumps(data))
        assert doc.campaigns[0].metrics is None

    @pytest.mark.unit
    def test_render_campaign_metrics_roundtrip(self) -> None:
        """metrics round-trips through render -> parse."""
        metrics = {
            "spend": 1000.0,
            "clicks": 50,
            "conversions": 5,
            "cpa": 200.0,
            "period": "LAST_30_DAYS",
            "fetched_at": "2026-06-17T00:00:00+00:00",
        }
        doc = StateDocument(
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1",
                    campaign_name="C",
                    status="ENABLED",
                    metrics=metrics,
                ),
            ),
        )
        restored = parse_state(render_state(doc))
        assert restored.campaigns[0].metrics == metrics

    @pytest.mark.unit
    def test_render_campaign_omits_none_metrics(self) -> None:
        """metrics is omitted from JSON when None (no diff churn)."""
        doc = StateDocument(
            campaigns=(
                CampaignSnapshot(campaign_id="1", campaign_name="C", status="ENABLED"),
            ),
        )
        rendered = render_state(doc)
        snap_dict = json.loads(rendered)["campaigns"][0]
        assert "metrics" not in snap_dict

    @pytest.mark.unit
    def test_render_platform_totals_and_period_roundtrip(self) -> None:
        """PlatformState.totals / metrics_period round-trip."""
        ps = PlatformState(
            account_id="123",
            campaigns=(
                CampaignSnapshot(campaign_id="1", campaign_name="C", status="ENABLED"),
            ),
            totals={"spend": 5000.0, "conversions": 20},
            metrics_period="LAST_30_DAYS",
        )
        doc = StateDocument(version="2", platforms={"google_ads": ps})
        restored = parse_state(render_state(doc))
        rp = restored.platforms["google_ads"]
        assert rp.totals == {"spend": 5000.0, "conversions": 20}
        assert rp.metrics_period == "LAST_30_DAYS"

    @pytest.mark.unit
    def test_render_platform_omits_none_totals_and_period(self) -> None:
        """totals / metrics_period are omitted from JSON when None."""
        ps = PlatformState(account_id="123")
        doc = StateDocument(version="2", platforms={"google_ads": ps})
        plat_dict = json.loads(render_state(doc))["platforms"]["google_ads"]
        assert "totals" not in plat_dict
        assert "metrics_period" not in plat_dict

    @pytest.mark.unit
    def test_parse_platform_without_metrics_defaults_none(self) -> None:
        """Legacy platform entry (no totals/metrics_period) parses to None."""
        data = {
            "version": "2",
            "platforms": {
                "google_ads": {
                    "account_id": "123",
                    "campaigns": [
                        {
                            "campaign_id": "1",
                            "campaign_name": "C",
                            "status": "ENABLED",
                        }
                    ],
                }
            },
        }
        doc = parse_state(json.dumps(data))
        ps = doc.platforms["google_ads"]
        assert ps.totals is None
        assert ps.metrics_period is None

    @pytest.mark.unit
    def test_render_reports_roundtrip(self) -> None:
        """StateDocument.reports round-trips through render -> parse."""
        reports = {
            "daily": {"summary": "healthy"},
            "weekly": {"summary": "watch"},
            "goal": {"progress": 0.8},
        }
        doc = StateDocument(version="2", reports=reports)
        restored = parse_state(render_state(doc))
        assert restored.reports == reports

    @pytest.mark.unit
    def test_render_omits_none_reports(self) -> None:
        """reports is omitted from JSON when None."""
        doc = StateDocument(version="2")
        assert "reports" not in render_state(doc)

    @pytest.mark.unit
    def test_old_state_json_parses_to_safe_defaults(self) -> None:
        """A complete old STATE.json (no metrics/totals/reports) parses
        with every new field defaulting to None — the hard backward-compat
        requirement."""
        old = {
            "version": "2",
            "last_synced_at": "2026-04-03T10:00:00Z",
            "customer_id": "1234567890",
            "campaigns": [
                {"campaign_id": "111", "campaign_name": "G", "status": "ENABLED"}
            ],
            "platforms": {
                "google_ads": {
                    "account_id": "1234567890",
                    "campaigns": [
                        {
                            "campaign_id": "111",
                            "campaign_name": "G",
                            "status": "ENABLED",
                        }
                    ],
                }
            },
            "action_log": [],
        }
        doc = parse_state(json.dumps(old))
        assert doc.campaigns[0].metrics is None
        assert doc.platforms["google_ads"].totals is None
        assert doc.platforms["google_ads"].metrics_period is None
        assert doc.reports is None
        # And re-rendering does NOT introduce any of the new keys.
        rendered = render_state(doc)
        assert "metrics" not in rendered
        assert "totals" not in rendered
        assert "metrics_period" not in rendered
        assert "reports" not in rendered


class TestRenderParseV2Roundtrip:
    """Full roundtrip for v2 format."""

    @pytest.mark.unit
    def test_v2_roundtrip(self) -> None:
        """render -> parse roundtrip preserves all v2 fields."""
        google_ps = PlatformState(
            account_id="1234567890",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="111",
                    campaign_name="Google Campaign",
                    status="ENABLED",
                ),
            ),
        )
        meta_ps = PlatformState(
            account_id="act_123456789",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="222",
                    campaign_name="Meta Campaign",
                    status="PAUSED",
                ),
            ),
        )
        entry = ActionLogEntry(
            timestamp="2026-04-03T09:30:00Z",
            action="negative_keywords.add",
            platform="google_ads",
            campaign_id="111",
            summary="Added 5 negative keywords",
            command="/search-term-cleanup",
        )
        original = StateDocument(
            version="2",
            last_synced_at="2026-04-03T10:00:00Z",
            customer_id="1234567890",
            campaigns=(
                CampaignSnapshot(
                    campaign_id="111",
                    campaign_name="Google Campaign",
                    status="ENABLED",
                ),
            ),
            platforms={"google_ads": google_ps, "meta_ads": meta_ps},
            action_log=(entry,),
        )
        text = render_state(original)
        restored = parse_state(text)

        assert restored.version == "2"
        assert restored.last_synced_at == original.last_synced_at
        assert restored.customer_id == original.customer_id
        assert len(restored.campaigns) == 1

        assert restored.platforms is not None
        assert len(restored.platforms) == 2
        assert restored.platforms["google_ads"].account_id == "1234567890"
        assert restored.platforms["meta_ads"].account_id == "act_123456789"
        assert len(restored.platforms["google_ads"].campaigns) == 1
        assert len(restored.platforms["meta_ads"].campaigns) == 1

        assert len(restored.action_log) == 1
        assert restored.action_log[0].action == "negative_keywords.add"
        assert restored.action_log[0].campaign_id == "111"


class TestSetPlatformMetrics:
    """set_platform_metrics — platform rollup write + preserve contracts."""

    @pytest.mark.unit
    def test_creates_platform_when_missing(self, tmp_path: Path) -> None:
        fp = tmp_path / "STATE.json"
        write_state_file(fp, StateDocument(version="2"))
        doc = set_platform_metrics(
            fp,
            "google_ads",
            "act_123",
            totals={"spend": 3000.0},
            metrics_period="LAST_30_DAYS",
            periods={"YESTERDAY": {"spend": 100.0}},
        )
        assert doc.platforms is not None
        ps = doc.platforms["google_ads"]
        assert ps.account_id == "act_123"
        assert ps.totals == {"spend": 3000.0}
        assert ps.metrics_period == "LAST_30_DAYS"
        assert ps.periods == {"YESTERDAY": {"spend": 100.0}}

    @pytest.mark.unit
    def test_omitted_fields_preserve_existing(self, tmp_path: Path) -> None:
        """A periods-only call must not reset totals/metrics_period to None."""
        fp = tmp_path / "STATE.json"
        write_state_file(fp, StateDocument(version="2"))
        set_platform_metrics(
            fp,
            "google_ads",
            "act_123",
            totals={"spend": 3000.0},
            metrics_period="LAST_30_DAYS",
        )
        doc = set_platform_metrics(
            fp, "google_ads", "act_123", periods={"YESTERDAY": {"spend": 100.0}}
        )
        ps = doc.platforms["google_ads"]
        assert ps.totals == {"spend": 3000.0}  # preserved
        assert ps.metrics_period == "LAST_30_DAYS"  # preserved
        assert ps.periods == {"YESTERDAY": {"spend": 100.0}}

    @pytest.mark.unit
    def test_periods_none_preserves_existing_map(self, tmp_path: Path) -> None:
        fp = tmp_path / "STATE.json"
        write_state_file(fp, StateDocument(version="2"))
        set_platform_metrics(
            fp, "google_ads", "act_123", periods={"LAST_30_DAYS": {"spend": 1.0}}
        )
        doc = set_platform_metrics(fp, "google_ads", "act_123", totals={"spend": 2.0})
        ps = doc.platforms["google_ads"]
        assert ps.periods == {"LAST_30_DAYS": {"spend": 1.0}}  # untouched

    @pytest.mark.unit
    def test_preserves_reports_section(self, tmp_path: Path) -> None:
        """Unlike the other mutators, this one must not drop reports."""
        fp = tmp_path / "STATE.json"
        write_state_file(fp, StateDocument(version="2"))
        set_report(fp, "daily", {"verdict": "Healthy"})
        doc = set_platform_metrics(
            fp, "google_ads", "act_123", periods={"YESTERDAY": {"spend": 1.0}}
        )
        assert doc.reports == {"daily": {"verdict": "Healthy"}}


class TestMutatorsPreserveReports:
    """Regression: every STATE.json mutator must preserve the reports section.

    `set_report` writes reports[daily|weekly|goal]; a later `upsert_campaign`
    or `append_action_log` rebuilds the document and historically dropped
    `reports` (omitted from the StateDocument constructor), silently wiping
    the dashboard's analysis summaries. These pin the preservation so the
    bug cannot regress.
    """

    @pytest.mark.unit
    def test_upsert_campaign_preserves_reports(self, tmp_path: Path) -> None:
        fp = tmp_path / "STATE.json"
        write_state_file(fp, StateDocument(version="2"))
        set_report(fp, "daily", {"verdict": "Healthy", "note": "all good"})

        doc = upsert_campaign(
            fp,
            CampaignSnapshot(campaign_id="g1", campaign_name="Brand", status="ENABLED"),
            platform="google_ads",
            account_id="act_123",
        )
        assert doc.reports == {"daily": {"verdict": "Healthy", "note": "all good"}}
        # And it survives to disk, not just the returned object.
        assert read_state_file(fp).reports == {
            "daily": {"verdict": "Healthy", "note": "all good"}
        }

    @pytest.mark.unit
    def test_append_action_log_preserves_reports(self, tmp_path: Path) -> None:
        fp = tmp_path / "STATE.json"
        write_state_file(fp, StateDocument(version="2"))
        set_report(fp, "weekly", {"verdict": "Watch"})

        doc = append_action_log(
            fp,
            ActionLogEntry(
                timestamp="2026-06-19T00:00:00+00:00",
                action="budget_update",
                platform="google_ads",
            ),
        )
        assert doc.reports == {"weekly": {"verdict": "Watch"}}
        assert read_state_file(fp).reports == {"weekly": {"verdict": "Watch"}}
