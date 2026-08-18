"""Why a platform's figures did not move (#638).

STATE.json could say "these are the numbers" and "here is how old they are",
but never "this platform was not collected, and here is why". So "not
collected" and "collected, and the answer was zero" were the same document,
and an operator looking at a card whose figures had not moved for eleven days
had nowhere to find out whether the account had stopped delivering or the
collector had stopped running. That card sat untouched for eleven days.

``PlatformState.not_collected`` is that missing fact. What these tests pin:

- it is **optional and additive** — a document written before it existed
  parses unchanged and gains no key on the next write;
- it can be **set and explicitly cleared**, and clearing is distinguishable
  from omitting it (omission preserves, everywhere in this file's merge
  semantics — which is exactly why a clear has to be sayable);
- recording a failed collection is **not a sync**, so it does not re-stamp
  ``last_synced_at``;
- it reaches the dashboard's wire payload, whitelisted, beside the freshness
  it explains.

It is a note about the COLLECTION, never a verdict on the figures: the
numbers stored are still the last ones that were truly collected. Nothing
here may be read as "these figures are wrong".
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
    write_state_file,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_PLATFORM = "google_ads"
_ACCOUNT = "123-456-7890"
_REASON = "Meta returned OAuthException 190: the access token expired"


def _entry(path: Path) -> PlatformState:
    doc = read_state_file(path)
    assert doc.platforms is not None
    return doc.platforms[_PLATFORM]


def _seeded(tmp_path: Path) -> Path:
    """A document with a rollup already in it, as a real workspace has."""
    path = tmp_path / "STATE.json"
    set_platform_metrics(
        path,
        _PLATFORM,
        _ACCOUNT,
        totals={"spend": 25862.0, "conversions": 2},
        metrics_period="LAST_30_DAYS",
    )
    return path


# ---------------------------------------------------------------------------
# The field itself
# ---------------------------------------------------------------------------


class TestTheFieldIsOptionalAndAdditive:
    def test_a_document_written_before_the_field_parses_unchanged(self) -> None:
        text = json.dumps(
            {
                "version": "2",
                "platforms": {
                    _PLATFORM: {
                        "account_id": _ACCOUNT,
                        "campaigns": [],
                        "totals": {"spend": 1.0},
                    }
                },
            }
        )
        doc = parse_state(text)
        assert doc.platforms is not None
        assert doc.platforms[_PLATFORM].not_collected is None

    def test_an_entry_without_it_emits_no_new_key(self) -> None:
        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {_PLATFORM: {"account_id": _ACCOUNT}},
                }
            )
        )
        rendered = json.loads(render_state(doc))
        assert "not_collected" not in rendered["platforms"][_PLATFORM]

    def test_it_round_trips_when_set(self) -> None:
        note = {"attempted_at": "2026-08-18T09:00:00+00:00", "reason": _REASON}
        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        _PLATFORM: {"account_id": _ACCOUNT, "not_collected": note}
                    },
                }
            )
        )
        assert doc.platforms is not None
        assert doc.platforms[_PLATFORM].not_collected == note
        rendered = json.loads(render_state(doc))
        assert rendered["platforms"][_PLATFORM]["not_collected"] == note

    def test_a_note_with_no_reason_is_no_note(self) -> None:
        """The reason IS the field's payload. A note that carries only a
        timestamp tells the operator that something happened and refuses to
        say what, which is the state this field exists to end."""
        for raw in ({}, {"attempted_at": "2026-08-18T09:00:00+00:00"}, {"reason": " "}):
            doc = parse_state(
                json.dumps(
                    {
                        "version": "2",
                        "platforms": {
                            _PLATFORM: {"account_id": _ACCOUNT, "not_collected": raw}
                        },
                    }
                )
            )
            assert doc.platforms is not None
            assert doc.platforms[_PLATFORM].not_collected is None

    def test_a_malformed_note_degrades_rather_than_raising(self) -> None:
        """Tolerant like every other optional platform field: a hand-edited
        value costs the note, never the document."""
        for raw in ("nonsense", 42, [], None):
            doc = parse_state(
                json.dumps(
                    {
                        "version": "2",
                        "platforms": {
                            _PLATFORM: {"account_id": _ACCOUNT, "not_collected": raw}
                        },
                    }
                )
            )
            assert doc.platforms is not None
            assert doc.platforms[_PLATFORM].not_collected is None

    def test_an_over_long_reason_is_truncated_on_read(self) -> None:
        """Capped at every boundary the field crosses, so a hand-edited or
        externally-written page of API JSON is not re-serialised in full on
        every subsequent write."""
        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {
                        _PLATFORM: {
                            "account_id": _ACCOUNT,
                            "not_collected": {"reason": "z" * 5000},
                        }
                    },
                }
            )
        )
        assert doc.platforms is not None
        note = doc.platforms[_PLATFORM].not_collected
        assert note is not None
        assert len(note["reason"]) == NOT_COLLECTED_REASON_MAX_CHARS

    def test_the_stored_note_is_a_defensive_copy(self) -> None:
        note: dict[str, Any] = {"attempted_at": "t", "reason": _REASON}
        state = PlatformState(account_id=_ACCOUNT, not_collected=note)
        note["reason"] = "mutated after the fact"
        assert state.not_collected is not None
        assert state.not_collected["reason"] == _REASON


# ---------------------------------------------------------------------------
# Setting and clearing
# ---------------------------------------------------------------------------


class TestSetAndClear:
    def test_a_reason_is_recorded_with_a_server_stamped_time(
        self, tmp_path: Path
    ) -> None:
        path = _seeded(tmp_path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=_REASON)
        note = _entry(path).not_collected
        assert note is not None
        assert note["reason"] == _REASON
        # Server-stamped (#460): the caller never supplies this, so a drifted
        # client clock cannot date the failure.
        assert isinstance(note["attempted_at"], str) and note["attempted_at"]

    def test_the_figures_are_left_exactly_as_they_were(self, tmp_path: Path) -> None:
        """The note says the numbers were not REFRESHED. It never touches
        them, and must never be read as "these figures are wrong"."""
        path = _seeded(tmp_path)
        before = _entry(path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=_REASON)
        after = _entry(path)
        assert after.totals == before.totals
        assert after.metrics_period == before.metrics_period
        assert after.campaigns == before.campaigns

    def test_a_none_reason_clears_the_note(self, tmp_path: Path) -> None:
        path = _seeded(tmp_path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=_REASON)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=None)
        assert _entry(path).not_collected is None

    def test_a_blank_reason_clears_it_too(self, tmp_path: Path) -> None:
        """A note with a blank reason would say "something is wrong" and
        refuse to say what — the same non-answer as no note, but permanent."""
        path = _seeded(tmp_path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=_REASON)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason="   ")
        assert _entry(path).not_collected is None

    def test_a_cleared_note_leaves_no_key_behind(self, tmp_path: Path) -> None:
        path = _seeded(tmp_path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=_REASON)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=None)
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert "not_collected" not in stored["platforms"][_PLATFORM]

    def test_clearing_is_distinguishable_from_omitting(self, tmp_path: Path) -> None:
        """The distinction this whole write path exists for. Every other
        mutator treats an omitted field as "leave it alone", so a successful
        collection that merely writes totals CANNOT clear the note — it has
        to say so. If omission cleared it, no writer could keep a note across
        an unrelated write; if a clear were unsayable, the note would outlive
        the failure and become the stale-forever field this issue is about."""
        path = _seeded(tmp_path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=_REASON)

        # A metrics write says nothing about the note → it survives.
        set_platform_metrics(
            path, _PLATFORM, _ACCOUNT, periods={"YESTERDAY": {"spend": 3.0}}
        )
        surviving = _entry(path).not_collected
        assert surviving is not None and surviving["reason"] == _REASON

        # Saying so → it goes.
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=None)
        assert _entry(path).not_collected is None

    def test_a_second_failure_replaces_the_first(self, tmp_path: Path) -> None:
        path = _seeded(tmp_path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason="first")
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason="second")
        note = _entry(path).not_collected
        assert note is not None
        assert note["reason"] == "second"

    def test_recording_a_failure_is_not_a_sync(self, tmp_path: Path) -> None:
        """``last_synced_at`` drives the card's "Synced N ago". Re-stamping it
        because a collection FAILED would report the document as just-synced
        on the strength of nothing having been collected — the same false
        statement, moved one field over."""
        path = _seeded(tmp_path)
        before = read_state_file(path).last_synced_at
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason=_REASON)
        assert read_state_file(path).last_synced_at == before

    def test_an_over_long_reason_is_truncated(self, tmp_path: Path) -> None:
        """A collector's raw error can be a page of API JSON. The card has one
        line for it, and STATE.json is read whole on every write."""
        path = _seeded(tmp_path)
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason="x" * 5000)
        note = _entry(path).not_collected
        assert note is not None
        assert len(note["reason"]) == NOT_COLLECTED_REASON_MAX_CHARS

    def test_it_creates_the_platform_entry_when_absent(self, tmp_path: Path) -> None:
        """A platform that failed on its very first collection has no entry
        yet — and that is precisely the case an operator cannot diagnose from
        an empty dashboard."""
        path = tmp_path / "STATE.json"
        set_platform_not_collected(path, "meta_ads", "act_1", reason=_REASON)
        doc = read_state_file(path)
        assert doc.platforms is not None
        created = doc.platforms["meta_ads"]
        assert created.account_id == "act_1"
        assert created.not_collected is not None

    def test_repointing_a_key_at_another_account_drops_the_note(
        self, tmp_path: Path
    ) -> None:
        """The note is about the account that failed. Re-pointing a key at a
        different ad account (allowed when nobody else holds it) carries the
        entry over — and a failure reported for the previous account would
        then be rendered as a fact about this one."""
        path = tmp_path / "STATE.json"
        set_platform_not_collected(path, _PLATFORM, "111", reason=_REASON)
        set_platform_metrics(path, _PLATFORM, "222", totals={"spend": 1.0})
        entry = _entry(path)
        assert entry.account_id == "222"
        assert entry.not_collected is None

    def test_stamping_an_id_onto_an_idless_entry_keeps_the_note(
        self, tmp_path: Path
    ) -> None:
        """An entry with no ``account_id`` claims no account, so learning one
        identifies the entry rather than replacing it — the same reading the
        duplicate guard takes of ``""``."""
        path = tmp_path / "STATE.json"
        write_state_file(
            path,
            StateDocument(
                version="2",
                platforms={
                    _PLATFORM: PlatformState(
                        account_id="",
                        not_collected={"attempted_at": "t", "reason": _REASON},
                    )
                },
            ),
        )
        set_platform_metrics(path, _PLATFORM, _ACCOUNT, totals={"spend": 1.0})
        note = _entry(path).not_collected
        assert note is not None and note["reason"] == _REASON

    def test_the_same_account_written_act_prefixed_keeps_the_note(
        self, tmp_path: Path
    ) -> None:
        """``act_`` tolerance, as everywhere else: one account written two
        ways is one account, not a re-point."""
        path = tmp_path / "STATE.json"
        set_platform_not_collected(path, "meta_ads", "123456", reason=_REASON)
        set_platform_metrics(path, "meta_ads", "act_123456", totals={"spend": 1.0})
        doc = read_state_file(path)
        assert doc.platforms is not None
        note = doc.platforms["meta_ads"].not_collected
        assert note is not None and note["reason"] == _REASON

    def test_it_shares_the_platform_key_guard(self, tmp_path: Path) -> None:
        """One ad account, one platform key — the same refusal every other
        targeted writer makes, so this one cannot be the way in."""
        path = tmp_path / "STATE.json"
        set_platform_metrics(path, "google_ads", "111", totals={"spend": 1.0})
        with pytest.raises(ValueError, match="google_ads"):
            set_platform_not_collected(path, "tiktok_ads", "111", reason=_REASON)


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


def _write(workspace: Path, **platform_kwargs: Any) -> None:
    write_state_file(
        workspace / "STATE.json",
        StateDocument(
            version="2",
            platforms={_PLATFORM: PlatformState(account_id="1", **platform_kwargs)},
        ),
    )


@pytest.mark.usefixtures("_reset_ctx")
class TestTheWire:
    def test_the_row_carries_the_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            totals={"spend": 1.0},
            not_collected={
                "attempted_at": "2026-08-18T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"] == {
            "attempted_at": "2026-08-18T09:00:00+00:00",
            "reason": _REASON,
        }

    def test_a_row_without_one_says_so_explicitly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``None``, not an absent key: the frontend reads one shape for
        every row and never has to guess whether a missing key means "no
        note" or "an older daemon"."""
        _write(tmp_path, totals={"spend": 1.0})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"] is None

    def test_only_the_two_known_keys_reach_the_browser(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Same whitelist discipline as ``totals``: a key a buggy or hostile
        writer slipped in never reaches the page."""
        _write(
            tmp_path,
            not_collected={
                "attempted_at": "2026-08-18T09:00:00+00:00",
                "reason": _REASON,
                "access_token": "EAAG-secret",
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert set(row["not_collected"]) == {"attempted_at", "reason"}
        assert "EAAG-secret" not in json.dumps(_summary(monkeypatch, tmp_path))

    def test_an_over_long_reason_is_truncated_on_the_way_out_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The write helper caps what it stores, but a digest can write the
        whole document without going near it — so the surface that renders
        caps as well."""
        _write(tmp_path, not_collected={"reason": "y" * 5000})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert len(row["not_collected"]["reason"]) == NOT_COLLECTED_REASON_MAX_CHARS

    def test_a_note_with_no_usable_reason_is_not_put_on_the_wire(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(tmp_path, not_collected={"attempted_at": "2026-08-18T09:00:00+00:00"})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"] is None

    def test_the_note_rides_alongside_freshness_rather_than_replacing_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Two different facts: how old the figures are, and why they are not
        newer. The card shows both, so neither may consume the other. Here
        they AGREE — the figures are older than the failure — which is the
        arrangement the note is true of."""
        _write(
            tmp_path,
            totals={"spend": 1.0, "fetched_at": "2020-01-01T00:00:00+00:00"},
            metrics_period="YESTERDAY",
            not_collected={
                "attempted_at": "2020-06-01T00:00:00+00:00",
                "reason": _REASON,
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["freshness"]["stale"] is True
        assert row["not_collected"]["reason"] == _REASON


# ---------------------------------------------------------------------------
# A note a later collection has already retired
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_reset_ctx")
class TestARetiredNoteIsNotShown:
    """The document must never state two contradictory answers to one
    question, and no writer's discipline may be what prevents it.

    The failing path this closes: the digest records "the Meta token
    expired", the operator fixes the token, and the next sync writes fresh
    figures through ``mureo_state_platform_metrics_set`` — a call whose
    schema says nothing about the note, so an agent driving only that tool
    has no clue a second call is needed. The document then carries a fresh
    ``fetched_at`` AND a days-old collection failure, permanently, and the
    card renders both. That is the shape of defect #638 is about (a false
    statement on a dashboard, unnoticed for eleven days) reintroduced by its
    own fix.

    So the read side decides it, ONCE, in the same place and the same way it
    already decides staleness: a note is retired by any collection that
    succeeded after it. The agency-side clearing contract stands — but the
    correctness of what an operator sees no longer depends on it.
    """

    def test_a_collection_that_succeeded_since_retires_the_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            totals={"spend": 1.0, "fetched_at": "2026-08-18T09:00:00+00:00"},
            not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"] is None

    def test_a_success_in_ANY_window_retires_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The note is platform-level, so any rollup proves the platform was
        reached — the daily-check writing YESTERDAY says as much about the
        token as a sync writing LAST_30_DAYS does. The newest ``fetched_at``
        anywhere is what it is compared against; the row's own window may be
        an old one the toggle happens to be showing."""
        _write(
            tmp_path,
            totals={"spend": 1.0, "fetched_at": "2026-08-01T09:00:00+00:00"},
            metrics_period="LAST_30_DAYS",
            periods={"YESTERDAY": {"spend": 2.0, "fetched_at": "2026-08-18T09:00:00Z"}},
            not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"] is None

    def test_an_older_collection_does_not_retire_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The figures predate the failure, which is exactly when the note is
        true and most needed. Only a LATER success retires it."""
        _write(
            tmp_path,
            totals={"spend": 1.0, "fetched_at": "2026-08-10T09:00:00+00:00"},
            not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"]["reason"] == _REASON

    def test_a_platform_never_collected_at_all_keeps_its_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The single most important case: no figures, no ``fetched_at``
        anywhere, and the only thing the dashboard can say is why. Retiring
        the note on the ABSENCE of a collection time would silence exactly
        the card that has nothing else on it."""
        _write(
            tmp_path,
            totals={"spend": 1.0},
            periods={"YESTERDAY": {"spend": 2.0}},
            not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"]["reason"] == _REASON

    def test_an_advisory_platform_with_no_rollups_keeps_its_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["not_collected"]["reason"] == _REASON

    def test_an_undatable_pair_keeps_the_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Retirement is a PROOF that a collection succeeded after the
        failure, and neither of these can supply one: a note with no
        ``attempted_at`` (mureo's own writer always stamps it, so this came
        from a hand edit or an outside writer) and a ``fetched_at`` that is
        not a timestamp. Unknown is not the same as retired — the same
        position the staleness verdict takes on an unparseable value."""
        for totals, note in (
            (
                {"spend": 1.0, "fetched_at": "2026-08-18T09:00:00+00:00"},
                {"reason": _REASON},
            ),
            (
                {"spend": 1.0, "fetched_at": "last tuesday"},
                {"attempted_at": "2026-08-15T09:00:00+00:00", "reason": _REASON},
            ),
        ):
            _write(tmp_path, totals=totals, not_collected=note)
            (row,) = _summary(monkeypatch, tmp_path)["platforms"]
            assert row["not_collected"]["reason"] == _REASON

    def test_the_period_toggle_cannot_resurrect_a_retired_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Switching window changes which figures are on screen, never
        whether the platform was reached. A note the newest collection
        retired stays retired in every window."""
        from mureo.core.runtime_context import default_runtime_context
        from mureo.web.reports import build_report_summary

        _write(
            tmp_path,
            periods={
                "YESTERDAY": {"spend": 2.0, "fetched_at": "2026-08-18T09:00:00+00:00"},
                "LAST_30_DAYS": {"spend": 9.0},
            },
            not_collected={
                "attempted_at": "2026-08-15T09:00:00+00:00",
                "reason": _REASON,
            },
        )
        ctx = default_runtime_context(workspace=tmp_path)
        monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
        for window in ("YESTERDAY", "LAST_30_DAYS"):
            (row,) = build_report_summary(period=window)["platforms"]
            assert row["not_collected"] is None, window


# ---------------------------------------------------------------------------
# The MCP path
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

        result = await handle_tool("mureo_state_platform_not_collected_set", arguments)
        return json.loads(result[0].text)

    async def test_it_records_a_reason(self, tmp_path: Path) -> None:
        payload = await self._call(
            {"platform": _PLATFORM, "account_id": _ACCOUNT, "reason": _REASON}
        )
        note = payload["platforms"][_PLATFORM]["not_collected"]
        assert note["reason"] == _REASON
        assert note["attempted_at"]

    async def test_omitting_the_reason_clears_the_note(self, tmp_path: Path) -> None:
        await self._call(
            {"platform": _PLATFORM, "account_id": _ACCOUNT, "reason": _REASON}
        )
        payload = await self._call({"platform": _PLATFORM, "account_id": _ACCOUNT})
        assert "not_collected" not in payload["platforms"][_PLATFORM]

    async def test_a_non_string_reason_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="reason"):
            await self._call(
                {"platform": _PLATFORM, "account_id": _ACCOUNT, "reason": {"a": 1}}
            )

    async def test_the_tool_is_registered_with_a_schema(self) -> None:
        from mureo.mcp.tools_mureo_context import TOOLS

        (tool,) = [
            t for t in TOOLS if t.name == "mureo_state_platform_not_collected_set"
        ]
        assert tool.inputSchema["required"] == ["platform", "account_id"]
        assert "reason" in tool.inputSchema["properties"]
        # The clearing contract is stated where the caller reads it — an
        # agent that cannot see how to remove the note leaves it forever.
        assert "clear" in tool.description.lower()

    async def test_the_metrics_tool_names_the_clearing_call(self) -> None:
        """The tool an agent reaches on SUCCESS is where the contract has to
        be readable. Saying it only on the failure tool tells the one caller
        who no longer needs to know: an agent driving
        mureo_state_platform_metrics_set alone had no clue a second call
        existed, so the note would be left behind forever."""
        from mureo.mcp.tools_mureo_context import TOOLS

        (metrics,) = [t for t in TOOLS if t.name == "mureo_state_platform_metrics_set"]
        assert "mureo_state_platform_not_collected_set" in metrics.description
        assert "clear" in metrics.description.lower()


def test_an_entry_under_an_unresolvable_key_can_still_record_why(
    tmp_path: Path,
) -> None:
    """An entry that already exists keeps taking writes under its own key —
    the create-only shape of every guard here. An operator holding a bad key
    is exactly the operator staring at figures that stopped moving, so this
    writer must not be the one that refuses them."""
    path = tmp_path / "STATE.json"
    write_state_file(
        path,
        StateDocument(
            version="2", platforms={"legacy_key": PlatformState(account_id="1")}
        ),
    )
    set_platform_not_collected(path, "legacy_key", "1", reason=_REASON)
    doc = read_state_file(path)
    assert doc.platforms is not None
    assert doc.platforms["legacy_key"].not_collected is not None
