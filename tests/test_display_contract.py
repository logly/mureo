"""The dashboard reads a write-guarded surface, not the agent's prose (#706).

STATE.json is the agent's working memory and is prose-heavy by design. The
dashboard had been rendering it directly, and what an operator got was walls
of jargon, thirty-row value dumps with sentences in numeric columns, and
work-journal action logs showing raw ``**`` markdown on screen.

So the two audiences are separated, and the separation is only real if the
contract is ENFORCED. That is what this file pins, in four groups:

**The bounds refuse.** Every limit in the issue's table, each checked at its
own boundary, and each refusing rather than truncating — a sentence cut in
half reads like a bug in mureo and nobody can tell what was removed (#662's
rule, applied to a second surface).

**A refusal changes nothing.** The write is validated before the lock is
taken, so a rejected call leaves STATE.json byte-for-byte as it was —
``last_synced_at`` included. Without this, "refused" would mean "refused,
and also half-written".

**The codec is honest in both directions.** A contract survives the round
trip; a document that has never had one gains no key; a document that has
one and then clears it leaves no key behind for a reader to render as live.

**The read side is tolerant.** Every bound here is a WRITE rule. A value
already on disk is content an operator has, and refusing to read it would
only delete that — the same asymmetry #659 settled for the metrics windows.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mureo.context.display_codec import (
    display_contract_to_dict,
    parse_display_contract,
)
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import (
    append_action_log,
    read_state_file,
    render_state,
    set_display,
    set_report,
    write_state_file,
)
from mureo.core.display_contract import (
    ACTION_LOG_DISPLAY_RULE,
    ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS,
    ACTION_LOG_DISPLAY_TITLE_MAX_CHARS,
    BREAKDOWN_NOTE_MAX_CHARS,
    BREAKDOWN_STATES,
    DISPLAY_CONTRACT_RULE,
    DISPLAY_OVERWRITE_RULE,
    DISPLAY_SECTIONS,
    DISPLAY_SOURCE_MAX_CHARS,
    HIGHLIGHT_TEXT_MAX_CHARS,
    HIGHLIGHT_TONE_BY_SEVERITY,
    HIGHLIGHT_TONE_RULE,
    HIGHLIGHT_TONES,
    HIGHLIGHTS_MAX_ITEMS,
    NAV_MESSAGE_MAX_CHARS,
    PROPOSAL_BODY_MAX_CHARS,
    PROPOSAL_DATE_MAX_CHARS,
    PROPOSAL_STATUSES,
    PROPOSAL_TITLE_MAX_CHARS,
    STATED_VALUE_LABEL_MAX_CHARS,
    STATED_VALUE_MAX_CHARS,
    validate_action_log_display,
    validate_display_contract,
)

pytestmark = pytest.mark.unit


def _validate_contract(display: dict[str, Any]) -> None:
    """Validate a payload, supplying the attribution every write needs (#706).

    ``source`` is required alongside any section, and it is orthogonal to
    every bound below — so it is added here rather than repeated in thirty
    literals, and the attribution rule gets a class of its own
    (:class:`TestTheScreenSaysWhoDrewIt`). A test that needs the payload
    exactly as written calls ``validate_display_contract`` directly.
    """
    validate_display_contract({"source": "daily-check", **display})


def _state(tmp_path: Path) -> Path:
    """A STATE.json with something in it, so "unchanged" can be asserted."""
    path = tmp_path / "STATE.json"
    write_state_file(
        path,
        StateDocument(version="2", last_synced_at="2026-08-08T09:00:00+09:00"),
    )
    return path


# ---------------------------------------------------------------------------
# The bounds refuse — one case per row of the issue's table
# ---------------------------------------------------------------------------


class TestEveryBoundRefuses:
    """Over the limit is REFUSED, and the refusal says the whole rule."""

    def test_nav_message_over_the_bound(self) -> None:
        with pytest.raises(ValueError) as exc:
            _validate_contract({"nav_message": "あ" * 81})
        assert str(NAV_MESSAGE_MAX_CHARS) in str(exc.value)
        assert "truncated" in str(exc.value)

    def test_nav_message_at_the_bound_is_accepted(self) -> None:
        """The bound is inclusive — a limit a normal write brushes against
        becomes noise an agent works around."""
        _validate_contract({"nav_message": "x" * NAV_MESSAGE_MAX_CHARS})

    def test_a_fourth_highlight(self) -> None:
        with pytest.raises(ValueError) as exc:
            _validate_contract(
                {
                    "highlights": [
                        {"tone": "good", "text": f"h{i}"}
                        for i in range(HIGHLIGHTS_MAX_ITEMS + 1)
                    ]
                }
            )
        # Nothing is DROPPED either: the caller chooses which three matter.
        assert "nothing was dropped" in str(exc.value)

    def test_highlight_text_over_the_bound(self) -> None:
        with pytest.raises(ValueError, match="highlights\\[0\\].text"):
            _validate_contract({"highlights": [{"tone": "good", "text": "x" * 61}]})

    def test_proposal_title_and_body_bounds(self) -> None:
        with pytest.raises(ValueError, match="proposals\\[0\\].title"):
            _validate_contract(
                {"proposals": [{"title": "x" * (PROPOSAL_TITLE_MAX_CHARS + 1)}]}
            )
        with pytest.raises(ValueError, match="proposals\\[0\\].body"):
            _validate_contract(
                {
                    "proposals": [
                        {"title": "ok", "body": "x" * (PROPOSAL_BODY_MAX_CHARS + 1)}
                    ]
                }
            )

    def test_proposal_date_is_bounded_but_not_formatted(self) -> None:
        """A date field is not a place for prose — but mureo imposes no
        format on a value it only displays."""
        _validate_contract({"proposals": [{"title": "ok", "date": "2026-08-08"}]})
        _validate_contract({"proposals": [{"title": "ok", "date": "last week"}]})
        with pytest.raises(ValueError, match="proposals\\[0\\].date"):
            _validate_contract(
                {
                    "proposals": [
                        {"title": "ok", "date": "x" * (PROPOSAL_DATE_MAX_CHARS + 1)}
                    ]
                }
            )

    def test_breakdown_note_over_the_bound(self) -> None:
        with pytest.raises(ValueError, match="breakdown.campaigns\\[0\\].note"):
            _validate_contract(
                {
                    "breakdown": {
                        "campaigns": [
                            {
                                "name": "Brand",
                                "note": "x" * (BREAKDOWN_NOTE_MAX_CHARS + 1),
                            }
                        ]
                    }
                }
            )

    def test_the_ad_group_table_is_guarded_too(self) -> None:
        """Both levels, not just the first one a reader thinks of."""
        with pytest.raises(ValueError, match="breakdown.adgroups\\[1\\].note"):
            _validate_contract(
                {
                    "breakdown": {
                        "adgroups": [
                            {"name": "ok"},
                            {"name": "Brand — exact", "note": "x" * 41},
                        ]
                    }
                }
            )

    def test_stated_value_label_over_the_bound(self) -> None:
        with pytest.raises(ValueError, match="stated_values\\[0\\].label"):
            _validate_contract(
                {
                    "stated_values": [
                        {
                            "label": "x" * (STATED_VALUE_LABEL_MAX_CHARS + 1),
                            "value": 1,
                        }
                    ]
                }
            )

    def test_action_log_display_bounds(self) -> None:
        with pytest.raises(ValueError, match="display_title"):
            validate_action_log_display(
                display_title="x" * (ACTION_LOG_DISPLAY_TITLE_MAX_CHARS + 1)
            )
        with pytest.raises(ValueError, match="display_summary"):
            validate_action_log_display(
                display_summary="x" * (ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS + 1)
            )
        # Both absent is every entry written before these existed.
        validate_action_log_display()


# ---------------------------------------------------------------------------
# The vocabularies are closed
# ---------------------------------------------------------------------------


class TestClosedVocabularies:
    """Each of these is rendered as a chip or a colour, so an invented value
    is a write that reports success and draws nothing."""

    @pytest.mark.parametrize("tone", HIGHLIGHT_TONES)
    def test_every_declared_tone_is_accepted(self, tone: str) -> None:
        _validate_contract({"highlights": [{"tone": tone, "text": "ok"}]})

    def test_an_invented_tone_is_refused(self) -> None:
        with pytest.raises(ValueError) as exc:
            _validate_contract({"highlights": [{"tone": "critical", "text": "ok"}]})
        # The message states the whole allow-list: an agent that reached for
        # "critical" needs to know what the alternatives ARE.
        for tone in HIGHLIGHT_TONES:
            assert tone in str(exc.value)

    @pytest.mark.parametrize("status", PROPOSAL_STATUSES)
    def test_every_declared_status_is_accepted(self, status: str) -> None:
        _validate_contract({"proposals": [{"title": "ok", "status": status}]})

    def test_an_invented_status_is_refused(self) -> None:
        with pytest.raises(ValueError, match="proposals\\[0\\].status"):
            _validate_contract(
                {"proposals": [{"title": "ok", "status": "in_progress"}]}
            )

    @pytest.mark.parametrize("state", BREAKDOWN_STATES)
    def test_every_declared_row_state_is_accepted(self, state: str) -> None:
        _validate_contract(
            {"breakdown": {"campaigns": [{"name": "Brand", "state": state}]}}
        )

    def test_an_invented_row_state_is_refused(self) -> None:
        with pytest.raises(ValueError, match="breakdown.campaigns\\[0\\].state"):
            _validate_contract(
                {"breakdown": {"campaigns": [{"name": "Brand", "state": "bad"}]}}
            )

    def test_a_section_the_dashboard_does_not_read_is_refused(self) -> None:
        """Unlike a report's ``totals`` — where an unknown key is still the
        report's own content and is stored — this surface has one view with a
        fixed layout, so a section it does not draw is a silent write."""
        with pytest.raises(ValueError) as exc:
            _validate_contract({"funnel": {"spend": 1}})
        assert "funnel" in str(exc.value)
        for section in DISPLAY_SECTIONS:
            assert section in str(exc.value)

    def test_a_third_breakdown_table_is_refused(self) -> None:
        with pytest.raises(ValueError, match="breakdown"):
            _validate_contract({"breakdown": {"keywords": []}})


# ---------------------------------------------------------------------------
# Prose where a value belongs
# ---------------------------------------------------------------------------


class TestStatedValuesRefuseProse:
    """The reported defect in miniature: whole sentences in a numeric column."""

    def test_a_number_is_accepted(self) -> None:
        _validate_contract({"stated_values": [{"label": "CVR", "value": 0.021}]})

    def test_a_short_string_is_accepted(self) -> None:
        """A report legitimately states what a number cannot carry — and
        refusing those would push that content back into the prose."""
        _validate_contract(
            {"stated_values": [{"label": "goals met", "value": "3 of 7"}]}
        )

    def test_a_sentence_is_refused(self) -> None:
        with pytest.raises(ValueError) as exc:
            _validate_contract(
                {
                    "stated_values": [
                        {
                            "label": "CPA",
                            "value": (
                                "CPA is 12% over target, driven by the two "
                                "brand ad groups"
                            ),
                        }
                    ]
                }
            )
        assert "numeric column" in str(exc.value)
        assert "truncated" in str(exc.value)

    def test_a_string_at_the_bound_is_accepted(self) -> None:
        _validate_contract(
            {"stated_values": [{"label": "x", "value": "y" * STATED_VALUE_MAX_CHARS}]}
        )

    def test_a_structure_is_refused(self) -> None:
        with pytest.raises(ValueError, match="never a structure"):
            _validate_contract(
                {"stated_values": [{"label": "x", "value": {"spend": 1}}]}
            )

    @pytest.mark.parametrize("value", [True, None])
    def test_a_boolean_or_nothing_is_refused(self, value: Any) -> None:
        """``True`` in a numeric column is not a figure, and rendering it as
        ``1`` would invent one."""
        with pytest.raises(ValueError, match="stated_values\\[0\\].value"):
            _validate_contract({"stated_values": [{"label": "x", "value": value}]})

    def test_a_formatted_figure_is_refused_in_the_breakdown(self) -> None:
        """The same refusal ``validate_report_summary`` makes: a string sits
        where the table reads a figure and renders as nothing."""
        with pytest.raises(ValueError, match="breakdown.campaigns\\[0\\].spend"):
            _validate_contract(
                {"breakdown": {"campaigns": [{"name": "Brand", "spend": "¥773,957"}]}}
            )


# ---------------------------------------------------------------------------
# A refusal changes nothing on disk
# ---------------------------------------------------------------------------


class TestARefusalLeavesTheFileAlone:
    """Validation runs before the lock is taken, so "refused" cannot also
    mean "half-written"."""

    def test_a_refused_display_write_does_not_touch_state_json(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        before = path.read_bytes()

        with pytest.raises(ValueError):
            set_display(path, source="daily-check", nav_message="x" * 200)

        assert path.read_bytes() == before

    def test_a_refused_display_write_does_not_restamp_last_synced_at(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)

        with pytest.raises(ValueError):
            set_display(
                path,
                source="daily-check",
                stated_values=[{"label": "x", "value": {"a": 1}}],
            )

        assert read_state_file(path).last_synced_at == "2026-08-08T09:00:00+09:00"

    def test_a_refused_action_log_append_writes_no_entry(self, tmp_path: Path) -> None:
        path = _state(tmp_path)

        with pytest.raises(ValueError, match="display_summary"):
            append_action_log(
                path,
                ActionLogEntry(
                    timestamp="2026-08-08T10:00:00+09:00",
                    action="google_ads_budget_update",
                    platform="google_ads",
                    display_summary="x" * 500,
                ),
            )

        assert read_state_file(path).action_log == ()


# ---------------------------------------------------------------------------
# What set_display actually writes
# ---------------------------------------------------------------------------


class TestSetDisplay:
    def test_it_writes_every_section(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        doc = set_display(
            path,
            source="daily-check",
            nav_message="CPA is over target — pause the two worst ad groups",
            highlights=[{"tone": "bad", "text": "CPA 12% over target"}],
            proposals=[{"title": "Pause two ad groups", "status": "proposed"}],
            breakdown={
                "campaigns": [
                    {
                        "name": "Brand Search",
                        "spend": 42000.0,
                        "mcpa": 5200.0,
                        "target_cpa": 4500.0,
                        "state": "worsening",
                        "note": "capped every afternoon",
                    }
                ],
                "adgroups": [{"name": "Brand — exact", "state": "target_met"}],
            },
            stated_values=[{"label": "CVR", "value": 0.021}],
        )
        contract = doc.display
        assert contract is not None
        assert contract.highlights[0].tone == "bad"
        assert contract.proposals[0].title == "Pause two ad groups"
        assert contract.breakdown.campaigns[0].mcpa == 5200.0
        assert contract.breakdown.adgroups[0].name == "Brand — exact"
        assert contract.stated_values[0].value == 0.021
        # …and it is on disk, not only in the returned object.
        assert read_state_file(path).display == contract

    def test_the_whole_section_is_replaced(self, tmp_path: Path) -> None:
        """One pass produces one screen. Merging per section would put last
        week's highlights beside today's nav line with nothing able to say
        they came from different runs."""
        path = _state(tmp_path)
        set_display(
            path,
            source="weekly-report",
            nav_message="old line",
            highlights=[{"tone": "watch", "text": "old chip"}],
        )

        doc = set_display(path, source="daily-check", nav_message="new line")

        assert doc.display is not None
        assert doc.display.nav_message == "new line"
        assert doc.display.highlights == ()

    def test_a_call_that_states_nothing_clears_the_contract(
        self, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        set_display(path, source="daily-check", nav_message="stale line")

        doc = set_display(path)

        assert doc.display is None
        # No empty key left behind for a reader to render as a live one.
        assert "display" not in json.loads(path.read_text(encoding="utf-8"))

    def test_it_does_not_disturb_the_report_summaries(self, tmp_path: Path) -> None:
        """Two sections, two audiences, two questions — a write of one must
        never touch the other."""
        path = _state(tmp_path)
        set_report(path, "daily", {"narrative": "healthy"})

        doc = set_display(path, source="daily-check", nav_message="on pace")

        assert doc.reports == {"daily": {"narrative": "healthy"}}


# ---------------------------------------------------------------------------
# The action-log display line
# ---------------------------------------------------------------------------


class TestActionLogDisplayLine:
    def test_a_bounded_line_is_stored_and_read_back(self, tmp_path: Path) -> None:
        path = _state(tmp_path)
        append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-08-08T10:00:00+09:00",
                action="google_ads_budget_update",
                platform="google_ads",
                summary="a" * 400,
                display_title="Raised the Brand budget",
                display_summary="Brand Search was capped every afternoon; +20%.",
            ),
        )
        entry = read_state_file(path).action_log[0]
        assert entry.display_title == "Raised the Brand budget"
        # It ADDS a rendering and replaces nothing: the work-journal note is
        # still there in full for the next agent.
        assert entry.summary == "a" * 400

    def test_an_entry_written_before_these_fields_parses_unchanged(
        self, tmp_path: Path
    ) -> None:
        """The whole compatibility promise, stated as the case that matters:
        a document on disk that has never heard of #706."""
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "action_log": [
                        {
                            "timestamp": "2026-08-01T10:00:00+09:00",
                            "action": "google_ads_budget_update",
                            "platform": "google_ads",
                            "summary": "raised daily budget",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        entry = read_state_file(path).action_log[0]
        assert entry.display_title is None
        assert entry.display_summary is None
        # …and it gains no key on the next write.
        assert "display_title" not in render_state(read_state_file(path))


# ---------------------------------------------------------------------------
# The codec, in both directions
# ---------------------------------------------------------------------------


class TestCodec:
    def test_a_document_with_no_contract_gains_no_key(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        write_state_file(path, StateDocument(version="2"))
        assert "display" not in json.loads(path.read_text(encoding="utf-8"))

    def test_an_empty_contract_is_the_same_as_none(self) -> None:
        """Nothing to draw is nothing to draw; collapsing the two is what
        keeps a document byte-stable through a round trip."""
        assert parse_display_contract({}) is None
        assert parse_display_contract({"highlights": []}) is None
        assert parse_display_contract("not an object") is None

    def test_a_partial_contract_round_trips_as_exactly_its_own_keys(self) -> None:
        contract = parse_display_contract({"nav_message": "on pace"})
        assert contract is not None
        assert display_contract_to_dict(contract) == {"nav_message": "on pace"}

    def test_a_figure_a_row_does_not_have_stays_absent(self) -> None:
        """A row with no conversions has no ``mcpa``, and writing 0 would
        state a perfect cost per acquisition rather than the absence of one."""
        contract = parse_display_contract(
            {"breakdown": {"campaigns": [{"name": "Brand", "spend": 100}]}}
        )
        assert contract is not None
        row = display_contract_to_dict(contract)["breakdown"]["campaigns"][0]
        assert row == {"name": "Brand", "spend": 100}


class TestTheReadSideIsTolerant:
    """Every bound is a WRITE rule. A value already on disk is content an
    operator has, and refusing to read it would only delete that (#659)."""

    def test_an_over_long_value_on_disk_is_read_back_verbatim(self) -> None:
        long_line = "x" * 500
        contract = parse_display_contract({"nav_message": long_line})
        assert contract is not None
        assert contract.nav_message == long_line

    def test_a_tone_outside_the_vocabulary_on_disk_survives(self) -> None:
        contract = parse_display_contract(
            {"highlights": [{"tone": "critical", "text": "ok"}]}
        )
        assert contract is not None
        assert contract.highlights[0].tone == "critical"

    def test_a_row_with_no_shape_is_dropped_and_the_rest_survives(self) -> None:
        """The one thing read tolerance does drop: an entry that is not an
        entry. A breakdown row with no name names nothing."""
        contract = parse_display_contract(
            {
                "breakdown": {
                    "campaigns": [
                        "a string",
                        {"note": "no name"},
                        {"name": "Brand"},
                    ]
                }
            }
        )
        assert contract is not None
        assert [r.name for r in contract.breakdown.campaigns] == ["Brand"]

    def test_a_malformed_display_section_costs_the_screen_not_the_document(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        path.write_text(
            json.dumps(
                {
                    "version": "2",
                    "display": "a paragraph someone pasted in",
                    "action_log": [
                        {
                            "timestamp": "2026-08-01T10:00:00+09:00",
                            "action": "x",
                            "platform": "google_ads",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        doc = read_state_file(path)
        assert doc.display is None
        assert len(doc.action_log) == 1


# ---------------------------------------------------------------------------
# One rule, shown on every path
# ---------------------------------------------------------------------------


class TestTheRuleIsStatedOnce:
    """#659's shape: the description an agent reads BEFORE it calls and the
    refusal it gets after must be the same sentences, or a caller is told two
    different things depending on which path refused it."""

    def test_the_refusal_repeats_the_rule(self) -> None:
        with pytest.raises(ValueError) as exc:
            _validate_contract({"nav_message": "x" * 200})
        assert DISPLAY_CONTRACT_RULE in str(exc.value)

    def test_the_action_log_refusal_repeats_its_rule(self) -> None:
        with pytest.raises(ValueError) as exc:
            validate_action_log_display(display_title="x" * 100)
        assert ACTION_LOG_DISPLAY_RULE in str(exc.value)

    def test_the_rule_states_every_bound_it_guards(self) -> None:
        """A bound enforced but not stated is a refusal an agent cannot have
        avoided."""
        for limit in (
            NAV_MESSAGE_MAX_CHARS,
            HIGHLIGHTS_MAX_ITEMS,
            HIGHLIGHT_TEXT_MAX_CHARS,
            PROPOSAL_TITLE_MAX_CHARS,
            PROPOSAL_BODY_MAX_CHARS,
            BREAKDOWN_NOTE_MAX_CHARS,
            STATED_VALUE_LABEL_MAX_CHARS,
            STATED_VALUE_MAX_CHARS,
        ):
            assert str(limit) in DISPLAY_CONTRACT_RULE

    def test_the_rule_states_every_vocabulary_it_closes(self) -> None:
        for word in (*HIGHLIGHT_TONES, *PROPOSAL_STATUSES, *BREAKDOWN_STATES):
            assert word in DISPLAY_CONTRACT_RULE

    def test_the_rule_names_what_the_agent_must_not_write(self) -> None:
        """The funnel and the chart are derived. Saying so in the description
        is what stops an agent writing them somewhere no view reads."""
        assert "funnel" in DISPLAY_CONTRACT_RULE
        assert "chart" in DISPLAY_CONTRACT_RULE


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


@pytest.mark.usefixtures("_reset_ctx")
class TestTheWire:
    """The read side of #706 — step 1 stops here. The browser is a separate
    issue; what this pins is that the payload carries the contract, and that
    it carries it as JSON a view can render without knowing about mureo's
    dataclasses."""

    def test_the_summary_carries_the_contract(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        set_display(
            path,
            source="daily-check",
            nav_message="on pace",
            highlights=[{"tone": "good", "text": "CPA under target"}],
        )

        summary = _summary(monkeypatch, tmp_path)

        assert summary["display"] == {
            # Attribution rides on the wire too (#706): step 3 shows which
            # skill drew the screen and when, so a card whose section a later
            # run replaced is still attributable rather than merely gone.
            "source": "daily-check",
            "generated_at": read_state_file(path).last_synced_at,
            "nav_message": "on pace",
            "highlights": [{"tone": "good", "text": "CPA under target"}],
        }

    def test_it_is_json_safe(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The payload is relayed verbatim by the ``/api/reports/*`` handlers,
        so a dataclass reaching the wire is a 500 at render time."""
        path = _state(tmp_path)
        set_display(
            path,
            source="daily-check",
            breakdown={"campaigns": [{"name": "Brand", "spend": 1.0}]},
            stated_values=[{"label": "CVR", "value": "3 of 7"}],
        )

        summary = _summary(monkeypatch, tmp_path)

        assert json.loads(json.dumps(summary))["display"] == summary["display"]

    def test_a_client_with_no_contract_is_told_so_explicitly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``None`` rather than an absent key, so the frontend reads one
        shape for every client."""
        _state(tmp_path)

        summary = _summary(monkeypatch, tmp_path)

        assert "display" in summary
        assert summary["display"] is None

    def test_the_action_rows_carry_the_display_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-08-08T10:00:00+09:00",
                action="google_ads_budget_update",
                platform="google_ads",
                summary="a" * 400,
                display_title="Raised the Brand budget",
                display_summary="Capped every afternoon; +20% daily.",
            ),
        )

        row = _summary(monkeypatch, tmp_path)["recent_actions"][0]

        assert row["display_title"] == "Raised the Brand budget"
        assert row["display_summary"] == "Capped every afternoon; +20% daily."
        # A field accepted on write and rendered nowhere is content nobody can
        # discover exists (#670) — but the fallback stays on the wire too.
        assert row["summary"] == "a" * 400

    def test_an_entry_with_no_display_line_still_has_the_keys(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _state(tmp_path)
        append_action_log(
            path,
            ActionLogEntry(
                timestamp="2026-08-08T10:00:00+09:00",
                action="google_ads_budget_update",
                platform="google_ads",
            ),
        )

        row = _summary(monkeypatch, tmp_path)["recent_actions"][0]

        assert row["display_title"] is None
        assert row["display_summary"] is None

    def test_the_wire_shape_is_the_codec_shape(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """One emitter for both, so what the dashboard reads and what is on
        disk cannot drift into two shapes."""
        path = _state(tmp_path)
        set_display(
            path,
            source="daily-check",
            nav_message="on pace",
            proposals=[{"title": "Pause two"}],
        )

        summary = _summary(monkeypatch, tmp_path)

        assert (
            summary["display"]
            == json.loads(path.read_text(encoding="utf-8"))["display"]
        )


# ---------------------------------------------------------------------------
# The screen says who drew it, and when
# ---------------------------------------------------------------------------


class TestTheScreenSaysWhoDrewIt:
    """Last-writer-wins is the design, and this is what it costs paid off.

    The contract is replaced wholesale, so a weekly review's proposals can be
    gone by the evening. That is deliberate — a screen is one moment, and
    merging two runs shows a moment that never happened — but a reader who
    cannot tell WHOSE answer survived has no way to make sense of what is in
    front of them. ``source`` and ``generated_at`` answer that.
    """

    def test_a_section_without_a_source_is_refused(self) -> None:
        with pytest.raises(ValueError, match="source is required"):
            validate_display_contract({"nav_message": "on pace"})

    @pytest.mark.parametrize("section", DISPLAY_SECTIONS)
    def test_every_section_requires_attribution(self, section: str) -> None:
        """All five, or an unattributed screen has a way in."""
        payload: dict[str, Any] = {
            "nav_message": "x",
            "highlights": [{"tone": "good", "text": "x"}],
            "proposals": [{"title": "x"}],
            "breakdown": {"campaigns": [{"name": "x"}]},
            "stated_values": [{"label": "x", "value": 1}],
        }
        with pytest.raises(ValueError, match="source is required"):
            validate_display_contract({section: payload[section]})

    def test_the_clear_needs_no_source(self) -> None:
        """It takes the screen down and leaves nothing to attribute — the one
        write for which "who" has nowhere to be stored."""
        validate_display_contract({})

    def test_an_overlong_source_is_refused(self) -> None:
        with pytest.raises(ValueError, match="source"):
            validate_display_contract(
                {
                    "source": "x" * (DISPLAY_SOURCE_MAX_CHARS + 1),
                    "nav_message": "on pace",
                }
            )

    def test_a_blank_source_is_not_a_source(self) -> None:
        with pytest.raises(ValueError, match="source is required"):
            validate_display_contract({"source": "   ", "nav_message": "on pace"})

    def test_generated_at_is_stamped_by_the_server(self, tmp_path: Path) -> None:
        """The #460 rule, on the one field a reader has to be able to trust.

        A model-supplied "now" is how a drifted clock gets persisted and read
        back as fact, and the age of the screen is exactly what tells an
        operator whether to believe it.
        """
        path = _state(tmp_path)
        doc = set_display(path, source="daily-check", nav_message="on pace")

        assert doc.display is not None
        assert doc.display.generated_at == doc.last_synced_at
        # …and it is not a parameter a caller could pass at all.
        with pytest.raises(TypeError):
            set_display(  # type: ignore[call-arg]
                path,
                source="daily-check",
                nav_message="on pace",
                generated_at="1999-01-01T00:00:00+00:00",
            )

    def test_clearing_drops_the_attribution_with_the_screen(
        self, tmp_path: Path
    ) -> None:
        """No attributed blank: there is no screen, so there is no author."""
        path = _state(tmp_path)
        set_display(path, source="daily-check", nav_message="on pace")

        doc = set_display(path)

        assert doc.display is None
        assert "display" not in json.loads(path.read_text(encoding="utf-8"))

    def test_a_contract_written_before_attribution_existed_still_reads(self) -> None:
        """The bounds are a WRITE rule, and so is this one: a screen already
        on disk from before #706's review round has no author, and dropping
        it to tidy that up would delete content an operator has."""
        contract = parse_display_contract({"nav_message": "on pace"})

        assert contract is not None
        assert contract.nav_message == "on pace"
        assert contract.source is None
        assert contract.generated_at is None

    def test_attribution_alone_is_not_a_screen(self) -> None:
        """A payload with an author and nothing to show renders nothing, so
        it round-trips to ``None`` rather than to an attributed blank."""
        assert (
            parse_display_contract(
                {"source": "daily-check", "generated_at": "2026-08-08T09:00:00+09:00"}
            )
            is None
        )

    def test_attribution_leads_the_stored_object(self, tmp_path: Path) -> None:
        """It is what a reader checks before believing any of the rest."""
        path = _state(tmp_path)
        set_display(path, source="weekly-report", nav_message="on pace")

        stored = json.loads(path.read_text(encoding="utf-8"))["display"]

        assert list(stored)[:2] == ["source", "generated_at"]


# ---------------------------------------------------------------------------
# Severity → tone
# ---------------------------------------------------------------------------


class TestTheToneMap:
    """A chip is a severity in fewer characters, so the two vocabularies need
    one table — mapped by feel, the same finding ends up amber on one
    client's card and red on another's."""

    def test_every_tone_it_maps_to_is_a_real_tone(self) -> None:
        assert set(HIGHLIGHT_TONE_BY_SEVERITY.values()) <= set(HIGHLIGHT_TONES)

    def test_every_severity_is_decided(self) -> None:
        """A fifth severity must not be able to appear without someone
        deciding whether it is a chip at all — which is the decision ``info``
        already has an answer to."""
        from mureo.analysis.report_flags import SEVERITIES

        undecided = set(SEVERITIES) - set(HIGHLIGHT_TONE_BY_SEVERITY) - {"info"}
        assert not undecided, (
            f"report_flags gained severity {sorted(undecided)}. Decide whether "
            "it becomes a highlight chip (add it to HIGHLIGHT_TONE_BY_SEVERITY) "
            "or stays in the report like `info` does."
        )

    def test_info_is_deliberately_not_a_chip(self) -> None:
        """The load-bearing half. There are at most three chips, so a neutral
        note takes one an action or a win needed — and the note is not lost,
        it is still in the report."""
        assert "info" not in HIGHLIGHT_TONE_BY_SEVERITY
        assert "info does NOT become a highlight" in HIGHLIGHT_TONE_RULE

    def test_the_rule_states_every_mapping_it_makes(self) -> None:
        for severity, tone in HIGHLIGHT_TONE_BY_SEVERITY.items():
            assert f"{severity} → {tone}" in HIGHLIGHT_TONE_RULE


# ---------------------------------------------------------------------------
# The overwrite rule
# ---------------------------------------------------------------------------


class TestTheOverwriteRule:
    """What a SECOND writer in the same day has to do, stated once (#659's
    shape) because no schema can enforce it: whether another skill's proposal
    is still live is a judgement about today's findings, which only the
    caller holds."""

    def test_the_tool_description_carries_it(self) -> None:
        from mureo.mcp.tools_mureo_context import TOOLS

        tool = next(t for t in TOOLS if t.name == "mureo_state_display_set")
        assert DISPLAY_OVERWRITE_RULE in tool.description

    def test_the_attribution_refusal_carries_it(self) -> None:
        """The refusal an unattributed write meets is the moment a caller is
        most likely to be a second writer that did not look first."""
        with pytest.raises(ValueError) as exc:
            validate_display_contract({"nav_message": "on pace"})
        assert DISPLAY_OVERWRITE_RULE in str(exc.value)

    def test_it_names_the_read_the_carry_over_and_the_limit(self) -> None:
        """Three instructions, and the third is what keeps the carry-over
        honest: only ``proposals`` travels, because only a recommendation is
        a standing commitment rather than a reading of one moment."""
        assert "mureo_state_get" in DISPLAY_OVERWRITE_RULE
        assert "proposals" in DISPLAY_OVERWRITE_RULE
        assert "NOTHING ELSE" in DISPLAY_OVERWRITE_RULE
        for section in ("nav_message", "highlights", "breakdown", "stated_values"):
            assert section in DISPLAY_OVERWRITE_RULE


async def test_the_real_dispatch_path_refuses_an_unattributed_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attribution requirement fires at the SCHEMA layer, like the bounds.

    Expressed as ``dependentRequired`` so the dispatcher refuses before the
    handler runs; the guard repeats it for callers that bypass the schema
    (an out-of-tree writer calling ``set_display`` directly).
    """
    from mureo.core.runtime_context import reset_runtime_context
    from mureo.mcp import server as server_mod

    monkeypatch.chdir(tmp_path)
    reset_runtime_context()
    try:
        with pytest.raises(ValueError) as exc:
            await server_mod.handle_call_tool(
                "mureo_state_display_set", {"nav_message": "on pace"}
            )
    finally:
        reset_runtime_context()

    message = str(exc.value)
    assert message.startswith("Invalid arguments for mureo_state_display_set: at ")
    assert "'source' is a dependency of 'nav_message'" in message
    # The handler never ran: its refusal always carries the rule text.
    assert DISPLAY_CONTRACT_RULE not in message
    assert not (tmp_path / "STATE.json").exists()
