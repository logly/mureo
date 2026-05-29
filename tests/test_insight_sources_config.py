"""Tests for ``mureo.learning.insight_sources``.

The config module owns the shape of ``~/.mureo/insight_sources.json``:
an immutable :class:`InsightSourceConfig` (the top-level document) plus
:class:`InsightSource` entries describing each external MCP server.

The parser:

- Tolerates a missing config file (returns the empty document).
- Tolerates an empty / malformed file with a logger warning (returns
  the empty document) so a misconfigured operator does not block the
  ``mureo_learning_insights_get`` tool entirely.
- Refuses unknown ``transport`` values at parse time so a typo blows
  up loudly rather than failing later on the network.
- Pins the defaults for optional fields (``timeout_sec`` default,
  empty ``env`` / ``headers`` / ``args``).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


@pytest.mark.unit
class TestInsightSourceModel:
    def test_stdio_source_minimal_required_fields(self) -> None:
        from mureo.learning.insight_sources import InsightSource

        src = InsightSource(
            name="acme",
            transport="stdio",
            tool="insights_get",
            command="acme-insights-mcp",
        )
        assert src.name == "acme"
        assert src.transport == "stdio"
        assert src.tool == "insights_get"
        assert src.command == "acme-insights-mcp"
        # Defaults
        assert src.args == ()
        assert src.env == {}
        assert src.timeout_sec == 10.0
        assert src.url is None
        assert src.headers == {}

    def test_sse_source_minimal_required_fields(self) -> None:
        from mureo.learning.insight_sources import InsightSource

        src = InsightSource(
            name="benchmarks",
            transport="sse",
            tool="benchmarks_get",
            url="https://benchmarks.example/mcp",
        )
        assert src.transport == "sse"
        assert src.url == "https://benchmarks.example/mcp"
        assert src.command is None

    def test_source_is_frozen(self) -> None:
        from mureo.learning.insight_sources import InsightSource

        src = InsightSource(
            name="a",
            transport="stdio",
            tool="t",
            command="c",
        )
        with pytest.raises(FrozenInstanceError):
            src.name = "b"  # type: ignore[misc]

    def test_stdio_source_without_command_raises(self) -> None:
        """``stdio`` transport requires a ``command``; a missing
        command at construction time should fail loudly, not silently
        produce a half-built source we'd try to spawn later."""
        from mureo.learning.insight_sources import InsightSource

        with pytest.raises(ValueError, match="command"):
            InsightSource(name="a", transport="stdio", tool="t")

    def test_sse_source_without_url_raises(self) -> None:
        from mureo.learning.insight_sources import InsightSource

        with pytest.raises(ValueError, match="url"):
            InsightSource(name="a", transport="sse", tool="t")

    def test_http_transport_accepted(self) -> None:
        """``http`` is an alias for the MCP streamable-HTTP transport
        — same shape as ``sse`` (URL + headers) but a different SDK
        helper handles it. We accept it at the config layer so future
        federation work can route on the value."""
        from mureo.learning.insight_sources import InsightSource

        src = InsightSource(
            name="kb",
            transport="http",
            tool="insights_get",
            url="https://kb.example/mcp",
        )
        assert src.transport == "http"

    def test_unknown_transport_raises(self) -> None:
        """An unknown transport value blocks construction so a typo
        in the JSON file surfaces at parse time, not at fetch time."""
        from mureo.learning.insight_sources import InsightSource

        with pytest.raises(ValueError, match="transport"):
            InsightSource(
                name="a",
                transport="ftp",  # type: ignore[arg-type]
                tool="t",
                command="c",
            )


@pytest.mark.unit
class TestLoadConfig:
    def test_missing_file_returns_empty_config(self, tmp_path: Path) -> None:
        from mureo.learning.insight_sources import load_insight_sources

        cfg = load_insight_sources(tmp_path / "does-not-exist.json")
        assert cfg.sources == ()

    def test_empty_sources_array_returns_empty_config(self, tmp_path: Path) -> None:
        from mureo.learning.insight_sources import load_insight_sources

        path = tmp_path / "insight_sources.json"
        path.write_text('{"sources": []}', encoding="utf-8")
        cfg = load_insight_sources(path)
        assert cfg.sources == ()

    def test_parses_mixed_transports(self, tmp_path: Path) -> None:
        from mureo.learning.insight_sources import load_insight_sources

        path = tmp_path / "insight_sources.json"
        path.write_text(
            """
            {
              "sources": [
                {
                  "name": "acme",
                  "transport": "stdio",
                  "tool": "insights_get",
                  "command": "acme-insights-mcp",
                  "args": ["--scope", "google-ads"],
                  "env": {"ACME_API_KEY": "secret"},
                  "timeout_sec": 5.0
                },
                {
                  "name": "benchmarks",
                  "transport": "sse",
                  "tool": "benchmarks_get",
                  "url": "https://benchmarks.example/mcp",
                  "headers": {"Authorization": "Bearer xyz"}
                }
              ]
            }
            """,
            encoding="utf-8",
        )
        cfg = load_insight_sources(path)
        assert len(cfg.sources) == 2

        acme, benchmarks = cfg.sources
        assert acme.name == "acme"
        assert acme.transport == "stdio"
        assert acme.command == "acme-insights-mcp"
        assert acme.args == ("--scope", "google-ads")
        assert acme.env == {"ACME_API_KEY": "secret"}
        assert acme.timeout_sec == 5.0

        assert benchmarks.transport == "sse"
        assert benchmarks.url == "https://benchmarks.example/mcp"
        assert benchmarks.headers == {"Authorization": "Bearer xyz"}

    def test_malformed_json_returns_empty_config_with_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A broken file should not block the diagnostic flow — log a
        warning that points the operator at the path, then return
        the empty document so :func:`mureo_learning_insights_get`
        still surfaces local insights."""
        import logging

        from mureo.learning.insight_sources import load_insight_sources

        path = tmp_path / "insight_sources.json"
        path.write_text("{this is not json", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="mureo.learning.insight_sources"):
            cfg = load_insight_sources(path)

        assert cfg.sources == ()
        # The operator should see the path in the log so they can fix it.
        assert any(str(path) in rec.getMessage() for rec in caplog.records)

    def test_invalid_source_entry_skipped_and_logged(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """One bad entry should not block valid sibling sources — log
        the bad one, return the valid ones."""
        import logging

        from mureo.learning.insight_sources import load_insight_sources

        path = tmp_path / "insight_sources.json"
        path.write_text(
            """
            {
              "sources": [
                {
                  "name": "good",
                  "transport": "stdio",
                  "tool": "insights_get",
                  "command": "good-mcp"
                },
                {
                  "name": "bad",
                  "transport": "stdio",
                  "tool": "insights_get"
                }
              ]
            }
            """,
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="mureo.learning.insight_sources"):
            cfg = load_insight_sources(path)

        assert [s.name for s in cfg.sources] == ["good"]
        assert any("bad" in rec.getMessage() for rec in caplog.records)

    def test_default_config_path_resolution(self) -> None:
        """The default path is ``~/.mureo/insight_sources.json`` so
        operators do not have to learn yet another location."""
        from mureo.learning.insight_sources import default_config_path

        path = default_config_path()
        assert path == Path.home() / ".mureo" / "insight_sources.json"
