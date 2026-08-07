"""Shared PreToolUse credential-guard hook templates (#393).

Single source of truth for the guard hooks installed into Claude Code's
``~/.claude/settings.json`` and Codex's ``~/.codex/hooks.json``.  The two
installers previously carried copy-pasted templates, which is how the
non-blocking ``sys.exit(1)`` bug shipped to both hosts.

Blocking contract (identical for Claude Code and Codex): a PreToolUse hook
blocks by printing ``{"hookSpecificOutput": {"permissionDecision": "deny",
...}}`` to stdout and exiting 0, or by exiting 2 with the reason on stderr.
Any other non-zero exit — including 1 — is a *non-blocking* hook error and
the tool call proceeds.  The deny-JSON form is used here because an
interpreter crash (exit 1) can never be mistaken for an intentional block.

Two guards are installed:

* Path guard (``Read|Edit|Write|Grep|Glob|NotebookEdit``): denies when
  *either* the realpath-resolved target (``os.path.realpath`` after
  ``expanduser``) *or* the logical target (``os.path.abspath`` after
  ``expanduser``, no symlink resolution) lands inside ``~/.mureo``. The
  realpath check closes the outside-in evasion (a link outside the dir that
  resolves into it); the logical check closes the inside-out evasion (a
  ``~/.mureo/credentials.json`` that is itself a symlink pointing OUT — its
  realpath escapes the dir, but the requested path is still under it). Both
  cover every file in the directory, not just ``credentials.json``.
* Bash guard: two rules over the command text; either one denies.

  Rule 1 (the name spelled out) denies any command whose text contains
  ``.mureo`` where a path component could *start*.  Anchoring on the
  directory name rather than on ``credentials`` also covers a wildcard
  that follows the name (``cat ~/.mureo/cred*``) — but only because the
  six characters of the name are still there verbatim.  Rule 2 below is
  what covers a wildcard placed *inside* the name.

  A bare substring test over-blocks badly, because case-folded ``.mureo``
  is also a prefix of things that are emphatically not the directory:
  mureo's own browser globals (``window.MUREO_REPORTS_FORMAT``) and every
  hostname under the project's domain (``pkgs.mureo.jp``,
  ``docs.mureo.jp``).  Naming either one in a commit message, a release
  note or a PR body was denied outright.

  What separates those from a real reference is what comes *before*: a
  path component named ``.mureo`` always starts at a boundary — after
  ``/``, ``~``, a quote, whitespace, or the start of the string — whereas
  the false positives are preceded by an identifier character that belongs
  to a longer name (``window``, ``pkgs``).  So the guard denies when the
  substring is at the start of the command or preceded by a non-identifier
  character.

  That test alone would be too weak, because an identifier character can
  also be the tail of a *substitution* that supplies the parent directory:
  with ``D=~/``, the command ``cat $D.mureo/credentials.json`` resolves
  into the protected directory while putting ``D`` immediately before the
  name.  Of all the ways a shell can splice text, only ``$NAME`` and
  ``$1`` end in an identifier character — ``${...}``, ``$(...)``,
  backticks and brace expansion all close with punctuation, which the
  boundary test already catches.  The same applies one level up, to
  format specifiers consumed by a program (``printf '%s.mureo/...' ~/``).
  So the guard additionally denies when the identifier run before the
  substring is itself introduced by ``$`` or ``%``.

  Note ``$`` cannot appear literally in the payload (see the NOTE below),
  hence ``chr(36)``.

  Nothing that names the directory in plain path syntax is admitted by
  this: sibling directories (``~/.mureoX``, ``~/.mureo_backup``) still
  deny, since only the text before the name is consulted.

  Rule 2 (the name written as a pattern) closes the other half.  A
  metacharacter placed inside the name breaks rule 1's six-character
  literal while the shell still expands the pattern onto the real
  directory: ``cat ~/.mure?/credentials.json`` prints the credentials
  file, and so do ``.[m]ureo``, ``.mur*``, ``.m?reo``, ``.?????``,
  ``.[!.]*`` and the brace form ``.mure{o,x}`` (checked against bash 5.2
  with a throwaway ``HOME``).  No regex over the command text can decide
  this, because the string that reaches the filesystem does not exist
  yet — so the guard asks the question the other way round.  It takes the
  path components of the command, keeps those that begin at a component
  boundary with a literal ``.`` and contain a metacharacter, and denies
  when ``fnmatch`` says the pattern matches ``.mureo``.

  Requiring the literal leading ``.`` is what makes that safe to do.  A
  shell will not let a wildcard match the leading period of a filename
  unless ``dotglob`` is set, so ``ls *``, ``rm -rf build/*`` and
  ``tests/*.py`` cannot reach ``.mureo`` and are never candidates.
  Without that restriction the rule would have to deny every glob anyone
  types, ``fnmatch('.mureo', '*')`` being true.

  Quoted spans are skipped for this rule, because quoting suppresses
  pathname expansion: ``sed 's/.*//'`` and ``find . -name '.*'`` are a
  regex and a literal, not globs, and ``cat "$HOME/.mure?/x"`` opens
  nothing.  Unquoted, those same characters do glob, and are denied.  A
  pattern spliced in by a substitution (``$D.mure?``, ``printf
  '%s.mure?/'``) is caught by the same ``$``/``%`` clause rule 1 uses,
  where quoting is not consulted: the pattern reaches the shell through a
  later expansion.  Brace groups are replaced by ``*`` before matching,
  an over-approximation that also denies things like ``mv .{env,bak}``
  which cannot name the directory — the safe direction.

  What rule 2 does not cover, and no part of the guard claims to:

  - a pattern the command text does not contain, because a variable set
    by an earlier command or by another program supplies it (``cat
    ~/$P/x``).  Written out in the same command, ``P=.mure?; cat ~/$P/x``
    is denied — the pattern is in the text;
  - patterns for *sibling* names (``~/.mur*_backup``): rule 2 asks only
    whether the pattern matches ``.mureo`` itself, whereas rule 1 does
    deny literal siblings such as ``~/.mureo_backup``;
  - extended globs (``.mure@(o|x)``), which bash has off by default;
  - quoting is scanned as balanced pairs and each quoted span is dropped
    whole, rather than parsed as a shell would.  A pattern split across
    the quoting (``~/'.'mure?/x`` — the quoted dot still counts as
    explicit to the shell) and one hidden behind a deliberately
    unbalanced quote earlier in the line both escape this half of the
    rule;
  - shells configured with ``dotglob`` or ``GLOBIGNORE``, where ``*``
    does reach dotfiles.

Both comparisons are case-folded: macOS and Windows filesystems are
case-insensitive by default, so ``~/.MUREO/credentials.json`` opens the
real file.  On case-sensitive filesystems this can only over-block (a
genuinely distinct ``~/.MUREO`` directory), never under-block — the right
direction for a guard.

The guard remains defense-in-depth, not the primary control: shell
indirection and encoded forms can still evade the Bash guard.  Real safety
comes from filesystem permissions on ``~/.mureo`` itself.

NOTE: the python payloads run inside double quotes on a shell command line
(``python3 -c "..."``), so they must not contain double quotes, ``$``,
backticks, backslashes, newlines, or ``!`` — the last because a shell with
history expansion enabled rewrites ``!`` sequences inside double quotes.
``chr(36)`` and ``chr(33)`` stand in for the two that the patterns need.
``tests/test_credential_guard.py`` enforces this along with the blocking
behavior.
"""

from __future__ import annotations

from typing import Any

# Unique identifier used to detect (and upgrade/remove) mureo-installed hooks.
GUARD_TAG = "[mureo-credential-guard]"

# Matchers are regexes over the tool name. PATH_TOOLS_MATCHER lists the
# Claude Code tools that receive a filesystem path; entries for tools a host
# does not expose (e.g. Codex has no Read tool) simply never fire.
PATH_TOOLS_MATCHER = "Read|Edit|Write|Grep|Glob|NotebookEdit"
BASH_MATCHER = "Bash"

# Characters allowed in a deny reason. The reason is interpolated into a
# single-quoted python literal inside a double-quoted shell command; anything
# outside this set (quotes, $, backticks, backslashes, braces, newlines...)
# could break parsing and turn the block into a fail-open exit-1 error —
# exactly the #393 failure mode.
_SAFE_REASON_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;~/-_"
)


def _deny_expr(reason: str) -> str:
    """A python expression that prints the PreToolUse deny JSON."""
    unsafe = set(reason) - _SAFE_REASON_CHARS
    if unsafe:
        raise ValueError(f"deny reason contains unsafe characters: {unsafe!r}")
    return (
        "print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse',"
        "'permissionDecision':'deny','permissionDecisionReason':"
        f"'{reason}'}}}}))"
    )


_PATH_GUARD_CODE = (
    "import sys,json,os; "
    "d=json.loads(sys.stdin.read() or '{}'); "
    "i=d.get('tool_input') or {}; "
    "p=str(i.get('file_path') or i.get('path') or i.get('notebook_path') or ''); "
    "e=os.path.expanduser(p); "
    "b=os.path.realpath(os.path.expanduser('~/.mureo')).lower(); "
    "bl=os.path.abspath(os.path.expanduser('~/.mureo')).lower(); "
    "r=os.path.realpath(e).lower() if p else ''; "
    "lp=os.path.abspath(e).lower() if p else ''; "
    + _deny_expr("mureo credential guard: files under ~/.mureo are protected")
    + " if p and (r==b or r.startswith(b+os.sep)"
    " or lp==bl or lp.startswith(bl+os.sep)) else None"
)

# Source of a python expression yielding the regex for one path component
# written as a shell pattern: a literal dot plus the run of characters a
# pattern may contain.  Neither ``/`` nor whitespace is in the set, so a run
# stops where the component does.  The class needs no backslash escapes:
# ``]`` comes first and ``-`` last, and ``!`` arrives via ``chr(33)`` (see
# the NOTE in the module docstring for both prohibitions).
_PATTERN_COMPONENT = "'[.][]a-z0-9_.*?[^{},' + chr(33) + '-]*'"

_BASH_GUARD_CODE = (
    "import sys,json,re,fnmatch; "
    "d=json.loads(sys.stdin.read() or '{}'); "
    "c=str((d.get('tool_input') or {}).get('command') or '').lower(); "
    # Quoted spans undergo no pathname expansion, so they hold no globs.
    "u=re.sub(chr(39) + '[^' + chr(39) + ']*' + chr(39), ' ', c); "
    "u=re.sub(chr(34) + '[^' + chr(34) + ']*' + chr(34), ' ', u); "
    "p=re.findall('(?:^|[^a-z0-9_])(' + " + _PATTERN_COMPONENT + " + ')', u) + "
    "re.findall('[' + chr(36) + '%][a-z0-9_]*(' + "
    + _PATTERN_COMPONENT
    + " + ')', c); "
    # A brace group stands for any of its alternatives; ``*`` covers them all.
    "g=[x for x in p if set('*?[{') & set(x) and "
    "fnmatch.fnmatchcase('.mureo', re.sub('[{].*[}]', '*', x))]; "
    "b=re.search('(^|[^a-z0-9_])[.]mureo', c) or "
    "re.search('[' + chr(36) + '%][a-z0-9_]*[.]mureo', c) or g; "
    + _deny_expr("mureo credential guard: commands referencing .mureo are blocked")
    + " if b else None"
)


def path_guard_command() -> str:
    """The shell command for the path-based guard (Read/Edit/Write/Grep/Glob)."""
    return f'python3 -c "{_PATH_GUARD_CODE}" # {GUARD_TAG}'


def bash_guard_command() -> str:
    """The shell command for the Bash command-text guard."""
    return f'python3 -c "{_BASH_GUARD_CODE}" # {GUARD_TAG}'


def path_guard_entry() -> dict[str, Any]:
    """A fresh PreToolUse entry for the path guard."""
    return {
        "matcher": PATH_TOOLS_MATCHER,
        "hooks": [{"type": "command", "command": path_guard_command()}],
    }


def bash_guard_entry() -> dict[str, Any]:
    """A fresh PreToolUse entry for the Bash guard."""
    return {
        "matcher": BASH_MATCHER,
        "hooks": [{"type": "command", "command": bash_guard_command()}],
    }


def guard_entries() -> list[dict[str, Any]]:
    """Fresh copies of both guard entries, in install order.

    Fresh so that callers merging them into parsed user config never alias
    dicts across two install targets.
    """
    return [path_guard_entry(), bash_guard_entry()]


def is_guard_entry(entry: Any) -> bool:
    """True when ``entry`` is a mureo-tagged PreToolUse entry.

    Detection is scoped to the inner ``command`` field so a user's own entry
    whose matcher happens to contain the tag literal is never claimed.

    Matching is entry-level: installers drop the whole entry when any inner
    hook carries the tag. mureo only ever writes single-hook entries, so
    this is equivalent to the finer hook-level stripping that
    ``mureo.cli.settings_remove`` performs — it differs only on a
    hand-merged config where a user appended their own hook to a mureo
    entry.
    """
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(hook, dict) and GUARD_TAG in str(hook.get("command", ""))
        for hook in hooks
    )
