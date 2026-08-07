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
* Bash guard: normalizes the command *once* into the text a shell would
  read after quoting, line continuations and expansions are resolved, and
  applies two rules to that one string.  Either one denies.

  The single reading is the load-bearing part, and it was learned the
  expensive way.  Earlier versions had one rule scanning the raw command
  and another scanning the folded text; every obfuscation one of them
  resolved was invisible to the other, so each new fold opened a new hole
  on the axis the other rule owned.  ``D=~/; cat $D.mu\\<newline>reo/…``
  reads the file: the continuation was folded away in the text the
  pattern rule read, while the rule that knew about ``$D`` was still
  looking at the raw command.  Nothing here may reintroduce a second
  reader.  If a rule needs information the fold destroys, the fold has to
  preserve it — which is what ``_COLLAPSE`` does for expansion
  boundaries — rather than the rule reaching for a different string.

  Rule 1 (the name spelled out) denies when the normalized text contains
  ``.mureo`` where a path component could *start*.  Anchoring on the
  directory name rather than on ``credentials`` also covers a wildcard
  that follows the name (``cat ~/.mureo/cred*``).  Rule 2 below covers a
  metacharacter placed *inside* the name.  Because both read the
  normalized text, a name that only becomes contiguous once the shell has
  worked on it — ``.mure"o"``, ``.mur'e'o``, ``.mu\\<newline>reo``,
  ``$D.mureo`` — is as visible to them as one written out.

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

  That boundary test would be too weak on the raw command, because an
  identifier character can also be the tail of a *substitution* that
  supplies the parent directory: with ``D=~/``, the command ``cat
  $D.mureo/credentials.json`` resolves into the protected directory while
  putting ``D`` immediately before the name.  The same applies one level
  up, to a format specifier a program will fill in (``printf
  '%s.mureo/...' ~/``).

  This is where an earlier design added a *second rule* over the raw text,
  and where the split-brain bugs came from.  Normalization handles it
  instead: an expansion becomes ``*/`` and swallows the identifier run
  that names it, so ``$D.mureo``, ``${D}.mureo``, ``$1.mureo`` and
  ``%s.mureo`` all read as ``*/.mureo``.  The dot then sits after a
  non-identifier character, exactly as it does in ``~/.mureo``, and the
  one boundary test sees every one of them — including when the name is
  *also* broken up, which is what the two-rule version could not do.

  Nothing that names the directory in plain path syntax is admitted by
  this: sibling directories (``~/.mureoX``, ``~/.mureo_backup``) still
  deny, since only the text before the name is consulted.

  Rule 2 (the name written as a pattern).  A metacharacter inside the name
  breaks rule 1's six-character literal while the shell still expands the
  pattern onto the real directory: ``cat ~/.mure?/credentials.json``
  prints the credentials file, and so do ``.[m]ureo``, ``.mur*``,
  ``.m?reo``, ``.?????``, ``.[!.]*`` and the brace form ``.mure{o,x}``
  (each run against bash 5.2 with a throwaway ``HOME``).  No pattern over
  the command text can decide this, because the string that reaches the
  filesystem does not exist yet — so the guard asks the question the other
  way round.  It takes the path components of the normalized command,
  keeps those beginning at a component boundary with a literal ``.`` and
  containing a metacharacter, and denies when ``fnmatch`` says the pattern
  matches ``.mureo``.

  Requiring the literal leading ``.`` is what makes that safe to do.  A
  shell will not let a wildcard match the leading period of a filename
  unless ``dotglob`` is set, so ``ls *``, ``rm -rf build/*`` and
  ``tests/*.py`` cannot reach ``.mureo`` and are never candidates.
  Without that restriction the rule would have to deny every glob anyone
  types, ``fnmatch('.mureo', '*')`` being true.

  Normalization produces that one reading, and it is a left fold over the
  characters with a five-state quoting automaton — unquoted, single-quoted,
  double-quoted, and the two escaped states — because that is the only way
  to get quoting right.  An earlier version stripped quoted spans with two
  regex passes and had the defect that shape invites: in ``echo "it's" ;
  cat ~/.mure?/x 'x'`` the single-quote pass read the apostrophe of
  ``it's`` as an opening delimiter, paired it with the unrelated ``'x'``
  at the end of the line, and deleted the real pattern sitting between
  them.  The fold cannot make that mistake, and it also gets ``echo
  it\\'s`` right, where an escaped quote is not a delimiter at all.

  The fold rewrites five things:

  - quote delimiters are dropped, so the text reads as the shell will read
    it (this is what catches ``~/.mure"o"``);
  - a line continuation — a backslash with a newline after it — is dropped
    whole, both characters, because that is what a shell does with the
    pair before it tokenises anything.  ``cat ~/.mu\\<newline>reo/…``
    prints the credentials file, and so do ``.\\<newline>mureo``,
    ``.mure\\<newline>?`` and the same spellings inside double quotes.
    Keeping the newline was enough to stop the name ever being contiguous.
    Inside *single* quotes a backslash is an ordinary character, so there
    is no continuation there and none is normalized away;
  - a *quoted* metacharacter becomes ``=``, because quoting makes it an
    ordinary character and no ordinary character in ``.mureo`` is a
    metacharacter.  That is why ``sed 's/.*//'`` and ``find . -name '.*'``
    are a regex and a literal rather than globs, and why ``cat
    "$HOME/.mure?/x"`` — which opens nothing — is allowed while the
    unquoted spelling is denied.  The placeholder has to be a character
    that reads as a *boundary*: it was ``_`` once, and since ``_`` is an
    identifier character, ``'{}.mureo'`` folded to ``__.mureo`` and the
    boundary test saw one long name rather than the directory;
  - the start of an expansion (``$``, backtick, ``%``) becomes ``*/`` and
    swallows the identifier run naming it: ``*`` because its text is
    unknown, ``/`` because its extent is unknown too, so what follows
    cannot be assumed to continue the same path component, and swallowing
    ``D`` in ``$D`` so the expansion reads as one unknown thing.  ``%`` is
    an expansion in every state, quoted or not, because the program that
    fills it in is the next one along, not this shell;
  - a quoted span containing ``%`` keeps its metacharacters live, because
    such a span is a template rather than text: ``printf
    '%s.mure?/x'`` builds a name whose ``?`` the shell then globs.  The
    flag resets at the end of the span, so a ``%`` in one argument cannot
    animate the metacharacters of a later one — ``echo "100%" ; sed
    's/.*//'`` is still allowed.

  A brace group is replaced by ``.*`` when any alternative contains a dot
  and by ``*`` otherwise, before the components are cut.  That is what
  catches both ``~/.mure{o,x}`` and ``~/{.,z}mureo``, where the group
  supplies the leading dot itself.

  Deliberate over-blocks, all in the safe direction:

  - a brace group with no dot in it becomes ``*``, so ``mv .{foo,bar}``
    and ``rm .{a,b,c}`` deny although neither can name the directory.
    (``mv .{env,env.bak}`` does not: the dot in an alternative makes the
    replacement ``.*``, which cannot match a six-character name starting
    with a single dot.)  Expanding the alternatives exactly would fix
    this, and is the change to make if it ever gets in the way;
  - anything unquoted that really does glob dotfiles: ``ls .*``, ``ls -d
    .??*``, ``rm -rf .[!.]*`` all reach ``~/.mureo`` from ``$HOME`` and
    all deny;
  - a component holding an expansion is unknown text, so ``ls .$X`` and
    ``cat .$(cmd)`` deny.  An arithmetic expansion is not treated any
    differently, so ``echo .$((1+1))`` and ``cat ~/.mure$((0))?/x`` deny
    too, though neither can reach the directory;
  - a format string that builds ``<something>.<something>`` is the shape
    of ``printf '%s.mureo/…' ~/``, and nothing in the text distinguishes
    them, so ``printf '%s.%s' a b`` denies.  Of twenty ``%``-heavy
    everyday commands (``date +%Y-%m-%d``, ``git log --format=%h``,
    ``awk '{printf "%.2f", $1}'``, ``grep '100%'``, a commit message
    reading ``30% faster``) that is the only one that does.

  What the guard does not cover — measured, not assumed, and pinned by
  ``test_known_open_bypasses``:

  - the shell's own options.  ``shopt -s dotglob; cat ~/*/x`` reads the
    file; the command text says nothing about whether ``dotglob`` is set,
    and it can have been set in an earlier call on the same persistent
    shell or in the user's rc file.  Denying every ``*`` instead is not an
    option;
  - anything whose text the command does not contain: a name or pattern
    produced by another program (``cat ~/$(printf '.')mureo/x``), taken
    from a variable set elsewhere (``cat ~/$P/x``), or written in a
    notation that has to be decoded first (``cat ~/$'\\x2emureo'/x``).
    Both rules can only read what is written down.  Where the text *is*
    written down the guard does see it, which is why ``P=.mure?; cat
    ~/$P/x`` denies;
  - extended globs (``.mure@(o|x)``), which bash parses only with
    ``extglob`` set, and which ``fnmatch`` does not implement;
  - patterns for *sibling* names (``~/.mur*_backup``): rule 2 asks only
    whether a pattern matches ``.mureo`` itself, whereas rule 1 does deny
    literal siblings such as ``~/.mureo_backup``.

  The first two are not closable by inspecting command text, and no
  further rule should be added pretending otherwise.

  Two differential tests against a real bash back that up, both checking
  what the shell actually reads rather than what the rule thinks:

  - an exhaustive product of {how the parent directory is supplied:
    literal, ``$HOME``, ``"$HOME"``, ``$VAR``, ``"$VAR"``, ``${VAR}``,
    ``$VAR$EMPTY``, ``$1``, ``$(cmd)``, backtick} x {how the name is
    broken: not at all, continuation, two continuations, single-quote
    split, single-quoted character, double-quote split, double-quoted
    character, escaped character, class, wildcard, brace, star} x {where}.
    All 560 members read the credentials file, and all 560 deny;
  - a random fuzz that spells the name one character at a time in the same
    forms: of 2500 commands, 1995 read the file — 825 with the name
    written out in the text, 0 through; 1170 assembled at runtime, 172
    through, every one of them producing the leading dot from a
    substitution.

  Both of the last two rounds of bugs were products of two axes, and both
  times the generator had only walked the margins: it emitted continuations
  and it emitted substitutions, but never a continuation *inside* a
  substituted parent, which is exactly where the guard was blind.  A form
  the generator cannot produce is a form nothing here has checked — and
  that applies to combinations, not just to features.  Extend it before
  trusting it.

Both comparisons are case-folded: macOS and Windows filesystems are
case-insensitive by default, so ``~/.MUREO/credentials.json`` opens the
real file.  On case-sensitive filesystems this can only over-block (a
genuinely distinct ``~/.MUREO`` directory), never under-block — the right
direction for a guard.

Both payloads fail closed.  A hook that exits non-zero for any reason
other than the documented block is a *non-blocking* error and the tool
call proceeds, so an exception escaping the payload is a bypass, not a
crash: ``sys.excepthook`` is set to print the deny JSON and exit 0.  This
was not academic — malformed stdin made both payloads exit 1 and let the
call through, as did a path with an embedded NUL, which makes
``os.path.realpath`` raise.

The payloads run under whatever ``python3`` the host finds on PATH, which
need not be the interpreter mureo itself was installed with.  The Bash
payload needs **Python 3.8 or newer** for ``itertools.accumulate(...,
initial=...)``; on anything older it raises, which fails closed — it
denies every Bash call rather than letting any through, so the symptom is
loud and safe rather than silent.  Keep it that way: a rewrite of the fold
that avoids ``initial=`` is fine, one that swallows the error is not.

WHAT THIS GUARD IS.  It is a deterrent against an agent reading the
credentials by accident or on a careless instruction — the cases that
actually happen.  It is not a security boundary and cannot be made into
one.  The agent runs as the user who owns the file, so it can read it
through any construction the text does not reveal: a variable, a
substitution, an encoding, a helper script, a language runtime.  The
earlier claim here that "real safety comes from filesystem permissions"
was wrong in the same direction: permissions do not stop a process running
as the owner either.  What actually limits the damage is not keeping
long-lived credentials where an autonomous agent runs, scoping and
rotating them, and the audit trail — not this hook.  Judge changes to it
by whether they make the common accident less likely without blocking real
work, and do not describe it as more than that.

NOTE: the python payloads run inside double quotes on a shell command line
(``python3 -c "..."``), so they must not contain double quotes, ``$``,
backticks, backslashes, newlines, or ``!`` — the last because a shell with
history expansion enabled rewrites ``!`` sequences inside double quotes.
Every one of those characters is also *data* the Bash guard needs, since
they are exactly the characters a shell treats as special, so each arrives
by ``chr()``: 33 ``!``, 34 ``"``, 36 ``$``, 39 ``'``, 92 backslash, 96
backtick.  ``tests/test_credential_guard.py`` enforces the prohibition, and
``TestGuardThroughARealShell`` runs the generated command through a real
bash so the wrapper's own quoting is exercised rather than assumed.
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


_PATH_REASON = "mureo credential guard: files under ~/.mureo are protected"

_PATH_GUARD_CODE = (
    "import sys,json,os; "
    # Fail closed: exit 1 is a non-blocking hook error in both hosts, so an
    # escaping exception would let the call through. A path that makes
    # realpath raise (an embedded NUL, say) must deny, not proceed.
    "sys.excepthook=lambda *a: (" + _deny_expr(_PATH_REASON) + ", "
    "sys.stdout.flush(), os._exit(0)); "
    "d=json.loads(sys.stdin.read() or '{}'); "
    "i=d.get('tool_input') or {}; "
    "p=str(i.get('file_path') or i.get('path') or i.get('notebook_path') or ''); "
    "e=os.path.expanduser(p); "
    "b=os.path.realpath(os.path.expanduser('~/.mureo')).lower(); "
    "bl=os.path.abspath(os.path.expanduser('~/.mureo')).lower(); "
    "r=os.path.realpath(e).lower() if p else ''; "
    "lp=os.path.abspath(e).lower() if p else ''; "
    + _deny_expr(_PATH_REASON)
    + " if p and (r==b or r.startswith(b+os.sep)"
    " or lp==bl or lp.startswith(bl+os.sep)) else None"
)

# Shell metacharacters, named once.  Most may not appear literally in the
# payload (see the NOTE in the module docstring), so each arrives as a
# chr() call: q1 ', q2 ", bs backslash, dl $, tk backtick, nl newline,
# pc %.  `ho` is the placeholder a quoted metacharacter collapses to — it
# must be none of: an identifier character (it has to read as a component
# boundary), a metacharacter, or a dot.
_CHARS = (
    "q1=chr(39); q2=chr(34); bs=chr(92); dl=chr(36); tk=chr(96); nl=chr(10); "
    "pc=chr(37); ho='='; mt='*?[]{},'; "
)

# The quoting automaton, as the step function of a left fold.  The state is
# a pair.  First, where we are: 0 unquoted, 1 single-quoted, 2
# double-quoted, 3 escaped (from unquoted), 4 escaped (inside double
# quotes).  Inside single quotes nothing is special, not even a backslash —
# the rule bash applies.
#
# Second, whether a `%` has appeared in the quoted span we are inside.  A
# quoted string is ordinary text, unless a program is going to build a path
# out of it: ``printf '%s.mure?/x'`` is a template whose metacharacters
# survive into a filename, and the shell then globs the result.  The flag
# resets on leaving the span, so the `%` in one argument cannot make the
# metacharacters of a later one live.
_QUOTE_STEP = (
    "lambda kv,x: ("
    "(1 if x==q1 else 2 if x==q2 else 3 if x==bs else 0) if kv[0]==0"
    " else (0 if x==q1 else 1) if kv[0]==1"
    " else (0 if x==q2 else 4 if x==bs else 2) if kv[0]==2"
    " else (0 if kv[0]==3 else 2),"
    " 1 if x==pc else (kv[1] if kv[0] else 0))"
)

# Rebuild the command with quoting resolved, one character at a time: drop
# the delimiters; drop the newline of a line continuation, since a shell
# removes the pair before it tokenises anything; turn a quoted
# metacharacter into the placeholder, because quoting makes it an ordinary
# character and no ordinary character in `.mureo` is a metacharacter; and
# turn the start of an expansion into `*/`.
#
# `*` because its text is unknown, and `/` because where it *ends* is
# unknown too: the characters after it in the command (`o` in `.mure$X`,
# `printf o` inside backticks) are not necessarily part of the same path
# component, so they must not extend the pattern being tested.
#
# `k>2` is the two escaped states: only there does a newline belong to a
# continuation. Inside single quotes a backslash is an ordinary character,
# so `.mu\\<newline>reo` in single quotes really is a name with a newline
# in it, and normalizing it away would over-block rather than protect.
#
# `%` becomes an expansion in *every* state, quoted or not, because it is
# the next program along that expands it, not this shell.
_NORMALIZE = (
    "''.join('' if (k==0 and x in q1+q2+bs) or (k==1 and x==q1)"
    " or (k==2 and x in q2+bs) or (k>2 and x==nl)"
    " else ('*/' if x in dl+tk+pc else (ho if k and not m and x in mt else x))"
    " for x,(k,m) in zip(c,st))"
)

# An expansion swallows the identifier run that names it: `$D` and `%s` are
# one unknown thing, not an unknown thing followed by the letters `d`/`s`.
# Collapsing them is what lets a single reading serve both rules — after
# it, `$D.mureo` reads as `*/.mureo`, whose dot sits at a boundary exactly
# like the one in `~/.mureo`, so the literal rule needs no separate scan of
# the raw text to find it.  This cannot hide a name: it removes only
# identifier characters, and every form the guard looks for contains a dot.
_COLLAPSE = "re.sub('[*]/[a-z0-9_]*', '*/', t)"

# A brace group stands for any of its alternatives.  One that contains a dot
# can supply the leading dot of a dotfile, so it becomes `.*`; any other
# becomes `*`.  Applied twice, which covers a group nested in a group.
_DEBRACE = "re.sub(gr, fb, re.sub(gr, fb, t))"

# Source of a python expression yielding the regex for one path component
# written as a shell pattern: a literal dot plus the run of characters a
# pattern may contain.  Neither ``/`` nor whitespace is in the set, so a run
# stops where the component does.  The class needs no backslash escapes:
# ``]`` comes first and ``-`` last, and ``!`` arrives via ``chr(33)``.
_PATTERN_COMPONENT = "'[.][]a-z0-9_.*?[^{},' + chr(33) + '-]*'"

_BASH_REASON = "mureo credential guard: commands that can reach ~/.mureo are blocked"

_BASH_GUARD_CODE = (
    "import sys,json,re,os,fnmatch,itertools; "
    # Fail closed: an escaping exception exits 1, which both hosts treat as a
    # non-blocking hook error, so every exception must deny instead.
    "sys.excepthook=lambda *a: (" + _deny_expr(_BASH_REASON) + ", "
    "sys.stdout.flush(), os._exit(0)); "
    "d=json.loads(sys.stdin.read() or '{}'); "
    "c=str((d.get('tool_input') or {}).get('command') or '').lower(); "
    + _CHARS
    + "st=list(itertools.accumulate(c, "
    + _QUOTE_STEP
    + ", initial=(0,0))); "
    # One reading of the command, built once, consumed by both rules below.
    "t=" + _NORMALIZE + "; "
    "t=" + _COLLAPSE + "; "
    "gr='[{][^{}]*[}]'; fb=lambda w: '.*' if '.' in w.group() else '*'; "
    "t=" + _DEBRACE + "; "
    "p=re.findall('(?:^|[^a-z0-9_])(' + " + _PATTERN_COMPONENT + " + ')', t); "
    "g=[x for x in p if set('*?[') & set(x) and fnmatch.fnmatchcase('.mureo', x)]; "
    "b=re.search('(^|[^a-z0-9_])[.]mureo', t) or g; "
    + _deny_expr(_BASH_REASON)
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
