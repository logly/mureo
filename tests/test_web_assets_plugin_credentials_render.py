"""Static-content guards for the plugin-credentials render fixes.

- #223: ``renderPluginCredentials`` is generation-guarded so two
  concurrent renders (the double ``renderAll()`` at init) cannot both
  append — the clear→await→append race that rendered every card twice.
- #224: declared fields pre-fill from the list payload's current state —
  non-secret values verbatim, secrets via a ``configured`` flag only.

No JS test harness ships in the repo, so the contract is pinned by
grepping the bundled ``dashboard.js``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
def test_render_plugin_credentials_is_generation_guarded() -> None:
    """#223: a module-level generation counter (declared, incremented, and
    compared after the await) drops a stale render so concurrent calls
    cannot double-append."""
    js = _read("dashboard.js")
    assert js.count("pluginRenderSeq") >= 3


@pytest.mark.unit
def test_credential_input_prefills_current_values() -> None:
    """#224: ``appendCredentialInput`` pre-fills a non-secret field from
    ``field.value`` and keys the secret placeholder off ``field.configured``
    (the secret value itself is never shipped)."""
    js = _read("dashboard.js")
    assert "field.value" in js
    assert "field.configured" in js


@pytest.mark.unit
def test_oauth_target_status_reflects_configured() -> None:
    """#338: the OAuth target status row shows "Configured ✓" when the token
    is already stored, instead of always prompting to Authenticate."""
    js = _read("dashboard.js")
    assert "dashboard.plugin_oauth_target_configured" in js
    # Branch is keyed off the injected field.configured state.
    assert "field.configured" in js
    assert "appendOAuthTargetStatus" in js


@pytest.mark.unit
def test_account_picker_rendered_for_picker_provider() -> None:
    """#336: a provider whose oauth block carries accounts_field +
    has_account_lister renders a post-auth account picker (Load → radios →
    Save) instead of a free-text input for that field."""
    js = _read("dashboard.js")
    assert "appendAccountPicker" in js
    assert "oauth.accounts_field" in js
    assert "oauth.has_account_lister" in js
    # The picker fetches the accounts endpoint and persists only the id.
    assert "/accounts" in js
    assert "loadPluginAccounts" in js
    assert "savePluginAccount" in js


@pytest.mark.unit
def test_picker_radios_excluded_from_form_values() -> None:
    """#336: the OAuth card's gatherFormValues must skip picker radios so
    they never leak into the Authenticate-is-save payload — the chosen
    account rides on the hidden input named after the field key."""
    js = _read("dashboard.js")
    assert 'input.type === "radio"' in js


@pytest.mark.unit
def test_oauth_success_refreshes_section() -> None:
    """#336/#338: a successful Authenticate re-renders the section so the
    target shows configured and the picker's Load becomes usable."""
    js = _read("dashboard.js")
    # The success branch of the OAuth poller triggers a re-render.
    assert js.count("renderPluginCredentials()") >= 1
