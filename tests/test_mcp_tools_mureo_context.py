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


@pytest.fixture
def cwd_to_tmp(tmp_path, monkeypatch):
    """Run each test with cwd = tmp_path so STRATEGY.md/STATE.json land
    inside the sandbox by default."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _import_tools():
    from mureo.mcp import tools_mureo_context

    return tools_mureo_context


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def test_tools_module_exports_five_tools() -> None:
    mod = _import_tools()
    assert len(mod.TOOLS) == 5
    expected = {
        "mureo_strategy_get",
        "mureo_strategy_set",
        "mureo_state_get",
        "mureo_state_action_log_append",
        "mureo_state_upsert_campaign",
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
    }
    result = await mod.handle_tool(
        "mureo_state_upsert_campaign", {"campaign": campaign}
    )
    payload = json.loads(result[0].text)
    # Either v1 (root campaigns) or v2 (platforms) shape is acceptable
    # depending on how the underlying upsert helper reconciles.
    flat = list(payload.get("campaigns", []))
    plats = payload.get("platforms") or {}
    found_in_platforms = any(
        c["campaign_id"] == "camp_xyz"
        for plat in plats.values()
        for c in plat.get("campaigns", [])
    )
    found_in_flat = any(c["campaign_id"] == "camp_xyz" for c in flat)
    assert found_in_flat or found_in_platforms


async def test_upsert_campaign_updates_existing(cwd_to_tmp) -> None:
    """Upserting the same campaign_id replaces the prior snapshot in place
    — the count stays at 1 and changed fields propagate."""
    mod = _import_tools()
    initial_campaign = {
        "campaign_id": "camp_xyz",
        "campaign_name": "Generic",
        "status": "ENABLED",
        "daily_budget": 5000,
    }
    await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": initial_campaign})

    updated = {
        "campaign_id": "camp_xyz",
        "campaign_name": "Generic",
        "status": "PAUSED",
        "daily_budget": 8000,
    }
    result = await mod.handle_tool("mureo_state_upsert_campaign", {"campaign": updated})
    payload = json.loads(result[0].text)

    flat = list(payload.get("campaigns", []))
    plats = payload.get("platforms") or {}
    all_snaps = list(flat) + [
        c for plat in plats.values() for c in plat.get("campaigns", [])
    ]
    matches = [c for c in all_snaps if c["campaign_id"] == "camp_xyz"]
    assert len(matches) == 1, f"expected exactly one snapshot, got {len(matches)}"
    assert matches[0]["status"] == "PAUSED"
    assert matches[0]["daily_budget"] == 8000


# ---------------------------------------------------------------------------
# Path traversal gate (security)
# ---------------------------------------------------------------------------


async def test_path_argument_refuses_traversal(cwd_to_tmp) -> None:
    """Custom ``path`` outside cwd is rejected — symmetric with rollback's
    ``_resolve_state_file`` guard. A prompt-injected agent must not be
    able to point mureo at an attacker-crafted file elsewhere on disk."""
    mod = _import_tools()
    with pytest.raises(ValueError, match="Refusing to read/write outside cwd"):
        await mod.handle_tool("mureo_strategy_get", {"path": "/etc/passwd"})
