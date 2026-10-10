"""``scripts/check_english_only.py`` keeps prose in shipped files English (#810).

The repository is public and English-only. Japanese is allowed in two
places: the ``*.ja.md`` translations, and string literals that are
Japanese data (ad-text samples, column headers a parser matches on,
character classes). These tests pin the classifier on small synthetic
inputs so that a change to it cannot quietly start passing prose or
start failing data.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = REPO_ROOT / "scripts" / "check_english_only.py"

# "Japanese" written as escapes so this file carries no Japanese of its own.
JA = "\u65e5\u672c\u8a9e"
KANA = "\u3072\u3089\u304c\u306a \u30ab\u30bf\u30ab\u30ca \uff76\uff80\uff76\uff85"


def _load_checker() -> object:
    spec = importlib.util.spec_from_file_location("_check_english_only", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_check_english_only"] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()
scan_python = CHECKER.scan_python  # type: ignore[attr-defined]
scan_markdown = CHECKER.scan_markdown  # type: ignore[attr-defined]
scan_file = CHECKER.scan_file  # type: ignore[attr-defined]
is_scanned = CHECKER.is_scanned  # type: ignore[attr-defined]


def _lines(hits: list[tuple[int, str]]) -> list[int]:
    return [line for line, _ in hits]


class TestPython:
    def test_comment_is_flagged(self) -> None:
        source = f"x = 1\n# {JA}\ny = 2  # {JA}\n"
        assert _lines(scan_python(source)) == [2, 3]

    def test_module_docstring_is_flagged(self) -> None:
        source = f'"""Summary.\n\n{JA}\n"""\n\nx = 1\n'
        assert _lines(scan_python(source)) == [3]

    def test_function_and_class_docstrings_are_flagged(self) -> None:
        source = (
            "class A:\n"
            f'    """{JA}"""\n'
            "\n"
            "    def f(self) -> None:\n"
            f'        """{JA}."""\n'
            "\n"
            "    async def g(self) -> None:\n"
            f'        """{JA}."""\n'
        )
        assert _lines(scan_python(source)) == [2, 5, 8]

    def test_string_literal_is_allowed(self) -> None:
        source = (
            f'HEADERS = ("{JA}", "{KANA}")\n'
            "\n"
            "def f() -> str:\n"
            '    """English docstring."""\n'
            f'    return "{JA}"\n'
        )
        assert scan_python(source) == []

    def test_a_string_that_is_not_the_first_statement_is_allowed(self) -> None:
        source = f'def f() -> None:\n    x = 1\n    "{JA}"\n'
        assert scan_python(source) == []

    def test_halfwidth_katakana_and_kana_are_flagged(self) -> None:
        source = f"# {KANA}\n"
        assert _lines(scan_python(source)) == [1]

    def test_english_source_is_clean(self) -> None:
        source = '"""Doc."""\n\n# comment\nx = "text"  # trailing\n'
        assert scan_python(source) == []


class TestMarkdown:
    def test_prose_line_is_flagged(self) -> None:
        text = f"# Title\n\n{JA}\n"
        assert _lines(scan_markdown(text)) == [3]

    def test_fenced_block_is_allowed(self) -> None:
        text = f"Intro\n\n```text\n{JA}\n```\n\n~~~\n{JA}\n~~~\n"
        assert scan_markdown(text) == []

    def test_line_after_a_closed_fence_is_flagged(self) -> None:
        text = f"```\n{JA}\n```\n{JA}\n"
        assert _lines(scan_markdown(text)) == [4]

    def test_indented_fence_inside_a_list_is_allowed(self) -> None:
        text = f"1. Step\n   ```\n   {JA}\n   ```\n"
        assert scan_markdown(text) == []

    def test_ja_literal_marker_is_allowed(self) -> None:
        text = f'Match the column "{JA}". <!-- ja-literal -->\n{JA}\n'
        assert _lines(scan_markdown(text)) == [2]

    def test_marker_must_end_the_line(self) -> None:
        text = f"<!-- ja-literal --> {JA}\n"
        assert _lines(scan_markdown(text)) == [1]


class TestSkillFrontmatter:
    """Only ``description:`` in a SKILL.md frontmatter may carry Japanese (#396)."""

    SKILL = "skills/example/SKILL.md"

    def test_description_with_japanese_passes(self) -> None:
        text = f'---\nname: example\ndescription: "Run it ({JA})."\n---\n\nBody.\n'
        assert scan_file(self.SKILL, text) == []

    def test_description_continuation_lines_pass(self) -> None:
        text = f"---\nname: example\ndescription: >\n  Run it.\n  {JA}\n---\n"
        assert scan_file(self.SKILL, text) == []

    def test_japanese_name_fails(self) -> None:
        text = f'---\nname: {JA}\ndescription: "Run it."\n---\n'
        assert _lines(scan_file(self.SKILL, text)) == [2]

    def test_key_after_description_fails(self) -> None:
        text = f'---\ndescription: "{JA}"\nname: {JA}\n---\n'
        assert _lines(scan_file(self.SKILL, text)) == [3]

    def test_japanese_in_body_fails(self) -> None:
        text = f'---\ndescription: "{JA}"\n---\n\n{JA}\ndescription: {JA}\n'
        assert _lines(scan_file(self.SKILL, text)) == [5, 6]

    def test_description_in_another_markdown_file_fails(self) -> None:
        text = f'---\ndescription: "{JA}"\n---\n'
        assert _lines(scan_file("docs/example.md", text)) == [2]
        assert _lines(scan_file("skills/example/NOTES.md", text)) == [2]


class TestWebComments:
    def test_css_comment_is_flagged(self) -> None:
        text = f"a {{\n  color: red; /* {JA} */\n}}\n/* ok\n   {JA}\n*/\n"
        assert _lines(scan_file("mureo/_data/web/app.css", text)) == [2, 5]

    def test_css_outside_comments_is_allowed(self) -> None:
        text = f'a::after {{ content: "{JA}"; }}\n/* English */\n'
        assert scan_file("mureo/_data/web/app.css", text) == []

    def test_html_comment_is_flagged(self) -> None:
        text = f"<div>\n  <!-- one\n       {JA} -->\n</div>\n"
        assert _lines(scan_file("mureo/_data/web/app.html", text)) == [3]

    def test_html_text_is_allowed(self) -> None:
        text = f'<button data-lang="ja">{JA}</button>\n<!-- English -->\n'
        assert scan_file("mureo/_data/web/app.html", text) == []


class TestFileSet:
    @pytest.mark.parametrize(
        "path",
        [
            "mureo/google_ads/client.py",
            "tests/test_x.py",
            "scripts/check_english_only.py",
            "README.md",
            "CHANGELOG.md",
            "docs/byod.md",
            "docs/sub/deep.md",
            "skills/learn/SKILL.md",
            "mureo/_data/skills/learn/SKILL.md",
            "mureo/_data/web/app.css",
            "mureo/_data/web/app.html",
        ],
    )
    def test_shipped_files_are_scanned(self, path: str) -> None:
        assert is_scanned(path)

    @pytest.mark.parametrize(
        "path",
        [
            "README.ja.md",
            "docs/byod.ja.md",
            "docs/sub/deep.ja.md",
            "mureo/_data/web/app.js",
            "pyproject.toml",
            "other/notes.md",
            "other/site.css",
        ],
    )
    def test_other_files_are_not_scanned(self, path: str) -> None:
        assert not is_scanned(path)


class TestCommandLine:
    def test_repository_is_clean(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_list_prints_the_scanned_set(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), "--list"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        listed = result.stdout.splitlines()
        assert "CHANGELOG.md" in listed
        assert "scripts/check_english_only.py" in listed
        assert "README.ja.md" not in listed

    def test_hits_are_reported_with_path_and_line(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "a.md").write_text(f"ok\n{JA}\n", encoding="utf-8")
        (tmp_path / "docs" / "a.ja.md").write_text(f"{JA}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), "--root", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert result.stdout.splitlines() == [f"docs/a.md:2: {JA}"]
