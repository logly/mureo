"""Reports read side: duplicate-account conflicts (#533) + staleness (#535).

The write guards (#534) stop mureo from CREATING a second ``platforms`` key
for one ad account, but they repair nothing — an operator whose STATE.json is
already doubled keeps seeing a doubled client card. These tests cover the read
side, which has to handle a document that is ALREADY wrong:

  - two keys resolving to one ad account are **surfaced**, never summed
    silently and never merged or dropped;
  - the shape actually reported from the field — one key with an id, one
    UNRECOGNISED key whose ``account_id`` is ``""`` — is surfaced too, by a
    second, independent signal (the account join deliberately cannot see it:
    ``account_ids_match("", "")`` is ``False``);
  - the two findings stay **distinct**, because an operator's next move
    differs between them;
  - a key that lands in BOTH findings carries ``account_known`` saying its
    ad account IS identified (#606), so the unrecognised-key note cannot be
    worded as the opposite of the duplicate note above it;
  - a legitimate multi-platform client raises neither;
  - no ad account id crosses the wire for any of it;
  - each platform row carries its OWN freshness (``fetched_at``), with a
    stale threshold scaled to the window the figure covers, so refreshing one
    platform can never make another platform's stale numbers read as fresh.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context import platform_guards
from mureo.context.models import PlatformState, StateDocument
from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
)
from mureo.web.reports import (
    CONFLICT_DUPLICATE_ACCOUNT,
    CONFLICT_UNRECOGNIZED_KEY,
    build_report_summary,
    platform_display_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


def _use_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    ctx = default_runtime_context(workspace=workspace)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)


def _write_state(workspace: Path, doc: StateDocument) -> None:
    from mureo.context.state import write_state_file

    write_state_file(workspace / "STATE.json", doc)


def _pin_installed_platforms(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Pin which plugin platforms the environment reports as installed (#631).

    The read side resolves a bare provider name through the same enumeration
    the write guard uses, so a fixture using one is machine-dependent
    otherwise: the machine that reported #631 really has the LOGLY and
    LINE/Yahoo bridges installed. Same pin the #609 / #610 tests use.
    """
    entries = tuple(SimpleNamespace(name=name) for name in names)
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: entries)


def _ago(days: float) -> str:
    """An ISO-8601 UTC timestamp ``days`` in the past."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _conflicts(summary: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    rows = summary["platform_conflicts"]
    return [row for row in rows if row["kind"] == kind]


# ---------------------------------------------------------------------------
# #533 — two keys, one ad account
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_two_keys_for_one_account_are_surfaced_as_one_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The classic double-count: both entries name the SAME ad account under
    two keys, so the join sees it. Both rows still render (nothing is merged
    or dropped — they hold different partial figures), and the conflict names
    both keys so the frontend can refuse to sum them."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123-456", totals={"spend": 900.0, "conversions": 9}
                ),
                "plugin:mureo-logly-bridge": PlatformState(
                    account_id="act_123-456", totals={"spend": 400.0}
                ),
            },
        ),
    )

    summary = build_report_summary()
    (found,) = _conflicts(summary, CONFLICT_DUPLICATE_ACCOUNT)
    assert found["platform_keys"] == ["google_ads", "plugin:mureo-logly-bridge"]
    # Neither entry was merged away — the operator repairs, mureo reports.
    assert {p["key"] for p in summary["platforms"]} == {
        "google_ads",
        "plugin:mureo-logly-bridge",
    }


@pytest.mark.unit
def test_sibling_providers_of_one_distribution_are_not_a_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#537 — two platforms from one package are two rows, not a problem.

    Distinct keys, distinct accounts: no duplicate-account finding, and
    both keys resolve to a label so neither reads as unrecognised. This is
    the state a client running both LINE and Yahoo could not have at all
    before, because the writer refused to file either.
    """
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "plugin:mureo-lineyahoo-bridge:line_ads": PlatformState(
                    account_id="line-1", totals={"spend": 100.0}
                ),
                "plugin:mureo-lineyahoo-bridge:yahoo_ads": PlatformState(
                    account_id="yahoo-1", totals={"spend": 200.0}
                ),
            },
        ),
    )

    summary = build_report_summary()
    assert summary["platform_conflicts"] == []
    assert {p["display_name"] for p in summary["platforms"]} == {
        "Line Ads (plugin)",
        "Yahoo Ads (plugin)",
    }


@pytest.mark.unit
def test_legacy_and_per_provider_key_for_one_account_is_surfaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The migration case, reported rather than merged (#533 / #537).

    A document that gained a per-provider entry for an account it already
    held under the legacy key is a duplicate like any other: both rows
    render, the conflict names both keys, and mureo rewrites neither.
    """
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "plugin:mureo-logly-bridge": PlatformState(
                    account_id="act_9", totals={"spend": 400.0}
                ),
                "plugin:mureo-logly-bridge:logly_ads_context": PlatformState(
                    account_id="9", totals={"spend": 100.0}
                ),
            },
        ),
    )

    summary = build_report_summary()
    (found,) = _conflicts(summary, CONFLICT_DUPLICATE_ACCOUNT)
    assert found["platform_keys"] == [
        "plugin:mureo-logly-bridge",
        "plugin:mureo-logly-bridge:logly_ads_context",
    ]
    assert _conflicts(summary, CONFLICT_UNRECOGNIZED_KEY) == []
    assert len(summary["platforms"]) == 2


@pytest.mark.unit
def test_the_reported_field_shape_is_caught_by_the_unrecognised_key_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shape actually reported from the field.

    One canonical key with a real id, one key an out-of-tree writer INVENTED
    (``logly_ads``, for a bridge whose platform is ``logly_ads_context``)
    whose ``account_id`` never resolved (``""``). ``account_ids_match("", "")``
    is ``False`` BY DESIGN, so the duplicate-account join reports nothing here
    — account joining alone does NOT detect the reported bug. The second
    signal (a key no mureo surface can label) is what catches it.

    The entry-point set is pinned (#631): the bridge's real platform name is
    installed on the reporting machine and is a key mureo resolves, so an
    unpinned fixture would assert something different there than in CI.
    """
    _pin_installed_platforms(monkeypatch, "logly_ads_context")
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123-456", totals={"spend": 900.0}
                ),
                "logly_ads": PlatformState(account_id="", totals={"spend": 400.0}),
            },
        ),
    )

    summary = build_report_summary()
    assert _conflicts(summary, CONFLICT_DUPLICATE_ACCOUNT) == []
    (found,) = _conflicts(summary, CONFLICT_UNRECOGNIZED_KEY)
    assert found["platform_keys"] == ["logly_ads"]


@pytest.mark.unit
def test_a_bare_installed_platform_name_is_not_reported_as_unrecognised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#631, end to end: the same document the repair command calls Clean.

    A bare provider name an installed plugin registered is a key mureo
    ACCEPTS on write (#609). Reporting it here told the operator, about an
    entry nothing is wrong with, that mureo cannot tell which platform it
    names — while ``mureo repair platform-key --all`` reported every client
    clean. The row still renders, now with a label.
    """
    _pin_installed_platforms(monkeypatch, "logly_ads_context")
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123-456", totals={"spend": 900.0}
                ),
                "logly_ads_context": PlatformState(
                    account_id="", totals={"spend": 400.0}
                ),
            },
        ),
    )

    summary = build_report_summary()
    assert summary["platform_conflicts"] == []
    labels = {p["key"]: p["display_name"] for p in summary["platforms"]}
    assert labels["logly_ads_context"] == "Logly Ads Context (plugin)"


@pytest.mark.unit
def test_the_two_findings_stay_distinct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A document carrying BOTH problems reports both, separately.

    They are different facts with different operator next-moves — "these KPIs
    are double-counted right now" versus "this entry's identity cannot be
    established" — so they must never collapse into one warning.
    """
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(account_id="1", totals={"spend": 1.0}),
                "meta_ads": PlatformState(account_id="act_1", totals={"spend": 2.0}),
                "logly_ads": PlatformState(account_id="", totals={"spend": 3.0}),
            },
        ),
    )

    summary = build_report_summary()
    kinds = [row["kind"] for row in summary["platform_conflicts"]]
    assert kinds.count(CONFLICT_DUPLICATE_ACCOUNT) == 1
    assert kinds.count(CONFLICT_UNRECOGNIZED_KEY) == 1
    (dup,) = _conflicts(summary, CONFLICT_DUPLICATE_ACCOUNT)
    (unknown,) = _conflicts(summary, CONFLICT_UNRECOGNIZED_KEY)
    assert dup["platform_keys"] == ["google_ads", "meta_ads"]
    assert unknown["platform_keys"] == ["logly_ads"]


@pytest.mark.unit
def test_one_key_in_both_findings_says_its_account_is_known(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shape from #606: two unrecognisable keys sharing ONE account id.

    Every other fixture keeps the two findings on disjoint keys, so nothing
    pinned what the unrecognised-key row says about an entry the account
    join has ALREADY reported with certainty. Here each key appears in both
    rows, and the unrecognised-key row must not be readable as "this
    entry's ad account cannot be identified" — ``duplicate_account`` just
    identified it. ``account_known`` is the fact the renderer needs to pick
    a sentence that does not contradict the row above it.
    """
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "ads_key_a": PlatformState(account_id="555", totals={"spend": 100.0}),
                "ads_key_b": PlatformState(account_id="555", totals={"spend": 40.0}),
            },
        ),
    )

    summary = build_report_summary()
    (dup,) = _conflicts(summary, CONFLICT_DUPLICATE_ACCOUNT)
    assert dup["platform_keys"] == ["ads_key_a", "ads_key_b"]
    # A duplicate group is built BY the id, so its account is known by
    # construction. The row states it anyway, so every conflict row answers
    # the same question and no consumer has to special-case a kind.
    assert dup["account_known"] is True

    unknown = _conflicts(summary, CONFLICT_UNRECOGNIZED_KEY)
    assert [row["platform_keys"] for row in unknown] == [["ads_key_a"], ["ads_key_b"]]
    assert [row["account_known"] for row in unknown] == [True, True]


@pytest.mark.unit
def test_an_unrecognised_key_with_no_usable_account_id_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The narrower shape the wording was originally written for.

    An entry that never said which ad account it describes is invisible to
    the account join (``account_ids_match("", "")`` is ``False``), so it may
    be a duplicate mureo cannot see — and only here is that clause true.
    ``account_known`` folds the same way the join does, so whitespace and a
    bare ``act_`` prefix count as "did not say" rather than as an id.
    """
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "ads_key_a": PlatformState(account_id="", totals={"spend": 1.0}),
                "ads_key_b": PlatformState(account_id="   ", totals={"spend": 2.0}),
                "ads_key_c": PlatformState(account_id="act_", totals={"spend": 3.0}),
            },
        ),
    )

    summary = build_report_summary()
    assert _conflicts(summary, CONFLICT_DUPLICATE_ACCOUNT) == []
    unknown = _conflicts(summary, CONFLICT_UNRECOGNIZED_KEY)
    assert [row["platform_keys"] for row in unknown] == [
        ["ads_key_a"],
        ["ads_key_b"],
        ["ads_key_c"],
    ]
    assert [row["account_known"] for row in unknown] == [False, False, False]


@pytest.mark.unit
def test_more_than_two_keys_for_one_account_are_one_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """N > 2 keys for one account is ONE finding naming all N, not N-1 pairs
    — the operator has one decision to make, about one account."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(account_id="7", totals={"spend": 1.0}),
                "meta_ads": PlatformState(account_id="act_7", totals={"spend": 2.0}),
                "tiktok_ads": PlatformState(account_id=" 7 ", totals={"spend": 3.0}),
            },
        ),
    )

    (found,) = _conflicts(build_report_summary(), CONFLICT_DUPLICATE_ACCOUNT)
    assert found["platform_keys"] == ["google_ads", "meta_ads", "tiktok_ads"]


@pytest.mark.unit
def test_a_legitimate_multi_platform_client_raises_neither_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Summing across genuinely different platforms is the feature, not the
    bug. Built-in keys and canonical ``plugin:<dist>`` keys with distinct
    accounts must produce an EMPTY conflict list — a false positive here
    would blank a healthy client's KPIs."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(account_id="111", totals={"spend": 1.0}),
                "meta_ads": PlatformState(account_id="act_222", totals={"spend": 2.0}),
                "ga4": PlatformState(account_id="333"),
                "plugin:mureo-logly-bridge": PlatformState(
                    account_id="444", totals={"spend": 4.0}
                ),
                # No account id at all — unknown is not a join key, and the key
                # itself IS recognisable, so neither signal fires.
                "plugin:acme-ads": PlatformState(account_id=""),
            },
        ),
    )

    assert build_report_summary()["platform_conflicts"] == []


@pytest.mark.unit
def test_conflicts_never_carry_an_ad_account_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``_platform_row`` omits ``account_id`` on purpose; the conflict rows
    must not smuggle it back onto the wire. The frontend joins on nothing —
    the grouping is already done for it."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="123-456-7890", totals={"spend": 1.0}
                ),
                "meta_ads": PlatformState(
                    account_id="act_123-456-7890", totals={"spend": 2.0}
                ),
            },
        ),
    )

    blob = json.dumps(build_report_summary()["platform_conflicts"])
    assert "123-456-7890" in json.dumps("123-456-7890")  # sanity: the id is findable
    assert "123-456-7890" not in blob
    assert "account_id" not in blob


@pytest.mark.unit
def test_no_conflicts_for_an_empty_or_missing_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The key is always present and always a list, so the frontend never
    has to guard for its absence."""
    _use_workspace(monkeypatch, tmp_path)
    assert build_report_summary()["platform_conflicts"] == []


# ---------------------------------------------------------------------------
# #533 — drift guard on the built-in display-name allowlist
# ---------------------------------------------------------------------------
#
# ``_BUILTIN_DISPLAY_NAMES`` is a hand-maintained allowlist, and
# ``CONFLICT_UNRECOGNIZED_KEY`` now turns a gap in it into a PERMANENT banner
# on a perfectly healthy install: add a native platform key anywhere else in
# mureo without updating that dict and every card carrying it is accused of
# being an unidentifiable possible-duplicate. That consequence is created by
# this feature, so the guard belongs with it.
#
# ANCHOR: the ``platform`` description on the ``mureo_state_platform_metrics_set``
# MCP tool. Reasoning, since there is no machine-readable source of truth for
# "the built-in STATE.json platform keys" to derive from:
#
#   - it is the WRITE-side counterpart of the read-side map — the surface that
#     tells an agent which built-in keys exist and may be written, so a new
#     native platform must be added there to be usable at all;
#   - it is the only place in the tree that enumerates exactly this vocabulary
#     and enumerates it COMPLETELY (google_ads / meta_ads / tiktok_ads /
#     search_console / ga4);
#   - the obvious code-level alternative, the provider registry, is a
#     DIFFERENT vocabulary and would produce false drift in both directions:
#     Amazon Ads is a provider but its STATE.json key is
#     ``plugin:mureo-amazon-ads-bridge``, and ``tiktok_ads`` is a hosted
#     connector with no provider at all;
#   - restating the five strings in a test file was rejected outright — that
#     moves the drift one file over instead of catching it.
#
# It is prose, so the extraction is a regex; both halves of it assert they
# matched something, or a reworded description would silently disable this
# guard rather than failing it.

_BUILTIN_ENUMERATION = re.compile(r"a built-in \(([^)]*)\)")
_KEY_TOKEN = re.compile(r"``([a-z0-9_]+)``")


def _write_path_builtin_keys() -> set[str]:
    """The built-in platform keys the write path advertises to agents."""
    from mureo.mcp.tools_mureo_context import TOOLS

    tool = next(t for t in TOOLS if t.name == "mureo_state_platform_metrics_set")
    description = tool.inputSchema["properties"]["platform"]["description"]
    enumeration = _BUILTIN_ENUMERATION.search(description)
    assert enumeration is not None, (
        "mureo_state_platform_metrics_set no longer describes its built-in "
        "platform keys as 'a built-in (...)'. This test anchors "
        "mureo.web.report_labels._BUILTIN_DISPLAY_NAMES to that enumeration; "
        "re-point it at the new wording rather than deleting it, or an "
        "unlisted native key silently earns a permanent 'unrecognized_key' "
        f"banner. Description was: {description!r}"
    )
    keys = set(_KEY_TOKEN.findall(enumeration.group(1)))
    assert keys, f"no platform keys parsed out of {enumeration.group(1)!r}"
    return keys


@pytest.mark.unit
def test_builtin_display_names_matches_the_write_paths_advertised_keys() -> None:
    """Read side and write side must name the same built-in platforms.

    A key the write path tells agents to use, but the display map has never
    heard of, resolves to itself — which is precisely the
    ``unrecognized_key`` signal — so drift here manufactures a false
    duplicate-suspicion on healthy state.
    """
    from mureo.web.reports import _BUILTIN_DISPLAY_NAMES

    assert set(_BUILTIN_DISPLAY_NAMES) == _write_path_builtin_keys()


@pytest.mark.unit
def test_no_advertised_builtin_key_is_ever_reported_as_unrecognised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The consequence, asserted end-to-end rather than by proxy.

    Every built-in key the write path advertises, all in one healthy document
    with distinct accounts, must produce an EMPTY conflict list.
    """
    keys = sorted(_write_path_builtin_keys())
    for key in keys:
        assert platform_display_name(key) != key, f"{key} resolves to no label"

    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                key: PlatformState(account_id=f"acct-{i}", totals={"spend": 1.0})
                for i, key in enumerate(keys)
            },
        ),
    )

    assert build_report_summary()["platform_conflicts"] == []


# ---------------------------------------------------------------------------
# #535 — per-platform freshness
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_each_row_carries_its_own_fetched_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_workspace(monkeypatch, tmp_path)
    fetched = _ago(0.1)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="1",
                    totals={"spend": 1.0, "fetched_at": fetched},
                    metrics_period="YESTERDAY",
                )
            },
        ),
    )

    (row,) = build_report_summary()["platforms"]
    assert row["freshness"]["fetched_at"] == fetched
    assert row["freshness"]["stale"] is False


@pytest.mark.unit
def test_missing_fetched_at_is_unknown_not_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``fetched_at`` is optional and writer-dependent. "We do not know how
    old this is" is a real state and must not be reported as either fresh or
    stale — both would be a claim mureo cannot back."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="1", totals={"spend": 1.0}, metrics_period="YESTERDAY"
                ),
                # No totals at all (advisory bridge) — also unknown.
                "plugin:acme-ads": PlatformState(account_id="2"),
            },
        ),
    )

    by_key = {p["key"]: p for p in build_report_summary()["platforms"]}
    for key in ("google_ads", "plugin:acme-ads"):
        assert by_key[key]["freshness"]["fetched_at"] is None
        assert by_key[key]["freshness"]["stale"] is None


@pytest.mark.unit
def test_an_unparseable_fetched_at_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A writer that stamped something that is not a timestamp gets "unknown",
    never a guess — and never an exception out of a read-only view.

    ``fetched_at`` is echoed back **verbatim** even then. It is the raw
    stored value, not a parsed one: ``stale is None`` is the authoritative
    "this could not be interpreted, do not compute with it" signal, and
    blanking the string would throw away the only clue an operator has for
    finding the writer that produced it. Reporting what the document
    actually says, rather than silently normalising it, is the same stance
    the write guards take when they refuse a bad key instead of rewriting
    it. Deliberate — hence pinned here.
    """
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="1",
                    totals={"spend": 1.0, "fetched_at": "last tuesday"},
                    metrics_period="YESTERDAY",
                )
            },
        ),
    )

    (row,) = build_report_summary()["platforms"]
    assert row["freshness"]["stale"] is None
    assert row["freshness"]["fetched_at"] == "last tuesday"


@pytest.mark.unit
def test_stale_threshold_scales_with_the_window_the_figure_covers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A YESTERDAY figure and a LAST_30_DAYS figure do not go stale at the
    same rate: the threshold is the window's own length plus one daily-sync
    grace day, i.e. the point at which the stored figure no longer overlaps
    the window it claims to describe. Ten days old is dead for YESTERDAY and
    perfectly current for LAST_30_DAYS."""
    _use_workspace(monkeypatch, tmp_path)
    ten_days = _ago(10)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="1",
                    periods={
                        "YESTERDAY": {"spend": 1.0, "fetched_at": ten_days},
                        "LAST_30_DAYS": {"spend": 30.0, "fetched_at": ten_days},
                    },
                )
            },
        ),
    )

    (yesterday,) = build_report_summary(period="YESTERDAY")["platforms"]
    assert yesterday["freshness"]["stale"] is True
    assert yesterday["freshness"]["stale_after_days"] == 2

    (last30,) = build_report_summary(period="LAST_30_DAYS")["platforms"]
    assert last30["freshness"]["stale"] is False
    assert last30["freshness"]["stale_after_days"] == 31


@pytest.mark.unit
def test_an_unknown_window_gets_the_most_forgiving_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A window mureo has no length for cannot be reasoned about, so it gets
    the longest known threshold rather than a guess — crying wolf on a figure
    we cannot judge would teach operators to ignore the marker."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="1",
                    totals={"spend": 1.0, "fetched_at": _ago(10)},
                    metrics_period="THIS_QUARTER",
                )
            },
        ),
    )

    (row,) = build_report_summary()["platforms"]
    assert row["freshness"]["stale_after_days"] == 31
    assert row["freshness"]["stale"] is False


@pytest.mark.unit
def test_refreshing_one_platform_does_not_make_another_read_fresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reported #535 failure. ``last_synced_at`` is re-stamped on ANY
    platform write, so the document-level timestamp says "just now" while
    meta_ads' numbers are a month old. Per-platform freshness must tell them
    apart."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            last_synced_at=_ago(0),
            platforms={
                "google_ads": PlatformState(
                    account_id="1",
                    totals={"spend": 1.0, "fetched_at": _ago(0.05)},
                    metrics_period="YESTERDAY",
                ),
                "meta_ads": PlatformState(
                    account_id="2",
                    totals={"spend": 2.0, "fetched_at": _ago(40)},
                    metrics_period="YESTERDAY",
                ),
            },
        ),
    )

    summary = build_report_summary()
    by_key = {p["key"]: p for p in summary["platforms"]}
    assert by_key["google_ads"]["freshness"]["stale"] is False
    assert by_key["meta_ads"]["freshness"]["stale"] is True
    # The document-level fact is untouched — it just no longer stands in for
    # per-platform freshness.
    assert summary["last_synced_at"] is not None


@pytest.mark.unit
def test_platform_row_keeps_its_five_fields_and_omits_account_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Freshness rides ALONGSIDE the existing row shape — nothing renamed,
    nothing dropped, and still no ad account id."""
    _use_workspace(monkeypatch, tmp_path)
    _write_state(
        tmp_path,
        StateDocument(
            version="2",
            platforms={
                "google_ads": PlatformState(
                    account_id="1", totals={"spend": 1.0}, metrics_period="YESTERDAY"
                )
            },
        ),
    )

    (row,) = build_report_summary()["platforms"]
    assert {
        "key",
        "display_name",
        "totals",
        "metrics_period",
        "campaign_count",
    } <= set(row)
    assert "account_id" not in row
