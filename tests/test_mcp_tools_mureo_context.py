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

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    """Reset the resolver cache before and after every test in this file
    so the workspace-aware ``_resolve_path`` rebuilds a
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


def test_tools_module_exports_six_tools() -> None:
    mod = _import_tools()
    assert len(mod.TOOLS) == 6
    expected = {
        "mureo_strategy_get",
        "mureo_strategy_set",
        "mureo_state_get",
        "mureo_state_action_log_append",
        "mureo_state_upsert_campaign",
        "mureo_state_report_set",
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
    md = "# Strategy\n\n" "## Persona\n30s\n\n" "## Quarterly Notes\nlaunch in Q3\n"
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
    """The tool's inputSchema constrains ``report`` to the three known kinds
    so the dispatcher's schema pass (#277) rejects anything else."""
    mod = _import_tools()
    tool = next(t for t in mod.TOOLS if t.name == "mureo_state_report_set")
    props = tool.inputSchema["properties"]
    assert props["report"]["enum"] == ["daily", "weekly", "goal"]
    assert props["summary"]["type"] == "object"
    assert set(tool.inputSchema["required"]) == {"report", "summary"}


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
