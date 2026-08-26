"""Tests for mureo's STRATEGY.md / STATE.json MCP tool surface.

These tools expose mureo's context layer (STRATEGY.md and STATE.json)
to MCP hosts that lack direct filesystem access — Claude Desktop chat,
claude.ai web, Codex/Cursor over remote MCP, etc. Without them, those
hosts can't read mureo's strategic context, which forces the user to
paste files into chat manually.

Coverage:
  - mureo_strategy_get        — read STRATEGY.md as markdown text
  - mureo_strategy_set        — replace STRATEGY.md (atomic write)
  - mureo_state_get           — read STATE.json as a dict
  - mureo_state_action_log_append — atomic action_log append
  - mureo_state_upsert_campaign   — atomic campaign snapshot upsert
  - path traversal refusal (security gate symmetric with rollback)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    """Reset the resolver cache before and after every test in this file
    so the workspace-aware ``resolve_workspace_path`` rebuilds a
    :class:`FilesystemStateStore` with the (per-test) CWD instead of
    reusing a stale one cached during an earlier test or test module."""
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def cwd_to_tmp(tmp_path, monkeypatch):
    """Run each test with cwd = tmp_path so STRATEGY.md/STATE.json land
    inside the sandbox by default. The autouse cache-reset fixture above
    runs first, so the resolver picks up the chdir on the next call."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _import_tools():
    from mureo.mcp import tools_mureo_context

    return tools_mureo_context


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def test_tools_module_exports_thirteen_tools() -> None:
    mod = _import_tools()
    assert len(mod.TOOLS) == 13
    expected = {
        "mureo_strategy_get",
        "mureo_strategy_set",
        "mureo_state_get",
        "mureo_state_action_log_append",
        "mureo_state_upsert_campaign",
        "mureo_state_report_set",
        # #706 — the dashboard's own write-guarded surface, separate from the
        # report summary an agent writes for whoever reads that report.
        "mureo_state_display_set",
        "mureo_state_platform_metrics_set",
        "mureo_state_platform_daily_set",
        "mureo_state_platform_not_collected_set",
        "mureo_state_workspace_not_collected_set",
        "mureo_state_set_conversion_events",
        "mureo_outcome_evaluate",
    }
    assert {t.name for t in mod.TOOLS} == expected


def test_tools_have_input_schema() -> None:
    mod = _import_tools()
    for tool in mod.TOOLS:
        assert tool.inputSchema["type"] == "object"
        assert "properties" in tool.inputSchema


# ---------------------------------------------------------------------------
# mureo_strategy_get / set
# ---------------------------------------------------------------------------


async def test_strategy_get_returns_file_text(cwd_to_tmp) -> None:
    (cwd_to_tmp / "STRATEGY.md").write_text(
        "# STRATEGY\n\n## Goals\n- Hit JPY 4500 CPA\n", encoding="utf-8"
    )
    mod = _import_tools()
    result = await mod.handle_tool("mureo_strategy_get", {})
    payload = json.loads(result[0].text)
    assert "# STRATEGY" in payload["markdown"]
    assert "JPY 4500" in payload["markdown"]


async def test_strategy_get_missing_file_returns_empty(cwd_to_tmp) -> None:
    """Missing STRATEGY.md is not an error — we return empty markdown.

    Many workflow skills run before the user has set up STRATEGY.md;
    they should see "no strategy yet" rather than a hard failure.
    """
    mod = _import_tools()
    result = await mod.handle_tool("mureo_strategy_get", {})
    payload = json.loads(result[0].text)
    assert payload["markdown"] == ""
    assert payload["exists"] is False


async def test_strategy_set_writes_file(cwd_to_tmp) -> None:
    mod = _import_tools()
    new_md = (
        "# STRATEGY\n\n## Operation Mode\nReview-only — no autonomous spend changes.\n"
    )
    await mod.handle_tool("mureo_strategy_set", {"markdown": new_md})
    written = (cwd_to_tmp / "STRATEGY.md").read_text(encoding="utf-8")
    assert "Review-only" in written


async def test_strategy_set_is_atomic(cwd_to_tmp, monkeypatch) -> None:
    """A failed write mid-flight must not leave a half-written file."""
    (cwd_to_tmp / "STRATEGY.md").write_text("# Original\n", encoding="utf-8")
    mod = _import_tools()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr("os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated rename failure"):
        await mod.handle_tool("mureo_strategy_set", {"markdown": "# Broken\n"})

    # Reading does not call os.replace, so the patched failure stays
    # active without affecting this assertion. The original file must
    # be intact because the failed os.replace never overwrote it.
    assert (cwd_to_tmp / "STRATEGY.md").read_text(encoding="utf-8") == "# Original\n"


@pytest.mark.parametrize("markdown", ["", "   ", "\n\t\n"])
async def test_strategy_set_rejects_empty_markdown(cwd_to_tmp, markdown) -> None:
    """Empty / whitespace-only markdown must NOT wipe STRATEGY.md (#276).

    A prompt-injected agent posting blank content would otherwise reduce the
    file to a bare ``# Strategy``. The pre-existing file must be untouched.
    """
    (cwd_to_tmp / "STRATEGY.md").write_text(
        "# Strategy\n\n## Persona\nkeep me\n", encoding="utf-8"
    )
    mod = _import_tools()
    # "" is rejected by _require ("not specified"); whitespace-only by the
    # explicit guard ("empty or whitespace-only"). Either way: rejected.
    with pytest.raises(ValueError, match="empty|not specified"):
        await mod.handle_tool("mureo_strategy_set", {"markdown": markdown})
    assert "keep me" in (cwd_to_tmp / "STRATEGY.md").read_text(encoding="utf-8")


async def test_strategy_set_backs_up_before_overwrite(cwd_to_tmp) -> None:
    """A timestamped ``.bak`` of the prior file is kept before replacement."""
    (cwd_to_tmp / "STRATEGY.md").write_text(
        "# Strategy\n\n## Persona\nold persona\n", encoding="utf-8"
    )
    mod = _import_tools()
    await mod.handle_tool(
        "mureo_strategy_set",
        {"markdown": "# Strategy\n\n## USP\nnew usp\n"},
    )

    backups = list(cwd_to_tmp.glob("STRATEGY.md.bak.*"))
    assert len(backups) == 1
    assert "old persona" in backups[0].read_text(encoding="utf-8")


async def test_strategy_set_preserves_unknown_heading(cwd_to_tmp) -> None:
    """An unrecognized heading round-trips and is reported, not dropped."""
    mod = _import_tools()
    md = "# Strategy\n\n## Persona\n30s\n\n## Quarterly Notes\nlaunch in Q3\n"
    result = await mod.handle_tool("mureo_strategy_set", {"markdown": md})
    payload = json.loads(result[0].text)

    assert payload["unrecognized"] == 1
    assert "## Quarterly Notes" in payload["markdown"]
    assert "launch in Q3" in payload["markdown"]
    written = (cwd_to_tmp / "STRATEGY.md").read_text(encoding="utf-8")
    assert "launch in Q3" in written


# ---------------------------------------------------------------------------
# mureo_state_get
# ---------------------------------------------------------------------------


async def test_state_get_returns_parsed_doc(cwd_to_tmp) -> None:
    state = {
        "version": "2",
        "last_synced_at": "2026-04-29T00:00:00+00:00",
        "platforms": {
            "google_ads": {
                "account_id": "demo",
                "campaigns": [
                    {
                        "campaign_id": "camp_abc",
                        "campaign_name": "Brand",
                        "status": "ENABLED",
                    }
                ],
            }
        },
        "action_log": [],
    }
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(state), encoding="utf-8")
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    assert payload["version"] == "2"
    assert "google_ads" in payload["platforms"]
    assert (
        payload["platforms"]["google_ads"]["campaigns"][0]["campaign_id"] == "camp_abc"
    )


async def test_state_get_missing_file_returns_default(cwd_to_tmp) -> None:
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    assert payload["version"] in ("1", "2")
    assert payload["action_log"] == []


# ---------------------------------------------------------------------------
# mureo_state_action_log_append
# ---------------------------------------------------------------------------


async def test_action_log_append_writes_entry(cwd_to_tmp) -> None:
    initial = {
        "version": "2",
        "platforms": {},
        "action_log": [],
    }
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    entry = {
        "timestamp": "2026-04-29T10:00:00+09:00",
        "action": "Increased budget +20%",
        "platform": "google_ads",
        "campaign_id": "camp_abc",
        "summary": "Test entry",
    }
    result = await mod.handle_tool("mureo_state_action_log_append", {"entry": entry})
    payload = json.loads(result[0].text)
    assert len(payload["action_log"]) == 1
    assert payload["action_log"][0]["action"] == "Increased budget +20%"
    on_disk = json.loads((cwd_to_tmp / "STATE.json").read_text(encoding="utf-8"))
    assert len(on_disk["action_log"]) == 1


async def test_action_log_append_validates_required_fields(cwd_to_tmp) -> None:
    mod = _import_tools()
    with pytest.raises(ValueError):
        await mod.handle_tool(
            "mureo_state_action_log_append", {"entry": {"summary": "x"}}
        )


# ---------------------------------------------------------------------------
# mureo_state_upsert_campaign
# ---------------------------------------------------------------------------


async def test_upsert_campaign_creates_when_missing(cwd_to_tmp) -> None:
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_xyz",
        "campaign_name": "Generic",
        "status": "ENABLED",
        "daily_budget": 5000,
        "platform": "google_ads",
        "account_id": "act_123",
    }
    result = await mod.handle_tool(
        "mureo_state_upsert_campaign", {"campaign": campaign}
    )
    payload = json.loads(result[0].text)
    # The v2 platforms section must carry the required account_id and the
    # campaign, and last_synced_at must be stamped, or the client renders
    # as inactive.
    plats = payload.get("platforms") or {}
    assert plats["google_ads"]["account_id"] == "act_123"
    found_in_platforms = any(
        c["campaign_id"] == "camp_xyz"
        for plat in plats.values()
        for c in plat.get("campaigns", [])
    )
    assert found_in_platforms
    assert payload.get("last_synced_at")


async def test_upsert_campaign_updates_existing(cwd_to_tmp) -> None:
    """Upserting the same campaign_id replaces the prior snapshot in place
    — the count stays at 1 and changed fields propagate."""
    mod = _import_tools()
    initial_campaign = {
        "campaign_id": "camp_xyz",
        "campaign_name": "Generic",
        "status": "ENABLED",
        "daily_budget": 5000,
        "platform": "google_ads",
        "account_id": "act_123",
    }
    await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": initial_campaign})

    updated = {
        "campaign_id": "camp_xyz",
        "campaign_name": "Generic",
        "status": "PAUSED",
        "daily_budget": 8000,
        "platform": "google_ads",
        "account_id": "act_123",
    }
    result = await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": updated})
    payload = json.loads(result[0].text)

    flat = list(payload.get("campaigns", []))
    plats = payload.get("platforms") or {}
    all_snaps = list(flat) + [
        c for plat in plats.values() for c in plat.get("campaigns", [])
    ]
    matches = [c for c in all_snaps if c["campaign_id"] == "camp_xyz"]
    # In-place replacement: every surviving snapshot reflects the update —
    # no stale ENABLED/5000 copy lingers in either the v1 flat list or the
    # v2 platforms section (which are dual-written in lockstep).
    assert matches, "campaign should be present"
    assert all(c["status"] == "PAUSED" and c["daily_budget"] == 8000 for c in matches)
    # And neither shape holds a duplicate of the same id.
    assert [c["campaign_id"] for c in flat].count("camp_xyz") <= 1
    for plat in plats.values():
        ids = [c["campaign_id"] for c in plat.get("campaigns", [])]
        assert ids.count("camp_xyz") <= 1


async def test_upsert_campaign_persists_metrics(cwd_to_tmp) -> None:
    """Stage a+b: an upsert carrying a ``metrics`` object persists it and
    round-trips via a subsequent read."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_xyz",
        "campaign_name": "Generic",
        "status": "ENABLED",
        "daily_budget": 5000,
        "platform": "google_ads",
        "account_id": "act_123",
        "metrics": {
            "spend": 12345.0,
            "impressions": 10000,
            "clicks": 250,
            "conversions": 12,
            "cpa": 1028.75,
            "ctr": 0.025,
            "period": "LAST_30_DAYS",
            "fetched_at": "2026-06-17T00:00:00+00:00",
        },
    }
    await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": campaign})

    # Round-trip via a fresh read of STATE.json.
    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    plat = payload["platforms"]["google_ads"]
    snap = next(c for c in plat["campaigns"] if c["campaign_id"] == "camp_xyz")
    assert snap["metrics"]["spend"] == 12345.0
    assert snap["metrics"]["conversions"] == 12
    assert snap["metrics"]["period"] == "LAST_30_DAYS"


async def test_upsert_campaign_persists_the_monthly_budget(cwd_to_tmp) -> None:
    """A platform whose campaigns carry a monthly budget can write it (#656).

    This is the route by which a platform's own monthly figure reaches
    mureo: the campaign snapshot, beside ``daily_budget``. No total is
    written anywhere — the sum is computed on read, so it cannot go stale.
    """
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_xyz",
        "campaign_name": "Always on",
        "status": "ENABLED",
        "daily_budget": 4000,
        "monthly_budget": 120000,
        "platform": "plugin:acme-ads:acme_ads",
        "account_id": "act_123",
    }
    await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": campaign})

    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    plat = payload["platforms"]["plugin:acme-ads:acme_ads"]
    snap = next(c for c in plat["campaigns"] if c["campaign_id"] == "camp_xyz")
    assert snap["monthly_budget"] == 120000
    assert snap["daily_budget"] == 4000


async def test_upsert_campaign_schema_offers_the_monthly_budget(cwd_to_tmp) -> None:
    """The field has to be discoverable, or only mureo's own code can write it."""
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_upsert_campaign")
    campaign_schema = tool.inputSchema["properties"]["campaign"]
    assert "monthly_budget" in campaign_schema["properties"]


async def test_upsert_campaign_without_metrics_still_works(cwd_to_tmp) -> None:
    """Regression: an upsert with no ``metrics`` key still succeeds and the
    persisted snapshot carries no ``metrics`` field."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_abc",
        "campaign_name": "Brand",
        "status": "ENABLED",
        "platform": "google_ads",
        "account_id": "act_123",
    }
    result = await mod.handle_tool(
        "mureo_state_upsert_campaign", {"campaign": campaign}
    )
    payload = json.loads(result[0].text)
    plat = payload["platforms"]["google_ads"]
    snap = next(c for c in plat["campaigns"] if c["campaign_id"] == "camp_abc")
    assert "metrics" not in snap


# ---------------------------------------------------------------------------
# mureo_state_report_set (stage c)
# ---------------------------------------------------------------------------


async def test_report_set_persists_summary(cwd_to_tmp) -> None:
    """A report summary is written into STATE.json ``reports[report]`` and
    round-trips via a subsequent read."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    summary = {
        "generated_at": "2026-06-17T00:00:00+00:00",
        "period": "2026-06-17",
        "kpis": {"google_ads": {"cpa": 4800}},
        "flags": ["cpa_over_target"],
        "narrative": "One campaign over target.",
    }
    result = await mod.handle_tool(
        "mureo_state_report_set", {"report": "daily", "summary": summary}
    )
    payload = json.loads(result[0].text)
    assert payload["reports"]["daily"] == summary

    # Round-trip via a fresh read of STATE.json.
    result2 = await mod.handle_tool("mureo_state_get", {})
    payload2 = json.loads(result2[0].text)
    assert payload2["reports"]["daily"]["flags"] == ["cpa_over_target"]


async def test_report_set_preserves_other_reports(cwd_to_tmp) -> None:
    """Writing one report kind does not clobber a previously written one."""
    initial = {
        "version": "2",
        "platforms": {},
        "action_log": [],
        "reports": {"weekly": {"narrative": "ok"}},
    }
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_report_set",
        {"report": "daily", "summary": {"narrative": "healthy"}},
    )
    payload = json.loads(result[0].text)
    assert payload["reports"]["daily"] == {"narrative": "healthy"}
    assert payload["reports"]["weekly"] == {"narrative": "ok"}


async def test_report_set_rejects_non_object_summary(cwd_to_tmp) -> None:
    """A non-object ``summary`` is refused by the handler."""
    mod = _import_tools()
    with pytest.raises(ValueError):
        await mod.handle_tool(
            "mureo_state_report_set",
            {"report": "daily", "summary": "not-a-dict"},
        )


async def test_report_set_requires_report_and_summary(cwd_to_tmp) -> None:
    """Both ``report`` and ``summary`` are required."""
    mod = _import_tools()
    with pytest.raises(ValueError):
        await mod.handle_tool("mureo_state_report_set", {"summary": {"narrative": "x"}})
    with pytest.raises(ValueError):
        await mod.handle_tool("mureo_state_report_set", {"report": "daily"})


def test_report_set_schema_enum_constrains_report() -> None:
    """The tool's inputSchema constrains ``report`` to the known kinds so the
    dispatcher's schema pass (#277) rejects anything else.

    WHICH kinds those are is the vocabulary's business — and that it covers
    every kind a shipped skill instructs is pinned in
    ``tests/test_report_kind_vocabulary.py`` (#671)."""
    from mureo.core.report_kinds import REPORT_KINDS

    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_report_set")
    props = tool.inputSchema["properties"]
    assert props["report"]["enum"] == list(REPORT_KINDS)
    assert props["summary"]["type"] == "object"
    assert set(tool.inputSchema["required"]) == {"report", "summary"}


async def test_report_set_normalizes_structured_flags(cwd_to_tmp) -> None:
    """A structured object flag with a known code but no explicit severity is
    persisted with the vocabulary's default severity filled in."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    summary = {
        "narrative": "One adspot spiking.",
        "flags": [
            {
                "code": "invalid_traffic_suspected",
                "params": {"adspot": "4311492", "spend": 115740, "ctr": 0.0466},
            }
        ],
    }
    result = await mod.handle_tool(
        "mureo_state_report_set", {"report": "daily", "summary": summary}
    )
    payload = json.loads(result[0].text)
    flag = payload["reports"]["daily"]["flags"][0]
    assert flag["code"] == "invalid_traffic_suspected"
    assert flag["severity"] == "action"
    assert flag["params"]["adspot"] == "4311492"


async def test_report_set_rejects_unknown_flag_code(cwd_to_tmp) -> None:
    """A non-``custom`` object flag whose code is outside the vocabulary is
    refused BEFORE it reaches STATE.json — validation is fail-closed, so a
    rejected write leaves the document byte-for-byte untouched (no partial
    write). Pinning the on-disk bytes guards the validate-before-write ordering
    against a future refactor."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    state_path = cwd_to_tmp / "STATE.json"
    state_path.write_text(json.dumps(initial), encoding="utf-8")
    before = state_path.read_text(encoding="utf-8")
    mod = _import_tools()
    with pytest.raises(ValueError):
        await mod.handle_tool(
            "mureo_state_report_set",
            {
                "report": "daily",
                "summary": {"flags": [{"code": "totally_made_up"}]},
            },
        )
    assert state_path.read_text(encoding="utf-8") == before


async def test_report_set_preserves_legacy_string_flags(cwd_to_tmp) -> None:
    """Legacy bare-string flags round-trip unchanged (no normalization)."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_report_set",
        {"report": "daily", "summary": {"flags": ["cpa_over_target"]}},
    )
    payload = json.loads(result[0].text)
    assert payload["reports"]["daily"]["flags"] == ["cpa_over_target"]


async def test_report_set_refuses_a_narrative_over_the_bound(cwd_to_tmp) -> None:
    """#662: the paragraph is refused at the tool boundary, and refusing
    writes nothing — the stored report is not replaced by a truncated one."""
    from mureo.core.report_summary import NARRATIVE_MAX_CHARS

    initial = {
        "version": "2",
        "platforms": {},
        "action_log": [],
        "reports": {"daily": {"narrative": "Healthy."}},
    }
    state_path = cwd_to_tmp / "STATE.json"
    state_path.write_text(json.dumps(initial), encoding="utf-8")
    before = state_path.read_text(encoding="utf-8")
    mod = _import_tools()
    with pytest.raises(ValueError) as excinfo:
        await mod.handle_tool(
            "mureo_state_report_set",
            {
                "report": "daily",
                "summary": {"narrative": "x" * (NARRATIVE_MAX_CHARS + 1)},
            },
        )
    assert str(NARRATIVE_MAX_CHARS) in str(excinfo.value)
    assert state_path.read_text(encoding="utf-8") == before


async def test_report_set_refuses_a_headline_figure_that_is_not_a_number(
    cwd_to_tmp,
) -> None:
    """``"¥773,957"`` is written where the view reads figures and renders as
    nothing — the same silent success #659 closed for metrics windows."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    state_path = cwd_to_tmp / "STATE.json"
    state_path.write_text(json.dumps(initial), encoding="utf-8")
    before = state_path.read_text(encoding="utf-8")
    mod = _import_tools()
    with pytest.raises(ValueError, match="spend"):
        await mod.handle_tool(
            "mureo_state_report_set",
            {"report": "daily", "summary": {"totals": {"spend": "¥773,957"}}},
        )
    assert state_path.read_text(encoding="utf-8") == before


async def test_report_set_accepts_the_structured_report_it_asks_for(
    cwd_to_tmp,
) -> None:
    """The shape the schema now instructs: figures in ``totals``, findings in
    ``flags``, judgement and proposal in a short ``narrative``."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    summary = {
        "generated_at": "2026-07-10T09:00:00+09:00",
        "period": "LAST_30_DAYS",
        "totals": {"spend": 773957, "conversions": 50, "cpa": 15479, "ctr": 0.0466},
        "flags": [
            {"code": "goals_met"},
            {
                "code": "invalid_traffic_suspected",
                "params": {"adspot": "4311492", "spend": 115740, "cv": 0},
            },
        ],
        "narrative": (
            "Healthy: both goals are met on the current trend. Proposing a "
            "move to SCALE_EXPANSION and restarting the paused SP/PSW "
            "adspots — neither applied yet."
        ),
    }
    result = await mod.handle_tool(
        "mureo_state_report_set", {"report": "daily", "summary": summary}
    )
    payload = json.loads(result[0].text)
    stored = payload["reports"]["daily"]
    assert stored["totals"] == summary["totals"]
    assert stored["flags"][0]["code"] == "goals_met"
    assert stored["narrative"] == summary["narrative"]


def test_report_set_schema_tells_the_writer_where_each_part_goes() -> None:
    """#659's lesson applied to a free-form object: no ``enum`` can constrain
    prose, so the rule has to be in the description the model reads BEFORE it
    calls — not only in the error it gets after."""
    from mureo.core.report_summary import REPORT_SUMMARY_RULE

    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_report_set")
    description = tool.inputSchema["properties"]["summary"]["description"]
    assert REPORT_SUMMARY_RULE in description


# ---------------------------------------------------------------------------
# Path traversal gate (security)
# ---------------------------------------------------------------------------


async def test_path_argument_refuses_traversal(cwd_to_tmp) -> None:
    """Custom ``path`` outside the active workspace is rejected —
    symmetric with rollback's ``_resolve_state_file`` guard. A
    prompt-injected agent must not be able to point mureo at an
    attacker-crafted file elsewhere on disk.

    The default workspace is CWD (the resolved
    :class:`FilesystemStateStore` derives ``workspace`` from
    ``Path.cwd()`` at construction), so this test exercises the
    workspace boundary while CWD is ``cwd_to_tmp``."""
    mod = _import_tools()
    with pytest.raises(ValueError, match="Refusing to read/write outside workspace"):
        await mod.handle_tool("mureo_strategy_get", {"path": "/etc/passwd"})


# ---------------------------------------------------------------------------
# RuntimeContext-routing (workspace-aware default path)
# ---------------------------------------------------------------------------


async def test_default_path_follows_runtime_context_workspace(
    tmp_path, monkeypatch
) -> None:
    """When no ``path`` argument is supplied, handlers read/write at
    ``state_store.workspace / 'STATE.json'`` — picking up any alternate
    :class:`StateStore` registered via the
    ``mureo.runtime_context_factory`` entry-point group.

    Verified by injecting a :class:`FilesystemStateStore` whose
    workspace is a sibling of CWD, then asserting the on-disk write
    lands in the injected workspace (NOT in CWD)."""
    from mureo.core.runtime_context import RuntimeContext, default_runtime_context

    # CWD is one dir, the injected workspace is a SIBLING dir.
    cwd_dir = tmp_path / "cwd"
    workspace_dir = tmp_path / "tenant"
    cwd_dir.mkdir()
    workspace_dir.mkdir()
    monkeypatch.chdir(cwd_dir)

    base = default_runtime_context(workspace=workspace_dir)
    injected = RuntimeContext(
        secret_store=base.secret_store,
        state_store=base.state_store,
        knowledge_store=base.knowledge_store,
        throttle_store=base.throttle_store,
        workspace_id="injected",
    )
    monkeypatch.setattr("mureo.core.runtime_context._cached_context", injected)

    mod = _import_tools()
    await mod.handle_tool(
        "mureo_state_action_log_append",
        {
            "entry": {
                "timestamp": "2026-05-21T00:00:00Z",
                "action": "test",
                "platform": "google_ads",
            }
        },
    )

    # The action_log write must land under the injected workspace,
    # NOT under CWD — proving the handler followed the RuntimeContext.
    assert (workspace_dir / "STATE.json").exists()
    assert not (cwd_dir / "STATE.json").exists()


# ---------------------------------------------------------------------------
# mureo_state_platform_metrics_set
# ---------------------------------------------------------------------------


async def test_platform_metrics_set_creates_platform_with_periods(cwd_to_tmp) -> None:
    """Writes the v2 platform entry with account_id + per-period rollups."""
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_platform_metrics_set",
        {
            "platform": "google_ads",
            "account_id": "act_123",
            "totals": {"spend": 3000.0, "conversions": 60},
            "metrics_period": "LAST_30_DAYS",
            "periods": {
                "LAST_30_DAYS": {"spend": 3000.0, "conversions": 60},
                "YESTERDAY": {"spend": 100.0, "conversions": 2},
            },
        },
    )
    payload = json.loads(result[0].text)
    plat = payload["platforms"]["google_ads"]
    assert plat["account_id"] == "act_123"
    assert plat["totals"]["spend"] == 3000.0
    assert plat["totals"]["conversions"] == 60
    assert plat["metrics_period"] == "LAST_30_DAYS"
    assert plat["periods"]["YESTERDAY"]["spend"] == 100.0
    assert plat["periods"]["YESTERDAY"]["conversions"] == 2
    assert payload.get("last_synced_at")
    # Every rollup this write supplied carries a write-time fetched_at (#637).
    assert plat["totals"]["fetched_at"] == payload["last_synced_at"]
    assert plat["periods"]["YESTERDAY"]["fetched_at"] == payload["last_synced_at"]


async def test_platform_metrics_set_merges_periods_per_window(cwd_to_tmp) -> None:
    """A YESTERDAY write must keep the LAST_30_DAYS bucket a prior call wrote."""
    mod = _import_tools()
    await mod.handle_tool(
        "mureo_state_platform_metrics_set",
        {
            "platform": "google_ads",
            "account_id": "act_123",
            "periods": {"LAST_30_DAYS": {"spend": 3000.0}},
        },
    )
    result = await mod.handle_tool(
        "mureo_state_platform_metrics_set",
        {
            "platform": "google_ads",
            "account_id": "act_123",
            "periods": {"YESTERDAY": {"spend": 100.0}},
        },
    )
    payload = json.loads(result[0].text)
    periods = payload["platforms"]["google_ads"]["periods"]
    assert sorted(periods) == ["LAST_30_DAYS", "YESTERDAY"]
    assert periods["LAST_30_DAYS"]["spend"] == 3000.0
    assert periods["YESTERDAY"]["spend"] == 100.0
    # The preserved window keeps the age it was collected at; only the window
    # this call supplied is stamped with the new write time (#637).
    assert periods["LAST_30_DAYS"]["fetched_at"] < periods["YESTERDAY"]["fetched_at"]
    assert periods["YESTERDAY"]["fetched_at"] == payload["last_synced_at"]


async def test_platform_metrics_set_preserves_campaigns_and_other_platforms(
    cwd_to_tmp,
) -> None:
    """Setting one platform's rollup leaves its campaigns + siblings intact."""
    mod = _import_tools()
    # Seed google_ads with a campaign, and meta_ads as a sibling platform.
    await mod.handle_tool(
        "mureo_state_upsert_campaign",
        {
            "campaign": {
                "campaign_id": "g1",
                "campaign_name": "Brand",
                "status": "ENABLED",
                "platform": "google_ads",
                "account_id": "act_123",
            }
        },
    )
    await mod.handle_tool(
        "mureo_state_platform_metrics_set",
        {"platform": "meta_ads", "account_id": "act_9", "totals": {"spend": 5.0}},
    )
    # Now set google_ads rollup — campaign + meta_ads must survive.
    result = await mod.handle_tool(
        "mureo_state_platform_metrics_set",
        {
            "platform": "google_ads",
            "account_id": "act_123",
            "periods": {"YESTERDAY": {"spend": 100.0}},
        },
    )
    payload = json.loads(result[0].text)
    google = payload["platforms"]["google_ads"]
    assert [c["campaign_id"] for c in google["campaigns"]] == ["g1"]
    assert payload["platforms"]["meta_ads"]["totals"]["spend"] == 5.0


async def test_platform_metrics_set_requires_platform_and_account(cwd_to_tmp) -> None:
    mod = _import_tools()
    with pytest.raises(ValueError, match="platform"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set", {"account_id": "act_123"}
        )
    with pytest.raises(ValueError, match="account_id"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set", {"platform": "google_ads"}
        )


def _metrics_schema() -> dict:
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_platform_metrics_set")
    return tool.inputSchema


def _platform_account_props(tool_name: str) -> dict:
    """The ``platform`` / ``account_id`` properties of a state-write tool,
    wherever the tool nests them."""
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == tool_name)
    props = tool.inputSchema["properties"]
    if "campaign" in props:  # mureo_state_upsert_campaign nests them
        props = props["campaign"]["properties"]
    return props


def test_platform_metrics_schema_documents_tiktok_ads() -> None:
    """#534 — ``tiktok_ads`` is a first-class ad-platform key (the reporting
    view treats it as one), so the tool that writes platform rollups must
    name it."""
    platform = _metrics_schema()["properties"]["platform"]
    assert "tiktok_ads" in platform["description"]


def test_platform_metrics_schema_constrains_non_empty_strings() -> None:
    """#534 — a bare ``{"type": "string"}`` accepts ``""``. An enum would
    reject a valid ``plugin:<dist>`` key, so the genuinely correct constraint
    is a minimum length."""
    props = _metrics_schema()["properties"]
    assert props["platform"]["minLength"] == 1
    assert props["account_id"]["minLength"] == 1


@pytest.mark.parametrize(
    "tool_name",
    [
        "mureo_state_platform_metrics_set",
        "mureo_state_upsert_campaign",
        "mureo_state_set_conversion_events",
    ],
)
def test_every_state_write_tool_states_the_one_account_one_key_rule(
    tool_name: str,
) -> None:
    """#534 — the runtime guard covers all three writers, so all three schemas
    must say so; an inconsistent one just teaches the next reader the wrong
    rule."""
    props = _platform_account_props(tool_name)
    assert props["platform"]["minLength"] == 1
    assert props["account_id"]["minLength"] == 1
    assert "one platform key" in props["platform"]["description"]


async def test_platform_metrics_set_rejects_explicit_empty_account_id(
    cwd_to_tmp,
) -> None:
    """#534 — an explicitly-passed ``""`` must not be reported as "not
    specified"; it WAS specified. Still fail-before-write.

    This is the DIRECT-handler path (no schema gate) — see
    ``test_empty_account_id_through_the_real_dispatcher`` for what an MCP
    client actually sees.
    """
    mod = _import_tools()
    with pytest.raises(ValueError, match="account_id must not be empty"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set",
            {"platform": "google_ads", "account_id": ""},
        )
    assert not (cwd_to_tmp / "STATE.json").exists()


async def test_empty_account_id_through_the_real_dispatcher(cwd_to_tmp) -> None:
    """What an MCP CLIENT observes for ``account_id=""``.

    ``handle_call_tool`` schema-validates against the declared ``inputSchema``
    before any handler runs, so the ``minLength: 1`` constraint fires first and
    the handler's own message is never reached on this path. Asserted here so
    the schema and the docs describe the message that is actually emitted.
    """
    from mureo.mcp import server as server_mod

    with pytest.raises(ValueError) as exc:
        await server_mod.handle_call_tool(
            "mureo_state_platform_metrics_set",
            {"platform": "google_ads", "account_id": ""},
        )
    message = str(exc.value)
    assert "account_id" in message
    assert "non-empty" in message
    assert not (cwd_to_tmp / "STATE.json").exists()


async def test_platform_metrics_set_rejects_a_duplicate_account(cwd_to_tmp) -> None:
    """#534 — the second key for one ad account is refused through the tool
    surface too, naming both keys and the account."""
    mod = _import_tools()
    await mod.handle_tool(
        "mureo_state_platform_metrics_set",
        {"platform": "meta_ads", "account_id": "act_1", "totals": {"spend": 1.0}},
    )
    with pytest.raises(ValueError) as exc:
        await mod.handle_tool(
            "mureo_state_platform_metrics_set",
            {
                "platform": "plugin:mureo-logly-bridge",
                "account_id": "act_1",
                "totals": {"spend": 2.0},
            },
        )
    message = str(exc.value)
    assert "meta_ads" in message
    assert "plugin:mureo-logly-bridge" in message
    assert "act_1" in message


async def test_platform_metrics_set_rejects_an_invented_platform_key(
    cwd_to_tmp, monkeypatch
) -> None:
    """#609 — the tool surface an agent actually calls refuses a key it made
    up, and tells it what would have been accepted.

    The installed set is pinned: this machine has real bridges installed, and
    a test that read the ambient environment would not be asserting the rule.
    """
    from types import SimpleNamespace

    from mureo.context import platform_guards

    monkeypatch.setattr(
        platform_guards,
        "_provider_entry_points",
        lambda: (SimpleNamespace(name="logly_ads_context"),),
    )
    mod = _import_tools()
    with pytest.raises(ValueError) as exc:
        await mod.handle_tool(
            "mureo_state_platform_metrics_set",
            {
                "platform": "logly_ads",
                "account_id": "act_1",
                "totals": {"spend": 1.0},
            },
        )
    message = str(exc.value)
    assert "logly_ads" in message
    assert "logly_ads_context" in message
    assert "google_ads" in message
    assert not (cwd_to_tmp / "STATE.json").exists()


async def test_platform_metrics_set_rejects_malformed_shapes(cwd_to_tmp) -> None:
    mod = _import_tools()
    base = {"platform": "google_ads", "account_id": "act_123"}
    with pytest.raises(ValueError, match="totals must be an object"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set", {**base, "totals": "nope"}
        )
    with pytest.raises(ValueError, match="periods must be an object"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set", {**base, "periods": [1, 2]}
        )
    with pytest.raises(ValueError, match=r"periods\['YESTERDAY'\] must be an object"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set",
            {**base, "periods": {"YESTERDAY": "nope"}},
        )
    with pytest.raises(ValueError, match="metrics_period must be a string"):
        await mod.handle_tool(
            "mureo_state_platform_metrics_set", {**base, "metrics_period": 30}
        )


# ---------------------------------------------------------------------------
# mureo_state_set_conversion_events (#342)
# ---------------------------------------------------------------------------


async def test_set_conversion_events_sets_and_clears(cwd_to_tmp) -> None:
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_set_conversion_events",
        {
            "platform": "meta_ads",
            "account_id": "act_9",
            "conversion_action_types": ["offsite_conversion.custom.123"],
        },
    )
    payload = json.loads(result[0].text)
    assert payload["platforms"]["meta_ads"]["conversion_action_types"] == [
        "offsite_conversion.custom.123"
    ]
    # Clearing with an empty list removes the override.
    result = await mod.handle_tool(
        "mureo_state_set_conversion_events",
        {"platform": "meta_ads", "account_id": "act_9", "conversion_action_types": []},
    )
    payload = json.loads(result[0].text)
    assert "conversion_action_types" not in payload["platforms"]["meta_ads"]


async def test_set_conversion_events_requires_platform_and_account(cwd_to_tmp) -> None:
    mod = _import_tools()
    with pytest.raises(ValueError, match="platform"):
        await mod.handle_tool(
            "mureo_state_set_conversion_events", {"account_id": "act_9"}
        )
    with pytest.raises(ValueError, match="account_id"):
        await mod.handle_tool(
            "mureo_state_set_conversion_events", {"platform": "meta_ads"}
        )


async def test_set_conversion_events_rejects_non_list(cwd_to_tmp) -> None:
    mod = _import_tools()
    with pytest.raises(ValueError, match="must be a list"):
        await mod.handle_tool(
            "mureo_state_set_conversion_events",
            {
                "platform": "meta_ads",
                "account_id": "act_9",
                "conversion_action_types": "lead",
            },
        )


async def test_set_conversion_events_read_write_path_agree(cwd_to_tmp) -> None:
    """#342 HIGH — the override written via the MCP tool (workspace-resolved)
    must be readable by the live counters' resolver with NO explicit path."""
    from mureo.context.state import load_conversion_action_types

    mod = _import_tools()
    await mod.handle_tool(
        "mureo_state_set_conversion_events",
        {
            "platform": "meta_ads",
            "account_id": "act_42",
            "conversion_action_types": ["offsite_conversion.custom.7"],
        },
    )
    assert load_conversion_action_types("act_42") == ("offsite_conversion.custom.7",)
    # act_ prefix tolerance: a bare-id live resolve still matches.
    assert load_conversion_action_types("42") == ("offsite_conversion.custom.7",)


# ---------------------------------------------------------------------------
# Server clock injection (#460)
#
# /daily-check ran with a days-old notion of "today": the agent read
# STATE.json, saw old dates (reports.daily.period, last_synced_at,
# action_log timestamps) and short-circuited with "today's data is already
# fetched". Nothing in the stack ever told it the real date, and the
# action_log timestamps it read back as fact were its own drifted values.
# Fix: the read entry points carry a ``server_now`` envelope field, and the
# action_log append stamps the timestamp server-side.
# ---------------------------------------------------------------------------


_FROZEN_NOW = datetime(2026, 7, 28, 10, 12, 33, tzinfo=timezone(timedelta(hours=9)))
_FROZEN_ISO = "2026-07-28T10:12:33+09:00"


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze the injected server clock (the single documented seam)."""
    import mureo.core.clock as clock

    monkeypatch.setattr(clock, "server_now", lambda: _FROZEN_NOW)
    return _FROZEN_ISO


async def test_state_get_returns_server_now(cwd_to_tmp, frozen_clock) -> None:
    (cwd_to_tmp / "STATE.json").write_text(
        json.dumps({"version": "2", "platforms": {}, "action_log": []}),
        encoding="utf-8",
    )
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    assert payload["server_now"] == frozen_clock


async def test_state_get_server_now_is_parseable_and_offset_bearing(
    cwd_to_tmp,
) -> None:
    """Real (unfrozen) clock: ISO 8601 WITH a UTC offset, close to now."""
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    parsed = datetime.fromisoformat(payload["server_now"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    assert abs(parsed - datetime.now(timezone.utc)) < timedelta(minutes=5)


async def test_state_get_server_now_present_when_file_absent(
    cwd_to_tmp, frozen_clock
) -> None:
    """The empty-default branch must carry the clock too — an onboarding
    run has no STATE.json yet and still needs to know the date."""
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {})
    assert json.loads(result[0].text)["server_now"] == frozen_clock


async def test_state_get_server_now_ignores_a_stale_value_on_disk(
    cwd_to_tmp, frozen_clock
) -> None:
    """A ``server_now`` that leaked into STATE.json (an agent echoing a read
    response back through a raw Write) must never be served as the clock."""
    (cwd_to_tmp / "STATE.json").write_text(
        json.dumps(
            {
                "version": "2",
                "server_now": "1999-01-01T00:00:00+09:00",
                "platforms": {},
                "action_log": [],
            }
        ),
        encoding="utf-8",
    )
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {})
    assert json.loads(result[0].text)["server_now"] == frozen_clock


async def test_server_now_is_not_persisted_by_a_later_write(cwd_to_tmp) -> None:
    """Round-trip guard: echo the whole read response back into STATE.json
    (what a Code-path bulk `Write` does), then let any mureo write touch the
    file — the response-only ``server_now`` key must not survive into the
    persisted document."""
    (cwd_to_tmp / "STATE.json").write_text(
        json.dumps({"version": "2", "platforms": {}, "action_log": []}),
        encoding="utf-8",
    )
    mod = _import_tools()
    read = json.loads((await mod.handle_tool("mureo_state_get", {}))[0].text)
    assert "server_now" in read
    # The agent echoes the response verbatim into the file.
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(read), encoding="utf-8")

    await mod.handle_tool(
        "mureo_state_action_log_append",
        {"entry": {"action": "test", "platform": "google_ads"}},
    )
    on_disk = json.loads((cwd_to_tmp / "STATE.json").read_text(encoding="utf-8"))
    assert "server_now" not in on_disk


async def test_strategy_get_returns_server_now(cwd_to_tmp, frozen_clock) -> None:
    """STRATEGY.md is the other step-1 read; keep the clock consistent so a
    skill that starts there does not have to make a second call."""
    (cwd_to_tmp / "STRATEGY.md").write_text("# Strategy\n", encoding="utf-8")
    mod = _import_tools()
    result = await mod.handle_tool("mureo_strategy_get", {})
    assert json.loads(result[0].text)["server_now"] == frozen_clock


async def test_strategy_get_server_now_present_when_file_absent(
    cwd_to_tmp, frozen_clock
) -> None:
    mod = _import_tools()
    result = await mod.handle_tool("mureo_strategy_get", {})
    payload = json.loads(result[0].text)
    assert payload["exists"] is False
    assert payload["server_now"] == frozen_clock


async def test_action_log_append_ignores_client_timestamp(
    cwd_to_tmp, frozen_clock
) -> None:
    """A model-supplied timestamp is accepted by the schema but IGNORED —
    a drifted date must not be persisted and read back later as fact."""
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_action_log_append",
        {
            "entry": {
                "timestamp": "1999-01-01T00:00:00+00:00",
                "action": "Increased budget +20%",
                "platform": "google_ads",
            }
        },
    )
    payload = json.loads(result[0].text)
    assert payload["action_log"][0]["timestamp"] == frozen_clock
    on_disk = json.loads((cwd_to_tmp / "STATE.json").read_text(encoding="utf-8"))
    assert on_disk["action_log"][0]["timestamp"] == frozen_clock


async def test_action_log_append_stamps_timestamp_when_omitted(
    cwd_to_tmp, frozen_clock
) -> None:
    """``timestamp`` is no longer a required input — the server supplies it."""
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_action_log_append",
        {"entry": {"action": "Paused campaign", "platform": "meta_ads"}},
    )
    payload = json.loads(result[0].text)
    assert payload["action_log"][0]["timestamp"] == frozen_clock


async def test_action_log_schema_documents_server_stamping() -> None:
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_action_log_append")
    entry = tool.inputSchema["properties"]["entry"]
    # Kept for schema compatibility (additionalProperties: false), but no
    # longer required and explicitly documented as ignored.
    assert "timestamp" in entry["properties"]
    assert "timestamp" not in entry["required"]
    description = entry["properties"]["timestamp"]["description"].lower()
    assert "server" in description
    assert "ignored" in description


@pytest.mark.parametrize("name", ["mureo_state_get", "mureo_strategy_get"])
async def test_read_tool_descriptions_advertise_server_now(name: str) -> None:
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == name)
    assert "server_now" in tool.description


# ---------------------------------------------------------------------------
# #468 — ad-level status travels through mureo_state_upsert_campaign
# ---------------------------------------------------------------------------


def test_upsert_campaign_schema_accepts_ads() -> None:
    """The ads list rides on the existing upsert (``additionalProperties:
    false`` means an undeclared key would be rejected outright)."""
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_upsert_campaign")
    campaign = tool.inputSchema["properties"]["campaign"]
    ads = campaign["properties"]["ads"]
    assert ads["type"] == "array"
    item_props = ads["items"]["properties"]
    for name in ("ad_id", "name", "status", "effective_status", "as_of"):
        assert name in item_props
    assert ads["items"]["required"] == ["ad_id"]


def test_action_log_schema_accepts_ad_id() -> None:
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_action_log_append")
    entry = tool.inputSchema["properties"]["entry"]
    assert "ad_id" in entry["properties"]


def test_action_log_schema_accepts_generic_entity_identity() -> None:
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_action_log_append")
    entry = tool.inputSchema["properties"]["entry"]
    assert "entity_type" in entry["properties"]
    assert "entity_id" in entry["properties"]
    assert entry["properties"]["entity_type"]["minLength"] == 1
    assert entry["properties"]["entity_id"]["minLength"] == 1
    assert entry["dependentRequired"] == {
        "entity_type": ["entity_id"],
        "entity_id": ["entity_type"],
        # #545: an external_id on a mureo-originated entry would poison
        # change-import dedup, so the schema refuses it too — not only the
        # model. Pinned as a whole dict so a rule cannot be dropped silently.
        "external_id": ["origin"],
    }


async def test_upsert_campaign_persists_ads(cwd_to_tmp) -> None:
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_1",
        "campaign_name": "Prospecting",
        "status": "ACTIVE",
        "platform": "meta_ads",
        "account_id": "act_123",
        "ads": [
            {
                "ad_id": "ad_1",
                "name": "Creative A",
                "status": "ACTIVE",
                "effective_status": "ADSET_PAUSED",
            },
            {"ad_id": "ad_2", "name": "Creative B", "status": "PAUSED"},
        ],
    }
    await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": campaign})

    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    snap = payload["platforms"]["meta_ads"]["campaigns"][0]
    ads = {a["ad_id"]: a for a in snap["ads"]}
    assert ads["ad_1"]["effective_status"] == "ADSET_PAUSED"
    assert ads["ad_2"]["status"] == "PAUSED"
    # An ad whose effective_status the platform did not report must not gain
    # an invented one.
    assert "effective_status" not in ads["ad_2"]


async def test_upsert_campaign_stamps_ad_as_of_server_side(
    cwd_to_tmp, frozen_clock
) -> None:
    """#460 pattern: ``as_of`` is the server's clock, never the model's. A
    drifted client date persisted here would later be read back as evidence of
    when the status was last observed."""
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_1",
        "campaign_name": "Prospecting",
        "status": "ACTIVE",
        "platform": "meta_ads",
        "account_id": "act_123",
        "ads": [{"ad_id": "ad_1", "as_of": "1999-01-01T00:00:00+09:00"}],
    }
    result = await mod.handle_tool(
        "mureo_state_upsert_campaign", {"campaign": campaign}
    )
    payload = json.loads(result[0].text)
    snap = payload["platforms"]["meta_ads"]["campaigns"][0]
    assert snap["ads"][0]["as_of"] == frozen_clock


async def test_upsert_campaign_without_ads_emits_no_ads_key(cwd_to_tmp) -> None:
    """Regression: campaigns that never had ad-level data stay unchanged."""
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_2",
        "campaign_name": "Brand",
        "status": "ACTIVE",
        "platform": "meta_ads",
        "account_id": "act_123",
    }
    result = await mod.handle_tool(
        "mureo_state_upsert_campaign", {"campaign": campaign}
    )
    payload = json.loads(result[0].text)
    snap = payload["platforms"]["meta_ads"]["campaigns"][0]
    assert "ads" not in snap


async def test_upsert_campaign_rejects_non_object_ad_entry(cwd_to_tmp) -> None:
    mod = _import_tools()
    campaign = {
        "campaign_id": "camp_3",
        "campaign_name": "Brand",
        "status": "ACTIVE",
        "platform": "meta_ads",
        "account_id": "act_123",
        "ads": ["ad_1"],
    }
    with pytest.raises(ValueError, match="ads"):
        await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": campaign})


async def test_action_log_append_persists_ad_id(cwd_to_tmp) -> None:
    mod = _import_tools()
    await mod.handle_tool(
        "mureo_state_action_log_append",
        {
            "entry": {
                "action": "ad_pause",
                "platform": "meta_ads",
                "campaign_id": "camp_1",
                "ad_id": "ad_1",
            }
        },
    )
    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    assert payload["action_log"][0]["ad_id"] == "ad_1"


async def test_action_log_append_persists_generic_entity_identity(cwd_to_tmp) -> None:
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_action_log_append",
        {
            "entry": {
                "action": "lower placement bid",
                "platform": "plugin:acme",
                "campaign_id": "campaign_1",
                "entity_type": "placement",
                "entity_id": "placement_1",
            }
        },
    )
    payload = json.loads(result[0].text)
    entry = payload["action_log"][0]
    assert entry["entity_type"] == "placement"
    assert entry["entity_id"] == "placement_1"


async def test_upsert_campaign_ads_merge_semantics_end_to_end(cwd_to_tmp) -> None:
    """The three ``ads`` states, exercised through the MCP tool itself.

    The Python-API tests cover the merge rule; this pins that it survives the
    handler path an agent actually drives — omitting ``ads`` inherits the last
    known statuses (so pausing a campaign does not erase its ad history), while
    an explicit empty list is a real observation that clears them.
    """
    mod = _import_tools()
    base = {
        "campaign_id": "camp_1",
        "campaign_name": "Prospecting",
        "platform": "meta_ads",
        "account_id": "act_123",
    }

    # 1. First sync while ACTIVE: ad-level status fetched and stored.
    await mod.handle_tool(
        "mureo_state_upsert_campaign",
        {
            "campaign": {
                **base,
                "status": "ACTIVE",
                "ads": [
                    {"ad_id": "ad_1", "status": "ACTIVE", "effective_status": "ACTIVE"}
                ],
            }
        },
    )

    # 2. Campaign now PAUSED, so the flows skip the ad-level call (cost guard)
    #    and send no ``ads`` — the stored statuses must survive.
    result = await mod.handle_tool(
        "mureo_state_upsert_campaign",
        {"campaign": {**base, "status": "PAUSED"}},
    )
    snap = json.loads(result[0].text)["platforms"]["meta_ads"]["campaigns"][0]
    assert snap["status"] == "PAUSED"
    assert [a["ad_id"] for a in snap["ads"]] == ["ad_1"]
    assert snap["ads"][0]["as_of"], "inherited ad keeps its original observation time"

    # 3. An explicit empty list is an observation ("no ads"), so it clears.
    result = await mod.handle_tool(
        "mureo_state_upsert_campaign",
        {"campaign": {**base, "status": "ACTIVE", "ads": []}},
    )
    snap = json.loads(result[0].text)["platforms"]["meta_ads"]["campaigns"][0]
    assert snap["ads"] == []


# ---------------------------------------------------------------------------
# mureo_state_get — action_log scoping (Part A: context weight-reduction)
#
# The full action_log is the single biggest context cost of a mureo_state_get.
# ``action_log`` scopes the returned log: "all" (default, byte-identical to the
# historical behaviour), "pending" (only entries with an OPEN observation_due),
# "none" (omit the log). When filtered, ``action_log_scope`` + ``action_log_total``
# mark the response so nothing pretends the log is complete.
# ---------------------------------------------------------------------------


# A STATE.json action_log with the four cases "pending" must discriminate:
#   [0] observation_due in the PAST   -> pending (must be evaluated this run)
#   [1] observation_due in the FUTURE -> pending (still under observation)
#   [2] NO observation_due            -> not pending (a plain log entry)
#   [3] observation_due, but ROLLED BACK by [4] -> closed, not pending
#   [4] the rollback entry (rollback_of=3, no observation_due) -> not pending
_MIXED_ACTION_LOG = [
    {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "action": "Increased budget +20%",
        "platform": "google_ads",
        "campaign_id": "c1",
        "observation_due": "2026-01-08",
        "metrics_at_action": {"cpa": 5000},
    },
    {
        "timestamp": "2026-07-20T00:00:00+00:00",
        "action": "Swapped creative",
        "platform": "meta_ads",
        "campaign_id": "c2",
        "observation_due": "2099-01-01",
    },
    {
        "timestamp": "2026-07-25T00:00:00+00:00",
        "action": "Ran daily check",
        "platform": "google_ads",
    },
    {
        "timestamp": "2026-07-26T00:00:00+00:00",
        "action": "Paused campaign",
        "platform": "google_ads",
        "campaign_id": "c3",
        "observation_due": "2026-08-01",
    },
    {
        "timestamp": "2026-07-27T00:00:00+00:00",
        "action": "campaigns_update_status",
        "platform": "google_ads",
        "campaign_id": "c3",
        "rollback_of": 3,
        "summary": "Rolled back #3: Paused campaign",
    },
]


def _write_mixed_state(root) -> None:
    state = {
        "version": "2",
        "last_synced_at": "2026-07-27T00:00:00+00:00",
        "platforms": {
            "google_ads": {
                "account_id": "act_123",
                "campaigns": [
                    {
                        "campaign_id": "c1",
                        "campaign_name": "Brand",
                        "status": "ENABLED",
                    }
                ],
            }
        },
        "action_log": _MIXED_ACTION_LOG,
        "reports": {"daily": {"period": "2026-07-27", "narrative": "healthy"}},
    }
    (root / "STATE.json").write_text(json.dumps(state), encoding="utf-8")


async def test_state_get_action_log_default_is_all_and_byte_identical(
    cwd_to_tmp, frozen_clock
):
    """Omitting ``action_log`` (and passing ``"all"``) is the historical
    behaviour verbatim: the full log, no scope markers, byte-for-byte equal.

    The clock is frozen (#460 seam) because the two responses each carry
    their own ``server_now`` stamp: unfrozen, "byte-for-byte" would only
    hold while both calls land in the same wall-clock second (#562)."""
    _write_mixed_state(cwd_to_tmp)
    mod = _import_tools()
    default = (await mod.handle_tool("mureo_state_get", {}))[0].text
    explicit_all = (await mod.handle_tool("mureo_state_get", {"action_log": "all"}))[
        0
    ].text
    assert default == explicit_all
    payload = json.loads(default)
    assert len(payload["action_log"]) == len(_MIXED_ACTION_LOG)
    assert "action_log_scope" not in payload
    assert "action_log_total" not in payload


async def test_state_get_action_log_pending_filters_correctly(cwd_to_tmp):
    """``pending`` keeps only entries with an OPEN observation_due — past-due
    and future-due — and drops entries with no observation_due AND entries a
    later rollback already closed."""
    _write_mixed_state(cwd_to_tmp)
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {"action_log": "pending"})
    payload = json.loads(result[0].text)
    assert payload["action_log_scope"] == "pending"
    assert payload["action_log_total"] == len(_MIXED_ACTION_LOG)
    kept = payload["action_log"]
    campaign_ids = {e.get("campaign_id") for e in kept}
    # c1 (past-due) and c2 (future) survive; c3's pause is closed by its
    # rollback, and the plain log entry / rollback entry have no observation_due.
    assert campaign_ids == {"c1", "c2"}
    assert all(e.get("observation_due") for e in kept)
    assert not any(e.get("rollback_of") is not None for e in kept)


async def test_state_get_action_log_none_omits(cwd_to_tmp):
    """``none`` omits the log entirely but still marks the scope + total so a
    reader knows the log was withheld, not empty."""
    _write_mixed_state(cwd_to_tmp)
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {"action_log": "none"})
    payload = json.loads(result[0].text)
    assert "action_log" not in payload
    assert payload["action_log_scope"] == "none"
    assert payload["action_log_total"] == len(_MIXED_ACTION_LOG)


@pytest.mark.parametrize("scope", ["pending", "none"])
async def test_state_get_rest_of_response_unchanged_when_filtered(
    cwd_to_tmp, frozen_clock, scope
):
    """Filtering the log must not touch anything else: platforms (incl.
    campaigns), reports, last_synced_at and server_now are identical.

    ``server_now`` is stamped per response, so the clock is frozen (#460
    seam) — otherwise this compares two wall-clock reads, not the filter's
    effect (#562)."""
    _write_mixed_state(cwd_to_tmp)
    mod = _import_tools()
    full = json.loads((await mod.handle_tool("mureo_state_get", {}))[0].text)
    filtered = json.loads(
        (await mod.handle_tool("mureo_state_get", {"action_log": scope}))[0].text
    )
    for key in ("version", "platforms", "campaigns", "reports", "last_synced_at"):
        assert filtered.get(key) == full.get(key)
    assert filtered["server_now"] == full["server_now"]


def test_state_get_schema_documents_action_log_scope() -> None:
    """The inputSchema exposes the enum, keeps the top-level closed, and the
    description documents the parameter and the subset marker."""
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_get")
    assert tool.inputSchema["additionalProperties"] is False
    prop = tool.inputSchema["properties"]["action_log"]
    assert prop["enum"] == ["all", "pending", "none"]
    assert "action_log_scope" in tool.description
    assert "pending" in tool.description


async def test_state_get_rejects_unknown_action_log_scope(cwd_to_tmp) -> None:
    """A value outside the enum reaching the handler directly (bypassing the
    server's schema validation) raises a clear ValueError, not a silent
    mis-scope."""
    _write_mixed_state(cwd_to_tmp)
    mod = _import_tools()
    with pytest.raises(ValueError, match="action_log must be one of"):
        await mod.handle_tool("mureo_state_get", {"action_log": "bogus"})


# ---------------------------------------------------------------------------
# mureo_state_get — pending closes on a later evaluation record (evaluation_of)
#
# ``mureo_outcome_evaluate`` is pure (writes nothing), so a past-due entry
# would otherwise stay pending forever — re-evaluated every day, the set
# growing without bound. An evaluation record (a later action_log entry
# tagged ``evaluation_of=<index>``) closes the observation, mirroring how
# ``rollback_of`` closes a reversed action.
# ---------------------------------------------------------------------------


def _write_state_with_action_log(root, action_log) -> None:
    state = {
        "version": "2",
        "platforms": {},
        "action_log": action_log,
    }
    (root / "STATE.json").write_text(json.dumps(state), encoding="utf-8")


async def test_state_get_pending_excludes_evaluation_closed(cwd_to_tmp) -> None:
    """A past-due entry whose observation was evaluated (a later entry carries
    ``evaluation_of`` pointing at it) leaves the pending set — otherwise it is
    re-evaluated forever."""
    _write_state_with_action_log(
        cwd_to_tmp,
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "action": "Increased budget +20%",
                "platform": "google_ads",
                "campaign_id": "c1",
                "observation_due": "2026-01-08",
                "metrics_at_action": {"cpa": 5000},
            },
            {
                "timestamp": "2026-01-09T00:00:00+00:00",
                "action": "Evaluated budget change: improved",
                "platform": "google_ads",
                "campaign_id": "c1",
                "evaluation_of": 0,
            },
        ],
    )
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {"action_log": "pending"})
    payload = json.loads(result[0].text)
    assert payload["action_log_scope"] == "pending"
    assert payload["action_log_total"] == 2
    # Index 0 is closed by index 1's evaluation_of; index 1 has no
    # observation_due of its own. Pending is therefore empty.
    assert payload["action_log"] == []


async def test_state_get_pending_entries_carry_their_full_log_index(
    cwd_to_tmp,
) -> None:
    """Each returned pending entry carries an ``index`` field — its position in
    the FULL log — so the agent can reference it in ``evaluation_of`` without
    ever loading the whole history."""
    _write_mixed_state(cwd_to_tmp)
    mod = _import_tools()
    result = await mod.handle_tool("mureo_state_get", {"action_log": "pending"})
    payload = json.loads(result[0].text)
    by_campaign = {e["campaign_id"]: e for e in payload["action_log"]}
    # c1 is at full-log index 0, c2 at index 1 (see _MIXED_ACTION_LOG).
    assert by_campaign["c1"]["index"] == 0
    assert by_campaign["c2"]["index"] == 1


async def test_action_log_append_round_trips_evaluation_of(cwd_to_tmp) -> None:
    """An evaluation record persists its ``evaluation_of`` and reads back."""
    _write_state_with_action_log(
        cwd_to_tmp,
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "action": "Increased budget +20%",
                "platform": "google_ads",
                "campaign_id": "c1",
                "observation_due": "2026-01-08",
            }
        ],
    )
    mod = _import_tools()
    await mod.handle_tool(
        "mureo_state_action_log_append",
        {
            "entry": {
                "action": "Evaluated budget change: regressed",
                "platform": "google_ads",
                "campaign_id": "c1",
                "evaluation_of": 0,
            }
        },
    )
    result = await mod.handle_tool("mureo_state_get", {})
    payload = json.loads(result[0].text)
    assert payload["action_log"][1]["evaluation_of"] == 0
    # And that entry now closes index 0's observation.
    pending = json.loads(
        (await mod.handle_tool("mureo_state_get", {"action_log": "pending"}))[0].text
    )
    assert pending["action_log"] == []


@pytest.mark.parametrize("field", ["evaluation_of", "rollback_of"])
async def test_action_log_append_rejects_out_of_range_index(cwd_to_tmp, field) -> None:
    """A behavioral-index field must point at a real entry — an out-of-range
    value would silently hide an open observation from the pending set."""
    _write_state_with_action_log(
        cwd_to_tmp,
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "action": "Increased budget +20%",
                "platform": "google_ads",
            }
        ],
    )
    mod = _import_tools()
    with pytest.raises(ValueError, match=f"{field}"):
        await mod.handle_tool(
            "mureo_state_action_log_append",
            {
                "entry": {
                    "action": "bad record",
                    "platform": "google_ads",
                    field: 99,
                }
            },
        )


@pytest.mark.parametrize("field", ["evaluation_of", "rollback_of"])
async def test_action_log_append_accepts_valid_index(cwd_to_tmp, field) -> None:
    """A valid in-range index is accepted."""
    _write_state_with_action_log(
        cwd_to_tmp,
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "action": "Increased budget +20%",
                "platform": "google_ads",
            }
        ],
    )
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_action_log_append",
        {"entry": {"action": "record", "platform": "google_ads", field: 0}},
    )
    payload = json.loads(result[0].text)
    assert payload["action_log"][1][field] == 0


def test_action_log_schema_accepts_evaluation_of() -> None:
    """``evaluation_of`` rides on the append schema (top-level
    ``additionalProperties: false`` would reject an undeclared key)."""
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_action_log_append")
    entry = tool.inputSchema["properties"]["entry"]
    assert "evaluation_of" in entry["properties"]


def test_state_get_description_documents_index_field() -> None:
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_get")
    assert "index" in tool.description


# ---------------------------------------------------------------------------
# mureo_state_display_set (#706)
# ---------------------------------------------------------------------------


async def test_display_set_persists_the_contract(cwd_to_tmp) -> None:
    """The five sections are written into STATE.json ``display`` and
    round-trip via a subsequent read."""
    initial = {"version": "2", "platforms": {}, "action_log": []}
    (cwd_to_tmp / "STATE.json").write_text(json.dumps(initial), encoding="utf-8")
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_display_set",
        {
            "nav_message": "CPA is over target — pause the two worst ad groups",
            "highlights": [{"tone": "bad", "text": "CPA 12% over target"}],
            "proposals": [{"title": "Pause two ad groups", "status": "proposed"}],
            "breakdown": {
                "campaigns": [
                    {"name": "Brand Search", "spend": 42000, "state": "worsening"}
                ]
            },
            "stated_values": [{"label": "CVR", "value": 0.021}],
        },
    )
    payload = json.loads(result[0].text)
    assert payload["display"]["highlights"] == [
        {"tone": "bad", "text": "CPA 12% over target"}
    ]

    result2 = await mod.handle_tool("mureo_state_get", {})
    payload2 = json.loads(result2[0].text)
    assert payload2["display"]["stated_values"] == [{"label": "CVR", "value": 0.021}]


async def test_display_set_refuses_prose_in_a_stated_value(cwd_to_tmp) -> None:
    """The handler surfaces the guard's refusal as a tool error — the
    dispatcher's schema pass cannot express "a number or a SHORT string"."""
    mod = _import_tools()
    with pytest.raises(ValueError, match="numeric column"):
        await mod.handle_tool(
            "mureo_state_display_set",
            {
                "stated_values": [
                    {"label": "CPA", "value": "CPA is 12% over target this month"}
                ]
            },
        )


async def test_display_set_with_no_section_clears_the_contract(cwd_to_tmp) -> None:
    """Nothing is required, and that is how a stale screen is taken down."""
    mod = _import_tools()
    await mod.handle_tool("mureo_state_display_set", {"nav_message": "stale"})
    result = await mod.handle_tool("mureo_state_display_set", {})
    assert "display" not in json.loads(result[0].text)


def test_display_set_schema_states_every_bound() -> None:
    """The schema layer rejects an over-long value BEFORE the handler runs,
    so the numbers have to be in the schema — and the REASON has to be in the
    description the model read before calling (#659 / #660)."""
    from mureo.core.display_contract import (
        DISPLAY_CONTRACT_RULE,
        HIGHLIGHT_TEXT_MAX_CHARS,
        HIGHLIGHT_TONES,
        HIGHLIGHTS_MAX_ITEMS,
        NAV_MESSAGE_MAX_CHARS,
        PROPOSAL_TITLE_MAX_CHARS,
        STATED_VALUE_LABEL_MAX_CHARS,
    )

    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_display_set")
    props = tool.inputSchema["properties"]
    assert props["nav_message"]["maxLength"] == NAV_MESSAGE_MAX_CHARS
    assert props["highlights"]["maxItems"] == HIGHLIGHTS_MAX_ITEMS
    highlight = props["highlights"]["items"]["properties"]
    assert highlight["tone"]["enum"] == list(HIGHLIGHT_TONES)
    assert highlight["text"]["maxLength"] == HIGHLIGHT_TEXT_MAX_CHARS
    proposal = props["proposals"]["items"]["properties"]
    assert proposal["title"]["maxLength"] == PROPOSAL_TITLE_MAX_CHARS
    stated = props["stated_values"]["items"]["properties"]
    assert stated["label"]["maxLength"] == STATED_VALUE_LABEL_MAX_CHARS
    # Nothing required: a call that states no section clears the contract.
    assert tool.inputSchema["required"] == []
    # …and the REASON rides on the tool description a model reads before it
    # composes anything, not only in the refusal it gets afterwards.
    assert DISPLAY_CONTRACT_RULE in tool.description


def test_display_set_schema_declares_both_breakdown_tables() -> None:
    """Both levels, with the same row shape — a second copy is how the two
    would start disagreeing about what a row is."""
    from mureo.core.display_contract import BREAKDOWN_STATES

    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_display_set")
    breakdown = tool.inputSchema["properties"]["breakdown"]
    assert set(breakdown["properties"]) == {"campaigns", "adgroups"}
    for level in ("campaigns", "adgroups"):
        row = breakdown["properties"][level]["items"]
        assert row["required"] == ["name"]
        assert row["properties"]["state"]["enum"] == list(BREAKDOWN_STATES)
        assert row["properties"]["spend"]["type"] == "number"


async def test_action_log_append_stores_the_display_line(cwd_to_tmp) -> None:
    mod = _import_tools()
    result = await mod.handle_tool(
        "mureo_state_action_log_append",
        {
            "entry": {
                "action": "google_ads_budget_update",
                "platform": "google_ads",
                "summary": "x" * 400,
                "display_title": "Raised the Brand budget",
                "display_summary": "Capped every afternoon; +20% daily.",
            }
        },
    )
    entry = json.loads(result[0].text)["action_log"][0]
    assert entry["display_title"] == "Raised the Brand budget"
    # It ADDS a rendering and replaces nothing.
    assert entry["summary"] == "x" * 400


async def test_action_log_append_refuses_an_overlong_display_line(cwd_to_tmp) -> None:
    mod = _import_tools()
    with pytest.raises(ValueError, match="display_title"):
        await mod.handle_tool(
            "mureo_state_action_log_append",
            {
                "entry": {
                    "action": "x",
                    "platform": "google_ads",
                    "display_title": "y" * 200,
                }
            },
        )


def test_action_log_schema_bounds_the_display_line() -> None:
    """The bound fires at the dispatcher, so it has to be in the schema."""
    from mureo.core.display_contract import (
        ACTION_LOG_DISPLAY_RULE,
        ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS,
        ACTION_LOG_DISPLAY_TITLE_MAX_CHARS,
    )

    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_action_log_append")
    entry = tool.inputSchema["properties"]["entry"]["properties"]
    assert entry["display_title"]["maxLength"] == ACTION_LOG_DISPLAY_TITLE_MAX_CHARS
    assert entry["display_summary"]["maxLength"] == ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS
    for field in ("display_title", "display_summary"):
        assert ACTION_LOG_DISPLAY_RULE in entry[field]["description"]
