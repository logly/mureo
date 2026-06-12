"""Static-content guards for the #222 multi-account MCP suppression.

When the status snapshot carries ``multi_account_auth = true`` (a
multi-account backend), the configure UI must not surface the bare
``mureo`` MCP registration — neither the wizard's basic-setup pill nor the
dashboard's basic-setup row — because that entry is harmful there
(per-client ``mureo-<slug>`` entries are the correct wiring). No JS test
harness ships in the repo, so the contract is pinned by grepping the
bundled assets; a refactor that drops the gate flips a test red here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
def test_wizard_gates_basic_mcp_on_multi_account() -> None:
    """``wizard.js`` consults ``multi_account_auth`` in both the completion
    derivation (so a suppressed MCP part is not required for completion)
    and the basic-step body (so the mureo_mcp pill is not rendered)."""
    js = _read("wizard.js")
    assert js.count("multi_account_auth") >= 2


@pytest.mark.unit
def test_dashboard_gates_basic_mcp_on_multi_account() -> None:
    """``dashboard.js`` skips the mureo_mcp basic-setup row when the status
    snapshot declares ``multi_account_auth``."""
    js = _read("dashboard.js")
    assert "multi_account_auth" in js
