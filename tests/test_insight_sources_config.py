"""Tests for ``mureo.learning.insight_sources``.

Pins the schema and tolerant parser for ``~/.mureo/insight_sources.json``.
Every error path must return the empty config + WARNING so a
misconfigured file never blocks local insights.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from mureo.learning.insight_sources import (
    InsightSource,
    InsightSourceConfig,
    default_config_path,
    load_insight_sources,
)


@pytest.mark.unit
class TestInsightSourceModel:
    def test_stdio_source_accepts_command(self) -> None:
        src = InsightSource(
            name="acme",
            transport="stdio",
            tool="vector_search",
            command="acme-mcp",
            args=("--scope", "ads"),
            env={"ACME_API_KEY": "x"},
        )
        assert src.name == "acme"
        assert src.transport == "stdio"
        assert src.command == "acme-mcp"

    def test_http_source_accepts_url(self) -> None:
        src = InsightSource(
            name="benchmarks",
            transport="http",
            tool="vector_search",
            url="https://benchmarks.example/mcp",
            headers={"Authorization": "Bearer x"},
        )
        assert src.url == "https://benchmarks.example/mcp"

    def test_sse_source_accepts_url(self) -> None:
        src = InsightSource(
            name="b",
            transport="sse",
            tool="vector_search",
            url="https://x.example/sse",
        )
        assert src.transport == "sse"

    def test_default_timeout_is_ten_seconds(self) -> None:
        src = InsightSource(name="a", transport="stdio", tool="t", command="x")
        assert src.timeout_sec == 10

    def test_default_top_k_is_five(self) -> None:
        src = InsightSource(name="a", transport="stdio", tool="t", command="x")
        assert src.top_k == 5

    def test_top_k_override(self) -> None:
        src = InsightSource(
            name="a", transport="stdio", tool="t", command="x", top_k=12
        )
        assert src.top_k == 12

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name"):
            InsightSource(name="", transport="stdio", tool="t", command="x")

    def test_whitespace_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name"):
            InsightSource(name="   ", transport="stdio", tool="t", command="x")

    def test_unknown_transport_rejected(self) -> None:
        with pytest.raises(ValueError, match="transport"):
            InsightSource(
                name="a", transport="ftp", tool="t", command="x"  # type: ignore[arg-type]
            )

    def test_stdio_without_command_rejected(self) -> None:
        with pytest.raises(ValueError, match="command"):
            InsightSource(name="a", transport="stdio", tool="t")

    def test_http_without_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="url"):
            InsightSource(name="a", transport="http", tool="t")

    def test_sse_without_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="url"):
            InsightSource(name="a", transport="sse", tool="t")

    def test_missing_tool_rejected(self) -> None:
        with pytest.raises(ValueError, match="tool"):
            InsightSource(name="a", transport="stdio", tool="", command="x")

    def test_negative_top_k_rejected(self) -> None:
        with pytest.raises(ValueError, match="top_k"):
            InsightSource(name="a", transport="stdio", tool="t", command="x", top_k=0)

    def test_top_k_above_cap_rejected(self) -> None:
        with pytest.raises(ValueError, match="top_k"):
            InsightSource(
                name="a", transport="stdio", tool="t", command="x", top_k=1000
            )

    def test_zero_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="timeout_sec"):
            InsightSource(
                name="a",
                transport="stdio",
                tool="t",
                command="x",
                timeout_sec=0,
            )

    def test_negative_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="timeout_sec"):
            InsightSource(
                name="a",
                transport="stdio",
                tool="t",
                command="x",
                timeout_sec=-1,
            )

    def test_huge_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="timeout_sec"):
            InsightSource(
                name="a",
                transport="stdio",
                tool="t",
                command="x",
                timeout_sec=1e6,
            )

    def test_env_default_is_none_means_inherit(self) -> None:
        """Distinguish 'omitted env' (inherit parent) from 'explicit
        empty env' (sealed subprocess) — collapsing them would leak
        operator secrets into advisor binaries."""
        src = InsightSource(name="a", transport="stdio", tool="t", command="x")
        assert src.env is None

    def test_explicit_empty_env_preserved(self) -> None:
        src = InsightSource(name="a", transport="stdio", tool="t", command="x", env={})
        assert src.env == {}
        assert src.env is not None

    def test_headers_default_is_none(self) -> None:
        src = InsightSource(
            name="a",
            transport="http",
            tool="t",
            url="https://x.example/mcp",
        )
        assert src.headers is None


@pytest.mark.unit
class TestLoadInsightSources:
    def test_missing_file_returns_empty_config(self, tmp_path: Path) -> None:
        cfg = load_insight_sources(tmp_path / "nope.json")
        assert isinstance(cfg, InsightSourceConfig)
        assert cfg.sources == ()

    def test_malformed_json_returns_empty_with_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text("not json {", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="mureo.learning.insight_sources"):
            cfg = load_insight_sources(path)
        assert cfg.sources == ()
        assert any("insight_sources" in r.message for r in caplog.records)

    def test_top_level_not_object_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text(json.dumps([]), encoding="utf-8")
        cfg = load_insight_sources(path)
        assert cfg.sources == ()

    def test_missing_sources_key_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text(json.dumps({}), encoding="utf-8")
        cfg = load_insight_sources(path)
        assert cfg.sources == ()

    def test_loads_valid_stdio_source(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "name": "acme",
                            "transport": "stdio",
                            "command": "acme-mcp",
                            "tool": "vector_search",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        cfg = load_insight_sources(path)
        assert len(cfg.sources) == 1
        assert cfg.sources[0].name == "acme"

    def test_loads_valid_http_source_with_top_k(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "name": "b",
                            "transport": "http",
                            "url": "https://x.example/mcp",
                            "tool": "vector_search",
                            "top_k": 8,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        cfg = load_insight_sources(path)
        assert cfg.sources[0].top_k == 8

    def test_invalid_entry_skipped_others_kept(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {"name": "", "transport": "stdio"},  # invalid
                        {
                            "name": "ok",
                            "transport": "stdio",
                            "command": "ok-mcp",
                            "tool": "vector_search",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="mureo.learning.insight_sources"):
            cfg = load_insight_sources(path)
        assert [s.name for s in cfg.sources] == ["ok"]

    def test_explicit_empty_env_round_trips_through_loader(
        self, tmp_path: Path
    ) -> None:
        """The parser preserves ``"env": {}`` as an empty dict so the
        operator's intent to seal the subprocess is honoured."""
        path = tmp_path / "insight_sources.json"
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "name": "sealed",
                            "transport": "stdio",
                            "command": "x",
                            "tool": "vector_search",
                            "env": {},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        cfg = load_insight_sources(path)
        assert cfg.sources[0].env == {}
        assert cfg.sources[0].env is not None

    def test_omitted_env_round_trips_as_none(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "name": "inherit",
                            "transport": "stdio",
                            "command": "x",
                            "tool": "vector_search",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        cfg = load_insight_sources(path)
        assert cfg.sources[0].env is None

    def test_duplicate_names_deduped_first_wins(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = tmp_path / "insight_sources.json"
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "name": "dup",
                            "transport": "stdio",
                            "command": "first",
                            "tool": "vector_search",
                        },
                        {
                            "name": "dup",
                            "transport": "stdio",
                            "command": "second",
                            "tool": "vector_search",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="mureo.learning.insight_sources"):
            cfg = load_insight_sources(path)
        assert len(cfg.sources) == 1
        assert cfg.sources[0].command == "first"


@pytest.mark.unit
class TestDefaultConfigPath:
    def test_resolves_under_home_mureo(self) -> None:
        path = default_config_path()
        assert path.name == "insight_sources.json"
        assert path.parent.name == ".mureo"
