"""Static-content guards for the stale-workflow-skills note (#728).

``tests/js/dashboard_setup_stale_skills.test.js`` drives the rendering, but
its ``MUREO.t`` answers with the key it was handed — by design, so those
assertions never argue about wording. The wording itself lives here, the
convention ``test_web_assets_meta_reauth.py`` set: the i18n keys exist in
BOTH locales, they interpolate the versions the row promises to name, and
the fix command the note ends on is one a shell would accept.

The command matters more than a note usually does: a deployed skill set that
is merely OLD looks identical to a current one from the outside, so the note
is the only thing telling the operator that ``pip install -U mureo`` did not
finish the job — and the wrong command there strands them.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _load_i18n() -> dict[str, Any]:
    ref = resources.files("mureo") / "_data" / "web" / "i18n.json"
    with resources.as_file(ref) as path:
        return json.loads(path.read_text(encoding="utf-8"))


# Both notes the stale state can show: one that can name the version on disk
# and one for copies too old to record one. Each must exist in BOTH locales.
_NEW_KEYS = (
    "dashboard.skills_stale_note",
    "dashboard.skills_stale_note_unknown",
)


@pytest.mark.unit
class TestStaleSkillsI18n:
    @pytest.mark.parametrize("locale", ["en", "ja"])
    @pytest.mark.parametrize("key", _NEW_KEYS)
    def test_key_present_and_translated(self, locale: str, key: str) -> None:
        block = _load_i18n()[locale]
        assert key in block, f"{key} missing from i18n.json '{locale}'"
        value = block[key]
        assert isinstance(value, str)
        assert value.strip() != ""
        assert value != key  # not an untranslated placeholder

    @pytest.mark.parametrize("locale", ["en", "ja"])
    def test_note_names_both_versions(self, locale: str) -> None:
        """The whole point is the comparison, so neither side may go missing
        in translation."""
        value = _load_i18n()[locale]["dashboard.skills_stale_note"]
        assert "{installed}" in value
        assert "{expected}" in value

    @pytest.mark.parametrize("locale", ["en", "ja"])
    def test_unknown_variant_names_the_shipped_version(self, locale: str) -> None:
        value = _load_i18n()[locale]["dashboard.skills_stale_note_unknown"]
        assert "{expected}" in value
        # Nothing to interpolate for the version that is not on disk.
        assert "{installed}" not in value

    def test_japanese_is_not_the_english_string(self) -> None:
        data = _load_i18n()
        for key in _NEW_KEYS:
            assert data["ja"][key] != data["en"][key]


@pytest.mark.unit
class TestStaleSkillsRow:
    def test_row_reads_the_state_from_the_status_payload(self) -> None:
        js = _read("dashboard_setup.js")
        assert 'parts.skills_state === "stale"' in js
        assert "parts.skills_installed_version" in js
        assert "parts.skills_expected_version" in js

    @pytest.mark.parametrize(
        "command",
        [
            "mureo setup claude-code --skip-auth",
            "mureo setup codex --skip-auth",
        ],
    )
    def test_fix_command_is_one_the_cli_accepts(self, command: str) -> None:
        """``mureo setup <host>`` exists for claude-code and codex; there is
        no ``claude-desktop`` subcommand, which is why Desktop is pointed at
        the claude-code one (it reads the same ~/.claude/skills)."""
        from mureo.cli.setup_cmd import setup_app

        assert command in _read("dashboard_setup.js")
        host = command.split()[2]
        names = {c.name for c in setup_app.registered_commands}
        assert host in names

    def test_note_carries_the_command_in_a_code_element(self) -> None:
        js = _read("dashboard_setup.js")
        assert 'document.createElement("code")' in js

    def test_note_has_a_style_hook_of_its_own(self) -> None:
        assert "dashboard-skills-stale-note" in _read("dashboard_setup.js")
        assert ".dashboard-skills-stale-note code" in _read("app.css")
