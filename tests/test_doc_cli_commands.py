"""The ``mureo`` commands the shipped docs show must exist in the CLI.

``docs/cli.md`` is the command reference and the other documents show
commands in code spans and fenced blocks. The commands live in the Typer
app, so a command that is renamed, removed or added changes the code and
leaves the docs telling an operator to type something the CLI rejects, or
leaves a command undocumented. Nothing in the code reads the docs, so only
a test that reads them notices (#1043).

The tree is built from the app the ``mureo`` console script points at in
``pyproject.toml``, walked through the click commands typer builds from
it (``typer.main.get_command``), so it is exactly what an
installed ``mureo`` accepts. Hidden commands are left out: the docs are not
meant to show them.
"""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Iterable, Mapping

import pytest
import typer

from tests._doc_surface import _REPO_ROOT, _doc_text, code_spans, fenced_lines

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

pytestmark = pytest.mark.unit

CommandTree = Mapping[str, "CommandTree"]

#: Documents whose code spans and fenced blocks are read for ``mureo``
#: commands, besides every ``docs/*.md``.
_TOP_LEVEL_DOCS = (
    "README.md",
    "README.ja.md",
    "AGENTS.md",
    "CONTEXT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
)

_CLI_DOC = "docs/cli.md"

#: ``mureo <word>`` strings in code that are not commands, keyed by the
#: document they appear in, so the same words elsewhere are still checked.
_NOT_COMMANDS = {
    (_CLI_DOC, "mureo cannot"): "CLI output quoted in the doc, not a command",
    (_CLI_DOC, "mureo refuses"): "CLI output quoted in the doc, not a command",
    (_CLI_DOC, "mureo does"): "CLI output quoted in the doc, not a command",
    ("docs/docker.md", "mureo mureo"): (
        "a Docker image named mureo, followed by the command"
    ),
}

# A shell or tree-diagram comment in a fenced block is prose.
_COMMENT = re.compile(r"(?:^|\s)#.*$")
# ``mureo`` as a word of its own: not ``~/.mureo``, ``mureo.cli``,
# ``mureo-acme-bridge``, ``mureo/`` or ``mureo_state_get``.
_MUREO = re.compile(r"(?<![\w./~-])mureo(?![\w./-])")
_COMMAND_WORD = re.compile(r"[a-z][a-z0-9-]*")


def _code_lines(markdown: str) -> list[tuple[int, str]]:
    """(line number, code text) for fenced lines and inline code spans."""
    found: list[tuple[int, str]] = []
    for number, (line, fenced) in enumerate(fenced_lines(markdown), 1):
        if fenced:
            found.append((number, _COMMENT.sub("", line)))
        else:
            found.extend((number, span) for span in code_spans(line))
    return found


def command_mentions(markdown: str) -> list[tuple[int, list[str]]]:
    """(line, words after ``mureo``) for each ``mureo <command-shaped word>``."""
    mentions: list[tuple[int, list[str]]] = []
    for number, code in _code_lines(markdown):
        for match in _MUREO.finditer(code):
            rest = code[match.end() :]
            words = rest.split()
            if rest[:1].isspace() and words and _COMMAND_WORD.fullmatch(words[0]):
                mentions.append((number, words))
    return mentions


def _resolve(words: list[str], tree: CommandTree) -> list[str]:
    """The longest prefix of ``words`` that is a command path in ``tree``."""
    path: list[str] = []
    node = tree
    for word in words:
        if word not in node:
            break
        path.append(word)
        node = node[word]
    return path


def _unresolved(words: list[str], tree: CommandTree) -> str | None:
    """The part of a mention the CLI rejects, or ``None`` when it resolves.

    A word after a command group is read as its subcommand when it is
    command-shaped, so ``mureo providers nuke`` is reported as well as an
    unknown first word.
    """
    path = _resolve(words, tree)
    if not path:
        return f"mureo {words[0]}"
    node = tree
    for word in path:
        node = node[word]
    following = words[len(path) :]
    if node and following and _COMMAND_WORD.fullmatch(following[0]):
        return f"mureo {' '.join([*path, following[0]])}"
    return None


def unresolved_mentions(markdown: str, tree: CommandTree) -> list[tuple[int, str]]:
    """(line, the mention cut where the CLI rejects it) for each that does not
    resolve: an unknown first word, or an unknown word after a group."""
    return [
        (number, unresolved)
        for number, words in command_mentions(markdown)
        if (unresolved := _unresolved(words, tree)) is not None
    ]


def command_paths(tree: CommandTree, prefix: str = "") -> list[str]:
    """Every command path in ``tree``, groups included (``auth``, ``auth setup``)."""
    paths: list[str] = []
    for name, sub in tree.items():
        path = f"{prefix}{name}"
        paths.append(path)
        paths.extend(command_paths(sub, f"{path} "))
    return paths


def missing_cli_paths(cli_markdown: str, paths: Iterable[str]) -> list[str]:
    """Command paths ``docs/cli.md`` never shows as ``mureo <path>``."""
    return [
        path
        for path in paths
        if not re.search(rf"mureo {re.escape(path)}(?![\w-])", cli_markdown)
    ]


def _tree_of(command: object) -> dict[str, CommandTree]:
    # Typed as ``object``: typer builds its commands on a click it vendors
    # (``typer._click``), so the public ``click.Command`` is not their type.
    subcommands = getattr(command, "commands", {})
    return {name: _tree_of(sub) for name, sub in subcommands.items() if not sub.hidden}


def _cli_tree() -> dict[str, CommandTree]:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    module_name, _, attribute = data["project"]["scripts"]["mureo"].partition(":")
    app = getattr(importlib.import_module(module_name), attribute)
    return _tree_of(typer.main.get_command(app))


def _shipped_docs() -> list[str]:
    docs = sorted(
        str(path.relative_to(_REPO_ROOT)) for path in (_REPO_ROOT / "docs").glob("*.md")
    )
    return [*_TOP_LEVEL_DOCS, *docs]


def _unresolved_everywhere() -> list[tuple[str, int, str]]:
    tree = _cli_tree()
    return [
        (rel, number, mention)
        for rel in _shipped_docs()
        for number, mention in unresolved_mentions(_doc_text(rel), tree)
    ]


def test_cli_tree_is_read_from_the_console_script() -> None:
    """Coverage guard: the walk reached the nested commands."""
    paths = command_paths(_cli_tree())
    assert {"auth setup", "providers add"} <= set(paths), paths


def test_cli_doc_shows_every_command() -> None:
    missing = missing_cli_paths(_doc_text(_CLI_DOC), command_paths(_cli_tree()))
    assert missing == [], f"{_CLI_DOC} never shows: {missing}"


def test_docs_mention_every_top_level_command() -> None:
    """Coverage guard: the matcher finds the commands the docs show, so a
    change that made it match nothing fails here instead of passing."""
    tree = _cli_tree()
    mentioned = {
        path[0]
        for rel in _shipped_docs()
        for _, words in command_mentions(_doc_text(rel))
        if (path := _resolve(words, tree))
    }
    assert sorted(set(tree) - mentioned) == []


def test_commands_shown_in_the_docs_exist() -> None:
    unknown = [u for u in _unresolved_everywhere() if (u[0], u[2]) not in _NOT_COMMANDS]
    assert unknown == [], f"docs show commands the CLI lacks: {unknown}"


def test_every_not_command_entry_is_still_needed() -> None:
    seen = {(rel, mention) for rel, _, mention in _unresolved_everywhere()}
    stale = sorted(set(_NOT_COMMANDS) - seen)
    assert stale == [], f"entries that match nothing any more: {stale}"


_SNIPPET_TREE: dict[str, CommandTree] = {"auth": {"setup": {}}, "configure": {}}


def test_unresolved_mentions_reports_a_command_the_cli_lacks() -> None:
    snippet = (
        "Run `mureo auth setup --web`, then `mureo configure`.\n"
        "\n"
        "```bash\n"
        "mureo setup claude-code  # mureo hands back here\n"
        "pip install mureo-acme-bridge ~/.mureo mureo.cli\n"
        "```\n"
    )
    assert unresolved_mentions(snippet, _SNIPPET_TREE) == [(4, "mureo setup")]


def test_unresolved_mentions_reports_an_unknown_subcommand() -> None:
    snippet = (
        "Run `mureo auth setup` (or `mureo configure`, `mureo auth`).\n"
        "\n"
        "```bash\n"
        "mureo auth nuke --yes\n"
        "mureo auth --help\n"
        "```\n"
    )
    assert unresolved_mentions(snippet, _SNIPPET_TREE) == [(4, "mureo auth nuke")]


def test_missing_cli_paths_reports_an_undocumented_command() -> None:
    snippet = "```bash\nmureo auth setup\nmureo authx\n```\n"
    paths = command_paths(_SNIPPET_TREE)
    assert missing_cli_paths(snippet, paths) == ["configure"]
