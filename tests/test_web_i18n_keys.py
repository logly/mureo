"""i18n key-presence guard for the Desktop Connectors instruction note.

A remote MCP (hosted_http, e.g. meta-ads-official) cannot be wired into
Claude Desktop via the config file: Desktop rejects the native http
shape and the mcp-remote bridge fails on Meta's no-DCR OAuth server. The
dashboard surfaces a one-time instruction (key
``dashboard.provider_desktop_connectors_note``) telling the user to add
it via Settings → Connectors. There is NO JS test harness in the repo,
so the EN/JA parity of the key is asserted here against the bundled
``mureo/_data/web/i18n.json`` content directly. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import pytest

_NEW_KEY = "dashboard.provider_desktop_connectors_note"
# Existing key — present today; used as a structural sanity anchor so a
# failure clearly isolates the NEW key rather than a path/shape problem.
_EXISTING_KEY = "dashboard.provider_hosted_oauth_note"


def _load_i18n() -> dict[str, Any]:
    ref = resources.files("mureo") / "_data" / "web" / "i18n.json"
    with resources.as_file(ref) as path:
        return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.unit
class TestI18nNodeNoteKeyParity:
    def test_i18n_json_has_en_and_ja_blocks(self) -> None:
        """Structural anchor: the bundled i18n has both locale blocks and
        the pre-existing hosted-oauth note (isolates the new-key failure)."""
        data = _load_i18n()
        assert "en" in data and isinstance(data["en"], dict)
        assert "ja" in data and isinstance(data["ja"], dict)
        assert _EXISTING_KEY in data["en"]
        assert _EXISTING_KEY in data["ja"]

    def test_node_note_present_in_english(self) -> None:
        """RED: ``dashboard.provider_desktop_node_note`` not yet in EN."""
        data = _load_i18n()
        en = data["en"]
        assert _NEW_KEY in en, f"{_NEW_KEY} missing from i18n.json 'en'"
        value = en[_NEW_KEY]
        assert isinstance(value, str)
        assert value.strip() != ""
        assert value != _NEW_KEY  # not an untranslated placeholder

    def test_node_note_present_in_japanese(self) -> None:
        """RED: ``dashboard.provider_desktop_node_note`` not yet in JA."""
        data = _load_i18n()
        ja = data["ja"]
        assert _NEW_KEY in ja, f"{_NEW_KEY} missing from i18n.json 'ja'"
        value = ja[_NEW_KEY]
        assert isinstance(value, str)
        assert value.strip() != ""
        assert value != _NEW_KEY

    def test_node_note_en_and_ja_are_distinct_translations(self) -> None:
        """The JA value must not be a copy of the EN value (real
        localization, mirrors the existing oauth-note convention)."""
        data = _load_i18n()
        assert data["en"][_NEW_KEY] != data["ja"][_NEW_KEY]
