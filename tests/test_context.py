"""ファイルベースコンテキストモジュールのテスト（STRATEGY.md / STATE.json）."""

from __future__ import annotations

import copy
import json
import logging
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from mureo.context.errors import ContextFileError
from mureo.context.models import CampaignSnapshot, StateDocument, StrategyEntry
from mureo.context.state import (
    get_campaign,
    parse_state,
    read_state_file,
    render_state,
    upsert_campaign,
    write_state_file,
)
from mureo.context.strategy import (
    add_strategy_entry,
    parse_strategy,
    read_strategy_file,
    remove_strategy_entry,
    render_strategy,
    write_strategy_file,
)


# ============================================================
# STRATEGY.md テスト
# ============================================================


class TestParseStrategy:
    """STRATEGY.md パーステスト."""

    @pytest.mark.unit
    def test_parse_strategy_empty(self) -> None:
        """空文字列をパースして空リストを返す."""
        result = parse_strategy("")
        assert result == []

    @pytest.mark.unit
    def test_parse_strategy_single_section(self) -> None:
        """1セクションのパース."""
        md = "# Strategy\n\n## Persona\nターゲットは30代男性\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "persona"
        assert result[0].title == "Persona"
        assert result[0].content == "ターゲットは30代男性"

    @pytest.mark.unit
    def test_parse_strategy_multiple_sections(self) -> None:
        """複数セクションのパース."""
        md = (
            "# Strategy\n\n"
            "## Persona\nターゲットは30代男性\n\n"
            "## USP\n業界最安値の広告運用自動化ツール\n\n"
            "## Target Audience\n- 年齢: 25-45歳\n- 職種: マーケター\n"
        )
        result = parse_strategy(md)
        assert len(result) == 3
        assert result[0].context_type == "persona"
        assert result[1].context_type == "usp"
        assert result[2].context_type == "target_audience"
        assert result[2].content == "- 年齢: 25-45歳\n- 職種: マーケター"

    @pytest.mark.unit
    def test_parse_strategy_custom_type(self) -> None:
        """`## Custom: タイトル` のパース."""
        md = "# Strategy\n\n## Custom: 季節要因\n年末商戦に向けてCPA許容値を上げる\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "custom"
        assert result[0].title == "季節要因"
        assert result[0].content == "年末商戦に向けてCPA許容値を上げる"

    @pytest.mark.unit
    def test_parse_strategy_deep_research(self) -> None:
        """`## Deep Research: タイトル` のパース."""
        md = "# Strategy\n\n## Deep Research: 競合調査\n競合A社の広告戦略は...\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "deep_research"
        assert result[0].title == "競合調査"
        assert result[0].content == "競合A社の広告戦略は..."

    @pytest.mark.unit
    def test_parse_strategy_sales_material(self) -> None:
        """`## Sales Material: タイトル` のパース."""
        md = "# Strategy\n\n## Sales Material: 営業資料Q4\n四半期の実績...\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "sales_material"
        assert result[0].title == "営業資料Q4"

    @pytest.mark.unit
    def test_parse_strategy_operation_mode(self) -> None:
        """`## Operation Mode` のパース."""
        md = "# Strategy\n\n## Operation Mode\nTURNAROUND_RESCUE\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "operation_mode"
        assert result[0].title == "Operation Mode"
        assert result[0].content == "TURNAROUND_RESCUE"

    @pytest.mark.unit
    def test_parse_strategy_unknown_section_ignored(self) -> None:
        """未知のセクションはスキップ."""
        md = (
            "# Strategy\n\n"
            "## Persona\nターゲット\n\n"
            "## Unknown Section\nこれは無視される\n\n"
            "## USP\n強み\n"
        )
        result = parse_strategy(md)
        assert len(result) == 2
        assert result[0].context_type == "persona"
        assert result[1].context_type == "usp"


class TestRenderStrategy:
    """STRATEGY.md レンダリングテスト."""

    @pytest.mark.unit
    def test_render_strategy(self) -> None:
        """StrategyEntry列からMarkdown文字列を生成."""
        entries = [
            StrategyEntry(context_type="persona", title="Persona", content="30代男性"),
            StrategyEntry(context_type="usp", title="USP", content="業界最安値"),
        ]
        md = render_strategy(entries)
        assert "# Strategy" in md
        assert "## Persona" in md
        assert "30代男性" in md
        assert "## USP" in md
        assert "業界最安値" in md

    @pytest.mark.unit
    def test_render_strategy_custom(self) -> None:
        """Custom型のレンダリング."""
        entries = [
            StrategyEntry(
                context_type="custom", title="季節要因", content="年末商戦"
            ),
        ]
        md = render_strategy(entries)
        assert "## Custom: 季節要因" in md

    @pytest.mark.unit
    def test_render_parse_roundtrip(self) -> None:
        """render -> parse -> render で内容が保持される."""
        original = [
            StrategyEntry(context_type="persona", title="Persona", content="30代男性"),
            StrategyEntry(context_type="usp", title="USP", content="業界最安値"),
            StrategyEntry(
                context_type="custom", title="季節要因", content="年末商戦"
            ),
            StrategyEntry(
                context_type="deep_research", title="競合調査", content="A社は..."
            ),
            StrategyEntry(
                context_type="operation_mode",
                title="Operation Mode",
                content="SCALE_EXPANSION",
            ),
        ]
        md = render_strategy(original)
        parsed = parse_strategy(md)
        assert len(parsed) == len(original)
        for orig, p in zip(original, parsed):
            assert orig.context_type == p.context_type
            assert orig.content == p.content


class TestStrategyFile:
    """STRATEGY.md ファイルI/Oテスト."""

    @pytest.mark.unit
    def test_read_strategy_file(self, tmp_path: Path) -> None:
        """ファイルから読み取り."""
        fp = tmp_path / "STRATEGY.md"
        fp.write_text(
            "# Strategy\n\n## Persona\nターゲット\n", encoding="utf-8"
        )
        result = read_strategy_file(fp)
        assert len(result) == 1
        assert result[0].context_type == "persona"

    @pytest.mark.unit
    def test_write_strategy_file(self, tmp_path: Path) -> None:
        """ファイルに書き込み."""
        fp = tmp_path / "STRATEGY.md"
        entries = [
            StrategyEntry(context_type="persona", title="Persona", content="30代男性"),
        ]
        write_strategy_file(fp, entries)
        assert fp.exists()
        content = fp.read_text(encoding="utf-8")
        assert "## Persona" in content
        assert "30代男性" in content

    @pytest.mark.unit
    def test_read_strategy_file_not_exists(self, tmp_path: Path) -> None:
        """ファイルがない場合は空リスト."""
        fp = tmp_path / "STRATEGY.md"
        result = read_strategy_file(fp)
        assert result == []

    @pytest.mark.unit
    def test_add_strategy_entry(self, tmp_path: Path) -> None:
        """既存ファイルにエントリ追加."""
        fp = tmp_path / "STRATEGY.md"
        fp.write_text(
            "# Strategy\n\n## Persona\nターゲット\n", encoding="utf-8"
        )
        new_entry = StrategyEntry(
            context_type="usp", title="USP", content="業界最安値"
        )
        add_strategy_entry(fp, new_entry)
        result = read_strategy_file(fp)
        assert len(result) == 2
        assert result[0].context_type == "persona"
        assert result[1].context_type == "usp"

    @pytest.mark.unit
    def test_remove_strategy_entry(self, tmp_path: Path) -> None:
        """特定のcontext_typeのエントリ削除."""
        fp = tmp_path / "STRATEGY.md"
        entries = [
            StrategyEntry(context_type="persona", title="Persona", content="30代男性"),
            StrategyEntry(context_type="usp", title="USP", content="業界最安値"),
        ]
        write_strategy_file(fp, entries)
        remove_strategy_entry(fp, "persona")
        result = read_strategy_file(fp)
        assert len(result) == 1
        assert result[0].context_type == "usp"

    @pytest.mark.unit
    def test_remove_strategy_entry_custom_with_title(self, tmp_path: Path) -> None:
        """Custom型エントリをtitle指定で削除."""
        fp = tmp_path / "STRATEGY.md"
        entries = [
            StrategyEntry(context_type="custom", title="季節要因", content="年末商戦"),
            StrategyEntry(context_type="custom", title="その他", content="メモ"),
        ]
        write_strategy_file(fp, entries)
        remove_strategy_entry(fp, "custom", title="季節要因")
        result = read_strategy_file(fp)
        assert len(result) == 1
        assert result[0].title == "その他"


# ============================================================
# STATE.json テスト
# ============================================================


class TestParseState:
    """STATE.json パーステスト."""

    @pytest.mark.unit
    def test_parse_state_empty(self) -> None:
        """空JSONのパース."""
        result = parse_state("{}")
        assert result.version == "1"
        assert result.campaigns == ()

    @pytest.mark.unit
    def test_parse_state_with_campaigns(self) -> None:
        """キャンペーン入りのパース."""
        import json

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
    """STATE.json レンダリングテスト."""

    @pytest.mark.unit
    def test_render_state(self) -> None:
        """StateDocumentからJSON文字列を生成."""
        import json

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
        """render -> parse -> render で内容が保持される."""
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
    """STATE.json ファイルI/Oテスト."""

    @pytest.mark.unit
    def test_read_state_file(self, tmp_path: Path) -> None:
        """ファイルから読み取り."""
        import json

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
        """ファイルに書き込み."""
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
        import json

        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["customer_id"] == "123"

    @pytest.mark.unit
    def test_read_state_file_not_exists(self, tmp_path: Path) -> None:
        """ファイルがない場合はデフォルト値."""
        fp = tmp_path / "STATE.json"
        result = read_state_file(fp)
        assert result.version == "1"
        assert result.campaigns == ()

    @pytest.mark.unit
    def test_upsert_campaign(self, tmp_path: Path) -> None:
        """既存キャンペーンの更新（upsert）."""
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

        # ファイルにも反映されている
        reloaded = read_state_file(fp)
        assert reloaded.campaigns[0].campaign_name == "New Name"

    @pytest.mark.unit
    def test_upsert_campaign_new(self, tmp_path: Path) -> None:
        """新規キャンペーンの追加."""
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
        """campaign_idで検索."""
        doc = StateDocument(
            campaigns=(
                CampaignSnapshot(
                    campaign_id="1", campaign_name="A", status="ENABLED"
                ),
                CampaignSnapshot(
                    campaign_id="2", campaign_name="B", status="PAUSED"
                ),
            ),
        )
        found = get_campaign(doc, "2")
        assert found is not None
        assert found.campaign_name == "B"

        not_found = get_campaign(doc, "999")
        assert not_found is None


# ============================================================
# CRITICAL: CampaignSnapshot イミュータビリティテスト
# ============================================================


class TestCampaignSnapshotImmutability:
    """CampaignSnapshotのmutableフィールドが防御コピーされることを検証."""

    @pytest.mark.unit
    def test_bidding_details_deepcopy_on_init(self) -> None:
        """コンストラクタに渡したdictを後で変更してもSnapshotに影響しない."""
        original_details: dict[str, Any] = {"target_cpa": 3000, "nested": {"a": 1}}
        snapshot = CampaignSnapshot(
            campaign_id="1",
            campaign_name="Test",
            status="ENABLED",
            bidding_details=original_details,
        )
        # 外部のdictを変更
        original_details["target_cpa"] = 9999
        original_details["nested"]["a"] = 999

        # Snapshotには影響しない
        assert snapshot.bidding_details is not None
        assert snapshot.bidding_details["target_cpa"] == 3000
        assert snapshot.bidding_details["nested"]["a"] == 1

    @pytest.mark.unit
    def test_device_targeting_is_tuple(self) -> None:
        """device_targetingがtupleに変換される."""
        devices = [{"device_type": "MOBILE", "enabled": True}]
        snapshot = CampaignSnapshot(
            campaign_id="1",
            campaign_name="Test",
            status="ENABLED",
            device_targeting=devices,  # type: ignore[arg-type]
        )
        # tupleに変換されている
        assert isinstance(snapshot.device_targeting, tuple)

    @pytest.mark.unit
    def test_device_targeting_deepcopy_on_init(self) -> None:
        """コンストラクタに渡したlistの中身を変更してもSnapshotに影響しない."""
        devices = [{"device_type": "MOBILE", "enabled": True}]
        snapshot = CampaignSnapshot(
            campaign_id="1",
            campaign_name="Test",
            status="ENABLED",
            device_targeting=devices,  # type: ignore[arg-type]
        )
        # 外部のlistを変更
        devices[0]["enabled"] = False

        assert snapshot.device_targeting is not None
        assert snapshot.device_targeting[0]["enabled"] is True


# ============================================================
# HIGH-1: ファイルI/Oエラーハンドリングテスト
# ============================================================


class TestFileIOErrorHandling:
    """ファイルI/Oの異常系テスト."""

    @pytest.mark.unit
    def test_read_state_file_invalid_json(self, tmp_path: Path) -> None:
        """不正JSONファイルでContextFileErrorが送出される."""
        fp = tmp_path / "STATE.json"
        fp.write_text("{invalid json content", encoding="utf-8")
        with pytest.raises(ContextFileError):
            read_state_file(fp)

    @pytest.mark.unit
    def test_read_strategy_file_permission_error(self, tmp_path: Path) -> None:
        """権限エラーでContextFileErrorが送出される."""
        fp = tmp_path / "STRATEGY.md"
        fp.write_text("# Strategy\n\n## Persona\nTest\n", encoding="utf-8")
        # read_textがPermissionErrorを送出するようモック
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with pytest.raises(ContextFileError):
                read_strategy_file(fp)

    @pytest.mark.unit
    def test_read_state_file_permission_error(self, tmp_path: Path) -> None:
        """STATE.json権限エラーでContextFileErrorが送出される."""
        fp = tmp_path / "STATE.json"
        fp.write_text("{}", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with pytest.raises(ContextFileError):
                read_state_file(fp)

    @pytest.mark.unit
    def test_parse_state_missing_required_field_campaign_id(self) -> None:
        """campaign_id欠損でValueErrorが送出される."""
        data = {
            "campaigns": [
                {"campaign_name": "Test", "status": "ENABLED"}
            ]
        }
        with pytest.raises(ValueError, match="campaign_id"):
            parse_state(json.dumps(data))

    @pytest.mark.unit
    def test_parse_state_missing_required_field_campaign_name(self) -> None:
        """campaign_name欠損でValueErrorが送出される."""
        data = {
            "campaigns": [
                {"campaign_id": "1", "status": "ENABLED"}
            ]
        }
        with pytest.raises(ValueError, match="campaign_name"):
            parse_state(json.dumps(data))

    @pytest.mark.unit
    def test_parse_state_missing_required_field_status(self) -> None:
        """status欠損でValueErrorが送出される."""
        data = {
            "campaigns": [
                {"campaign_id": "1", "campaign_name": "Test"}
            ]
        }
        with pytest.raises(ValueError, match="status"):
            parse_state(json.dumps(data))


# ============================================================
# HIGH-2: アトミック書き込みテスト
# ============================================================


class TestAtomicWrite:
    """アトミック書き込みのテスト."""

    @pytest.mark.unit
    def test_write_state_file_atomic(self, tmp_path: Path) -> None:
        """書き込み後にファイルが正しい内容であること."""
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
        """親ディレクトリが存在しない場合に自動作成される."""
        fp = tmp_path / "subdir" / "deep" / "STATE.json"
        doc = StateDocument(version="1", customer_id="456")
        write_state_file(fp, doc)
        assert fp.exists()
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["customer_id"] == "456"

    @pytest.mark.unit
    def test_write_strategy_file_creates_parent_dir(self, tmp_path: Path) -> None:
        """Strategy書き込み時も親ディレクトリが自動作成される."""
        fp = tmp_path / "subdir" / "deep" / "STRATEGY.md"
        entries = [
            StrategyEntry(context_type="persona", title="Persona", content="Test"),
        ]
        write_strategy_file(fp, entries)
        assert fp.exists()
        assert "## Persona" in fp.read_text(encoding="utf-8")

    @pytest.mark.unit
    def test_write_state_file_atomic_failure_no_corrupt(self, tmp_path: Path) -> None:
        """書き込み失敗時に既存ファイルが壊れない."""
        fp = tmp_path / "STATE.json"
        original_doc = StateDocument(version="1", customer_id="original")
        write_state_file(fp, original_doc)

        # os.replaceをモックして失敗させる
        new_doc = StateDocument(version="1", customer_id="new")
        with patch("mureo.context.state.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                write_state_file(fp, new_doc)

        # 元のファイルは壊れていない
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["customer_id"] == "original"


# ============================================================
# WARNING-3: 未知セクションのlogging.warningテスト
# ============================================================


class TestUnknownSectionWarning:
    """未知セクションスキップ時のwarningログテスト."""

    @pytest.mark.unit
    def test_unknown_section_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """未知セクションのパース時にwarningがログ出力される."""
        md = (
            "# Strategy\n\n"
            "## Persona\nターゲット\n\n"
            "## Unknown Section\nこれは無視される\n\n"
            "## USP\n強み\n"
        )
        with caplog.at_level(logging.WARNING, logger="mureo.context.strategy"):
            result = parse_strategy(md)

        assert len(result) == 2
        assert any("Unknown Section" in record.message for record in caplog.records)


# ============================================================
# SUGGESTION-1: _TYPE_TO_PREFIX定数テスト
# ============================================================


class TestTypeToPrefixConstant:
    """モジュールレベルの_TYPE_TO_PREFIX定数が存在することを確認."""

    @pytest.mark.unit
    def test_type_to_prefix_exists(self) -> None:
        """strategy.pyに_TYPE_TO_PREFIX定数が定義されている."""
        from mureo.context import strategy
        assert hasattr(strategy, "_TYPE_TO_PREFIX")
        assert strategy._TYPE_TO_PREFIX["custom"] == "Custom"
        assert strategy._TYPE_TO_PREFIX["deep_research"] == "Deep Research"
        assert strategy._TYPE_TO_PREFIX["sales_material"] == "Sales Material"


# ============================================================
# __init__.py エクスポートテスト
# ============================================================


class TestInitExports:
    """__init__.pyのエクスポート確認."""

    @pytest.mark.unit
    def test_context_file_error_exported(self) -> None:
        """ContextFileErrorが__init__.pyからエクスポートされている."""
        import mureo.context as context_mod
        assert hasattr(context_mod, "ContextFileError")
        assert context_mod.ContextFileError is ContextFileError


# typing import for tests
from typing import Any
