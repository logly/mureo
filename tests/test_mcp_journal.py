"""Unit tests for the dispatcher-level journal (mureo.mcp.journal).

Phase 1 of #758: every MCP tool call leaves exactly one append-only
JSON-Lines record, whatever the family and whatever the outcome. This
module pins the record shape, the masking/scrubbing reuse, the path
rule, the opt-out env var and the never-raises contract; the wiring into
``handle_call_tool`` is pinned by ``tests/test_mcp_journal_dispatch.py``.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import mureo
from mureo.core.runtime_context import (
    RuntimeContext,
    default_runtime_context,
    reset_runtime_context,
)
from mureo.core.state_store import FilesystemStateStore
from mureo.mcp import journal


@pytest.fixture(autouse=True)
def _reset_context_cache():
    reset_runtime_context()
    journal._batch_cache = None
    yield
    journal._batch_cache = None
    reset_runtime_context()


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the journal at a throwaway file."""
    path = tmp_path / "ws" / "JOURNAL.jsonl"
    monkeypatch.setattr(journal, "journal_path", lambda: path)
    return path


def _inject_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    """Resolve the runtime context to a filesystem store under ``workspace``."""
    base = default_runtime_context()
    ctx = RuntimeContext(
        secret_store=base.secret_store,
        state_store=FilesystemStateStore(workspace=workspace),
        knowledge_store=base.knowledge_store,
        throttle_store=base.throttle_store,
        workspace_id="ws-under-test",
    )
    monkeypatch.setattr("mureo.core.runtime_context._cached_context", ctx)


def _record(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "tool": "google_ads_campaigns_list",
        "family": "google_ads",
        "mutating": False,
        "arguments": {"customer_id": "123"},
        "outcome": "ok",
        "duration_ms": 12,
    }
    kwargs.update(overrides)
    journal.record_call(**kwargs)


def _lines(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.unit
class TestRecordShape:
    def test_every_key_is_written_in_the_documented_order(
        self, log: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _inject_workspace(monkeypatch, log.parent)
        _record(
            tool="acme_ads_pause",
            family="plugin",
            source="acme-dist",
            mutating=True,
            outcome="exception",
            reason="RuntimeError('nope')",
            rollback=True,
        )
        rec = _lines(log)[0]
        assert list(rec) == [
            "v",
            "ts",
            "session",
            "client",
            "mureo",
            "workspace_id",
            "tool",
            "family",
            "source",
            "mutating",
            "args",
            "outcome",
            "reason",
            "duration_ms",
            "batch_id",
            "rollback",
        ]
        assert rec["v"] == 1
        assert rec["mureo"] == mureo.__version__
        assert rec["workspace_id"] == "ws-under-test"
        assert rec["source"] == "acme-dist"
        assert rec["mutating"] is True
        assert rec["rollback"] is True

    def test_source_is_absent_for_a_builtin(self, log: Path) -> None:
        _record()
        rec = _lines(log)[0]
        assert "source" not in rec
        assert "rollback" not in rec
        assert rec["family"] == "google_ads"
        assert rec["duration_ms"] == 12
        assert rec["batch_id"] is None

    def test_ts_is_parseable_utc_with_second_precision(self, log: Path) -> None:
        _record()
        ts = _lines(log)[0]["ts"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0
        assert parsed.microsecond == 0

    def test_session_is_stable_across_calls_in_one_process(self, log: Path) -> None:
        _record()
        _record()
        first, second = _lines(log)
        assert first["session"] == second["session"]
        assert len(first["session"]) == 32

    def test_client_is_null_until_the_sdk_reports_one(
        self, log: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(journal, "_client", None)
        _record()
        assert _lines(log)[0]["client"] is None
        journal.set_client_info("Claude Code", "1.4.2")
        _record()
        assert _lines(log)[1]["client"] == "Claude Code/1.4.2"

    def test_records_append_rather_than_overwrite(self, log: Path) -> None:
        _record()
        _record(tool="meta_ads_campaigns_list", family="meta_ads")
        assert [rec["tool"] for rec in _lines(log)] == [
            "google_ads_campaigns_list",
            "meta_ads_campaigns_list",
        ]


@pytest.mark.unit
class TestMaskingAndScrubbing:
    def test_sensitive_argument_keys_are_masked(self, log: Path) -> None:
        _record(arguments={"campaign_id": "c1", "api_key": "SHHH", "cookie": "c"})
        args = _lines(log)[0]["args"]
        assert args["campaign_id"] == "c1"
        assert args["api_key"] == "***"
        assert args["cookie"] == "***"

    def test_long_argument_strings_are_truncated(self, log: Path) -> None:
        _record(arguments={"note": "x" * 2000})
        note = _lines(log)[0]["args"]["note"]
        assert note.endswith("…<truncated>")
        assert len(note) <= 512

    def test_reason_is_scrubbed_of_secret_shapes(self, log: Path) -> None:
        _record(
            outcome="exception",
            reason=(
                "HTTPError 401: Authorization: Bearer Atza|SECRETTOKEN.abc "
                "body client_secret=SECRET-CLIENT-VALUE"
            ),
        )
        reason = _lines(log)[0]["reason"]
        assert "SECRETTOKEN" not in reason
        assert "SECRET-CLIENT-VALUE" not in reason
        assert "client_secret=***" in reason
        assert "HTTPError 401" in reason  # the diagnostic survives

    def test_reason_is_capped(self, log: Path) -> None:
        _record(outcome="platform_error", reason="y" * 2000)
        assert len(_lines(log)[0]["reason"]) == 512


@pytest.mark.unit
class TestOutcomes:
    @pytest.mark.parametrize(
        ("outcome", "reason"),
        [
            ("platform_error", "API error: FIELD_VALUE_IS_INVALID"),
            ("exception", "ValueError('boom')"),
            ("denied", "read-only mode is active"),
            ("refused", "would exclude 42% of delivery"),
            ("invalid_args", "Invalid arguments for x: at 'amount'"),
        ],
    )
    def test_each_non_ok_outcome_carries_its_reason(
        self, log: Path, outcome: str, reason: str
    ) -> None:
        _record(outcome=outcome, reason=reason)
        rec = _lines(log)[0]
        assert rec["outcome"] == outcome
        assert rec["reason"] == reason

    def test_ok_has_no_reason_key(self, log: Path) -> None:
        _record(outcome="ok", reason="ignored for an ok call")
        rec = _lines(log)[0]
        assert rec["outcome"] == "ok"
        assert "reason" not in rec


@pytest.mark.unit
class TestOptOut:
    def test_exact_one_disables_the_journal(
        self, log: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(journal.OPT_OUT_ENV_VAR, "1")
        _record()
        assert not log.exists()

    def test_any_other_value_leaves_it_enabled(
        self, log: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(journal.OPT_OUT_ENV_VAR, "true")
        _record()
        assert len(_lines(log)) == 1


@pytest.mark.unit
class TestJournalPath:
    def test_workspace_with_state_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "STATE.json").write_text("{}", encoding="utf-8")
        _inject_workspace(monkeypatch, tmp_path)
        assert journal.journal_path() == tmp_path / "JOURNAL.jsonl"

    def test_workspace_with_only_strategy_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "STRATEGY.md").write_text("# s\n", encoding="utf-8")
        _inject_workspace(monkeypatch, tmp_path)
        assert journal.journal_path() == tmp_path / "JOURNAL.jsonl"

    def test_bare_directory_falls_back_to_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``tests/conftest.py`` already points HOME at a throwaway dir.
        workspace = tmp_path / "bare"
        workspace.mkdir()
        _inject_workspace(monkeypatch, workspace)
        assert journal.journal_path() == Path.home() / ".mureo" / "journal.jsonl"

    def test_unresolvable_context_falls_back_to_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> RuntimeContext:
            raise RuntimeError("no context here")

        monkeypatch.setattr(
            "mureo.core.runtime_context.get_runtime_context", _boom, raising=True
        )
        assert journal.journal_path() == Path.home() / ".mureo" / "journal.jsonl"


@pytest.mark.unit
class TestBatchId:
    def test_open_batch_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import begin_batch

        record = begin_batch(tmp_path / "STATE.json", label="bulk exclusion pass")
        _inject_workspace(monkeypatch, tmp_path)
        log = tmp_path / "JOURNAL.jsonl"
        monkeypatch.setattr(journal, "journal_path", lambda: log)

        _record()
        assert _lines(log)[0]["batch_id"] == record.batch_id

    def test_closed_batch_leaves_it_null(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.context.state import begin_batch, end_batch

        begin_batch(tmp_path / "STATE.json", label="done pass")
        end_batch(tmp_path / "STATE.json")
        _inject_workspace(monkeypatch, tmp_path)
        log = tmp_path / "JOURNAL.jsonl"
        monkeypatch.setattr(journal, "journal_path", lambda: log)

        _record()
        assert _lines(log)[0]["batch_id"] is None

    def test_unreadable_state_leaves_it_null(
        self, log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (log.parent).mkdir(parents=True, exist_ok=True)
        (log.parent / "STATE.json").write_text("{not json", encoding="utf-8")
        _inject_workspace(monkeypatch, log.parent)
        _record()
        assert _lines(log)[0]["batch_id"] is None

    def test_an_unchanged_state_file_is_parsed_only_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STATE.json is re-read per call otherwise — once per TOOL CALL.

        The journal is on the hot path of every dispatch, so the batch
        lookup memoises on the file's identity rather than parsing a
        whole STATE.json again for a file that has not moved.
        """
        from mureo.context import state as state_mod

        record = state_mod.begin_batch(tmp_path / "STATE.json", label="hot path")
        _inject_workspace(monkeypatch, tmp_path)
        log = tmp_path / "JOURNAL.jsonl"
        monkeypatch.setattr(journal, "journal_path", lambda: log)

        reads: list[Path] = []
        original = state_mod.read_state_file

        def _counting(path: Path, *args: Any, **kwargs: Any) -> Any:
            reads.append(path)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(state_mod, "read_state_file", _counting)

        _record()
        _record()

        assert [rec["batch_id"] for rec in _lines(log)] == [record.batch_id] * 2
        assert len(reads) == 1

    def test_a_rewritten_state_file_invalidates_the_memo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Closing the batch must be visible on the very next record."""
        from mureo.context.state import begin_batch, end_batch

        record = begin_batch(tmp_path / "STATE.json", label="short pass")
        _inject_workspace(monkeypatch, tmp_path)
        log = tmp_path / "JOURNAL.jsonl"
        monkeypatch.setattr(journal, "journal_path", lambda: log)

        _record()
        end_batch(tmp_path / "STATE.json")
        _record()

        assert [rec["batch_id"] for rec in _lines(log)] == [record.batch_id, None]


@pytest.mark.unit
class TestNeverRaises:
    def test_io_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> Path:
            raise OSError("disk gone")

        monkeypatch.setattr(journal, "journal_path", _boom)
        _record()  # must not raise — journaling can never break a tool call

    def test_unserialisable_arguments_are_still_recorded(self, log: Path) -> None:
        _record(arguments={"obj": object()})
        assert isinstance(_lines(log)[0]["args"]["obj"], str)


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
class TestFileMode:
    def test_journal_is_owner_only(self, log: Path) -> None:
        _record()
        assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
