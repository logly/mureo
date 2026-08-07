"""STATE.json related tests (parsing, rendering, file I/O, v1/v2 compat)."""

from __future__ import annotations

import dataclasses
import json
import logging
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
        with (
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            pytest.raises(ContextFileError),
        ):
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

    @pytest.mark.unit
    def test_parse_state_strict_false_skips_malformed_campaigns(self) -> None:
        """``strict=False`` drops nonconforming campaign entries (top-level
        AND per-platform) instead of raising, and preserves the rest of the
        document. The read-only Reports view depends on this so a single
        variant / hand-authored campaign cannot blank a whole STATE.json
        whose platforms/totals/reports are perfectly readable."""
        data = {
            "version": "2",
            "campaigns": [
                {"id": "69680", "name": "variant shape"},  # no campaign_id/_name
                {"campaign_id": "ok", "campaign_name": "Good", "status": "ENABLED"},
            ],
            "platforms": {
                "logly_ads_context": {
                    "account_id": "acct-1",
                    "campaigns": [
                        {"campaign_id": "72804", "name": "E2E", "status": "paused"},
                    ],
                    "totals": {"spend": 8739.0},
                    "metrics_period": "YESTERDAY",
                }
            },
            "reports": {"daily": {"verdict": "Healthy"}},
        }
        doc = parse_state(json.dumps(data), strict=False)

        # The one conforming top-level campaign survives; the variant is gone.
        assert [c.campaign_id for c in doc.campaigns] == ["ok"]
        # The platform's nonconforming campaign is dropped, the platform kept.
        assert doc.platforms is not None
        plat = doc.platforms["logly_ads_context"]
        assert plat.campaigns == ()
        assert plat.totals == {"spend": 8739.0}
        assert doc.reports == {"daily": {"verdict": "Healthy"}}

    @pytest.mark.unit
    def test_parse_state_strict_true_is_default_and_still_raises(self) -> None:
        """The default (strict) path is unchanged — the writer contract still
        hard-fails on a nonconforming campaign."""
        data = {"campaigns": [{"id": "x", "name": "variant"}]}
        with pytest.raises(ValueError, match="campaign_id"):
            parse_state(json.dumps(data))

    @pytest.mark.unit
    def test_parse_state_strict_false_tolerates_missing_account_id(self) -> None:
        """``strict=False`` defaults a platform's missing ``account_id`` to ''
        instead of crashing, so the read-only Reports view still renders the
        platform. Reproduces the customer case: an agent-authored STATE.json
        whose platforms omit account_id and whose campaigns use `name` (skipped)
        — the tolerant read must NOT blow up with KeyError('account_id')."""
        data = {
            "version": "2",
            "platforms": {
                "google_ads": {
                    # no account_id
                    "campaigns": [
                        {"campaign_id": "22279041552", "name": "x", "status": "PAUSED"},
                    ],
                    "totals": {"spend": 180206.0},
                    "metrics_period": "LAST_30_DAYS",
                }
            },
        }
        doc = parse_state(json.dumps(data), strict=False)
        assert doc.platforms is not None
        plat = doc.platforms["google_ads"]
        assert plat.account_id == ""  # defaulted, not crashed
        assert plat.campaigns == ()  # `name`-variant campaign skipped (by design)
        assert plat.totals == {"spend": 180206.0}  # platform data still rendered

    @pytest.mark.unit
    def test_parse_state_strict_true_raises_on_missing_account_id(self) -> None:
        """The writer contract is preserved: a platform missing account_id
        still raises under strict (the default)."""
        data = {
            "version": "2",
            "platforms": {
                "google_ads": {
                    "campaigns": [],
                    "totals": {"spend": 1.0},
                }
            },
        }
        with pytest.raises(KeyError, match="account_id"):
            parse_state(json.dumps(data))

    @pytest.mark.unit
    def test_missing_account_id_logs_at_debug_not_warning(self, caplog) -> None:
        """The tolerant default must not add per-poll WARNING noise — the
        customer complaint included a log flood, so the missing-account_id
        fallback is logged at DEBUG only."""
        data = {
            "version": "2",
            "platforms": {"google_ads": {"campaigns": [], "totals": {"spend": 1.0}}},
        }
        with caplog.at_level(logging.DEBUG, logger="mureo.context.state_codec"):
            parse_state(json.dumps(data), strict=False)
        assert any(
            "missing 'account_id'" in r.message and r.levelno == logging.DEBUG
            for r in caplog.records
        )
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.unit
    def test_parse_state_strict_false_skips_log_at_debug_not_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Skipped nonconforming entries log at DEBUG, never WARNING+.

        The read-only Reports view re-parses STATE.json on every dashboard
        poll, so a per-entry WARNING would flood the daemon log for an account
        with many legacy / hand-authored campaigns — and read as a failure when
        it is graceful degradation. Pin DEBUG so the noise never returns."""
        data = {
            "campaigns": [{"id": "x", "name": "variant, no campaign_id/_name"}],
            "action_log": [{"summary": "legacy, no timestamp/action/platform"}],
        }
        with caplog.at_level(logging.DEBUG, logger="mureo.context.state_codec"):
            parse_state(json.dumps(data), strict=False)

        # The skips still happen and are observable at DEBUG …
        assert any("skipping unparseable" in r.message for r in caplog.records)
        # … but nothing is emitted at WARNING or above (the per-render flood).
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.unit
    def test_parse_state_strict_false_skips_malformed_action_log(self) -> None:
        """``strict=False`` drops action_log entries missing a required field
        (timestamp / action / platform) instead of raising, and keeps the rest
        of the document. The read-only Reports view relies on this — an old /
        hand-authored entry written before those fields were required (e.g. one
        with only a `summary`) must not blank a whole STATE.json."""
        data = {
            "version": "2",
            "action_log": [
                {"summary": "old entry, no timestamp/action/platform"},  # bad
                {
                    "timestamp": "2026-06-16T10:00:00+00:00",
                    "action": "budget_update",
                    "platform": "google_ads",
                    "summary": "good entry",
                },
            ],
            "reports": {"daily": {"verdict": "Healthy"}},
        }
        doc = parse_state(json.dumps(data), strict=False)

        # The conforming entry survives; the field-less one is dropped.
        assert [e.action for e in doc.action_log] == ["budget_update"]
        assert doc.reports == {"daily": {"verdict": "Healthy"}}

    @pytest.mark.unit
    def test_parse_state_strict_true_raises_on_action_log_missing_timestamp(
        self,
    ) -> None:
        """The default (strict) path still hard-fails on an action_log entry
        missing a required field — the writer contract is unchanged."""
        data = {"action_log": [{"action": "x", "platform": "google_ads"}]}
        with pytest.raises(KeyError):
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
        with (
            patch("mureo.context.state.os.replace", side_effect=OSError("disk full")),
            pytest.raises(OSError),
        ):
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
        assert entry.entity_type is None
        assert entry.entity_id is None

    @pytest.mark.unit
    def test_action_log_entity_identity_requires_complete_pair(self) -> None:
        with pytest.raises(ValueError, match="provided together"):
            ActionLogEntry(
                timestamp="t",
                action="a",
                platform="p",
                entity_type="placement",
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("field", ["entity_type", "entity_id"])
    def test_action_log_entity_identity_rejects_blank_values(self, field: str) -> None:
        values = {"entity_type": "placement", "entity_id": "p1"}
        values[field] = "   "
        with pytest.raises(ValueError, match="non-empty string"):
            ActionLogEntry(
                timestamp="t",
                action="a",
                platform="p",
                **values,
            )

    @pytest.mark.unit
    def test_action_log_entity_identity_strips_outer_whitespace(self) -> None:
        entry = ActionLogEntry(
            timestamp="t",
            action="a",
            platform="p",
            entity_type=" placement ",
            entity_id=" p1 ",
        )
        assert entry.entity_type == "placement"
        assert entry.entity_id == "p1"

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


@pytest.mark.unit
class TestConversionActionTypesOverride:
    """#342 — operator-declared per-account conversion action_type override."""

    def _state_with_meta(self, tmp_path: Path, account_id: str = "act_1") -> Path:
        p = tmp_path / "STATE.json"
        p.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        "meta_ads": {"account_id": account_id, "campaigns": []}
                    },
                }
            ),
            encoding="utf-8",
        )
        return p

    def test_set_and_load_roundtrip(self, tmp_path: Path) -> None:
        from mureo.context.state import (
            load_conversion_action_types,
            set_conversion_action_types,
        )

        p = self._state_with_meta(tmp_path)
        set_conversion_action_types(
            p, "meta_ads", "act_1", ["offsite_conversion.custom.123"]
        )
        assert load_conversion_action_types("act_1", path=p) == (
            "offsite_conversion.custom.123",
        )
        # Serialized as a JSON list under the platform entry.
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["platforms"]["meta_ads"]["conversion_action_types"] == [
            "offsite_conversion.custom.123"
        ]

    def test_clear_with_empty_list(self, tmp_path: Path) -> None:
        from mureo.context.state import (
            load_conversion_action_types,
            set_conversion_action_types,
        )

        p = self._state_with_meta(tmp_path)
        set_conversion_action_types(p, "meta_ads", "act_1", ["lead"])
        set_conversion_action_types(p, "meta_ads", "act_1", [])
        assert load_conversion_action_types("act_1", path=p) is None
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "conversion_action_types" not in data["platforms"]["meta_ads"]

    def test_load_account_mismatch_returns_none(self, tmp_path: Path) -> None:
        from mureo.context.state import (
            load_conversion_action_types,
            set_conversion_action_types,
        )

        p = self._state_with_meta(tmp_path, account_id="act_1")
        set_conversion_action_types(p, "meta_ads", "act_1", ["lead"])
        assert load_conversion_action_types("act_OTHER", path=p) is None

    def test_load_missing_file_or_unset_is_none(self, tmp_path: Path) -> None:
        from mureo.context.state import load_conversion_action_types

        assert (
            load_conversion_action_types("act_1", path=tmp_path / "absent.json") is None
        )
        p = self._state_with_meta(tmp_path)
        assert load_conversion_action_types("act_1", path=p) is None  # unset

    def test_preserved_across_upsert_and_metrics(self, tmp_path: Path) -> None:
        from mureo.context.models import CampaignSnapshot
        from mureo.context.state import (
            load_conversion_action_types,
            set_conversion_action_types,
            set_platform_metrics,
            upsert_campaign,
        )

        p = self._state_with_meta(tmp_path)
        set_conversion_action_types(p, "meta_ads", "act_1", ["lead"])
        upsert_campaign(
            p,
            CampaignSnapshot(campaign_id="c1", campaign_name="C1", status="ACTIVE"),
            platform="meta_ads",
            account_id="act_1",
        )
        assert load_conversion_action_types("act_1", path=p) == ("lead",)
        set_platform_metrics(
            p, "meta_ads", "act_1", totals={"spend": 1.0}, metrics_period="LAST_30_DAYS"
        )
        assert load_conversion_action_types("act_1", path=p) == ("lead",)

    def test_parse_render_roundtrip(self, tmp_path: Path) -> None:
        from mureo.context.state import parse_state, render_state

        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        "meta_ads": {
                            "account_id": "act_1",
                            "campaigns": [],
                            "conversion_action_types": ["lead", "purchase"],
                        }
                    },
                }
            )
        )
        ps = doc.platforms["meta_ads"]
        assert ps.conversion_action_types == ("lead", "purchase")
        # Round-trips through render.
        re = parse_state(render_state(doc))
        assert re.platforms["meta_ads"].conversion_action_types == ("lead", "purchase")

    def test_load_never_raises_on_malformed_json(self, tmp_path: Path) -> None:
        """#342 HIGH — the resolver runs inside live analysis; a non-object /
        malformed STATE.json must yield None, never raise (which would take
        down the whole report)."""
        from mureo.context.state import load_conversion_action_types

        for bad in ("[1,2,3]", '"a string"', "123", "null", "{not json", ""):
            p = tmp_path / "STATE.json"
            p.write_text(bad, encoding="utf-8")
            assert load_conversion_action_types("act_1", path=p) is None

    def test_load_tolerates_act_prefix_mismatch(self, tmp_path: Path) -> None:
        """#342 — a bare-numeric stored id matches the act_* live id and vice
        versa, so the override isn't silently dropped over the prefix."""
        from mureo.context.state import (
            load_conversion_action_types,
            set_conversion_action_types,
        )

        p = self._state_with_meta(tmp_path, account_id="123456")  # bare
        set_conversion_action_types(p, "meta_ads", "123456", ["lead"])
        # Live counters resolve with the act_* form.
        assert load_conversion_action_types("act_123456", path=p) == ("lead",)

    def _state_with_override(self, tmp_path: Path, *, account_id: str) -> Path:
        """A hand-authored / externally written STATE.json carrying an override.

        Written as raw JSON rather than through ``set_conversion_action_types``
        because the MCP write path blocks an empty ``account_id`` — the only
        way an entry reaches ``load_conversion_action_types`` with one is a
        file mureo did not write (#536).
        """
        p = tmp_path / "STATE.json"
        p.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        "meta_ads": {
                            "account_id": account_id,
                            "campaigns": [],
                            "conversion_action_types": ["lead"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return p

    def test_empty_stored_account_id_never_matches(self, tmp_path: Path) -> None:
        """#536 — an entry whose ``account_id`` is empty must not hand its
        override to every account on the platform.

        The override redefines what counts as a conversion, so applying one
        recorded for an unknown account to an unrelated account silently
        miscounts its CV/CPA. An unknown id fails closed: the counters fall
        back to the documented built-in generic set.
        """
        from mureo.context.state import load_conversion_action_types

        p = self._state_with_override(tmp_path, account_id="")
        assert load_conversion_action_types("act_1", path=p) is None
        assert load_conversion_action_types("act_2", path=p) is None

    def test_missing_stored_account_id_never_matches(self, tmp_path: Path) -> None:
        """#536 — the tolerant read path synthesizes ``""`` for a missing
        ``account_id``, which must be "unknown", never a join key."""
        from mureo.context.state import load_conversion_action_types

        p = tmp_path / "STATE.json"
        p.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        "meta_ads": {
                            "campaigns": [],
                            "conversion_action_types": ["lead"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        assert load_conversion_action_types("act_1", path=p) is None

    def test_empty_requested_account_id_never_matches(self, tmp_path: Path) -> None:
        """#536 — the second conjunct was symmetrically broken: a caller
        passing ``""`` received another account's override."""
        from mureo.context.state import load_conversion_action_types

        p = self._state_with_override(tmp_path, account_id="act_1")
        assert load_conversion_action_types("", path=p) is None

    def test_control_known_ids_still_match_and_mismatch(self, tmp_path: Path) -> None:
        """#536 control — the fix must not break the matching case."""
        from mureo.context.state import load_conversion_action_types

        p = self._state_with_override(tmp_path, account_id="act_1")
        assert load_conversion_action_types("act_1", path=p) == ("lead",)
        assert load_conversion_action_types("act_2", path=p) is None


# ---------------------------------------------------------------------------
# #534 — one ad account, one platform key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDuplicateAccountEntryGuard:
    """#534 — a write that would create a SECOND platform key for an ad account
    already stored under another key is rejected.

    The guard lives in the state layer rather than only in the MCP handler
    because the writer that produced the observed duplicate writes through
    these functions directly and never passes MCP validation.
    """

    def _seed(self, tmp_path: Path, platform: str, account_id: str) -> Path:
        path = tmp_path / "STATE.json"
        set_platform_metrics(path, platform, account_id, totals={"spend": 1.0})
        return path

    def test_second_key_for_the_same_account_is_rejected(self, tmp_path: Path) -> None:
        path = self._seed(tmp_path, "meta_ads", "act_1")
        with pytest.raises(ValueError) as exc:
            set_platform_metrics(
                path, "plugin:mureo-logly-bridge", "act_1", totals={"spend": 2.0}
            )
        message = str(exc.value)
        # Names BOTH keys and the account so the operator can repair it.
        assert "plugin:mureo-logly-bridge" in message
        assert "meta_ads" in message
        assert "act_1" in message
        # Fail-before-write: no second entry landed.
        assert set(read_state_file(path).platforms) == {"meta_ads"}

    def test_non_canonical_and_canonical_plugin_key_collide(
        self, tmp_path: Path
    ) -> None:
        """The registry-name spelling and the canonical ``plugin:<dist>`` key
        are two keys for one account — exactly the #533 ingress."""
        path = self._seed(tmp_path, "mureo-logly-bridge", "act_1")
        with pytest.raises(ValueError, match="mureo-logly-bridge"):
            set_platform_metrics(
                path, "plugin:mureo-logly-bridge", "act_1", totals={"spend": 2.0}
            )

    def test_act_prefix_variants_are_the_same_account(self, tmp_path: Path) -> None:
        path = self._seed(tmp_path, "meta_ads", "123456")
        with pytest.raises(ValueError, match="123456"):
            set_platform_metrics(path, "plugin:x", "act_123456", totals={"spend": 2.0})

    def test_update_of_an_existing_entry_always_succeeds(self, tmp_path: Path) -> None:
        """An operator whose document ALREADY holds the duplicate pair must
        still be able to sync — rejecting their updates would strand them with
        state they cannot fix."""
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        "meta_ads": {"account_id": "act_1", "campaigns": []},
                        "plugin:mureo-logly-bridge": {
                            "account_id": "act_1",
                            "campaigns": [],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        doc = set_platform_metrics(path, "meta_ads", "act_1", totals={"spend": 9.0})
        assert doc.platforms["meta_ads"].totals == {"spend": 9.0}
        doc = set_platform_metrics(
            path, "plugin:mureo-logly-bridge", "act_1", totals={"spend": 8.0}
        )
        assert doc.platforms["plugin:mureo-logly-bridge"].totals == {"spend": 8.0}
        # Neither entry was deleted or merged — repair is the operator's call.
        assert set(doc.platforms) == {"meta_ads", "plugin:mureo-logly-bridge"}

    def test_different_accounts_under_different_keys_are_fine(
        self, tmp_path: Path
    ) -> None:
        path = self._seed(tmp_path, "google_ads", "123")
        doc = set_platform_metrics(path, "meta_ads", "act_9", totals={"spend": 2.0})
        assert set(doc.platforms) == {"google_ads", "meta_ads"}

    def test_empty_stored_account_id_never_joins(self, tmp_path: Path) -> None:
        """``""`` is "unknown", not a value that equals another ``""``."""
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {"legacy": {"account_id": "", "campaigns": []}},
                }
            ),
            encoding="utf-8",
        )
        doc = set_platform_metrics(path, "meta_ads", "act_1", totals={"spend": 1.0})
        assert set(doc.platforms) == {"legacy", "meta_ads"}

    def test_empty_incoming_account_id_never_joins(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {"legacy": {"account_id": "", "campaigns": []}},
                }
            ),
            encoding="utf-8",
        )
        doc = set_platform_metrics(path, "meta_ads", "", totals={"spend": 1.0})
        assert set(doc.platforms) == {"legacy", "meta_ads"}

    def test_upsert_campaign_shares_the_guard(self, tmp_path: Path) -> None:
        """Same key-only get-then-overwrite shape, same ingress."""
        path = self._seed(tmp_path, "meta_ads", "act_1")
        with pytest.raises(ValueError, match="meta_ads"):
            upsert_campaign(
                path,
                CampaignSnapshot(campaign_id="c1", campaign_name="C1", status="ACTIVE"),
                platform="plugin:mureo-logly-bridge",
                account_id="act_1",
            )
        assert set(read_state_file(path).platforms) == {"meta_ads"}

    def test_set_conversion_action_types_shares_the_guard(self, tmp_path: Path) -> None:
        from mureo.context.state import set_conversion_action_types

        path = self._seed(tmp_path, "meta_ads", "act_1")
        with pytest.raises(ValueError, match="meta_ads"):
            set_conversion_action_types(
                path, "plugin:mureo-logly-bridge", "act_1", ["lead"]
            )
        assert set(read_state_file(path).platforms) == {"meta_ads"}

    def test_rejects_a_platform_key_that_is_not_a_key(self, tmp_path: Path) -> None:
        """An empty / whitespace-only key, a plugin key carrying no
        distribution (``"plugin:"``), and one claiming the per-provider form
        while naming no provider (``"plugin:<dist>:"``, #537), are not
        usable keys."""
        path = tmp_path / "STATE.json"
        for bad in ("", "   ", "plugin:", "plugin:mureo-logly-bridge:"):
            with pytest.raises(ValueError, match="platform"):
                set_platform_metrics(path, bad, "act_1", totals={"spend": 1.0})
        assert not path.exists()

    def test_a_canonical_plugin_key_is_written_verbatim(self, tmp_path: Path) -> None:
        """The write path never rewrites the key the operator passed."""
        path = tmp_path / "STATE.json"
        doc = set_platform_metrics(
            path, "plugin:mureo-logly-bridge", "act_1", totals={"spend": 1.0}
        )
        assert set(doc.platforms) == {"plugin:mureo-logly-bridge"}

    def test_the_per_provider_key_is_accepted_and_written_verbatim(
        self, tmp_path: Path
    ) -> None:
        """#537 — the write guard accepts ``plugin:<dist>:<provider>``.

        Two providers of one distribution are two separate accounts, so
        they must both land rather than one being refused as a duplicate.
        """
        path = tmp_path / "STATE.json"
        set_platform_metrics(
            path,
            "plugin:mureo-lineyahoo-bridge:line_ads",
            "act_line",
            totals={"spend": 1.0},
        )
        doc = set_platform_metrics(
            path,
            "plugin:mureo-lineyahoo-bridge:yahoo_ads",
            "act_yahoo",
            totals={"spend": 2.0},
        )
        assert set(doc.platforms) == {
            "plugin:mureo-lineyahoo-bridge:line_ads",
            "plugin:mureo-lineyahoo-bridge:yahoo_ads",
        }

    def test_legacy_and_per_provider_keys_for_one_account_still_collide(
        self, tmp_path: Path
    ) -> None:
        """#534's guard is unchanged by #537 — and this is the migration cost.

        An operator whose STATE.json already holds ``plugin:<dist>`` for an
        account, writing that same account under the new per-provider key,
        is refused rather than quietly given two entries the Reports view
        would sum. mureo does not merge or rewrite either entry; the
        operator decides.
        """
        path = tmp_path / "STATE.json"
        set_platform_metrics(
            path, "plugin:mureo-logly-bridge", "act_1", totals={"spend": 1.0}
        )
        with pytest.raises(ValueError, match="plugin:mureo-logly-bridge"):
            set_platform_metrics(
                path,
                "plugin:mureo-logly-bridge:logly_ads_context",
                "act_1",
                totals={"spend": 1.0},
            )

    # -- re-pointing an EXISTING key at a different account -----------------
    #
    # "Create" is not "the key is absent". Reusing a key while changing which
    # account it describes manufactures a brand-new duplicate through the
    # guarded functions themselves, which is how the first cut of this guard
    # leaked.

    def test_repointing_a_key_onto_a_taken_account_is_rejected(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        set_platform_metrics(path, "google_ads", "act_2", totals={"spend": 1.0})
        set_platform_metrics(path, "meta_ads", "act_1", totals={"spend": 1.0})
        # meta_ads exists, but re-pointing it at act_2 would make TWO keys for
        # act_2 — a create in every sense that matters.
        with pytest.raises(ValueError) as exc:
            set_platform_metrics(path, "meta_ads", "act_2", totals={"spend": 5.0})
        message = str(exc.value)
        assert "meta_ads" in message
        assert "google_ads" in message
        assert "act_2" in message
        stored = {k: v.account_id for k, v in read_state_file(path).platforms.items()}
        assert stored == {"google_ads": "act_2", "meta_ads": "act_1"}

    def test_repointing_a_key_onto_a_free_account_is_allowed(
        self, tmp_path: Path
    ) -> None:
        """Re-pointing at an account nobody else holds is a legitimate move
        (an operator switching which account a platform tracks)."""
        path = tmp_path / "STATE.json"
        set_platform_metrics(path, "meta_ads", "act_1", totals={"spend": 1.0})
        doc = set_platform_metrics(path, "meta_ads", "act_9", totals={"spend": 5.0})
        assert doc.platforms["meta_ads"].account_id == "act_9"

    def test_a_plain_update_keeps_working(self, tmp_path: Path) -> None:
        """Branch 1: the stored id MATCHES the incoming one — nothing about
        identity changes, so the write is a plain update."""
        path = tmp_path / "STATE.json"
        set_platform_metrics(path, "meta_ads", "123456", totals={"spend": 1.0})
        # act_-tolerant: the same account in the other spelling is still a
        # plain update, not a re-point.
        doc = set_platform_metrics(path, "meta_ads", "act_123456", totals={"spend": 2})
        assert doc.platforms["meta_ads"].totals == {"spend": 2}

    def test_stamping_an_id_onto_an_idless_entry_is_allowed_even_if_it_collides(
        self, tmp_path: Path
    ) -> None:
        """Branch 2, and deliberately NOT a hole.

        The existing entry has no ``account_id``, so it does not yet claim any
        account. Stamping one on cannot create a real-world duplicate: if the
        two keys really are one account, that was already true and merely
        invisible. Allowing the write is what makes the duplicate DETECTABLE
        (``duplicate_account_entries`` can now see it) and therefore
        surfaceable to the operator — rejecting would block the very write
        that reveals the problem. This is the repair path.
        """
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        "google_ads": {"account_id": "act_1"},
                        "legacy": {"account_id": ""},
                    },
                }
            ),
            encoding="utf-8",
        )
        doc = set_platform_metrics(path, "legacy", "act_1", totals={"spend": 1.0})
        assert doc.platforms["legacy"].account_id == "act_1"
        # ...and the now-visible duplicate is reported by the shared join.
        from mureo.context.platform_accounts import duplicate_account_entries

        (group,) = duplicate_account_entries(doc.platforms)
        assert group.platform_keys == ("google_ads", "legacy")

    def test_upsert_campaign_rejects_a_repoint(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_platform_metrics(path, "google_ads", "act_2", totals={"spend": 1.0})
        set_platform_metrics(path, "meta_ads", "act_1", totals={"spend": 1.0})
        with pytest.raises(ValueError, match="google_ads"):
            upsert_campaign(
                path,
                CampaignSnapshot(campaign_id="c1", campaign_name="C1", status="ACTIVE"),
                platform="meta_ads",
                account_id="act_2",
            )
        assert read_state_file(path).platforms["meta_ads"].account_id == "act_1"

    def test_set_conversion_action_types_rejects_a_repoint(
        self, tmp_path: Path
    ) -> None:
        from mureo.context.state import set_conversion_action_types

        path = tmp_path / "STATE.json"
        set_platform_metrics(path, "google_ads", "act_2", totals={"spend": 1.0})
        set_platform_metrics(path, "meta_ads", "act_1", totals={"spend": 1.0})
        with pytest.raises(ValueError, match="google_ads"):
            set_conversion_action_types(path, "meta_ads", "act_2", ["lead"])
        assert read_state_file(path).platforms["meta_ads"].account_id == "act_1"

    def test_rejects_a_padded_key_on_create(self, tmp_path: Path) -> None:
        """``" google_ads"`` is a distinct dict key from ``"google_ads"`` —
        never intentional, and another route to two entries for one account."""
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="surrounding whitespace"):
            set_platform_metrics(path, " google_ads", "123", totals={"spend": 1.0})
        assert not path.exists()

    def test_a_padded_key_that_already_exists_stays_writable(
        self, tmp_path: Path
    ) -> None:
        """Same create-vs-update rule as the duplicate guard: an operator
        holding a padded entry must still be able to write to it (and the key
        is never silently stripped — that would change what they see)."""
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {" google_ads": {"account_id": "123"}},
                }
            ),
            encoding="utf-8",
        )
        doc = set_platform_metrics(path, " google_ads", "123", totals={"spend": 1.0})
        assert doc.platforms[" google_ads"].totals == {"spend": 1.0}
        assert set(doc.platforms) == {" google_ads"}

    def test_an_unusable_key_that_already_exists_stays_writable(
        self, tmp_path: Path
    ) -> None:
        """The create-vs-update rule covers EVERY key check, not just the
        duplicate one — otherwise a bad key strands the operator holding it."""
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {"version": "2", "platforms": {"plugin:": {"account_id": "123"}}}
            ),
            encoding="utf-8",
        )
        doc = set_platform_metrics(path, "plugin:", "123", totals={"spend": 1.0})
        assert doc.platforms["plugin:"].totals == {"spend": 1.0}


# ---------------------------------------------------------------------------
# #534 — whole-document writes: detection, not enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWholeDocumentDuplicateWarning:
    """A writer that assembles a whole ``StateDocument`` and writes it wholesale
    never touches the upsert helpers, so the create-time guard cannot see it.

    ``write_state_file`` is the one funnel every such writer goes through
    (``FilesystemStateStore.write_state`` included), so the duplicate is at
    least made VISIBLE there. It must not reject: a document that already
    contains a duplicate has to stay writable or the operator can never repair
    it.
    """

    def _duplicated_doc(self) -> StateDocument:
        return StateDocument(
            version="2",
            platforms={
                "meta_ads": PlatformState(account_id="act_1"),
                "plugin:mureo-logly-bridge": PlatformState(account_id="1"),
            },
        )

    # The warn-once latch is reset by the session-wide autouse fixture in
    # tests/conftest.py — see there for why it does not live on this class.

    def test_warns_naming_both_keys_and_the_account(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "STATE.json"
        with caplog.at_level(logging.WARNING, logger="mureo.context.platform_guards"):
            write_state_file(path, self._duplicated_doc())
        (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
        message = record.getMessage()
        assert "meta_ads" in message
        assert "plugin:mureo-logly-bridge" in message
        assert "act_1" in message

    def test_the_write_still_happens(self, tmp_path: Path) -> None:
        """Detection, NOT enforcement — the document must land on disk."""
        path = tmp_path / "STATE.json"
        write_state_file(path, self._duplicated_doc())
        assert set(read_state_file(path).platforms) == {
            "meta_ads",
            "plugin:mureo-logly-bridge",
        }

    def test_warns_once_per_process_per_group(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """This runs on every write; a per-call warning would flood the log."""
        path = tmp_path / "STATE.json"
        with caplog.at_level(logging.WARNING, logger="mureo.context.platform_guards"):
            write_state_file(path, self._duplicated_doc())
            write_state_file(path, self._duplicated_doc())
            write_state_file(path, self._duplicated_doc())
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    def test_a_different_group_still_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The latch is per key-pair, so one warned pair cannot silence another."""
        path = tmp_path / "STATE.json"
        other = StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(account_id="999"),
                "plugin:other": PlatformState(account_id="999"),
            },
        )
        with caplog.at_level(logging.WARNING, logger="mureo.context.platform_guards"):
            write_state_file(path, self._duplicated_doc())
            write_state_file(path, other)
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2

    def test_the_same_group_in_another_workspace_still_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The latch is keyed by (path, group): an agency process serves many
        workspaces, and one tenant's duplicate must not silence another's."""
        one = tmp_path / "a" / "STATE.json"
        two = tmp_path / "b" / "STATE.json"
        with caplog.at_level(logging.WARNING, logger="mureo.context.platform_guards"):
            write_state_file(one, self._duplicated_doc())
            write_state_file(two, self._duplicated_doc())
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2
        assert str(one) in warnings[0].getMessage()
        assert str(two) in warnings[1].getMessage()

    def test_the_latch_is_bounded(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """It must not grow without bound in a long-lived multi-tenant process.
        Clearing (rather than evicting) biases towards warning again, which is
        the safe direction for a visibility feature."""
        from mureo.context import platform_guards

        cap = platform_guards._DUPLICATE_ACCOUNT_WARN_LATCH_MAX
        with caplog.at_level(logging.WARNING, logger="mureo.context.platform_guards"):
            for i in range(cap + 5):
                write_state_file(
                    tmp_path / str(i) / "STATE.json", self._duplicated_doc()
                )
        assert len(platform_guards._DUPLICATE_ACCOUNT_WARNED) <= cap

    def test_a_clean_document_is_silent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "STATE.json"
        doc = StateDocument(
            version="2",
            platforms={
                "meta_ads": PlatformState(account_id="act_1"),
                "google_ads": PlatformState(account_id="999"),
                "legacy": PlatformState(account_id=""),
            },
        )
        with caplog.at_level(logging.WARNING, logger="mureo.context.platform_guards"):
            write_state_file(path, doc)
        assert [r for r in caplog.records if r.levelno == logging.WARNING] == []

    def test_the_store_write_state_path_is_covered(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The observed producer writes a whole document through the store."""
        from mureo.core.state_store import FilesystemStateStore

        store = FilesystemStateStore(workspace=tmp_path)
        with caplog.at_level(logging.WARNING, logger="mureo.context.platform_guards"):
            store.write_state(self._duplicated_doc())
        assert [r for r in caplog.records if r.levelno == logging.WARNING]
        assert set(store.read_state().platforms) == {
            "meta_ads",
            "plugin:mureo-logly-bridge",
        }


# ---------------------------------------------------------------------------
# #468 — ad-level state
# ---------------------------------------------------------------------------


class TestAdState:
    """Ad-level delivery status persisted under its campaign.

    Without this, ``/sync-state`` and ``/daily-check`` have nowhere to record
    what each ad's status was, so every run re-discovers (or misses) a manual
    pause and no run can diff against the previous one.
    """

    @pytest.mark.unit
    def test_ad_state_is_frozen(self) -> None:
        from mureo.context.models import AdState

        ad = AdState(ad_id="ad_1")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ad.ad_id = "ad_2"  # type: ignore[misc]

    @pytest.mark.unit
    def test_ad_state_optional_fields_default_to_none(self) -> None:
        from mureo.context.models import AdState

        ad = AdState(ad_id="ad_1")
        assert ad.name is None
        assert ad.status is None
        assert ad.effective_status is None
        assert ad.as_of is None

    @pytest.mark.unit
    def test_campaign_ads_round_trip(self) -> None:
        """A campaign's ads survive render -> parse unchanged."""
        from mureo.context.models import AdState

        doc = StateDocument(
            version="2",
            platforms={
                "meta_ads": PlatformState(
                    account_id="act_1",
                    campaigns=(
                        CampaignSnapshot(
                            campaign_id="c1",
                            campaign_name="Prospecting",
                            status="ACTIVE",
                            ads=(
                                AdState(
                                    ad_id="ad_1",
                                    name="Creative A",
                                    status="ACTIVE",
                                    effective_status="ADSET_PAUSED",
                                    as_of="2026-07-29T10:00:00+09:00",
                                ),
                            ),
                        ),
                    ),
                )
            },
        )
        reparsed = parse_state(render_state(doc))
        ads = reparsed.platforms["meta_ads"].campaigns[0].ads
        assert ads is not None
        assert ads[0].ad_id == "ad_1"
        assert ads[0].name == "Creative A"
        assert ads[0].status == "ACTIVE"
        assert ads[0].effective_status == "ADSET_PAUSED"
        assert ads[0].as_of == "2026-07-29T10:00:00+09:00"

    @pytest.mark.unit
    def test_ads_is_a_tuple_after_construction(self) -> None:
        """Defensive copy: a caller-supplied list becomes an immutable tuple."""
        from mureo.context.models import AdState

        snap = CampaignSnapshot(
            campaign_id="c1",
            campaign_name="C",
            status="ACTIVE",
            ads=[AdState(ad_id="ad_1")],  # type: ignore[arg-type]
        )
        assert isinstance(snap.ads, tuple)

    @pytest.mark.unit
    def test_legacy_state_without_ads_loads_and_emits_no_ads_key(self) -> None:
        """Backward compatibility: a STATE.json written before this field
        parses unchanged AND does not gain an ``ads`` key on the next write
        (no diff churn for accounts that never fetched ad-level status)."""
        legacy = {
            "version": "2",
            "last_synced_at": "2026-07-01T00:00:00+09:00",
            "customer_id": None,
            "campaigns": [
                {
                    "campaign_id": "c1",
                    "campaign_name": "Legacy",
                    "status": "ENABLED",
                    "bidding_strategy_type": None,
                    "bidding_details": None,
                    "daily_budget": 5000.0,
                    "device_targeting": None,
                    "campaign_goal": None,
                    "notes": None,
                }
            ],
            "platforms": None,
            "action_log": [
                {
                    "timestamp": "2026-07-01T00:00:00+09:00",
                    "action": "budget_update",
                    "platform": "meta_ads",
                }
            ],
        }
        doc = parse_state(json.dumps(legacy))
        assert doc.campaigns[0].ads is None
        assert doc.action_log[0].ad_id is None
        rendered = json.loads(render_state(doc))
        assert "ads" not in rendered["campaigns"][0]
        assert "ad_id" not in rendered["action_log"][0]
        # Byte-stable round-trip of the legacy document.
        assert rendered == legacy

    @pytest.mark.unit
    def test_parse_ads_requires_ad_id(self) -> None:
        data = {
            "version": "2",
            "campaigns": [
                {
                    "campaign_id": "c1",
                    "campaign_name": "C",
                    "status": "ACTIVE",
                    "ads": [{"name": "no id"}],
                }
            ],
        }
        with pytest.raises(ValueError, match="ad_id"):
            parse_state(json.dumps(data))

    @pytest.mark.unit
    def test_parse_ads_tolerant_mode_skips_malformed_entry(self) -> None:
        """The read-only Reports view must not blank a whole document over a
        single hand-authored ad entry."""
        data = {
            "version": "2",
            "campaigns": [
                {
                    "campaign_id": "c1",
                    "campaign_name": "C",
                    "status": "ACTIVE",
                    "ads": [{"name": "no id"}, {"ad_id": "ad_ok"}],
                }
            ],
        }
        doc = parse_state(json.dumps(data), strict=False)
        ads = doc.campaigns[0].ads
        assert ads is not None
        assert [a.ad_id for a in ads] == ["ad_ok"]

    @pytest.mark.unit
    def test_action_log_entry_carries_ad_id(self) -> None:
        """An ad-level pause must be attributable to a specific ad, so a later
        run can match the observed status against what mureo itself did."""
        entry = ActionLogEntry(
            timestamp="2026-07-29T10:00:00+09:00",
            action="ad_pause",
            platform="meta_ads",
            campaign_id="c1",
            ad_id="ad_1",
        )
        doc = StateDocument(version="2", action_log=(entry,))
        reparsed = parse_state(render_state(doc))
        assert reparsed.action_log[0].ad_id == "ad_1"

    @pytest.mark.unit
    def test_upsert_campaign_persists_ads(self, tmp_path: Path) -> None:
        from mureo.context.models import AdState

        path = tmp_path / "STATE.json"
        campaign = CampaignSnapshot(
            campaign_id="c1",
            campaign_name="Prospecting",
            status="ACTIVE",
            ads=(AdState(ad_id="ad_1", status="ACTIVE", effective_status="ACTIVE"),),
        )
        upsert_campaign(path, campaign, platform="meta_ads", account_id="act_1")
        doc = read_state_file(path)
        ads = doc.platforms["meta_ads"].campaigns[0].ads
        assert ads is not None
        assert ads[0].ad_id == "ad_1"

    @pytest.mark.unit
    def test_upsert_campaign_preserves_ads_when_not_resupplied(
        self, tmp_path: Path
    ) -> None:
        """A later upsert that carries no ``ads`` must not wipe the ad-level
        state a prior run recorded.

        ``/sync-state`` and ``/daily-check`` fetch ads only for ACTIVE
        campaigns (an API-cost guard), so the very moment a campaign is
        paused — exactly when "what were its ads doing?" matters most — the
        next metrics-only upsert would otherwise reset ``ads`` from "last
        known statuses" back to "never fetched", silently destroying the
        audit trail this issue exists to create. Each ad carries its own
        ``as_of``, so an inherited value stays honestly dated.
        """
        from mureo.context.models import AdState

        path = tmp_path / "STATE.json"
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="Prospecting",
                status="ACTIVE",
                ads=(
                    AdState(
                        ad_id="ad_1",
                        status="ACTIVE",
                        effective_status="ACTIVE",
                        as_of="2026-07-28T10:00:00+09:00",
                    ),
                ),
            ),
            platform="meta_ads",
            account_id="act_1",
        )
        # Second write: campaign now PAUSED, no ad-level fetch this run.
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1", campaign_name="Prospecting", status="PAUSED"
            ),
            platform="meta_ads",
            account_id="act_1",
        )

        doc = read_state_file(path)
        snap = doc.platforms["meta_ads"].campaigns[0]
        assert snap.status == "PAUSED"
        assert snap.ads is not None, "prior ad-level state must survive"
        assert snap.ads[0].ad_id == "ad_1"
        assert snap.ads[0].as_of == "2026-07-28T10:00:00+09:00"
        # The legacy v1 flat list is platform-blind, so it deliberately does
        # NOT inherit — see test_legacy_flat_list_does_not_bleed_ads_across_
        # platforms. The v2 platforms section is the one the dashboard and the
        # skills read.
        assert doc.campaigns[0].status == "PAUSED"
        assert doc.campaigns[0].ads is None

    @pytest.mark.unit
    def test_upsert_campaign_replaces_ads_when_resupplied(self, tmp_path: Path) -> None:
        """Preservation must not become stickiness: a fresh fetch replaces the
        stored ads wholesale, including removing ads that no longer exist."""
        from mureo.context.models import AdState

        path = tmp_path / "STATE.json"
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="P",
                status="ACTIVE",
                ads=(AdState(ad_id="ad_1"), AdState(ad_id="ad_2")),
            ),
            platform="meta_ads",
            account_id="act_1",
        )
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="P",
                status="ACTIVE",
                ads=(AdState(ad_id="ad_1", status="PAUSED"),),
            ),
            platform="meta_ads",
            account_id="act_1",
        )

        doc = read_state_file(path)
        ads = doc.platforms["meta_ads"].campaigns[0].ads
        assert ads is not None
        assert [a.ad_id for a in ads] == ["ad_1"]
        assert ads[0].status == "PAUSED"

    @pytest.mark.unit
    def test_upsert_campaign_empty_ads_list_clears_stored_ads(
        self, tmp_path: Path
    ) -> None:
        """``()`` means "fetched, this campaign has no ads" and is a real
        observation — it must overwrite, not be treated as 'not supplied'."""
        from mureo.context.models import AdState

        path = tmp_path / "STATE.json"
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="P",
                status="ACTIVE",
                ads=(AdState(ad_id="ad_1"),),
            ),
            platform="meta_ads",
            account_id="act_1",
        )
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1", campaign_name="P", status="ACTIVE", ads=()
            ),
            platform="meta_ads",
            account_id="act_1",
        )

        doc = read_state_file(path)
        assert doc.platforms["meta_ads"].campaigns[0].ads == ()

    @pytest.mark.unit
    def test_legacy_flat_list_does_not_bleed_ads_across_platforms(
        self, tmp_path: Path
    ) -> None:
        """Ad inheritance must be platform-scoped.

        The legacy v1 flat ``campaigns`` list is matched on ``campaign_id``
        ALONE — it has no platform dimension — so two platforms that happen to
        reuse an id (Google and Meta ids are independent namespaces; a bare
        numeric collision is entirely possible) match each other there. If the
        flat list inherited ``ads``, a Google campaign upsert would silently
        adopt the Meta campaign's ad statuses and mureo would report ads that
        belong to a different account. Inheritance therefore lives only in the
        platform-scoped v2 path; the legacy list keeps full-replace semantics.
        """
        from mureo.context.models import AdState

        path = tmp_path / "STATE.json"
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="Meta Prospecting",
                status="ACTIVE",
                ads=(AdState(ad_id="meta_ad_1", status="ACTIVE"),),
            ),
            platform="meta_ads",
            account_id="act_1",
        )
        # Same campaign_id under a DIFFERENT platform, with no ad-level fetch.
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1", campaign_name="Google Brand", status="ENABLED"
            ),
            platform="google_ads",
            account_id="123",
        )

        doc = read_state_file(path)
        # v2: per-platform isolation — Google gains nothing, Meta keeps its own.
        assert doc.platforms["google_ads"].campaigns[0].ads is None
        meta_ads_state = doc.platforms["meta_ads"].campaigns[0].ads
        assert meta_ads_state is not None
        assert meta_ads_state[0].ad_id == "meta_ad_1"
        # v1 legacy flat list: full replace, no cross-platform inheritance.
        flat = [c for c in doc.campaigns if c.campaign_id == "c1"]
        assert len(flat) == 1
        assert flat[0].campaign_name == "Google Brand"
        assert flat[0].ads is None, "legacy flat list must not inherit ads"

    @pytest.mark.unit
    def test_v2_inheritance_still_works_for_the_same_platform(
        self, tmp_path: Path
    ) -> None:
        """Guard against over-correcting: scoping inheritance to v2 must not
        disable it for repeat upserts on the SAME platform."""
        from mureo.context.models import AdState

        path = tmp_path / "STATE.json"
        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="P",
                status="ACTIVE",
                ads=(AdState(ad_id="ad_1", status="ACTIVE"),),
            ),
            platform="meta_ads",
            account_id="act_1",
        )
        upsert_campaign(
            path,
            CampaignSnapshot(campaign_id="c1", campaign_name="P", status="PAUSED"),
            platform="meta_ads",
            account_id="act_1",
        )

        doc = read_state_file(path)
        ads = doc.platforms["meta_ads"].campaigns[0].ads
        assert ads is not None and ads[0].ad_id == "ad_1"
