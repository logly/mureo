"""Static-content guards for the extension dashboard-card renderer.

Pins the shape of ``extensions.js`` so a refactor that drops the card
injection path (or widens the client-side group allowlist) flips a
test red before an operator notices the regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
def test_extensions_js_declares_card_group_allowlist() -> None:
    js = _read("extensions.js")
    # Mirrors BUILTIN_CARD_GROUPS in mureo/web/extensions.py — widening
    # one side without the other is a bug this assertion surfaces (#425
    # added "reports").
    assert 'const CARD_GROUPS = ["advanced", "reports"];' in js


@pytest.mark.unit
def test_extensions_js_card_group_allowlist_matches_python() -> None:
    """The client allowlist must equal ``BUILTIN_CARD_GROUPS`` exactly — a
    group accepted by the Python constructor but missing here would let a card
    validate on the server and then silently never render (#425)."""
    import re

    from mureo.web.extensions import BUILTIN_CARD_GROUPS

    js = _read("extensions.js")
    match = re.search(r"const CARD_GROUPS = (\[[^\]]*\]);", js)
    assert match is not None, "CARD_GROUPS declaration not found"
    js_groups = re.findall(r'"([^"]+)"', match.group(1))
    assert tuple(js_groups) == BUILTIN_CARD_GROUPS


@pytest.mark.unit
def test_extensions_js_renders_cards_for_every_extension() -> None:
    js = _read("extensions.js")
    assert "function _renderCards(" in js
    # Cards must render for the FULL discovery set — headless (viewless)
    # extensions may contribute cards too.
    assert "_allExtensions.forEach(_renderCards);" in js
    assert "dashboard_cards" in js


@pytest.mark.unit
def test_extensions_js_card_injection_is_idempotent_and_attributed() -> None:
    js = _read("extensions.js")
    # Deterministic element id guards double-injection across init() calls.
    assert '"ext-card-"' in js
    # Owner attribute lets support/debugging attribute a card to its plugin.
    assert "data-ext-card-owner" in js
