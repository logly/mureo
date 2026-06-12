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
