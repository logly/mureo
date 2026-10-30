"""``scripts/check_comment_provenance.py`` keeps provenance out of shipped text.

Comments, docstrings, docs and CHANGELOG entries say why the code has its
shape, never how the change came about. These tests pin the patterns and
the scanned set on small synthetic inputs. Every offending phrase is built
from fragments, so this file carries no literal hit of its own.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from tests._script_loader import clean_env, load_script, run_script

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_NAME = "check_comment_provenance"
CHECKER = load_script(_NAME)
scan_python = CHECKER.scan_python
scan_markdown = CHECKER.scan_markdown
scan_comments = CHECKER.scan_comments
scan_file = CHECKER.scan_file
is_scanned = CHECKER.is_scanned
is_provenance = CHECKER.is_provenance

# One phrase per pattern, keyed by the pattern's name, each split so no
# line here matches.
FAMILIES = {
    "ROLE_ACTION": "the ow" + "ner asked for a wider column",
    "WORKFLOW_ROLE": "so th" + "e revi" + "ewer cannot drop it",
    "REVIEW_FINDING": "this was a revie" + "w finding",
    "REVIEW_PASS": "the captur" + "e review caught it",
    "ROUND_REVIEW": "the roun" + "d-2 review asked for it",
    "REVIEW_VERB": "the revie" + "w insisted on a cap",
    "DESIGN_DOC": "see the desig" + "n doc, section 3",
    "ACCEPTANCE_CRITERIA": "per the acceptanc" + "e criteria L131",
    "ROLE_PASSIVE": "approved b" + "y the maintainer",
    "WORKFLOW_PHASE": "tests for the RE" + "D phase",
    "TDD_CYCLE": "TDD: RE" + "D -> GREEN -> IMPROVE",
    "IMPL" + "EMENTER": "a future impl" + "ementer may add it",
    "CONVERSATION": "as discu" + "ssed, the cap is 64 KiB",
    "WERE_ASKED": "we were as" + "ked to keep it",
    "PER_SOURCE": "pe" + "r the spec, the key is optional",
    "HANDOFF_DOC": "see the HAND" + "OFF for the design",
    "PLANNER_HANDOFF": "see plann" + "er handoff",
    "HAND" + "OVER": "noted in the hand" + "over",
    "PLAN_LABEL": "subtask P" + "1-05",
    "EXECUTIVE": "the C" + "EO",
}

# Product text that shares words with the patterns.
CLEAN = (
    "The OAuth handoff returns the code to the wizard.",
    "the operator asked for the section to be collapsed",
    "The planner refuses an unregistered operation.",
    "returns the planner's verdict on reversing it",
    "the rollback planner's report-only vocabulary",
    "Fixed in #731; see PR #742.",
)


def _lines(hits: list[tuple[int, str]]) -> list[int]:
    return [line for line, _ in hits]


class TestPatterns:
    @pytest.mark.parametrize(("name", "phrase"), FAMILIES.items(), ids=FAMILIES)
    def test_each_pattern_matches_its_phrase(self, name: str, phrase: str) -> None:
        assert getattr(CHECKER, name).search(phrase)
        assert is_provenance(phrase)

    def test_every_pattern_has_a_phrase(self) -> None:
        assert {getattr(CHECKER, name) for name in FAMILIES} == set(CHECKER.PATTERNS)

    def test_role_with_a_decision_noun_is_a_hit(self) -> None:
        assert is_provenance("C" + "TO decision: keep the mixin out")

    @pytest.mark.parametrize("phrase", CLEAN)
    def test_product_text_is_clean(self, phrase: str) -> None:
        assert not is_provenance(phrase)

    def test_handoff_doc_is_case_sensitive(self) -> None:
        assert not is_provenance("an OAuth hand" + "off")
        assert is_provenance("the HAND" + "OFF says so")

    def test_executive_title_is_case_sensitive(self) -> None:
        assert not is_provenance("a c" + "to-style toggle")

    def test_hyphenated_phase_is_a_hit(self) -> None:
        assert CHECKER.WORKFLOW_PHASE.search("a RE" + "D-phase import")
        assert CHECKER.WORKFLOW_PHASE.search("the gree" + "n-phase change")

    @pytest.mark.parametrize("arrow", ["->", "\u2192", "=>"])
    def test_tdd_cycle_takes_any_arrow(self, arrow: str) -> None:
        assert CHECKER.TDD_CYCLE.search("RE" + f"D {arrow} GREEN")

    def test_tdd_cycle_is_case_sensitive(self) -> None:
        assert not is_provenance("a re" + "d -> green gradient")

    @pytest.mark.parametrize("noun", ["impl" + "ementer", "Impl" + "ementers"])
    def test_bare_implementer_is_a_hit(self, noun: str) -> None:
        pattern = getattr(CHECKER, "IMPL" + "EMENTER")
        assert pattern.search(f"{noun} may pass it either way")

    def test_implementation_is_not_a_hit(self) -> None:
        assert not is_provenance("breaks every implementation of the Protocol")

    def test_plan_label_takes_a_one_digit_suffix(self) -> None:
        assert CHECKER.PLAN_LABEL.search("guarantees from P" + "2-2")

    def test_plan_label_is_case_sensitive(self) -> None:
        assert not is_provenance("the p" + "1-05 range")

    def test_round_review_takes_a_space(self) -> None:
        assert CHECKER.ROUND_REVIEW.search("the roun" + "d 3 review")

    @pytest.mark.parametrize("verb", ["flagged", "caught", "found", "insisted"])
    def test_review_verb_takes_each_verb(self, verb: str) -> None:
        assert CHECKER.REVIEW_VERB.search("revie" + f"w {verb} it")

    def test_design_doc_is_not_design_documentation(self) -> None:
        assert not is_provenance("see the design documentation")

    @pytest.mark.parametrize("title", ["the owner", "CEO", "the founder"])
    def test_role_passive_takes_each_title(self, title: str) -> None:
        assert CHECKER.ROLE_PASSIVE.search("decided b" + f"y {title}")

    def test_passive_by_the_operator_is_not_a_hit(self) -> None:
        assert not is_provenance("requested by the operator in the wizard")


class TestPython:
    def test_comment_is_flagged(self) -> None:
        source = (
            f"x = 1\n# {FAMILIES['ROLE_ACTION']}\ny = 2  # {FAMILIES['PLAN_LABEL']}\n"
        )
        assert _lines(scan_python(source)) == [2, 3]

    def test_docstring_is_flagged(self) -> None:
        source = f'"""Summary.\n\n{FAMILIES["WORKFLOW_PHASE"]}.\n"""\n\nx = 1\n'
        assert _lines(scan_python(source)) == [3]

    def test_test_name_is_flagged(self) -> None:
        source = "def test_ow" + "ner_asked_for_wider_column() -> None:\n    pass\n"
        assert _lines(scan_file("tests/a.py", source)) == [1]

    def test_test_name_in_product_terms_is_clean(self) -> None:
        source = "def test_operator_asked_for_section() -> None:\n    pass\n"
        assert scan_file("tests/a.py", source) == []

    def test_string_literal_is_not_scanned(self) -> None:
        source = (
            "def f() -> str:\n"
            '    """English docstring."""\n'
            f'    return "{FAMILIES["HANDOFF_DOC"]}"\n'
        )
        assert scan_python(source) == []


class TestMarkdown:
    def test_prose_line_is_flagged(self) -> None:
        text = f"ok\n{FAMILIES['EXECUTIVE']} said so\n"
        assert _lines(scan_markdown(text)) == [2]

    def test_fenced_block_is_not_scanned(self) -> None:
        text = f"```\n{FAMILIES['EXECUTIVE']}\n```\n"
        assert scan_markdown(text) == []

    def test_skill_description_is_scanned(self) -> None:
        text = f"---\nname: x\ndescription: {FAMILIES['REVIEW_PASS']}\n---\nbody\n"
        assert _lines(scan_file("skills/x/SKILL.md", text)) == [3]


class TestWebComments:
    def test_css_comment_is_flagged(self) -> None:
        text = f"/* {FAMILIES['REVIEW_PASS']} */\na {{ color: red; }}\n"
        assert _lines(scan_file("mureo/_data/web/app.css", text)) == [1]

    def test_js_line_comment_is_flagged(self) -> None:
        text = f"// {FAMILIES['WORKFLOW_ROLE']}\nconst x = 1;\n"
        assert _lines(scan_file("tests/js/a.test.js", text)) == [1]


class TestFileSet:
    @pytest.mark.parametrize(
        "path",
        ["CHANGELOG.md", "README.md", "docs/cli.md", "mureo/x.py", "tests/a.py"],
    )
    def test_shipped_files_are_scanned(self, path: str) -> None:
        assert is_scanned(path)

    @pytest.mark.parametrize(
        "path",
        [
            "AGENTS.md",
            "CONTRIBUTING.md",
            "scripts/check_comment_provenance.py",
            "tests/test_check_comment_provenance.py",
            "README.ja.md",
            "docs/cli.ja.md",
        ],
    )
    def test_rule_files_and_translations_are_not_scanned(self, path: str) -> None:
        assert not is_scanned(path)


class TestCommandLine:
    def test_repository_is_clean(self) -> None:
        result = run_script(_NAME, [])
        assert result.returncode == 0, result.stdout + result.stderr

    def test_list_excludes_the_rule_files(self) -> None:
        result = run_script(_NAME, ["--list"])
        assert result.returncode == 0, result.stderr
        listed = result.stdout.splitlines()
        assert "CHANGELOG.md" in listed
        assert "AGENTS.md" not in listed
        assert "scripts/check_comment_provenance.py" not in listed

    def test_hits_are_reported_with_path_and_line(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=clean_env())
        (tmp_path / "docs").mkdir()
        phrase = FAMILIES["PLANNER_HANDOFF"]
        (tmp_path / "docs" / "a.md").write_text(f"ok\n{phrase}\n", encoding="utf-8")
        (tmp_path / "docs" / "a.ja.md").write_text(f"{phrase}\n", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text(f"{phrase}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, env=clean_env())
        result = run_script(_NAME, ["--root", str(tmp_path)])
        assert result.returncode == 1, result.stderr
        assert result.stdout.splitlines() == [f"docs/a.md:2: {phrase}"]
