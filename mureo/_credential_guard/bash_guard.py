"""Rules 1 to 4, and the Bash guard's payload assembled from every piece."""

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
# see rule 4 in the credential_guard.py docstring for why, and for what that costs.
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
