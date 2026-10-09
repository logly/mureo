"""Behavioral tests for the Bash guard's rules 1 to 4 and its refusal reasons.

Rules 1 and 2 read the directory name, rules 3 and 4 what a search that
never spells the directory does write down; the last class pins which
reason a refusal of unresolved brace structure gives.

How these tests run the hook payloads is described in
``tests/test_credential_guard.py``; the helpers they share are in
``tests/credential_guard_support.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.credential_guard_support import (
    _bash_guard_command,
    _refusal_category,
)
from tests.hook_guard_runner import deny_decision, run_guard

# ---------------------------------------------------------------------------
# Bash guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBashGuardBehavior:
    def test_denies_wildcard_read(self, fake_home: Path) -> None:
        """``cat ~/.mureo/cred*`` evaded the old 'credentials' substring check."""
        proc = run_guard(
            _bash_guard_command(),
            {"command": "cat ~/.mureo/cred*"},
            fake_home,
            tool_name="Bash",
        )
        assert proc.returncode == 0
        assert deny_decision(proc) == "deny"

    @pytest.mark.parametrize(
        "command",
        [
            "cat ~/.mureo/credentials.json",
            "cat $HOME/.mureo/config.json",
            "cp -r ~/.mureo /tmp/exfil",
            "python3 -c 'print(open(\"/Users/x/.mureo/agency.json\").read())'",
            "cat ~/.MUREO/credentials.json",  # case-insensitive filesystems
        ],
    )
    def test_denies_mureo_dir_references(self, fake_home: Path, command: str) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert deny_decision(proc) == "deny"

    @pytest.mark.parametrize(
        "command",
        [
            # End of the command string: nothing follows the directory name.
            "ls -la ~/.mureo",
            "tar cf /tmp/x.tar ~/.mureo",
            # Trailing separator, and every quoting form of the same path.
            "ls ~/.mureo/",
            'cat "$HOME/.mureo/credentials.json"',
            "cat '~/.mureo/credentials.json'",
            "cat ~/'.mureo'/credentials.json",
            'cat ~/.mureo""/credentials.json',
            # Mixed case still opens the real file on case-insensitive
            # filesystems, so it must stay blocked.
            "cat ~/.Mureo/credentials.json",
            "ls ~/.MUREO",
            # Anything at all may follow the directory name — the rule only
            # consults what comes before it.
            "cat ~/.mureo$SUFFIX/credentials.json",
            "cat ~/.mureo{,}/credentials.json",
            "cat ~/.mureo*/credentials.json",
            "cat ~/.mureoX/../.mureo/credentials.json",
            # Sibling names are blocked too: only the text before the name is
            # consulted, so ``.mureoX`` — which may well be a symlink INTO the
            # protected directory — is not admitted.
            "cat ~/.mureoX/credentials.json",
            "ls ~/.mureo_backup",
            # A substitution supplying the parent directory leaves an
            # identifier character immediately before the name. These are the
            # forms that make a naive preceded-by test unsafe: each one
            # resolves into ~/.mureo.
            "D=~/; cat $D.mureo/credentials.json",
            "D=~/; cat $D.MUREO/credentials.json",
            "set -- ~/; cat $1.mureo/credentials.json",
            "D=~/; E=; cat $D$E.mureo/credentials.json",
            "cat $(printf '%s.mureo/credentials.json' ~/)",
            "python3 -c \"print(open('%s.mureo/credentials.json' % h).read())\"",
            # ...while every other splice closes with punctuation, which the
            # boundary test catches on its own.
            "D=~/; cat ${D}.mureo/credentials.json",
            'D=~/; cat "$D".mureo/credentials.json',
            "cat $(printf '%s' ~/).mureo/credentials.json",
            "python3 -c \"print(open('{}.mureo/x'.format(h)).read())\"",
        ],
    )
    def test_denies_every_spelling_of_the_mureo_dir(
        self, fake_home: Path, command: str
    ) -> None:
        """The boundary rule must not shrink what is blocked.

        Every form here resolves into ``~/.mureo`` — verified by expanding
        each one with a real shell against a throwaway ``$HOME`` — and every
        one of them was blocked by the previous bare-substring check.
        """
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # Every one of these was verified against a throwaway $HOME with a
            # real bash 5.2: each prints the contents of the credentials file.
            "cat ~/.mure?/credentials.json",
            "cat ~/.[m]ureo/credentials.json",
            "cat ~/.mur*/credentials.json",
            "cat ~/.m?reo/credentials.json",
            "cat ~/.?????/credentials.json",
            "cat ~/.[!.]*/credentials.json",
            "cat ~/.mure[o]/credentials.json",
            # Brace expansion runs before pathname expansion, so it produces
            # the real directory name without any wildcard at all.
            "cat ~/.mure{o,x}/credentials.json",
            "cat ~/.mur{eo,ex}/credentials.json",
            # Same patterns, other spellings of the parent directory.
            "ls -la ~/.mure?",
            "cp -r ~/.m?reo /tmp/exfil",
            "cat $HOME/.mure?/credentials.json",
            "cat ${HOME}/.mur*/credentials.json",
            'cat "$HOME"/.mure?/credentials.json',
            "cat /Users/x/.mur*/credentials.json",
            # Case-folded, as everywhere else in the guard.
            "cat ~/.MURE?/credentials.json",
            "cat ~/.[M]UREO/credentials.json",
            # A substitution supplies the parent, so the pattern does not
            # start at a path boundary — the same shapes rule 1 covers for
            # the literal name.
            "D=~/; cat $D.mure?/credentials.json",
            "cat $(printf '%s.mure?/credentials.json' ~/)",
            "python3 -c \"print(open('%s.mure?/credentials.json' % h).read())\"",
        ],
    )
    def test_denies_glob_patterns_matching_the_mureo_dir(
        self, fake_home: Path, command: str
    ) -> None:
        """A wildcard inside the directory name still reaches the real files.

        The literal-substring rule looks for six consecutive characters, so
        any metacharacter placed *inside* ``.mureo`` breaks the match while
        the shell still expands the pattern onto the protected directory.
        """
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # Wildcards that cannot reach a dotfile at all: the shell requires
            # a leading period to be matched explicitly.
            "ls *",
            "rm -rf build/*",
            "cp dist/* /tmp/",
            "node --test tests/js/*.test.js",
            "pytest tests/test_*.py",
            "ls -d */",
            "git add -- mureo/*.py",
            # Dot-leading patterns that cannot spell the directory name.
            "rm -f .coverage*",
            "ls -d .git*",
            "cat .env.*",
            "rm -rf .pytest_cache .ruff_cache",
            # Quoted metacharacters never reach pathname expansion — regexes
            # and format strings must not be read as globs.
            "sed 's/.*//' notes.txt",
            "grep -rn '.*TODO' mureo/",
            "find . -name '*.py' -newer setup.py",
            "find . -name '.*' -maxdepth 1",
            "git log --grep '.*fix'",
            # ...including a fully quoted path: quoting suppresses globbing,
            # so `?` here is a literal character and opens nothing.
            'cat "$HOME/.mure?/credentials.json"',
            # Ordinary commands with no pattern at all.
            "ruff check .",
            "git diff -- .",
            "black --check .",
        ],
    )
    def test_allows_everyday_glob_commands(self, fake_home: Path, command: str) -> None:
        """The pattern rule must not fire on day-to-day shell usage."""
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == "", command

    @pytest.mark.parametrize("command", ["echo hello", "ls -la", "git status"])
    def test_allows_unrelated_commands(self, fake_home: Path, command: str) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    @pytest.mark.parametrize(
        "command",
        [
            # mureo's own public browser namespace, case-folding to `.mureo_`.
            "gh release create v0.10.43 --notes 'adds window.MUREO_REPORTS_FORMAT'",
            "git commit -m 'feat: reorder via window.MUREO_REPORTS_ORDER'",
            "grep -rn window.MUREO_WIZARD mureo/_data/web/",
            "node --test tests/js/reports_format.test.js # window.MUREO_AUTH_META",
            # Hostnames under the project's domain, case-folding to `.mureo.`.
            "gh pr create --body 'published to pkgs.mureo.jp'",
            "pip install --index-url https://pkgs.mureo.jp/simple/ mureo-agency",
            "curl -sS https://pkgs.mureo.jp/simple/index.html",
            "open https://docs.mureo.jp/byod",
            "echo www.mureo.jp",
        ],
    )
    def test_allows_mureo_own_identifiers(self, fake_home: Path, command: str) -> None:
        """mureo's browser globals and hostnames are not the directory.

        Both false positives were observed for real: the ``gh release
        create`` call for v0.10.43 was denied over ``window.MUREO_REPORTS_*``
        in its notes, and a ``gh pr create`` was denied over
        ``pkgs.mureo.jp`` in its body. In each the substring is preceded by
        an identifier character belonging to a longer name, so it cannot be
        the start of a ``.mureo`` path component.
        """
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == "", command


@pytest.mark.unit
class TestSearchByNameRatherThanByDirectory:
    """Rules 3 and 4: a command that never spells the directory.

    Rules 1 and 2 read the directory name, so every test above hands the
    guard some spelling of ``~/.mureo``.  A tree search does not have to
    supply one: ``find ~ -name credentials.json -exec cat {} ;`` and
    ``find ~ -path '*mureo*' -exec cat {} ;`` both print the credentials
    while mentioning no directory rule 1 or 2 can see.  Neither needs
    obfuscation, and "find any leftover credential files under my home
    directory" is an ordinary instruction rather than an attack — which
    is exactly the accident this guard exists to make less likely.
    """

    @pytest.mark.parametrize(
        "command",
        [
            # Rule 4 — the filename is the only thing written down.
            "find ~ -name credentials.json -exec cat {} ;",
            "find ~ -name credentials.json | xargs cat",
            "find ~ -iname credentials.json",
            "find / -name agency.json -exec cat {} ;",
            "find ~ -name setup_state.json",
            "find ~ -name 'credentials.json'",
            "locate credentials.json",
            "find ~ -name credentials.json.bak",
            "fd credentials.json ~",
            # The name reached through a substitution the guard cannot
            # read still denies, because the name itself is written down.
            "cat $(find ~ -name credentials.json)",
        ],
    )
    def test_denies_a_protected_filename(self, fake_home: Path, command: str) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # Rule 3 — a pattern reaching the directory with no leading
            # dot of its own. `find -path` matches the whole path, so the
            # period is inside the part `*` covers.
            "find ~ -path '*mureo*' -exec cat {} ;",
            "find ~ -name '*mureo*'",
            "find ~ -path *mureo*",
            "grep -rl SECRET ~ --include='*mureo*'",
            "ls ~/*mureo*",
            "find ~ -path '?mureo'",
        ],
    )
    def test_denies_a_pattern_reaching_the_name(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert deny_decision(proc) == "deny", command

    def test_rule_three_reads_the_raw_text_not_only_the_expansion(
        self, fake_home: Path
    ) -> None:
        """A quoted ``*`` is dead to the shell and alive to ``find``.

        Normalization models what the SHELL expands, so it neutralizes the
        metacharacters in ``-path '*mureo*'`` — correctly, because the
        shell will not expand them.  But that is why the quotes are there:
        they hand the pattern to ``find`` intact.  Judged only on the
        normalized reading the pattern has already become ``=mureo=`` and
        no rule fires, which is why rule 3 also reads the raw command.

        Pinning both spellings keeps that property from being optimized
        away by a future change that moves rule 3 onto the readings.
        """
        for command in ("find ~ -path '*mureo*'", "find ~ -path *mureo*"):
            proc = run_guard(
                _bash_guard_command(),
                {"command": command},
                fake_home,
                tool_name="Bash",
            )
            assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # `config.json` is deliberately not guarded by name: it is one
            # of the most common filenames in software and denying it
            # would block real work in every project. The cost is real and
            # is stated in the module docstring rather than hidden.
            "cat config.json",
            "cat ./config.json",
            "vim src/config.json",
            "find . -name config.json",
            # A project file whose name merely contains a guarded one.
            "cat src/my_credentials.jsonl",
            "cat app-credentials.jsonc",
            "cat credentialsxjson",
            # The written-out name with no pattern in front of it: working
            # inside a checkout of this repository must stay possible.
            "grep -r foo mureo/",
            "ls mureo/skills",
            "pytest tests/test_credential_guard.py",
            # A path in front of the name is not a search. Which file it
            # is has already been decided from the directory: this one is
            # the user's own, under a directory the guard does not
            # protect, and refusing it would be overreach.
            "cp ~/backups/credentials.json /tmp/",
            "tar cf /tmp/x.tar ~/x/credentials.json.bak",
            "cat ./secrets/agency.json",
        ],
    )
    def test_allows_ordinary_work(self, fake_home: Path, command: str) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == "", command

    def test_the_filename_rule_says_what_matched(self, fake_home: Path) -> None:
        """A wrong reason costs a retry.

        Told the command "can reach ~/.mureo" when it never named the
        directory, an agent goes looking for a reference that is not
        there.  Rule 4's reason names what actually matched and points at
        the Read tool, which is guarded by path and so still opens a
        same-named file of the user's own.
        """
        proc = run_guard(
            _bash_guard_command(),
            {"command": "find ~ -name credentials.json"},
            fake_home,
            tool_name="Bash",
        )
        reason = json.loads(proc.stdout)["hookSpecificOutput"][
            "permissionDecisionReason"
        ]
        assert "credential file" in reason
        assert "Read tool" in reason

        # A directory reference keeps the original reason.
        proc = run_guard(
            _bash_guard_command(),
            {"command": "cat ~/.mureo/credentials.json"},
            fake_home,
            tool_name="Bash",
        )
        reason = json.loads(proc.stdout)["hookSpecificOutput"][
            "permissionDecisionReason"
        ]
        assert "~/.mureo" in reason


# Nine brace groups on one line: one more than the expansion budget resolves,
# and nothing in it refers to the protected directory.  This is the shape the
# budget refusal exists for, isolated from every other rule.
_OVER_THE_BRACE_BUDGET = "echo " + " ".join(f"x{{{i},{i + 1}}}" for i in range(9))


@pytest.mark.unit
class TestTheBudgetRefusalSaysWhatHappened:
    """Unresolved brace structure denies for its own reason (#806).

    The budget answers before rules 1 to 4 and independently of them, so it
    cannot claim anything about what matched.  Borrowing rule 1's reason told
    the command it "can reach ~/.mureo" when the command never mentioned the
    directory — the same mistake rule 4's own reason exists to avoid (#582):
    the agent goes looking for a reference that is not there and retries.

    What the refusal does *not* change is which commands are refused.  The
    budget denied before the rules on both sides of this change; only the
    sentence it prints is different.
    """

    def test_unresolved_structure_does_not_borrow_rule_ones_reason(
        self, fake_home: Path
    ) -> None:
        proc = run_guard(
            _bash_guard_command(),
            {"command": _OVER_THE_BRACE_BUDGET},
            fake_home,
            tool_name="Bash",
        )
        assert proc.returncode == 0
        assert deny_decision(proc) == "deny"
        assert _refusal_category(proc) == "budget"
        reason = json.loads(proc.stdout)["hookSpecificOutput"][
            "permissionDecisionReason"
        ]
        assert "~/.mureo" not in reason, "the command never named the directory"

    def test_a_directory_reference_keeps_the_directory_reason(
        self, fake_home: Path
    ) -> None:
        proc = run_guard(
            _bash_guard_command(),
            {"command": "cat ~/.mureo/credentials.json"},
            fake_home,
            tool_name="Bash",
        )
        assert deny_decision(proc) == "deny"
        assert _refusal_category(proc) == "directory"

    def test_the_budget_answers_before_the_directory_rules(
        self, fake_home: Path
    ) -> None:
        """A command that trips both is refused on the budget.

        The budget runs first because its answer is "nothing was concluded
        about this command": the readings rule 1 would judge are the ones the
        guard failed to finish producing.  Reporting a match off an unfinished
        expansion would be reporting a guess.
        """
        proc = run_guard(
            _bash_guard_command(),
            {"command": f"cat ~/.mureo/credentials.json; {_OVER_THE_BRACE_BUDGET}"},
            fake_home,
            tool_name="Bash",
        )
        assert deny_decision(proc) == "deny"
        assert _refusal_category(proc) == "budget"
