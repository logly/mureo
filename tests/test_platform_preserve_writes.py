"""Writers, repair and refusals around hand-written platform entries (#881).

The companion of ``tests/test_platform_preserve.py``, which pins the codec's
round trip. Here every case goes through a public path a real workspace
takes — the targeted writers, ``mureo repair``'s plan and apply, and
``parse_state`` on a shape it refuses — on the two shapes observed in real
workspaces and on the ones review found:

- a ``campaigns`` list mixing objects and other values keeps the others when
  a writer replaces the object entries (same for a campaign's ``ads``);
- ``mureo repair`` never offers an entry carrying hand-written content as an
  empty stub;
- a ``platforms`` value or a platform value that is not an object is kept
  verbatim on the document in both modes (#882); only a top-level value
  that is not an object is still refused with a ``ValueError``;
- the one stated loss: an upsert matching a campaign in the legacy v1 flat
  list replaces it whole, unknown keys included.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context import platform_guards
from mureo.context.models import AdState, CampaignSnapshot
from mureo.context.platform_repair import (
    DROP_EMPTY_STUB,
    KEEP_CARRIES_FIGURES,
    apply_state_file_repairs,
    plan_platform_keys,
)
from mureo.context.state import (
    read_state_file,
    set_conversion_action_types,
    set_platform_metrics,
    set_platform_not_collected,
    upsert_campaign,
)
from mureo.context.state_codec import parse_state, render_state
from mureo.core.runtime_context import reset_runtime_context
from tests.test_platform_preserve import (
    _HAND_CAMPAIGN,
    _NO_ACCOUNT_ID,
    _STRING_CAMPAIGNS,
    _campaign,
    _document,
    _on_disk,
    _text,
    _with_platforms,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(_text(_document()), encoding="utf-8")
    return path


def _write_platforms(tmp_path: Path, platforms: dict[str, Any]) -> Path:
    path = tmp_path / "STATE.json"
    path.write_text(_with_platforms(platforms), encoding="utf-8")
    return path


def _no_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """No plugin platform installed: only the built-ins resolve."""
    entries: tuple[SimpleNamespace, ...] = ()
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: entries)


# ---------------------------------------------------------------------------
# Targeted writers on the two observed shapes
# ---------------------------------------------------------------------------

#: ``(platform key, the on-disk entry, the account id the writer passes)``.
_OBSERVED = [
    pytest.param("google_ads", _STRING_CAMPAIGNS, "111-222-3333", id="string"),
    pytest.param("logly_ads", _NO_ACCOUNT_ID, "555", id="no-account_id"),
]


def _metrics(path: Path, platform: str, account_id: str) -> None:
    set_platform_metrics(
        path, platform, account_id, totals={"spend": 9.0}, metrics_period="YESTERDAY"
    )


def _not_collected(path: Path, platform: str, account_id: str) -> None:
    set_platform_not_collected(path, platform, account_id, reason="token expired")


def _conversions(path: Path, platform: str, account_id: str) -> None:
    set_conversion_action_types(path, platform, account_id, ["purchase"])


#: ``(writer, the keys it owns, what it must have written)``.
_WRITERS: list[Any] = [
    pytest.param(
        _metrics,
        {"totals", "metrics_period", "periods"},
        lambda p: p["metrics_period"] == "YESTERDAY",
        id="set_platform_metrics",
    ),
    pytest.param(
        _not_collected,
        {"not_collected"},
        lambda p: p["not_collected"]["reason"] == "token expired",
        id="set_platform_not_collected",
    ),
    pytest.param(
        _conversions,
        {"conversion_action_types"},
        lambda p: p["conversion_action_types"] == ["purchase"],
        id="set_conversion_action_types",
    ),
]


class TestTargetedWritersKeepTheRest:
    @pytest.mark.parametrize(("writer", "owned", "landed"), _WRITERS)
    @pytest.mark.parametrize(("platform", "entry", "account_id"), _OBSERVED)
    def test_the_write_lands_and_the_hand_written_rest_is_kept(
        self,
        state_file: Path,
        writer: Callable[[Path, str, str], None],
        owned: set[str],
        landed: Callable[[dict[str, Any]], bool],
        platform: str,
        entry: dict[str, Any],
        account_id: str,
    ) -> None:
        before = _on_disk(state_file)["platforms"]

        writer(state_file, platform, account_id)

        after = _on_disk(state_file)["platforms"]
        stored = after[platform]
        assert landed(stored)
        assert stored["account_id"] == account_id
        untouched = {k: v for k, v in entry.items() if k not in owned}
        assert {k: stored[k] for k in untouched} == untouched
        assert [k for k in stored if k in untouched] == list(untouched), "order"
        others = {k: v for k, v in before.items() if k != platform}
        assert {k: after[k] for k in others} == others


# ---------------------------------------------------------------------------
# Mixed lists: a writer never drops what the model could not hold
# ---------------------------------------------------------------------------


def _mixed(*campaigns: Any) -> dict[str, Any]:
    return {"logly_ads": {"account_id": "1", "campaigns": list(campaigns)}}


class TestMixedListsKeepTheirNonObjects:
    def test_a_new_campaign_is_added_and_the_note_kept(self, tmp_path: Path) -> None:
        path = _write_platforms(
            tmp_path,
            _mixed(
                _campaign(campaign_id="c1"),
                "paused the rest",
                _campaign(campaign_id="c2"),
            ),
        )

        upsert_campaign(
            path,
            CampaignSnapshot(campaign_id="c3", campaign_name="C", status="ENABLED"),
            platform="logly_ads",
            account_id="1",
        )

        stored = _on_disk(path)["platforms"]["logly_ads"]["campaigns"]
        assert [c if isinstance(c, str) else c["campaign_id"] for c in stored] == [
            "c1",
            "paused the rest",
            "c2",
            "c3",
        ]

    def test_an_updated_campaign_keeps_the_note_in_place(self, tmp_path: Path) -> None:
        path = _write_platforms(
            tmp_path, _mixed("see sheet", _campaign(campaign_id="c1"), 7)
        )

        upsert_campaign(
            path,
            CampaignSnapshot(campaign_id="c1", campaign_name="A", status="PAUSED"),
            platform="logly_ads",
            account_id="1",
        )

        stored = _on_disk(path)["platforms"]["logly_ads"]["campaigns"]
        assert stored[0] == "see sheet"
        assert stored[1]["status"] == "PAUSED"
        assert stored[2] == 7

    def test_non_objects_past_the_end_are_appended_in_order(self) -> None:
        text = _with_platforms(
            _mixed("a", _campaign(campaign_id="c1"), "b", _campaign(), "c")
        )
        doc = parse_state(text)
        assert doc.platforms is not None
        emptied = dataclasses.replace(doc.platforms["logly_ads"], campaigns=())
        changed = dataclasses.replace(doc, platforms={"logly_ads": emptied})

        stored = json.loads(render_state(changed))
        assert stored["platforms"]["logly_ads"]["campaigns"] == ["a", "b", "c"]

    def test_replaced_ads_keep_the_non_objects(self, tmp_path: Path) -> None:
        path = _write_platforms(
            tmp_path,
            _mixed(_campaign(campaign_id="c1", ads=[{"ad_id": "a1"}, 42])),
        )

        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="c1",
                campaign_name="A",
                status="ENABLED",
                ads=(AdState(ad_id="a1", status="PAUSED"), AdState(ad_id="a2")),
            ),
            platform="logly_ads",
            account_id="1",
        )

        stored = _on_disk(path)["platforms"]["logly_ads"]["campaigns"][0]["ads"]
        assert stored == [{"ad_id": "a1", "status": "PAUSED"}, 42, {"ad_id": "a2"}]


# ---------------------------------------------------------------------------
# A missing ``campaigns`` key stays missing
# ---------------------------------------------------------------------------


class TestAbsentCampaignsStaysAbsent:
    def test_a_metrics_write_adds_no_campaigns_key(self, tmp_path: Path) -> None:
        path = _write_platforms(
            tmp_path, {"logly_ads": {"account_id": "1", "owner": "ops team"}}
        )

        set_platform_metrics(path, "logly_ads", "1", metrics_period="YESTERDAY")

        stored = _on_disk(path)["platforms"]["logly_ads"]
        assert "campaigns" not in stored
        assert stored["owner"] == "ops team"

    def test_an_upsert_adds_it(self, tmp_path: Path) -> None:
        path = _write_platforms(
            tmp_path, {"logly_ads": {"account_id": "1", "owner": "ops team"}}
        )

        upsert_campaign(
            path,
            CampaignSnapshot(campaign_id="c1", campaign_name="A", status="ENABLED"),
            platform="logly_ads",
            account_id="1",
        )

        stored = _on_disk(path)["platforms"]["logly_ads"]
        assert [c["campaign_id"] for c in stored["campaigns"]] == ["c1"]


# ---------------------------------------------------------------------------
# ``raw`` holds only what the write reads back
# ---------------------------------------------------------------------------


class TestRawIsTrimmed:
    def test_figures_are_placeholders_and_the_round_trip_is_exact(self) -> None:
        entry = {
            "account_id": "1",
            "campaigns": [_campaign(metrics={"spend": 5.0}, owner="x")],
            "daily": {"2026-10-20": {"spend": 5.0}},
            "periods": {"LAST_30_DAYS": {"spend": 5.0}},
            "region": "JP",
        }
        text = _with_platforms({"p": entry})

        doc = parse_state(text)

        assert doc.platforms is not None
        platform = doc.platforms["p"]
        assert platform.raw == {
            "account_id": "1",
            "campaigns": [],
            "daily": None,
            "periods": None,
            "region": "JP",
        }
        campaign_raw = platform.campaigns[0].raw
        assert campaign_raw is not None
        assert campaign_raw["metrics"] is None
        assert campaign_raw["owner"] == "x"
        assert campaign_raw["campaign_id"] == "c1"
        assert render_state(doc) == text


# ---------------------------------------------------------------------------
# ``mureo repair`` and hand-written content
# ---------------------------------------------------------------------------

_UNREAD = [
    pytest.param(
        {"campaigns": "hand written", "operator_note": "important"}, id="review-case"
    ),
    pytest.param({"account_id": "1", "operator_note": "important"}, id="unknown-key"),
    pytest.param({"account_id": "1", "campaigns": "hand written"}, id="string"),
    pytest.param({"account_id": "1", "campaigns": ["see sheet"]}, id="non-objects"),
]


class TestRepairKeepsHandWrittenContent:
    @pytest.mark.parametrize("entry", _UNREAD)
    def test_it_is_not_an_empty_stub(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        entry: dict[str, Any],
    ) -> None:
        _no_plugins(monkeypatch)
        path = _write_platforms(tmp_path, {"google_adz": entry})

        plan = plan_platform_keys(read_state_file(path))

        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.reason == KEEP_CARRIES_FIGURES
        assert finding.entry.has_unread_content is True

    def test_apply_all_leaves_it_on_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_plugins(monkeypatch)
        path = _write_platforms(
            tmp_path,
            {"google_adz": {"campaigns": "hand written", "operator_note": "important"}},
        )
        before = path.read_text(encoding="utf-8")

        apply_state_file_repairs(path)

        assert path.read_text(encoding="utf-8") == before

    def test_a_kept_entry_with_nothing_unread_is_still_a_stub(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No ``account_id`` keeps ``raw`` but holds nothing to lose."""
        _no_plugins(monkeypatch)
        path = _write_platforms(tmp_path, {"google_adz": {"campaigns": []}})

        plan = plan_platform_keys(read_state_file(path))

        (repair,) = plan.repairs
        assert repair.reason == DROP_EMPTY_STUB
        assert repair.entry.has_unread_content is False


# ---------------------------------------------------------------------------
# Document-level values that are not objects
# ---------------------------------------------------------------------------


def _document_with(**overrides: Any) -> str:
    return _text({**_document(), **overrides})


class TestDocumentLevelShapes:
    @pytest.mark.parametrize("strict", [True, False])
    @pytest.mark.parametrize("value", ["hello-secret", None, ["a"], 7])
    def test_a_platform_value_is_kept(self, strict: bool, value: Any) -> None:
        """#882: the whole object is kept on the document, so the value is
        written back as found, in its place."""
        platforms = {"p": value, "google_ads": _STRING_CAMPAIGNS}
        text = _document_with(platforms=platforms)

        doc = parse_state(text, strict=strict)

        assert doc.platforms is not None
        assert list(doc.platforms) == ["google_ads"]
        assert doc.raw == {"platforms": platforms}
        assert render_state(doc) == text

    @pytest.mark.parametrize("strict", [True, False])
    @pytest.mark.parametrize("value", ["hello-secret", ["a"], 7])
    def test_the_platforms_section_is_kept(self, strict: bool, value: Any) -> None:
        """#882: kept whole on the document, written back as found."""
        text = _document_with(platforms=value)

        doc = parse_state(text, strict=strict)

        assert doc.platforms is None
        assert doc.raw == {"platforms": value}
        assert render_state(doc) == text

    @pytest.mark.parametrize("strict", [True, False])
    @pytest.mark.parametrize("value", [[], "hello-secret", 1, None])
    def test_the_top_level(self, strict: bool, value: Any) -> None:
        with pytest.raises(ValueError, match="top level must be an object"):
            parse_state(json.dumps(value), strict=strict)

    def test_null_platforms_still_reads_as_absent(self) -> None:
        assert parse_state(_document_with(platforms=None)).platforms is None


# ---------------------------------------------------------------------------
# The stated exception: the v1 flat list
# ---------------------------------------------------------------------------


class TestFlatListUpsert:
    def test_a_matched_flat_entry_loses_its_unknown_keys(self, tmp_path: Path) -> None:
        """Platform-blind id match, so its ``raw`` is not carried (#881)."""
        path = tmp_path / "STATE.json"
        path.write_text(
            _document_with(campaigns=[_HAND_CAMPAIGN], platforms=None),
            encoding="utf-8",
        )

        upsert_campaign(
            path,
            CampaignSnapshot(
                campaign_id="72804", campaign_name="E2E", status="ENABLED"
            ),
            platform="google_ads",
            account_id="111-222-3333",
        )

        (flat,) = _on_disk(path)["campaigns"]
        assert flat["status"] == "ENABLED"
        assert "budget_note" not in flat
        assert "name" not in flat
