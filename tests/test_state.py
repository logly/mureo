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
        new_doc = upsert_campaign(fp, updated)
        assert len(new_doc.campaigns) == 1
        assert new_doc.campaigns[0].campaign_name == "New Name"
        assert new_doc.campaigns[0].status == "PAUSED"
        assert new_doc.campaigns[0].daily_budget == 10000.0

        # Verify persisted to file
        reloaded = read_state_file(fp)
        assert reloaded.campaigns[0].campaign_name == "New Name"

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
        new_doc = upsert_campaign(fp, new_campaign)
        assert len(new_doc.campaigns) == 2
        assert new_doc.campaigns[0].campaign_id == "1"
        assert new_doc.campaigns[1].campaign_id == "2"

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
            "operation": "google_ads.budgets.update",
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
