"""Sanity tests for the Claude Cowork plugin manifests.

These guard three classes of regression that would only surface when a
non-engineer tries to install the plugin:
  - JSON syntax errors (trailing commas, etc.) in any of the three
    manifest files Cowork reads at install time
  - Version drift between ``pyproject.toml`` and the plugin manifest
  - Drift between the canonical ``skills/`` tree and the bundled copy
    under ``mureo/_data/skills/`` that ships in the PyPI wheel

Failing one of these in CI means the plugin is broken before the user
even sees it. They run cheaply (file I/O only).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_json(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


# ---------------------------------------------------------------------------
# .claude-plugin/plugin.json
# ---------------------------------------------------------------------------


def test_plugin_json_is_valid_and_has_required_keys() -> None:
    plugin = _load_json(".claude-plugin/plugin.json")
    assert plugin["name"] == "mureo"
    assert "version" in plugin
    assert "description" in plugin


def test_plugin_version_matches_pyproject() -> None:
    """Version in plugin.json must match pyproject.toml — when mureo
    bumps to 0.8.0 we must remember to bump here too. Catching the
    drift in CI saves us from shipping a stale plugin manifest."""
    plugin = _load_json(".claude-plugin/plugin.json")
    assert plugin["version"] == _pyproject_version(), (
        f"plugin.json version ({plugin['version']}) != pyproject.toml "
        f"({_pyproject_version()}). Bump both."
    )


# ---------------------------------------------------------------------------
# .claude-plugin/marketplace.json
# ---------------------------------------------------------------------------


def test_marketplace_json_is_valid() -> None:
    market = _load_json(".claude-plugin/marketplace.json")
    assert market["name"] == "mureo"
    assert isinstance(market["plugins"], list)
    assert len(market["plugins"]) >= 1
    mureo_plugin = next(p for p in market["plugins"] if p["name"] == "mureo")
    assert mureo_plugin["source"] == "."
    assert "description" in mureo_plugin


# ---------------------------------------------------------------------------
# .mcp.json (project-scoped MCP for Claude Code + Cowork plugin runtime)
# ---------------------------------------------------------------------------


def test_mcp_json_declares_mureo_server() -> None:
    mcp = _load_json(".mcp.json")
    assert "mcpServers" in mcp
    assert "mureo" in mcp["mcpServers"]


def test_mcp_json_command_gates_missing_wrapper() -> None:
    """If a contributor opens the repo in Claude Code without having
    run ``mureo install-desktop``, the wrapper script does not exist.
    The MCP entry must fail soft (exit 0 with a friendly message)
    rather than spam the agent with launch errors every session."""
    mcp = _load_json(".mcp.json")
    server = mcp["mcpServers"]["mureo"]
    # Either ``sh`` or ``bash`` is acceptable — what matters is that the
    # command is a shell that can run the existence-check / soft-fail
    # script body, not the specific shell binary chosen.
    assert server["command"] in {"sh", "bash"}, (
        "Expected a shell gate so missing wrapper exits cleanly. "
        "See HIGH finding from Phase 3 review."
    )
    args = server["args"]
    body = " ".join(args)
    # Either ``test -x`` or ``[ -x ... ]`` is acceptable — both are
    # POSIX-shell idioms for "executable check, fail soft otherwise".
    assert ("test -x" in body) or (
        "[ -x" in body
    ), "Expected an executable-existence guard before invoking the wrapper"
    assert "mureo-mcp-wrapper.sh" in body
    assert "exit 0" in body, "Soft-fail path should exit 0, not crash"


# ---------------------------------------------------------------------------
# Skill-tree sync: skills/ ↔ mureo/_data/skills/
# ---------------------------------------------------------------------------


_CANONICAL_SKILLS = REPO_ROOT / "skills"
_PACKAGED_SKILLS = REPO_ROOT / "mureo" / "_data" / "skills"


def _packaged_names() -> set[str]:
    return {p.name for p in _PACKAGED_SKILLS.iterdir() if p.is_dir()}


def test_packaged_skills_match_canonical_byte_for_byte() -> None:
    """``mureo/_data/skills/`` is what PyPI users get; ``skills/`` is
    the canonical source. They must stay byte-identical for every skill
    that the package ships, otherwise the docs on GitHub diverge from
    what installed users see in their editors."""
    drift: list[str] = []
    for packaged_dir in sorted(p for p in _PACKAGED_SKILLS.iterdir() if p.is_dir()):
        skill = packaged_dir.name
        canonical_dir = _CANONICAL_SKILLS / skill
        if not canonical_dir.exists():
            drift.append(f"{skill}: missing in canonical skills/")
            continue
        for packaged_file in packaged_dir.rglob("*"):
            if packaged_file.is_dir():
                continue
            rel = packaged_file.relative_to(packaged_dir)
            canonical_file = canonical_dir / rel
            if not canonical_file.exists():
                drift.append(f"{skill}/{rel}: missing in canonical")
                continue
            if packaged_file.read_bytes() != canonical_file.read_bytes():
                drift.append(f"{skill}/{rel}: contents differ")
    assert not drift, "Drift between skills/ and mureo/_data/skills/:\n" + "\n".join(
        f"  - {d}" for d in drift
    )


def test_canonical_skills_not_unexpectedly_richer() -> None:
    """Every skill in ``skills/`` must also be packaged unless it's an
    explicit opt-out (currently: ``mureo-pro-diagnosis``). Forgetting to
    sync a new skill into ``mureo/_data/skills/`` would silently break
    the PyPI install."""
    intentional_canonical_only = {"mureo-pro-diagnosis"}
    canonical = {
        p.name for p in _CANONICAL_SKILLS.iterdir() if p.is_dir()
    } - intentional_canonical_only
    packaged = _packaged_names()
    missing = canonical - packaged
    assert not missing, (
        f"Skills in skills/ but not in mureo/_data/skills/: {sorted(missing)}. "
        "Either add them to the packaged copy or extend "
        "intentional_canonical_only in this test."
    )
