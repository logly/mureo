"""Rules 1 to 4, and the Bash guard's payload assembled from every piece.

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
three cases the guard already reasons about and allows —
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
"""

from __future__ import annotations

from mureo._credential_guard.braces import _BRACE_HELPERS, _EXPAND
from mureo._credential_guard.chars import _CHARS, _SANITIZE
from mureo._credential_guard.path_guard import _STDIN
from mureo._credential_guard.quoting import (
    _NORMALIZE_CHAR,
    _QUOTE_INIT,
    _QUOTE_NEXT,
    _QUOTE_STEP,
)
from mureo._credential_guard.reasons import (
    _BASH_REASON,
    _BUDGET_REASON,
    _CRASH_REASON,
    _EMPTY_STDIN_REASON,
    _FILENAME_REASON,
    _HEREDOC_REASON,
    _OVERSIZE_REASON,
    _SPAN_REASON,
    _UNRESOLVED_REASON,
    _deny_expr,
)
from mureo._credential_guard.spans import _READINGS, _SPAN_STEP

# Source of a python expression yielding the regex for one path component
# written as a shell pattern: a literal dot plus the run of characters a
# pattern may contain.  Neither ``/`` nor whitespace is in the set, so a run
# stops where the component does.  The class needs no backslash escapes:
# ``]`` comes first and ``-`` last, and ``!`` arrives via ``chr(33)``.
_PATTERN_COMPONENT = "'[.][]a-z0-9_.*?[^{},' + chr(33) + '-]*'"

# The files rule 4 matches by name, so a tree search cannot walk to them
# without naming the directory. ``config.json`` is deliberately absent —
# see rule 4 in this module's docstring for why, and for what that costs.
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

_BASH_GUARD_CODE = (
    "import sys,json,re,os,fnmatch,functools,itertools; "
    # Fail closed: an escaping exception exits 1, which both hosts treat as a
    # non-blocking hook error, so every exception must deny instead.
    "sys.excepthook=lambda *a: (" + _deny_expr(_CRASH_REASON) + ", "
    "sys.stdout.flush(), os._exit(0)); "
    + _STDIN
    + "c=str((d.get('tool_input') or {}).get('command') or '').lower(); "
    # A guard that is merely slow is a guard that is bypassed: the host
    # kills a hook that overruns and that process exits non-zero without
    # printing the deny JSON, which is the non-blocking case. So an
    # oversized command is refused before any of the work below, and every
    # later step runs on the empty string instead.
    "bg=len(c)>65536; cc='' if bg else c; "
    + _CHARS
    + _SANITIZE
    + _QUOTE_NEXT
    + "st=list(itertools.accumulate(cc, "
    + _QUOTE_STEP
    + ", initial="
    + _QUOTE_INIT
    + ")); "
    # Whether the here-document latch ever closed over the command. It does
    # not change a single decision; it changes what the refusal is allowed to
    # claim, because within the latch the guard has read text without
    # resolving quoting and cannot say whether a reference it found is live.
    + "lt=bool(st[-1][2]); "
    # One pass over the command, producing the readings: the command with
    # every expansion replaced by a placeholder, and one reading per
    # expansion body. Brace expansion then turns those into the list of
    # readings the shell would produce; every rule sees all of them, so none
    # depends on a guess about any single one.
    + _NORMALIZE_CHAR
    + _SPAN_STEP
    + _READINGS
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
    "f=[s for s in ls + lq if re.search(" + _FILENAME_PATTERN + ", s + chr(32))]; "
    # `ut`, `un` and `nu` are answered on their own, before rules 1 to 3:
    # structure the guard could not resolve denies, but each denies for its own
    # reason rather than borrowing one that claims a match, or one that names a
    # step that did not run. `bg` is answered first of all. Within the
    # here-document latch rules 1 to 3 cannot claim the reference is live
    # either, so the refusal they produce says so.
    #
    # Rules 1 and 4 see both reading sets, so a name the shell will reach is
    # found whether the quoting around it was this shell's to resolve or the
    # next one's. Rules 2 and 3 stay on the first set and the raw text: rule 2
    # asks whether a pattern matches, and the second set's answer to that
    # question would be "every quoted glob does".
    "b=[s for s in ls + lq if re.search('(^|[^a-z0-9_])[.]mureo', s)] or g or h; "
    "fb=[] if b or ut or un or nu else f; "
    + _deny_expr(_EMPTY_STDIN_REASON)
    + " if not ib else ("
    + _deny_expr(_OVERSIZE_REASON)
    + " if bg else ("
    + _deny_expr(_SPAN_REASON)
    + " if ut else ("
    + _deny_expr(_BUDGET_REASON)
    + " if un else ("
    + _deny_expr(_UNRESOLVED_REASON)
    + " if nu else ("
    + _deny_expr(_BASH_REASON)
    + " if b and not lt else ("
    + _deny_expr(_HEREDOC_REASON)
    + " if b else ("
    + _deny_expr(_FILENAME_REASON)
    + " if fb else None)))))))"
)
