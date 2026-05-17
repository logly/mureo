"""Unit tests for #114 Phase 2: plugin tool safety semantics +
mutating-call promotion into STATE.json's action_log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.types import Tool, ToolAnnotations

from mureo.mcp.plugin_semantics import derive_semantics, record_mutation_action_log
from mureo.throttle import ThrottleConfig

if TYPE_CHECKING:
    from pathlib import Path


def _tool(*, annotations=None, meta=None) -> Tool:
    return Tool(
        name="acme_ads_x",
        description="x",
        inputSchema={"type": "object", "properties": {}},
        annotations=annotations,
        meta=meta,
    )


@pytest.mark.unit
class TestDeriveSemantics:
    def test_undeclared_is_mutating(self) -> None:
        assert derive_semantics(_tool()).mutating is True

    def test_read_only_hint_is_non_mutating(self) -> None:
        sem = derive_semantics(_tool(annotations=ToolAnnotations(readOnlyHint=True)))
        assert sem.mutating is False

    def test_destructive_without_readonly_is_mutating(self) -> None:
        sem = derive_semantics(_tool(annotations=ToolAnnotations(destructiveHint=True)))
        assert sem.mutating is True

    def test_reversal_meta_captured_only_when_dict(self) -> None:
        ok = derive_semantics(
            _tool(meta={"mureo": {"reversal": {"operation": "acme_ads_resume"}}})
        )
        assert ok.reversal == {"operation": "acme_ads_resume"}
        bad = derive_semantics(_tool(meta={"mureo": {"reversal": "nope"}}))
        assert bad.reversal is None

    def test_throttle_meta_parsed_and_malformed_ignored(self) -> None:
        good = derive_semantics(
            _tool(meta={"mureo": {"throttle": {"rate": 2.0, "burst": 3}}})
        )
        assert good.throttle == ThrottleConfig(rate=2.0, burst=3)
        bad = derive_semantics(_tool(meta={"mureo": {"throttle": {"rate": "x"}}}))
        assert bad.throttle is None


@pytest.mark.unit
class TestRecordMutationActionLog:
    def _seed_state(self, d: Path) -> Path:
        from mureo.context.models import StateDocument
        from mureo.context.state import write_state_file

        p = d / "STATE.json"
        write_state_file(p, StateDocument())
        return p

    def test_appends_when_state_json_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import read_state_file

        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(
            tool="acme_ads_pause",
            source="acme-dist",
            reversal={"operation": "acme_ads_resume"},
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        e = doc.action_log[0]
        assert e.action == "acme_ads_pause"
        assert e.platform == "plugin:acme-dist"
        assert e.reversible_params == {"operation": "acme_ads_resume"}

    def test_noop_without_state_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        record_mutation_action_log(tool="t", source="s", reversal=None)  # no raise
        assert not (tmp_path / "STATE.json").exists()  # never created

    def test_never_raises_on_append_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)

        def _boom(*_a: object, **_k: object) -> None:
            raise OSError("disk gone")

        monkeypatch.setattr("mureo.context.state.append_action_log", _boom)
        record_mutation_action_log(tool="t", source="s", reversal=None)  # swallowed
