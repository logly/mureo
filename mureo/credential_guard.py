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
  applies four rules to it.  Any one of them denies.  Rules 1 and 2 read
  the directory name, rules 3 and 4 the two things a search that never
  spells the directory does write down.

  "Once" means one pass producing *sets* of readings — the command with its
  expansions taken out of its structure, the body of each expansion, and
  then every string brace expansion makes of those, read both the way this
  shell reads a quoted metacharacter and the way the next shell along does
  — and every rule runs against every reading it is entitled to.  What is
  forbidden is a rule that owns a string of its own; see bash_guard.

  How each step works, and why, is written down beside the code that does
  it: rules 1 to 4 and the single-reading principle in
  :mod:`mureo._credential_guard.bash_guard`, the quoting fold in
  :mod:`~mureo._credential_guard.quoting`, expansion spans and the second
  set of readings in :mod:`~mureo._credential_guard.spans`, and brace
  expansion and its budget in :mod:`~mureo._credential_guard.braces`.
  What follows here is what all of them add up to: what the guard refuses
  that it need not, what it does not cover, and how both are checked.

  Deliberate over-blocks, all in the safe direction:

  - anything unquoted that really does glob dotfiles: ``ls .*``, ``ls -d
    .??*``, ``rm -rf .[!.]*`` all reach ``~/.mureo`` from ``$HOME`` and
    all deny;
  - a component holding an expansion is unknown text, so ``ls .$X`` and
    ``cat .$(cmd)`` deny.  An arithmetic expansion is not treated any
    differently, so ``echo .$((1+1))`` and ``cat ~/.mure$((0))?/x`` deny
    too, though neither can reach the directory;
  - a format string that builds ``<something>.<something>`` is the shape
    of ``printf '%s.mureo/…' ~/``, and nothing in the text distinguishes
    them, so ``printf '%s.%s' a b`` denies.  ``%``-heavy everyday commands
    (``date +%Y-%m-%d``, ``git log --format=%h``, ``awk '{printf "%.2f",
    $1}'``, ``grep '100%'``, a commit message reading ``30% faster``) do
    not: the shape it refuses is a ``%`` template building ``x.y``;
  - brace structure the expansion budget could not resolve: more than
    eight groups in one command, an inert span nested past the passes the
    mapping is given, or an expansion whose normalized text exceeds the
    byte budget, in the first reading set; and in a quoted string or a
    here-document body the second set reads, a group it cannot enumerate,
    or an indivisible run of comma-bearing groups with no space anywhere
    between them — eleven or more two-way ones, a single group of more than
    1,024 alternatives, three or more letter ranges, or group-bearing words
    whose candidates pass the total — a run a shell re-reading the string
    would multiply too.  The first set spends its budget over all its
    readings at once; the second spends a bounded budget per word, over the
    inner shell's own words, and counts only the words that hold a group;
  - an expansion whose body *ends* on a prefix of the directory's name,
    which is what reading the result as text of unknown extent costs.  A
    bare ``.`` is such a prefix, so ``echo $(ls .)`` denies although what it
    produces is a listing.  The expansion's result is not in the text, and a
    guard that cannot tell has to answer on the deny side; the bound on the
    cost is that the body has to end there — ``echo $(ls -a)``, ``echo
    $(basename a.txt)``, ``cd $(dirname a/b.txt)`` and ``diff <(sort a)
    <(sort b)`` are all allowed;
  - brace structure whose contents did not resolve: a ``{...}`` the shell
    would expand whose contents hold both a separator and an expansion
    (``echo {a, $(date)}``, ``echo {a, $x}``), or a separator of the second
    kind.  Bash expands neither, so nothing real is refused by the first
    half; the second half costs a comma-bearing group written around text
    in another language, measured with the here-document bullet below.
    Both are the price of failing closed on contents the guard cannot
    account for rather than ignoring them, and both say so in their own
    reason rather than borrowing the budget's;
  - structure the span fold could not pair up: ``cat ~/x$(``, an unclosed
    backtick, and an unquoted ``{`` with no ``}`` after it (``echo a{b``,
    which bash does print).  The last is the price of refusing a brace group
    left open around an expansion, where the group's closing brace is the
    one the expansion took: the two are the same shape, and the guard cannot
    tell them apart without deciding the extent it just failed to decide.  A
    *closing* brace with nothing to close is not refused — ``echo a}b`` is
    allowed — because a stray closer hides nothing;
  - after an unquoted ``<<``, whatever a quote used to neutralise is live.
    An unmatched ``(`` or ``{`` in a body is structure the span fold cannot
    pair up, so ``print("{")`` and ``print("(")`` as the body of a python
    here-document are refused on the unresolved-structure ground above;
    and a quoted pattern written after a body is read as a pattern, so
    ``ls '.*'``, ``sed 's/.*//'`` and ``find . -name '.*'`` deny on the
    line after a terminator although the bullet above allows all three on
    their own.  A body holding a comma-bearing brace group around a call
    (``d = {"n": len([1, 2])}``) was on this list until a body's
    punctuation stopped being read as a command line's; it is an everyday
    script, and refusing it was the kind of cost that teaches people to turn
    a guard off.  What is left is the price of reading a body the way bash
    reads it, and the alternative, resolving quoting inside a body, is not
    something bash does, and a guard that has to agree with bash about where
    the shell text is cannot do it either.  Within the latch a refusal from
    rules 1 to 3 cannot claim the reference is live, because the guard has
    read text without resolving quoting and does not know; it says that
    instead of claiming the command can reach the directory;
  - a command longer than 64 KB, which is refused unread (see below);
  - sequence syntax this does not recognise — a three-part ``{a..z..2}``,
    an endpoint that is neither an integer nor a single letter — which is
    refused rather than reasoned about.  Bash expands a sequence only for
    those two endpoint kinds, so ``{-..0}`` is not a sequence at all and
    stays literal; the refusal costs nothing real.  Sequences that *are*
    recognised are read exactly, so ``echo {1..100}``, ``for i in
    {1..5}``, ``printf '%s' {A..Z}`` and ``touch file{1..20}.log`` are
    allowed — every one of them denied until the endpoints were consulted,
    which is the kind of over-block that teaches people to turn a guard
    off.

  Brace expansion itself used to be on this list — ``mv .{foo,bar}`` and
  ``rm .{a,b,c}`` denied although neither can name the directory.
  Expanding the alternatives exactly, rather than folding them to a
  placeholder, removed those: each alternative is judged on its own, and
  both are allowed.  That is the shape of the right fix for the remaining
  entries — compute what the shell would produce instead of approximating
  it — and where that is impossible, refuse rather than approximate.

  The coarse approximations that are left: an expansion's *text*
  (unknowable, so ``*`` in the command reading and a trailing wildcard on the
  body's), an expansion's *extent* (unknowable, so ``/``), and a ``%``
  template's result.  Two more — an unrecognised sequence group and a group
  with absurdly many alternatives — still take a coarse reading in the first
  reading set rather than being enumerated: a recognised sequence takes
  ``*`` alone, since neither an integer nor a letter can be a leading dot,
  and the other forms take both ``*`` and ``.*``.  The second reading set
  enumerates both of these where it can — a comma list whole, a letter range
  as a superset of the characters bash makes of it, an integer sequence as
  one endpoint — and refuses what it cannot.

  What the guard does not cover — measured, not assumed, and pinned by
  ``test_known_open_bypasses``:

  - the shell's own options.  ``shopt -s dotglob; cat ~/*/x`` reads the
    file; the command text says nothing about whether ``dotglob`` is set,
    and it can have been set in an earlier call on the same persistent
    shell or in the user's rc file.  Denying every ``*`` instead is not an
    option;
  - anything whose text the command does not contain: a name taken from a
    variable set elsewhere (``cat ~/$P/x``), or one written in a notation
    that has to be decoded first (``cat ~/$'\\x2emureo'/x``).  Every rule
    can only read what is written down.  Where the text *is* written down
    the guard does see it, which is why ``P=.mure?; cat ~/$P/x`` denies —
    and why a name an expansion assembles out of text its own body spells
    out is now decided, since a body's reading ends in a wildcard.  That
    narrows this entry rather than closing it: a body that spells none of
    the name is still a body with nothing in it to read;
  - extended globs (``.mure@(o|x)``), which bash parses only with
    ``extglob`` set, and which ``fnmatch`` does not implement;
  - patterns for *sibling* names (``~/.mur*_backup``): rule 2 asks only
    whether a pattern matches ``.mureo`` itself, whereas rule 1 does deny
    literal siblings such as ``~/.mureo_backup``;
  - ``config.json`` reached by a filename search, for the reason given
    with rule 4: the name is too common to deny;
  - a symlink into the directory under a name that mentions neither the
    directory nor a protected filename (``cat ~/notes/backup.json`` where
    that path is a link to the credentials file).  The *path* guard
    resolves symlinks in both directions and closes this; the Bash guard
    never touches the filesystem, so it cannot.  The two guards protect
    the same directory with different reach, and this is where they
    differ.

  The first two are not closable by inspecting command text, and no
  further rule should be added pretending otherwise.

  What is actually checked, and where — every number below is produced by
  committed code, not by a measurement someone once took:

  - ``tests/credential_guard_product.py`` builds a product of {how the
    parent directory is supplied: literal, ``$HOME``, ``"$HOME"``,
    ``$VAR``, ``"$VAR"``, ``${VAR}``, ``$VAR$EMPTY``, ``$1``, ``$(cmd)``,
    backtick} x {how the name is broken: not at all, continuation, two
    continuations, single-quote split, single-quoted character,
    double-quote split, double-quoted character, escaped character, class,
    wildcard, brace here, brace tail, brace whole, sequence, star} x {what
    the breaking form contains: plain, an alternative with its own dot,
    with two, a backup-looking name, a nested group, a metacharacter, a
    leading dot, a substitution, a substitution holding a space, a
    backtick substitution, an arithmetic expansion} x {how deeply it
    nests: 0, 1, 2, 3, 5, 8, 9, 11, 14, 20} x {where}.  3098 members.
    ``pytest -m slow`` runs all of them, executing each in a throwaway
    ``HOME`` to confirm it really does read the marker file and then
    asking the guard: all 3098 read it, all 3098 deny.  The default run
    checks an evenly-strided sample of 135, so every commit defends the
    property even without the slow pass;
  - the nesting cliff has its own table: every depth from 1 to 20 with
    two, three and five alternatives per level, 60 cells, run by default.
    Each asserts that the command really reads the marker file *and* that
    the guard denies it.  Against the commit before the refusal rule the
    deeper cells were allowed while bash read the file, the cliff falling
    at depth 11 for two alternatives per level and earlier for more;
  - the resource bounds have their own tests: expansion bombs up to
    multi-megabyte commands must still answer, and the 64 KB boundary must
    refuse on one side and not the other.

  Older figures that once appeared here — a random single-character fuzz —
  are gone rather than restated, because nothing in the repository
  reproduces them.  A number in a docstring with no committed artifact is
  a claim about the past, not a property of the code; if a measurement is
  worth quoting it is worth committing the thing that produces it.

  Each round of bugs here has been a product of axes the generator only
  walked the margins of.  It emitted continuations and it emitted
  substitutions, but never a continuation *inside* a substituted parent.
  Then it emitted brace groups, but every alternative was inert filler, so
  a group holding an unrelated dot could not be produced.  Then it had a
  "nested group" filler at one fixed depth, so 1510 members all sat at
  depth two or less and the cliff at eleven was invisible.  Each time the
  missing dimension was one level *inside* the last one added.

  Take the pattern rather than the instances: a form the generator cannot
  produce is a form nothing here has checked, and that applies to the
  insides of forms, to how deeply they nest, and to combinations of them,
  not only to the list of features.  Before trusting a number in this
  docstring, look at whether the generator can express the shape it claims
  to cover — and prefer a rule that fails closed on what it cannot resolve
  over a measurement that says the gap is not reachable.

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

Failing closed is about time as well as exceptions.  ``sys.excepthook``
catches what Python raises; it cannot catch the host killing a hook that
overruns, and that process exits non-zero *without* printing the deny
JSON — which is precisely the non-blocking case where the tool call
proceeds.  A guard that is merely slow is a guard that is bypassed, and a
4 MB command of nested brace groups used to take it there: no answer in
45 seconds, 1.95 GB resident.  Three bounds keep that shut, all of them
cheap: the command is refused unread above 64 KB, expansion is budgeted on
total normalized bytes rather than on how many candidates there are, and a
pass that has to revert stops the loop instead of letting the remaining
seven recompute and discard the same expansion.  Multi-megabyte bombs now
answer in about a fifth of a second.  Nothing legitimate comes near 64 KB;
if that ever stops being true, raise the bound deliberately rather than
letting the work grow to fit.

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

# The payloads are assembled in mureo._credential_guard, one module per
# step.  What callers and tests import is re-exported here: the payloads,
# the protected filenames, and the deny reasons callers refer to by name,
# with the check on them.  Nothing here uses the re-exports, hence the
# blanket per-import noqa.  The crash and empty-stdin reasons are built into
# the payloads and referred to by no caller, so they are not among the
# re-exports; tests that sweep every reason read the reasons module directly.
from mureo._credential_guard.bash_guard import (  # noqa: F401
    _BASH_GUARD_CODE,
    GUARDED_FILENAMES,
)
from mureo._credential_guard.path_guard import _PATH_GUARD_CODE
from mureo._credential_guard.reasons import (  # noqa: F401
    _BASH_REASON,
    _BUDGET_REASON,
    _FILENAME_REASON,
    _HEREDOC_REASON,
    _OVERSIZE_REASON,
    _PATH_REASON,
    _SAFE_REASON_CHARS,
    _SPAN_REASON,
    _UNRESOLVED_REASON,
    _deny_expr,
)

# Unique identifier used to detect (and upgrade/remove) mureo-installed hooks.
GUARD_TAG = "[mureo-credential-guard]"

# Matchers are regexes over the tool name. PATH_TOOLS_MATCHER lists the
# Claude Code tools that receive a filesystem path; entries for tools a host
# does not expose (e.g. Codex has no Read tool) simply never fire.
PATH_TOOLS_MATCHER = "Read|Edit|Write|Grep|Glob|NotebookEdit"
BASH_MATCHER = "Bash"


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
