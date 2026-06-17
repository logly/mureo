"""Unit tests for the insight-sources writer (add / remove).

The external-advisor MCP list lives at ``~/.mureo/insight_sources.json``.
``mureo.learning.insight_sources`` already ships a tolerant *reader*; this
module pins the new *writer* that the configure UI's "External advisor MCP"
card calls to list / add / delete entries.

The writer is the real-spend-adjacent safety boundary, so it reuses the
#276-hardened safe-write stack:

- read the existing file FAIL-CLOSED (``ConfigWriteError`` on malformed
  JSON, never the tolerant ``load_insight_sources`` that silently drops a
  bad file) so a corrupt file is never clobbered;
- reject a duplicate ``name`` (``ValueError``);
- ``backup_file`` (rolling ``.bak``) BEFORE the overwrite, then an atomic
  write;
- round-trip with ``load_insight_sources`` and preserve the
  ``env={}`` vs ``env=None`` distinction.

All FS via ``tmp_path``. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mureo.learning.insight_sources import (
    InsightSource,
    add_insight_source,
    load_insight_sources,
    remove_insight_source,
    serialize_insight_source,
)
from mureo.providers.config_writer import ConfigWriteError

if TYPE_CHECKING:
    from pathlib import Path


def _stdio(name: str = "advisor-1", **overrides: object) -> InsightSource:
    kwargs: dict[str, object] = {
        "name": name,
        "transport": "stdio",
        "tool": "vector_search",
        "command": "/usr/bin/advisor",
    }
    kwargs.update(overrides)
    return InsightSource(**kwargs)  # type: ignore[arg-type]


def _http(name: str = "advisor-http") -> InsightSource:
    return InsightSource(
        name=name,
        transport="http",
        tool="vector_search",
        url="https://advisor.example.com/mcp",
    )


@pytest.mark.unit
class TestSerializeInsightSource:
    def test_stdio_round_trips_through_loader(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        src = _stdio(args=("--flag", "v"), env={"K": "V"})
        add_insight_source(src, path=path)
        loaded = load_insight_sources(path)
        assert loaded.sources == (src,)

    def test_http_round_trips_through_loader(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        src = _http()
        add_insight_source(src, path=path)
        loaded = load_insight_sources(path)
        assert loaded.sources == (src,)

    def test_env_empty_dict_is_preserved_distinct_from_none(self) -> None:
        """``env={}`` (sealed empty env) must serialize to an explicit
        empty object and survive the read, NOT collapse into ``None``."""
        sealed = serialize_insight_source(_stdio(env={}))
        assert sealed["env"] == {}
        inherit = serialize_insight_source(_stdio(env=None))
        assert "env" not in inherit

    def test_env_empty_dict_round_trips_via_loader(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        src = _stdio(env={})
        add_insight_source(src, path=path)
        loaded = load_insight_sources(path)
        assert loaded.sources[0].env == {}

    def test_optional_none_fields_are_omitted(self) -> None:
        data = serialize_insight_source(_stdio())
        # No url / headers for a stdio source; no empty env / args noise.
        assert "url" not in data
        assert "headers" not in data
        assert "env" not in data
        assert "args" not in data
        assert data["command"] == "/usr/bin/advisor"

    def test_http_omits_stdio_only_fields(self) -> None:
        data = serialize_insight_source(_http())
        assert "command" not in data
        assert "args" not in data
        assert "env" not in data
        assert data["url"] == "https://advisor.example.com/mcp"


@pytest.mark.unit
class TestAddInsightSource:
    def test_add_to_absent_file_creates_it(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        cfg = add_insight_source(_stdio(), path=path)
        assert path.exists()
        assert len(cfg.sources) == 1
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(on_disk["sources"], list)
        assert on_disk["sources"][0]["name"] == "advisor-1"

    def test_add_appends_preserving_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        add_insight_source(_stdio("a"), path=path)
        cfg = add_insight_source(_http("b"), path=path)
        names = [s.name for s in cfg.sources]
        assert names == ["a", "b"]

    def test_duplicate_name_raises_and_does_not_write(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        add_insight_source(_stdio("dup"), path=path)
        before = path.read_text(encoding="utf-8")
        with pytest.raises(ValueError, match="dup"):
            add_insight_source(_http("dup"), path=path)
        # No second write happened.
        assert path.read_text(encoding="utf-8") == before

    def test_malformed_existing_file_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        corrupt = '{"sources": [,,,'
        path.write_text(corrupt, encoding="utf-8")
        with pytest.raises(ConfigWriteError):
            add_insight_source(_stdio(), path=path)
        # The corrupt file is untouched — never clobbered.
        assert path.read_text(encoding="utf-8") == corrupt

    def test_backup_written_before_overwrite(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        add_insight_source(_stdio("a"), path=path)
        # Second add overwrites → a rolling .bak of the prior file is kept.
        add_insight_source(_http("b"), path=path)
        backup = tmp_path / "insight_sources.json.bak"
        assert backup.exists()
        prior = json.loads(backup.read_text(encoding="utf-8"))
        assert [s["name"] for s in prior["sources"]] == ["a"]

    def test_no_backup_on_first_write(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        add_insight_source(_stdio("a"), path=path)
        # Nothing existed before the first write → no backup.
        assert not (tmp_path / "insight_sources.json.bak").exists()


@pytest.mark.unit
class TestRemoveInsightSource:
    def test_remove_existing_returns_true_and_persists(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        add_insight_source(_stdio("a"), path=path)
        add_insight_source(_http("b"), path=path)
        removed = remove_insight_source("a", path=path)
        assert removed is True
        loaded = load_insight_sources(path)
        assert [s.name for s in loaded.sources] == ["b"]

    def test_remove_absent_name_is_idempotent_noop(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        add_insight_source(_stdio("a"), path=path)
        before = path.read_text(encoding="utf-8")
        removed = remove_insight_source("missing", path=path)
        assert removed is False
        # No write on a no-op removal.
        assert path.read_text(encoding="utf-8") == before

    def test_remove_from_absent_file_returns_false(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        assert remove_insight_source("a", path=path) is False
        assert not path.exists()

    def test_remove_backs_up_before_overwrite(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        add_insight_source(_stdio("a"), path=path)
        add_insight_source(_http("b"), path=path)
        # Clear the .bak from the second add so we assert THIS overwrite's bak.
        (tmp_path / "insight_sources.json.bak").unlink()
        remove_insight_source("a", path=path)
        backup = tmp_path / "insight_sources.json.bak"
        assert backup.exists()
        prior = json.loads(backup.read_text(encoding="utf-8"))
        assert [s["name"] for s in prior["sources"]] == ["a", "b"]

    def test_remove_malformed_file_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "insight_sources.json"
        corrupt = '{"sources": [,,,'
        path.write_text(corrupt, encoding="utf-8")
        with pytest.raises(ConfigWriteError):
            remove_insight_source("a", path=path)
        assert path.read_text(encoding="utf-8") == corrupt
