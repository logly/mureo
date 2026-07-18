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


@pytest.mark.unit
def test_auth_wizard_hides_ga4_slot_under_multi_account() -> None:
    """#442: ``auth_wizards.js`` gates the GA4 auth slot on the multi-account
    flag, and ``wizard.js`` hydrates it from the status snapshot -- so under a
    multi-account backend the single-shared-SA GA4 slot is not offered."""
    assert "state.multiAccountAuth" in _read("auth_wizards.js")
    assert "STATE.multiAccountAuth" in _read("wizard.js")


@pytest.mark.unit
def test_wizard_removes_ga4_entirely_under_multi_account() -> None:
    """#442 (full removal): under a multi-account backend GA4 must not appear
    anywhere in Setup, not just the auth slot. The wizard forces the ga4
    platform off on hydration (so every step-relevance check drops it) and the
    platform-selection step skips its checkbox."""
    wizard = _read("wizard.js")
    # Forced off on hydration -> hasAuthQueued / hasOfficialProviderQueued /
    # the summary all see ga4 = false.
    assert "STATE.platforms.ga4 = false" in wizard
    # Selection checkbox is not rendered (cannot be re-enabled by the user).
    assert 'p === "ga4" && STATE.multiAccountAuth' in wizard


@pytest.mark.unit
def test_providers_install_hides_ga4_under_multi_account() -> None:
    """#442: the provider-install ("official MCP setup instructions") step also
    drops the GA4 entry under a multi-account backend."""
    aw = _read("auth_wizards.js")
    assert 'platform === "ga4" && state.platforms.ga4 && !state.multiAccountAuth' in aw
