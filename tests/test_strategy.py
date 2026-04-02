"""STRATEGY.md related tests (parsing, rendering, file I/O, Goal section)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from mureo.context.errors import ContextFileError
from mureo.context.models import StrategyEntry
from mureo.context.strategy import (
    add_strategy_entry,
    parse_strategy,
    read_strategy_file,
    remove_strategy_entry,
    render_strategy,
    write_strategy_file,
)


# ============================================================
# STRATEGY.md parse tests
# ============================================================


class TestParseStrategy:
    """STRATEGY.md parse tests."""

    @pytest.mark.unit
    def test_parse_strategy_empty(self) -> None:
        """Empty string parses to empty list."""
        result = parse_strategy("")
        assert result == []

    @pytest.mark.unit
    def test_parse_strategy_single_section(self) -> None:
        """Single section parse."""
        md = "# Strategy\n\n## Persona\nターゲットは30代男性\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "persona"
        assert result[0].title == "Persona"
        assert result[0].content == "ターゲットは30代男性"

    @pytest.mark.unit
    def test_parse_strategy_multiple_sections(self) -> None:
        """Multiple sections parse."""
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
        """`## Custom: title` parse."""
        md = "# Strategy\n\n## Custom: 季節要因\n年末商戦に向けてCPA許容値を上げる\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "custom"
        assert result[0].title == "季節要因"
        assert result[0].content == "年末商戦に向けてCPA許容値を上げる"

    @pytest.mark.unit
    def test_parse_strategy_deep_research(self) -> None:
        """`## Deep Research: title` parse."""
        md = "# Strategy\n\n## Deep Research: 競合調査\n競合A社の広告戦略は...\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "deep_research"
        assert result[0].title == "競合調査"
        assert result[0].content == "競合A社の広告戦略は..."

    @pytest.mark.unit
    def test_parse_strategy_sales_material(self) -> None:
        """`## Sales Material: title` parse."""
        md = "# Strategy\n\n## Sales Material: 営業資料Q4\n四半期の実績...\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "sales_material"
        assert result[0].title == "営業資料Q4"

    @pytest.mark.unit
    def test_parse_strategy_operation_mode(self) -> None:
        """`## Operation Mode` parse."""
        md = "# Strategy\n\n## Operation Mode\nTURNAROUND_RESCUE\n"
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "operation_mode"
        assert result[0].title == "Operation Mode"
        assert result[0].content == "TURNAROUND_RESCUE"

    @pytest.mark.unit
    def test_parse_strategy_unknown_section_ignored(self) -> None:
        """Unknown sections are skipped."""
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


# ============================================================
# STRATEGY.md render tests
# ============================================================


class TestRenderStrategy:
    """STRATEGY.md rendering tests."""

    @pytest.mark.unit
    def test_render_strategy(self) -> None:
        """Generate Markdown from StrategyEntry list."""
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
        """Custom type rendering."""
        entries = [
            StrategyEntry(context_type="custom", title="季節要因", content="年末商戦"),
        ]
        md = render_strategy(entries)
        assert "## Custom: 季節要因" in md

    @pytest.mark.unit
    def test_render_parse_roundtrip(self) -> None:
        """render -> parse -> render preserves content."""
        original = [
            StrategyEntry(context_type="persona", title="Persona", content="30代男性"),
            StrategyEntry(context_type="usp", title="USP", content="業界最安値"),
            StrategyEntry(context_type="custom", title="季節要因", content="年末商戦"),
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


# ============================================================
# STRATEGY.md file I/O tests
# ============================================================


class TestStrategyFile:
    """STRATEGY.md file I/O tests."""

    @pytest.mark.unit
    def test_read_strategy_file(self, tmp_path: Path) -> None:
        """Read from file."""
        fp = tmp_path / "STRATEGY.md"
        fp.write_text("# Strategy\n\n## Persona\nターゲット\n", encoding="utf-8")
        result = read_strategy_file(fp)
        assert len(result) == 1
        assert result[0].context_type == "persona"

    @pytest.mark.unit
    def test_write_strategy_file(self, tmp_path: Path) -> None:
        """Write to file."""
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
        """Missing file returns empty list."""
        fp = tmp_path / "STRATEGY.md"
        result = read_strategy_file(fp)
        assert result == []

    @pytest.mark.unit
    def test_add_strategy_entry(self, tmp_path: Path) -> None:
        """Add entry to existing file."""
        fp = tmp_path / "STRATEGY.md"
        fp.write_text("# Strategy\n\n## Persona\nターゲット\n", encoding="utf-8")
        new_entry = StrategyEntry(context_type="usp", title="USP", content="業界最安値")
        add_strategy_entry(fp, new_entry)
        result = read_strategy_file(fp)
        assert len(result) == 2
        assert result[0].context_type == "persona"
        assert result[1].context_type == "usp"

    @pytest.mark.unit
    def test_remove_strategy_entry(self, tmp_path: Path) -> None:
        """Remove entry by context_type."""
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
        """Remove custom entry by title."""
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
# Strategy file I/O error handling tests
# ============================================================


class TestStrategyFileErrorHandling:
    """Strategy file I/O error tests."""

    @pytest.mark.unit
    def test_read_strategy_file_permission_error(self, tmp_path: Path) -> None:
        """Permission error raises ContextFileError."""
        fp = tmp_path / "STRATEGY.md"
        fp.write_text("# Strategy\n\n## Persona\nTest\n", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with pytest.raises(ContextFileError):
                read_strategy_file(fp)

    @pytest.mark.unit
    def test_write_strategy_file_creates_parent_dir(self, tmp_path: Path) -> None:
        """Parent directory is auto-created on write."""
        fp = tmp_path / "subdir" / "deep" / "STRATEGY.md"
        entries = [
            StrategyEntry(context_type="persona", title="Persona", content="Test"),
        ]
        write_strategy_file(fp, entries)
        assert fp.exists()
        assert "## Persona" in fp.read_text(encoding="utf-8")


# ============================================================
# Unknown section warning test
# ============================================================


class TestUnknownSectionWarning:
    """Warning log test for unknown sections."""

    @pytest.mark.unit
    def test_unknown_section_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown section triggers warning log."""
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
# _TYPE_TO_PREFIX constant test
# ============================================================


class TestTypeToPrefixConstant:
    """Module-level _TYPE_TO_PREFIX constant test."""

    @pytest.mark.unit
    def test_type_to_prefix_exists(self) -> None:
        """_TYPE_TO_PREFIX constant is defined in strategy.py."""
        from mureo.context import strategy

        assert hasattr(strategy, "_TYPE_TO_PREFIX")
        assert strategy._TYPE_TO_PREFIX["custom"] == "Custom"
        assert strategy._TYPE_TO_PREFIX["deep_research"] == "Deep Research"
        assert strategy._TYPE_TO_PREFIX["sales_material"] == "Sales Material"


# ============================================================
# Goal section tests
# ============================================================


class TestGoalSection:
    """Goal section parsing and rendering tests."""

    @pytest.mark.unit
    def test_parse_goal_section(self) -> None:
        """Parse a STRATEGY.md with ## Goal: title -> context_type='goal'."""
        md = (
            "# Strategy\n\n"
            "## Goal: Reduce CPA below 5000 JPY\n"
            "- Target: CPA < 5,000 JPY\n"
            "- Deadline: 2026-06-30\n"
            "- Current: CPA 6,200 JPY\n"
            "- Platform: Google Ads, Meta Ads\n"
            "- Priority: HIGH\n"
        )
        result = parse_strategy(md)
        assert len(result) == 1
        assert result[0].context_type == "goal"
        assert result[0].title == "Reduce CPA below 5000 JPY"
        assert "Target: CPA < 5,000 JPY" in result[0].content
        assert "Priority: HIGH" in result[0].content

    @pytest.mark.unit
    def test_parse_multiple_goals(self) -> None:
        """Parse STRATEGY.md with 2 Goal sections -> 2 entries."""
        md = (
            "# Strategy\n\n"
            "## Goal: Reduce CPA below 5000 JPY\n"
            "- Target: CPA < 5,000 JPY\n"
            "- Deadline: 2026-06-30\n"
            "- Priority: HIGH\n\n"
            "## Goal: Increase monthly leads to 100\n"
            "- Target: Leads >= 100/month\n"
            "- Deadline: 2026-05-31\n"
            "- Priority: MEDIUM\n"
        )
        result = parse_strategy(md)
        assert len(result) == 2
        assert result[0].context_type == "goal"
        assert result[0].title == "Reduce CPA below 5000 JPY"
        assert result[1].context_type == "goal"
        assert result[1].title == "Increase monthly leads to 100"

    @pytest.mark.unit
    def test_write_goal_section(self) -> None:
        """Write a StrategyEntry with type='goal' -> outputs '## Goal: title'."""
        entries = [
            StrategyEntry(
                context_type="goal",
                title="Reduce CPA below 5000 JPY",
                content="- Target: CPA < 5,000 JPY\n- Priority: HIGH",
            ),
        ]
        md = render_strategy(entries)
        assert "## Goal: Reduce CPA below 5000 JPY" in md
        assert "- Target: CPA < 5,000 JPY" in md

    @pytest.mark.unit
    def test_goal_coexists_with_other_sections(self) -> None:
        """Parse a full STRATEGY.md with Persona + USP + Goal -> all 3 entries."""
        md = (
            "# Strategy\n\n"
            "## Persona\n30-40 year old marketing managers\n\n"
            "## USP\nAI-powered ad optimization\n\n"
            "## Goal: Reduce CPA below 5000 JPY\n"
            "- Target: CPA < 5,000 JPY\n"
            "- Priority: HIGH\n"
        )
        result = parse_strategy(md)
        assert len(result) == 3
        assert result[0].context_type == "persona"
        assert result[1].context_type == "usp"
        assert result[2].context_type == "goal"
        assert result[2].title == "Reduce CPA below 5000 JPY"

    @pytest.mark.unit
    def test_goal_roundtrip(self) -> None:
        """render -> parse roundtrip preserves goal entries."""
        original = [
            StrategyEntry(
                context_type="persona", title="Persona", content="Target user"
            ),
            StrategyEntry(
                context_type="goal",
                title="Reduce CPA",
                content="- Target: CPA < 5,000 JPY\n- Priority: HIGH",
            ),
        ]
        md = render_strategy(original)
        parsed = parse_strategy(md)
        assert len(parsed) == 2
        assert parsed[1].context_type == "goal"
        assert parsed[1].title == "Reduce CPA"
        assert parsed[1].content == original[1].content
