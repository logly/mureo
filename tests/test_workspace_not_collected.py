"""Why a WORKSPACE could not be collected at all (#661).

#638 gave a platform somewhere to say why its figures did not move
(``platforms[<key>].not_collected``). There was no equivalent for the
workspace as a whole — and when collection dies *before* any platform is
reached, the platform key and the account id are exactly what could not be
resolved, so the per-platform field cannot carry it without asking the
failure to supply what the failure destroyed. A workspace that has never
been collected has no entry to write onto at all.

``StateDocument.workspace_not_collected`` is that missing home. What these
tests pin:

- it needs **no platform key and no account id**, and is writable on a
  document that holds nothing;
- it is **optional and additive** — a document written before it existed
  parses unchanged and gains no key on the next write;
- it is **retired by evidence, not by discipline** — any rollup ANYWHERE in
  the document that was collected after the failure drops the note, whether
  or not the writer remembered to clear it;
- it is **distinguishable** from the per-platform note: the two are separate
  keys, retire on separate evidence, and neither is ever rendered as the
  other.

Like the per-platform note it is a statement about the COLLECTION, never a
verdict on the figures already stored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.models import (
    NOT_COLLECTED_REASON_MAX_CHARS,
    PlatformState,
    StateDocument,
)
from mureo.context.state import (
    parse_state,
    read_state_file,
    render_state,
    set_platform_metrics,
    set_platform_not_collected,
    set_workspace_not_collected,
    write_state_file,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_PLATFORM = "google_ads"
_ACCOUNT = "123-456-7890"
_REASON = "the workspace credentials file could not be read"


# ---------------------------------------------------------------------------
# The field itself
# ---------------------------------------------------------------------------


class TestTheFieldIsOptionalAndAdditive:
    def test_a_document_written_before_the_field_parses_unchanged(self) -> None:
        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "last_synced_at": "2026-08-18T09:00:00+09:00",
                    "platforms": {_PLATFORM: {"account_id": _ACCOUNT}},
                }
            )
        )
        assert doc.workspace_not_collected is None
        assert doc.last_synced_at == "2026-08-18T09:00:00+09:00"

    def test_a_document_without_it_emits_no_new_key(self) -> None:
        rendered = json.loads(render_state(StateDocument(version="2")))
        assert "workspace_not_collected" not in rendered

    def test_it_round_trips_when_set(self) -> None:
        note = {"attempted_at": "2026-08-18T09:00:00+09:00", "reason": _REASON}
        doc = StateDocument(version="2", workspace_not_collected=note)
        assert parse_state(render_state(doc)).workspace_not_collected == note

    def test_a_note_with_no_reason_is_no_note(self) -> None:
        """A timestamp alone says something happened and refuses to say what —
        the exact non-answer this field exists to end."""
        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "workspace_not_collected": {"attempted_at": "2026-08-18T09:00:00Z"},
                }
            )
        )
        assert doc.workspace_not_collected is None

    def test_a_malformed_note_degrades_rather_than_raising(self) -> None:
        doc = parse_state(
            json.dumps({"version": "2", "workspace_not_collected": "boom"})
        )
        assert doc.workspace_not_collected is None

    def test_an_over_long_reason_is_truncated_on_read(self) -> None:
        """Capped at BOTH ends: a document can be written wholesale by a
        digest that never goes near the write helper."""
        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "workspace_not_collected": {"reason": "x" * 5000},
                }
            )
        )
        assert doc.workspace_not_collected is not None
        assert (
            len(doc.workspace_not_collected["reason"]) == NOT_COLLECTED_REASON_MAX_CHARS
        )

    def test_the_stored_note_is_a_defensive_copy(self) -> None:
        note: dict[str, Any] = {"reason": _REASON}
        doc = StateDocument(version="2", workspace_not_collected=note)
        note["reason"] = "mutated"
        assert doc.workspace_not_collected == {"reason": _REASON}


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


class TestSetAndClear:
    def test_it_records_a_reason_with_a_server_stamped_time(
        self, tmp_path: Path
    ) -> None:
        doc = set_workspace_not_collected(tmp_path / "STATE.json", reason=_REASON)
        assert doc.workspace_not_collected is not None
        assert doc.workspace_not_collected["reason"] == _REASON
        assert doc.workspace_not_collected["attempted_at"]

    def test_it_needs_no_platform_key_and_no_account_id(self, tmp_path: Path) -> None:
        """The circularity the per-platform field could not escape: the two
        arguments it requires are the two a workspace-level failure could not
        resolve. This writer asks for neither, and invents no entry."""
        path = tmp_path / "STATE.json"
        doc = set_workspace_not_collected(path, reason=_REASON)
        assert doc.platforms is None
        assert json.loads(path.read_text())["platforms"] is None

    def test_it_is_writable_on_a_workspace_that_has_never_been_collected(
        self, tmp_path: Path
    ) -> None:
        """The absence of numbers is the thing being reported, so the write
        cannot be conditional on having any."""
        path = tmp_path / "STATE.json"
        assert not path.exists()
        doc = set_workspace_not_collected(path, reason=_REASON)
        assert doc.workspace_not_collected is not None
        assert doc.campaigns == ()

    def test_a_none_reason_clears_the_note(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_workspace_not_collected(path, reason=_REASON)
        assert (
            set_workspace_not_collected(path, reason=None).workspace_not_collected
            is None
        )

    def test_a_blank_reason_clears_it_too(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_workspace_not_collected(path, reason=_REASON)
        assert (
            set_workspace_not_collected(path, reason="   ").workspace_not_collected
            is None
        )

    def test_a_cleared_note_leaves_no_key_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_workspace_not_collected(path, reason=_REASON)
        set_workspace_not_collected(path, reason=None)
        assert "workspace_not_collected" not in json.loads(path.read_text())

    def test_a_second_failure_replaces_the_first(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_workspace_not_collected(path, reason=_REASON)
        doc = set_workspace_not_collected(path, reason="and again, an hour later")
        assert doc.workspace_not_collected is not None
        assert doc.workspace_not_collected["reason"] == "and again, an hour later"

    def test_recording_a_failure_is_not_a_sync(self, tmp_path: Path) -> None:
        """``last_synced_at`` is not re-stamped, for the same reason the
        per-platform writer does not: reporting the document as just-synced on
        the strength of nothing having been collected is a false statement one
        field over."""
        path = tmp_path / "STATE.json"
        set_platform_metrics(path, _PLATFORM, _ACCOUNT, totals={"spend": 1.0})
        before = read_state_file(path).last_synced_at
        after = set_workspace_not_collected(path, reason=_REASON)
        assert after.last_synced_at == before

    def test_an_over_long_reason_is_truncated(self, tmp_path: Path) -> None:
        doc = set_workspace_not_collected(tmp_path / "STATE.json", reason="x" * 5000)
        assert doc.workspace_not_collected is not None
        assert (
            len(doc.workspace_not_collected["reason"]) == NOT_COLLECTED_REASON_MAX_CHARS
        )

    def test_it_leaves_every_platform_alone(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_platform_metrics(
            path,
            _PLATFORM,
            _ACCOUNT,
            totals={"spend": 25862.0},
            metrics_period="LAST_30_DAYS",
        )
        before = read_state_file(path)
        after = set_workspace_not_collected(path, reason=_REASON)
        assert before.platforms is not None
        assert after.platforms == before.platforms

    def test_the_two_notes_are_independent(self, tmp_path: Path) -> None:
        """Setting one never sets or clears the other: "this workspace could
        not be collected" and "this workspace's Google Ads failed" are
        different facts calling for different actions."""
        path = tmp_path / "STATE.json"
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason="token expired")
        doc = set_workspace_not_collected(path, reason=_REASON)
        assert doc.platforms is not None
        assert doc.platforms[_PLATFORM].not_collected is not None
        assert doc.platforms[_PLATFORM].not_collected["reason"] == "token expired"
        assert doc.workspace_not_collected is not None
        assert doc.workspace_not_collected["reason"] == _REASON

        cleared = set_workspace_not_collected(path, reason=None)
        assert cleared.platforms is not None
        assert cleared.platforms[_PLATFORM].not_collected is not None


# ---------------------------------------------------------------------------
# The dashboard wire
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_ctx() -> Iterator[None]:
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


def _summary(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> dict[str, Any]:
    from mureo.core.runtime_context import default_runtime_context
    from mureo.web.reports import build_report_summary

    ctx = default_runtime_context(workspace=workspace)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    return build_report_summary()


def _write(
    workspace: Path,
    *,
    platforms: dict[str, PlatformState] | None = None,
    **doc_kwargs: Any,
) -> None:
    write_state_file(
        workspace / "STATE.json",
        StateDocument(version="2", platforms=platforms, **doc_kwargs),
    )


@pytest.mark.usefixtures("_reset_ctx")
class TestTheWire:
    def test_the_summary_carries_the_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            workspace_not_collected={
                "attempted_at": "2026-08-18T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        assert _summary(monkeypatch, tmp_path)["workspace_not_collected"] == {
            "attempted_at": "2026-08-18T09:00:00+00:00",
            "reason": _REASON,
        }

    def test_a_document_without_one_says_so_explicitly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(tmp_path)
        summary = _summary(monkeypatch, tmp_path)
        assert "workspace_not_collected" in summary
        assert summary["workspace_not_collected"] is None

    def test_only_the_two_known_keys_reach_the_browser(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            workspace_not_collected={
                "attempted_at": "2026-08-18T09:00:00+00:00",
                "reason": _REASON,
                "access_token": "SECRET",
            },
        )
        note = _summary(monkeypatch, tmp_path)["workspace_not_collected"]
        assert set(note) == {"attempted_at", "reason"}

    def test_an_over_long_reason_is_truncated_on_the_way_out_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(tmp_path, workspace_not_collected={"reason": "x" * 5000})
        note = _summary(monkeypatch, tmp_path)["workspace_not_collected"]
        assert len(note["reason"]) == NOT_COLLECTED_REASON_MAX_CHARS

    def test_a_workspace_note_never_appears_as_a_platform_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The acceptance condition, on the wire: the two must not render as
        one sentence, so a workspace failure puts nothing on any platform
        row."""
        _write(
            tmp_path,
            platforms={_PLATFORM: PlatformState(account_id=_ACCOUNT)},
            workspace_not_collected={"reason": _REASON},
        )
        summary = _summary(monkeypatch, tmp_path)
        (row,) = summary["platforms"]
        assert row["not_collected"] is None
        assert summary["workspace_not_collected"]["reason"] == _REASON

    def test_a_platform_note_never_appears_as_a_workspace_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    not_collected={"reason": "the Meta access token expired"},
                )
            },
        )
        summary = _summary(monkeypatch, tmp_path)
        assert summary["workspace_not_collected"] is None
        (row,) = summary["platforms"]
        assert row["not_collected"]["reason"] == "the Meta access token expired"


@pytest.mark.usefixtures("_reset_ctx")
class TestARetiredNoteIsNotShown:
    """Retired by evidence, not by discipline.

    The per-platform rule (#638), one level up: a note is dropped once ANY
    rollup in the document carries a ``fetched_at`` later than the failure it
    describes. A collection that succeeded after the failure has already
    answered it, and the correctness of what an operator sees must not depend
    on the writer having remembered to clear the note.
    """

    def test_a_collection_that_succeeded_since_retires_the_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    totals={"spend": 1.0, "fetched_at": "2026-08-18T09:00:00+00:00"},
                )
            },
            workspace_not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        assert _summary(monkeypatch, tmp_path)["workspace_not_collected"] is None

    def test_a_success_on_ANY_platform_retires_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The note is about the workspace, so any platform being reached
        proves the collection ran — including one that is not the platform
        whose own note is still open."""
        _write(
            tmp_path,
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    not_collected={
                        "attempted_at": "2026-08-18T09:00:00+00:00",
                        "reason": "the Google Ads token expired",
                    },
                ),
                "meta_ads": PlatformState(
                    account_id="act_1",
                    periods={
                        "YESTERDAY": {
                            "spend": 2.0,
                            "fetched_at": "2026-08-18T09:00:00+00:00",
                        }
                    },
                ),
            },
            workspace_not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        summary = _summary(monkeypatch, tmp_path)
        assert summary["workspace_not_collected"] is None
        # …and the platform note, whose own failure is NEWER than that
        # rollup, is untouched by the document-level rule.
        google = [r for r in summary["platforms"] if r["key"] == _PLATFORM][0]
        assert google["not_collected"]["reason"] == "the Google Ads token expired"

    def test_an_older_collection_does_not_retire_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    totals={"spend": 1.0, "fetched_at": "2026-08-10T09:00:00+00:00"},
                )
            },
            workspace_not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        note = _summary(monkeypatch, tmp_path)["workspace_not_collected"]
        assert note is not None and note["reason"] == _REASON

    def test_a_workspace_never_collected_at_all_keeps_its_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The case the record matters most for: no platforms, no rollups,
        nothing to retire it — and the note is the only thing the page can
        say."""
        _write(
            tmp_path,
            workspace_not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        note = _summary(monkeypatch, tmp_path)["workspace_not_collected"]
        assert note is not None and note["reason"] == _REASON

    def test_an_undatable_pair_keeps_the_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Retirement is a proof, not a guess: an unparseable ``fetched_at``
        leaves the question open, and open is not retired."""
        _write(
            tmp_path,
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    totals={"spend": 1.0, "fetched_at": "today"},
                )
            },
            workspace_not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        assert _summary(monkeypatch, tmp_path)["workspace_not_collected"] is not None

    def test_a_note_with_no_attempted_at_is_never_retired(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    totals={"spend": 1.0, "fetched_at": "2026-08-18T09:00:00+00:00"},
                )
            },
            workspace_not_collected={"reason": _REASON},
        )
        assert _summary(monkeypatch, tmp_path)["workspace_not_collected"] is not None

    def test_the_period_toggle_cannot_resurrect_a_retired_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mureo.core.runtime_context import default_runtime_context
        from mureo.web.reports import build_report_summary

        _write(
            tmp_path,
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    periods={
                        "LAST_30_DAYS": {
                            "spend": 1.0,
                            "fetched_at": "2026-08-10T09:00:00+00:00",
                        },
                        "YESTERDAY": {
                            "spend": 2.0,
                            "fetched_at": "2026-08-18T09:00:00+00:00",
                        },
                    },
                )
            },
            workspace_not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        ctx = default_runtime_context(workspace=tmp_path)
        monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
        for period in (None, "LAST_30_DAYS", "YESTERDAY"):
            summary = build_report_summary(period=period)
            assert summary["workspace_not_collected"] is None


# ---------------------------------------------------------------------------
# The MCP tool
# ---------------------------------------------------------------------------


class TestTheMcpTool:
    @pytest.fixture(autouse=True)
    def _cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
        from mureo.core.runtime_context import reset_runtime_context

        reset_runtime_context()
        monkeypatch.chdir(tmp_path)
        yield tmp_path
        reset_runtime_context()

    async def _call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from mureo.mcp.tools_mureo_context import handle_tool

        result = await handle_tool("mureo_state_workspace_not_collected_set", arguments)
        return json.loads(result[0].text)

    async def test_it_records_a_reason(self) -> None:
        payload = await self._call({"reason": _REASON})
        assert payload["workspace_not_collected"]["reason"] == _REASON
        assert payload["workspace_not_collected"]["attempted_at"]

    async def test_omitting_the_reason_clears_the_note(self) -> None:
        await self._call({"reason": _REASON})
        assert "workspace_not_collected" not in await self._call({})

    async def test_a_non_string_reason_is_refused(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            await self._call({"reason": {"a": 1}})

    async def test_the_tool_requires_no_platform_and_no_account_id(self) -> None:
        from mureo.mcp.tools_mureo_context import TOOLS

        (tool,) = [
            t for t in TOOLS if t.name == "mureo_state_workspace_not_collected_set"
        ]
        assert tool.inputSchema.get("required", []) == []
        assert "platform" not in tool.inputSchema["properties"]
        assert "account_id" not in tool.inputSchema["properties"]
        assert "clear" in tool.description.lower()

    async def test_it_is_distinguishable_from_the_platform_tool(self) -> None:
        """Two tools, because they record two different facts. An agent that
        reads one must not think it has read the other."""
        from mureo.mcp.tools_mureo_context import TOOLS

        (workspace,) = [
            t for t in TOOLS if t.name == "mureo_state_workspace_not_collected_set"
        ]
        assert "mureo_state_platform_not_collected_set" in workspace.description


# ---------------------------------------------------------------------------
# The skill that tells the caller it exists
# ---------------------------------------------------------------------------
#
# A tool nothing points at is a tool nobody calls. ``_mureo-strategy`` is
# where an agent learns how to write STATE.json, and it already routes the
# per-platform failure; without the workspace-level half beside it, an agent
# whose collection died before any platform was reached records nothing — or
# reaches for one of the two workarounds #661 exists to retire (a platforms
# entry with a blank account_id, or the ``reports`` section).
#
# No existing suite pins this file's mirror: tests/test_skill_ja_triggers.py
# skips every ``_``-prefixed foundation skill, and
# tests/test_skill_server_now_clock.py pins ``_mureo-shared`` only. So the
# byte-identity check is made here rather than assumed.

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED_STRATEGY_SKILL = (
    _REPO_ROOT / "mureo" / "_data" / "skills" / "_mureo-strategy" / "SKILL.md"
)
_MIRROR_STRATEGY_SKILL = _REPO_ROOT / "skills" / "_mureo-strategy" / "SKILL.md"


class TestTheSkillRoutesTheCaller:
    def test_the_skill_names_the_workspace_level_tool(self) -> None:
        body = _PACKAGED_STRATEGY_SKILL.read_text(encoding="utf-8")
        assert "mureo_state_workspace_not_collected_set" in body
        assert "workspace_not_collected" in body

    def test_it_says_which_of_the_two_to_use(self) -> None:
        """Both tools named in one place, with the question that picks
        between them — a skill that documents only one of a pair teaches the
        wrong one for half the failures."""
        body = _PACKAGED_STRATEGY_SKILL.read_text(encoding="utf-8")
        assert "mureo_state_platform_not_collected_set" in body
        assert "before any platform was reached" in body

    def test_it_forbids_both_workarounds(self) -> None:
        """The two shapes #661 exists to retire, named so an agent does not
        reinvent either: a platforms entry that says nothing about an account,
        and the analysis-summary section used as a failure log."""
        body = _PACKAGED_STRATEGY_SKILL.read_text(encoding="utf-8")
        assert "invent a `platforms` entry" in body
        assert "`reports`" in body

    def test_the_packaged_copy_and_the_mirror_are_identical(self) -> None:
        """The repo-root ``skills/`` tree is what an operator reads and
        ``mureo/_data/skills`` is what ships; an edit landing on one side only
        is a rule that exists for half the hosts."""
        assert (
            _MIRROR_STRATEGY_SKILL.read_bytes() == _PACKAGED_STRATEGY_SKILL.read_bytes()
        )
