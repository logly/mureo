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

  Rule 3 reads the raw text too, and that is not the thing this paragraph
  forbids — read this before adding another rule that does the same,
  because the difference is the whole point.  The split-brain bug was
  *partition*: each rule owned one string and was blind to the other, so
  an obfuscation resolved on one axis walked past the rule that owned the
  other.  Rule 3 is a *union* — it runs against the readings AND the raw
  command, so nothing is invisible to it and no fold can open a hole
  underneath it.  It also does not want anything the fold destroys: it
  looks for a pattern that a program other than the shell will expand,
  and the fold models the shell alone, so there is nothing for
  ``_COLLAPSE`` to preserve on its behalf.  A rule reading the raw text
  *instead of* the readings would be the old bug returning.

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

  Rules 1 and 2 both read the *directory* name, and for a long time that
  was all the guard read.  It meant a command that never spelled the
  directory at all walked straight past: ``find ~ -path '*mureo*' -exec
  cat {} ;`` and ``find ~ -name credentials.json -exec cat {} ;`` both
  printed the credentials, with no obfuscation and no adversarial intent
  required.  "Look for any leftover credential files under my home
  directory" is an ordinary instruction, and it is exactly the accident
  this guard exists for.  Rules 3 and 4 read the two things such a command
  does write down.

  Rule 3 (a pattern reaching into the name without the dot).  Rule 2 only
  considers components that begin with a literal ``.``, so ``*mureo*`` —
  which ``find -path`` happily matches against the full path, leading
  period included — was not a candidate.  Rule 3 denies when a glob
  metacharacter stands immediately before the literal ``mureo``.  It is
  deliberately narrower than "any pattern that could match": ``mureo`` has
  to be written out, so working inside a checkout of this very repository
  (``grep -r foo mureo/``) is untouched, while ``-path '*mureo*'`` and
  ``-name '*mureo*'`` are not.

  Rule 3 reads the raw command text as well as the normalized readings,
  and that is the point of it.  Normalization models what the *shell*
  expands, so it neutralizes a quoted ``*`` — correctly, for the shell.
  But the quotes in ``-path '*mureo*'`` are there precisely to keep the
  shell off the pattern so that ``find`` can expand it itself, and by the
  time the normalized reading exists the pattern has become ``=mureo=``
  and there is nothing left to match.  A pattern meant for a downstream
  program is written literally in the command; that is where rule 3 looks
  for it.  Every other rule stays on the normalized readings, because
  every other rule is about what the shell will do.

  Rule 4 (the protected filenames).  A tree search can name the file
  instead of the directory, so the filenames are candidates in their own
  right — but only where the name stands on its own, with no ``/`` before
  it.  That restriction is the rule.  A name with a path in front of it is
  not a search but a specific file, and which file it is has already been
  settled by rules 1 to 3 from the directory: ``~/.mureo/credentials.json``
  denies on rule 1, while ``~/backups/credentials.json`` is the user's own
  file and refusing it would be the guard overreaching into a directory it
  does not protect.  Without the restriction the rule also contradicted
  three cases this file already reasons about and allows —
  ``cat "$HOME/.mure?/credentials.json"`` and the two fully-quoted paths —
  where the name is written but the shell cannot reach the directory.

  ``config.json`` is deliberately NOT among them.  It is one of the most
  common filenames in software, and denying it would stop ``cat
  config.json`` in every project the agent ever works in — the guard is
  judged by whether it makes the common accident less likely *without
  blocking real work*, and that trade lands the wrong way.  The cost is
  stated rather than hidden: ``find ~ -name config.json -exec cat {} ;``
  still reads that one file.  The names that are matched are specific
  enough that a project file colliding with one is rare, and when it does
  the deny reason says to use the Read tool, which is guarded by path and
  so allows a same-named file anywhere outside ``~/.mureo``.

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

  Brace groups are then *expanded*, not approximated: the normalized text
  becomes the list of strings the shell would produce, and every rule runs
  against all of them.  ``~/.mure{o,x}`` and ``~/{.,z}mureo`` are caught
  because ``.mureo`` is literally among the results.

  An earlier version folded each group to one placeholder and guessed
  which — ``.*`` if the group held a dot anywhere, ``*`` otherwise — and
  the guess is what broke.  ``~/.{mureo,x.y}`` has a dot before the group
  and a dot inside an alternative that has nothing to do with the
  directory; the fold read them as one, produced ``..*``, which requires
  two leading dots, and meanwhile the literal ``.mureo`` that rule 1 would
  have matched had already been replaced.  Both rules passed and the file
  was read.  Expanding removes the guess instead of refining it.

  Two groups are not lists of alternatives and cannot be enumerated this
  way: a sequence (``.{l..n}ureo`` covers ``m`` without the letter
  appearing anywhere) and one with absurdly many alternatives.  Those fall
  back to *both* coarse readings, ``*`` and ``.*``, which between them
  cover "supplies a leading dot" and "does not" — the pair the single
  guess was missing.  A group with neither a comma nor a ``..`` is not
  brace expansion at all; bash leaves ``{eo}`` literal, so the guard does
  too, and ``~/.mur{eo}`` is allowed because it opens nothing.

  Expansion has a budget — eight passes, 400 strings — so a pathological
  command cannot explode the hook.  **Whatever the budget does not resolve
  is refused.**  Anything still holding an expandable group after the
  passes denies on that ground alone, without being examined further.

  That rule replaced a fallback that collapsed leftovers coarsely, and it
  is worth saying plainly why, because the docstring claimed the fallback
  "over-approximates rather than dropping candidates" and that was false.
  Past ten levels of nesting the collapse left literal ``{`` and ``}`` in
  the candidates, which ``fnmatch`` reads as ordinary characters, so
  *neither* rule fired: ``cat ~/.{z11,{z10,…{z1,mureo}}}/…`` — ninety
  characters, no exotic syntax — was allowed while bash read the file.  A
  budget that shrugs is a bypass with a length requirement.  The general
  form of the rule is: when the guard cannot compute what the shell would
  produce, it denies.

  What that refuses in practice is a command with more than eight brace
  groups, or one whose expansion exceeds 400 strings.  Of twenty-one
  brace-using everyday commands — ``awk '{print $1}'``, ``find . -exec rm
  {} ;``, ``mkdir -p build/{lib,bin,share}``, ``mv file{1..10}.txt``,
  ``jq '{name: .name}'``, eight groups on one line — exactly one is
  refused: nine groups on one line.  Quoted braces never reach this step,
  and a group with no comma and no ``..`` is literal to bash and to ``fe``.

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
    them, so ``printf '%s.%s' a b`` denies.  Of twenty ``%``-heavy
    everyday commands (``date +%Y-%m-%d``, ``git log --format=%h``,
    ``awk '{printf "%.2f", $1}'``, ``grep '100%'``, a commit message
    reading ``30% faster``) that is the only one that does;
  - brace structure the expansion budget could not resolve: more than
    eight groups in one command, or an expansion whose normalized text
    exceeds 200 KB;
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
  (unknowable, so ``*``), an expansion's *extent* (unknowable, so ``/``),
  and a ``%`` template's result.  Two more — a sequence group and a group
  with more than 64 alternatives — still take both coarse readings rather
  than being enumerated; enumerating them is a contained change and the
  place to start if this list is ever shortened again.

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
    leading dot} x {how deeply it nests: 0, 1, 2, 3, 5, 8, 9, 11, 14, 20}
    x {where}.  2698 members.  ``pytest -m slow`` runs all of them,
    executing each in a throwaway ``HOME`` to confirm it really does read
    the marker file and then asking the guard: all 2698 read it, all 2698
    deny.  The default run checks an evenly-strided sample of 118, so
    every commit defends the property even without the slow pass;
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
    " for x,(k,m) in zip(cc,st))"
)

# An expansion swallows the identifier run that names it: `$D` and `%s` are
# one unknown thing, not an unknown thing followed by the letters `d`/`s`.
# Collapsing them is what lets a single reading serve the rules — after
# it, `$D.mureo` reads as `*/.mureo`, whose dot sits at a boundary exactly
# like the one in `~/.mureo`, so the literal rule needs no separate scan of
# the raw text to find it.  This cannot hide a name: it removes only
# identifier characters, and every form the guard looks for contains a dot.
_COLLAPSE = "re.sub('[*]/[a-z0-9_]*', '*/', t)"

# Brace expansion, done properly: the command is turned into the *list* of
# strings the shell would produce, and every rule runs against all of them.
#
# The previous version folded a group to one placeholder and guessed which:
# `.*` if the group contained a dot anywhere, `*` otherwise. It never asked
# *where* the dot was, so `~/.{mureo,x.y}` — a dot before the group and a
# dot inside an unrelated alternative — folded to `..*`, which wants two
# leading dots, while the literal `.mureo` that rule 1 would have caught had
# already been replaced. It read the credentials file. Expanding removes the
# guess rather than refining it, and it also stops over-blocking
# `mv .{foo,bar}`, since each alternative is now judged on its own.
#
# `fe` finds the first *expandable* innermost group, skipping `{a}`, which
# bash leaves alone — a group is expandable only with a comma or a `..`.
# `al` gives its alternatives; a sequence (`{l..n}`) is not a list of
# alternatives this can enumerate, and neither is a group with absurdly many
# of them, so those are read coarsely — see `sq` below for which of the two
# coarse readings applies and why.
#
# `ga` excludes the newline from a group's contents, because an unquoted
# newline is a token separator: bash will not expand a brace group across
# one, so neither should this. Matching across newlines would also let two
# unrelated braces on different lines of a multi-line command pair up and
# swallow everything between them.
_BRACE_HELPERS = (
    "ga='[{][^{}' + nl + ']*[}]'; "
    "fe=lambda s: next((w for w in re.finditer(ga, s)"
    " if ',' in w.group() or '..' in w.group()), None); "
    # A sequence bash recognises has endpoints that are integers or single
    # *letters*, and neither can be a dot: an integer never contains one,
    # and a letter range lies within ASCII 65..122, well clear of 46. So a
    # recognised sequence cannot supply the leading dot of a dotfile and
    # `*` alone reads it. Without that, `echo {1..100}` folded to `.*` and
    # denied — a common idiom, and not an attempt at anything.
    #
    # The `.*` reading is kept for everything this does not recognise as a
    # sequence: a three-part `{a..z..2}`, a range with an endpoint that is
    # neither, anything malformed. Those are refused conservatively rather
    # than reasoned about — bash leaves most of them literal (`{-..0}` is
    # not a sequence at all and stays as written), so the cost is an
    # over-block on text nobody types and the benefit is not having to be
    # right about a syntax this does not parse.
    "sq=lambda v: (lambda e: ['*'] if len(e)==2 and"
    " ((e[0].lstrip(chr(45)).isdigit() and e[1].lstrip(chr(45)).isdigit())"
    " or (len(e[0])==1 and len(e[1])==1 and not"
    " (min(ord(e[0]),ord(e[1]))<=46<=max(ord(e[0]),ord(e[1])))))"
    " else ['*','.*'])(v.split('..')); "
    "al=lambda w: (lambda v: v if ',' in w.group() and len(v)<=64"
    " else sq(w.group()[1:-1]))(w.group()[1:-1].split(',')); "
    "ex=lambda s: (lambda w: [s[:w.start()] + a + s[w.end():] for a in al(w)]"
    " if w else [s])(fe(s)); "
)

# Eight passes expand eight groups, innermost first, so nesting resolves as
# the outer group becomes innermost, and a cap stops a pathological command
# from exploding the hook.
#
# Whatever is left when the budget runs out is *refused*, not approximated:
# `un` collects the candidates that still hold an expandable group, and a
# non-empty `un` denies on that ground alone. The budget used to end in a
# coarse fallback of two `re.sub` collapses, which past ten levels of
# nesting left literal braces in the candidates — text `fnmatch` reads as
# ordinary characters, so neither rule fired and
# `~/.{z11,{z10,...{z1,mureo}}}` was allowed while bash read the file. A
# budget that shrugs is a bypass with a length requirement.
#
# The rule is general: when the guard cannot compute what the shell would
# produce, it denies. Nothing legitimate is refused by it — a quoted
# `awk '{print $1}'` never reaches this step, and `find . -exec {} \\;` has
# neither a comma nor a `..`, so bash leaves it literal and so does `fe`.
# What is left is a command with more than eight brace groups, or one whose
# expansion exceeds 400 strings, and neither is a thing anyone types.
_EXPAND = (
    "rs=functools.reduce(lambda q,_: q if q[1] else"
    " (lambda n: (q[0],True) if sum(map(len,n))>200000"
    " else (n, n==q[0]))"
    "([y for x in q[0] for y in ex(x)]), range(8), ([t],False)); "
    "ls=rs[0]; un=[x for x in ls if fe(x)]; "
)

# Source of a python expression yielding the regex for one path component
# written as a shell pattern: a literal dot plus the run of characters a
# pattern may contain.  Neither ``/`` nor whitespace is in the set, so a run
# stops where the component does.  The class needs no backslash escapes:
# ``]`` comes first and ``-`` last, and ``!`` arrives via ``chr(33)``.
_PATTERN_COMPONENT = "'[.][]a-z0-9_.*?[^{},' + chr(33) + '-]*'"

_BASH_REASON = "mureo credential guard: commands that can reach ~/.mureo are blocked"

# The files rule 4 matches by name, so a tree search cannot walk to them
# without naming the directory. ``config.json`` is deliberately absent —
# see rule 4 in the module docstring for why, and for what that costs.
GUARDED_FILENAMES = (
    "credentials.json",
    "credentials.json.bak",
    "agency.json",
    "setup_state.json",
)

# One alternation over those names, matched only where the name stands on
# its own — no ``/`` before it. That restriction is what keeps the rule on
# its own subject. A name with a path in front of it is not a search, it
# is a specific file, and which file it is has already been decided by
# rules 1 to 3 from the directory: ``~/.mureo/credentials.json`` denies on
# rule 1, and ``~/backups/credentials.json`` is somebody's own file that
# the guard has no business refusing. Only the bare form — ``find ~ -name
# credentials.json``, ``locate credentials.json`` — is the shape rule 4
# exists for.
#
# Dots become ``[.]`` rather than ``\.`` because the payload may not
# contain a backslash, and the trailing boundary is a character class
# rather than ``$`` because it may not contain one of those either — the
# candidate has a space appended before the search so the end of the
# string counts as a boundary.
_FILENAME_PATTERN = (
    "'(^|[^a-z0-9_./-])("
    + "|".join(n.replace(".", "[.]") for n in GUARDED_FILENAMES)
    + ")[^a-z0-9_-]'"
)

# Rule 4 says what actually matched rather than borrowing _BASH_REASON.
# Told the command "can reach ~/.mureo" when it never mentioned the
# directory, an agent goes looking for a reference that is not there and
# retries; told a credential filename appeared, it can tell at once
# whether it meant its own project file, and the Read tool takes that one.
_FILENAME_REASON = (
    "mureo credential guard: this command names a mureo credential file; "
    "if you meant a file of your own with the same name, read it with the "
    "Read tool instead"
)

# A refusal is not a match, and the agent reading the reason acts on the
# difference: told the command references ~/.mureo, it goes looking for a
# reference that is not there and retries. This one says what actually
# happened — the command was too long to read, so nothing was concluded
# about it.
_OVERSIZE_REASON = (
    "mureo credential guard: command over 65536 bytes was refused unread, "
    "not analysed; shorten it or run it in pieces"
)

_BASH_GUARD_CODE = (
    "import sys,json,re,os,fnmatch,functools,itertools; "
    # Fail closed: an escaping exception exits 1, which both hosts treat as a
    # non-blocking hook error, so every exception must deny instead.
    "sys.excepthook=lambda *a: (" + _deny_expr(_BASH_REASON) + ", "
    "sys.stdout.flush(), os._exit(0)); "
    "d=json.loads(sys.stdin.read() or '{}'); "
    "c=str((d.get('tool_input') or {}).get('command') or '').lower(); "
    # A guard that is merely slow is a guard that is bypassed: the host
    # kills a hook that overruns and that process exits non-zero without
    # printing the deny JSON, which is the non-blocking case. So an
    # oversized command is refused before any of the work below, and every
    # later step runs on the empty string instead.
    "bg=len(c)>65536; cc='' if bg else c; "
    + _CHARS
    + "st=list(itertools.accumulate(cc, "
    + _QUOTE_STEP
    + ", initial=(0,0))); "
    # One reading of the command, built once. Brace expansion turns it into
    # the list of readings the shell would produce; every rule sees all of
    # them, so none depends on a guess about any single one.
    "t=" + _NORMALIZE + "; "
    "t="
    + _COLLAPSE
    + "; "
    + _BRACE_HELPERS
    + _EXPAND
    + "p=[x for s in ls for x in re.findall("
    "'(?:^|[^a-z0-9_])(' + " + _PATTERN_COMPONENT + " + ')', s)]; "
    "g=[x for x in p if set('*?[') & set(x) and fnmatch.fnmatchcase('.mureo', x)]; "
    # Rule 3: a metacharacter standing immediately before the written-out
    # name. `find -path` matches the whole path, leading period included,
    # so `*mureo*` reaches the directory although no component of it
    # begins with a dot and rule 2 therefore never sees it.
    #
    # This one reads the RAW text as well as the normalized readings, and
    # that is the whole point. Normalization models what the SHELL expands,
    # so it correctly neutralizes a quoted `*` — but the quotes in
    # `-path '*mureo*'` exist precisely to keep the shell off the pattern
    # so that `find` can expand it itself. Judged on the normalized
    # reading alone the pattern has already become `=mureo=` and nothing
    # fires. What a downstream program will expand is written literally in
    # the command, so that is where to look for it.
    "h=[x for x in ls + [cc] if re.search('[]*?[]mureo', x)]; "
    # Rule 4: the protected filenames, at a component boundary. A space is
    # appended so the end of a candidate counts as a boundary without the
    # pattern needing a `$`, which the payload may not contain.
    "f=[s for s in ls if re.search(" + _FILENAME_PATTERN + ", s + chr(32))]; "
    # `un` first: structure the guard could not resolve denies on its own.
    # `bg` is answered separately below, because it needs its own reason.
    "b=un or [s for s in ls if re.search('(^|[^a-z0-9_])[.]mureo', s)]"
    " or g or h; "
    # Rule 4 carries its own reason: told the command "can reach ~/.mureo"
    # when it never mentioned the directory, an agent goes looking for a
    # reference that is not there. This one says what actually matched.
    "fb=[] if b else f; "
    + _deny_expr(_OVERSIZE_REASON)
    + " if bg else ("
    + _deny_expr(_BASH_REASON)
    + " if b else ("
    + _deny_expr(_FILENAME_REASON)
    + " if fb else None))"
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
