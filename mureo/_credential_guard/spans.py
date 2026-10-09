"""Expansion spans, and the readings the command is split into."""

from __future__ import annotations

from mureo._credential_guard.quoting import _COLLAPSE, _QUOTE_INIT

# An expansion is one indivisible token, and the characters inside it are not
# the command's.  The separators, parentheses and *braces* within `$(...)`,
# `${...}`, `$((...))`, a backtick pair or `<(...)` are the expansion's own:
# bash neither splits a word nor opens a brace group on them.  So
# `~/.mur{e,${q}}o/<file>` is one word whose group has two alternatives, and
# the first of them is the real protected directory — while a reading that
# pairs the group's `{` with the *parameter expansion's* `}` sees no group at
# all and lets the command through.
#
# The step below is the fold that finds those spans.  It runs on the quoting
# states, so only a character the shell would act on can open or close one:
# inside single quotes, and after a backslash, a `(` is an ordinary
# character.  A span opens on `(` preceded by one of `$ < > @ ? * + !`, on `{`
# preceded by `$`, and on a backtick (which toggles).  Inside a span, `(` and
# `{` nest and `)` and `}` close, each against the opener it belongs to — a
# `}` cannot close a `$(`, which is how a command that leaves an expansion
# open is told apart from one that does not.
#
# The state is a stack as a linked list — `(entry, parent)` — so pushing and
# popping are O(1) and a deeply nested command cannot turn the fold
# quadratic.  An entry is `(closer, span)`: `P`/`B`/backtick mark an entry
# that *is* an expansion, `)`/`}` one that is merely nested inside the
# command, and `span` numbers the reading the characters under it belong to.
# A closer with nothing to close is ignored rather than treated as an error:
# `case x in a)` and `esac` are ordinary shell.
#
# Each step also yields what the character contributes and which reading it
# contributes to, so grouping the output by reading is all that is left to do.
# A span's opening sigil already normalizes to `*/` (`$` and the backtick do;
# an unquoted `<` or `>` is a separator placeholder and the rest read as
# themselves), its brackets contribute nothing, and its closer contributes
# the boundary placeholder so that the identifier collapse stops there — `$(x)credentials.json` must stay
# as visible as `$(x) credentials.json`.
_SPAN_STEP = (
    "lv=lambda k: k==0 or k==2; "
    "sg=dl+'<>@?*+'+chr(33); "
    "tp=lambda s: s[0][0] if s else ''; "
    "cs=lambda s: s[0][1] if s else 0; "
    "ds=lambda v: lambda a,z: (lambda x,k,m,px,pk,s,n,j,e:"
    " ((('P',n),s), n+1, cs(s), '')"
    " if x=='(' and lv(k) and lv(pk) and px in sg"
    " else ((('B',n),s), n+1, cs(s), '')"
    " if x=='{' and lv(k) and lv(pk) and px==dl"
    " else ((s[1], n, cs(s[1]), ho) if tp(s)==tk else (((tk,n),s), n+1, cs(s), '*/'))"
    " if x==tk and lv(k)"
    " else (((')',cs(s)),s), n, cs(s), nz(x,k,m,j,e,v)) if x=='(' and k==0"
    " else ((('}',cs(s)),s), n, cs(s), nz(x,k,m,j,e,v)) if x=='{' and k==0"
    " else (s[1], n, cs(s[1]), ho if tp(s)=='P' else nz(x,k,m,j,e,v))"
    " if x==')' and lv(k) and tp(s) in ('P', ')')"
    " else (s[1], n, cs(s[1]), ho if tp(s)=='B' else nz(x,k,m,j,e,v))"
    " if x=='}' and lv(k) and tp(s) in ('B', '}')"
    " else (s, n, cs(s), nz(x,k,m,j,e,v))"
    ")(z[0], z[1][0], z[1][1], z[2], z[3][0], a[0], a[1], z[1][4], z[1][2]); "
)

# The readings: one for the command with every expansion replaced by `*/`, and
# one per expansion holding its body with the expansions *inside it* replaced
# the same way.  Nesting therefore needs no recursion — an expansion two
# levels in is simply its own reading — and rules 1 to 4 run against all of
# them, so taking an expansion out of the command's structure does not take
# its text out of the guard's sight.  `cat $(echo ~/.mureo/<file>)` is denied
# because the body is a reading, not because the span was left in place.
#
# `ut` is the structure the fold could not finish: a stack that is not empty
# at the end of the command means a bracket or an expansion whose extent is
# undecided — either it never closes or its closer does not match its opener.
# Anything the guard would then conclude about the braces around it would be a
# guess, so it concludes nothing and refuses, the same rule the brace budget
# follows.  An expansion that never closes is a command bash will not run
# either, so that part costs nothing real; a plain bracket left open is not,
# and the refusal of `print` of a lone brace in a here-document body is an
# over-block the reason is at least honest about.
#
# An expansion body reading ends where the expansion's closer is, and what
# follows the closer in the command continues the *same* word: the shell
# splices the body's result in and carries on. So the extent of the result is
# unknown in both directions, and the reading says so by ending in a wildcard.
# Without it a body that stops on a prefix of the directory name — the rest of
# the name written after the closer — is read as a name that merely resembles
# it, and the command reading, where the body is one unknown token, has no dot
# to judge. Each reading dropped the question for its own reason.
#
# `rq` is the second reading set: the same spans and the same bodies, with a
# quoted metacharacter left live.  It answers rules 1 and 4 only — the two that
# read something written out.  It must not answer rule 2, which asks whether a
# *pattern* matches: a quoted pattern is text the shell will not act on, which
# is the whole reason the first reading collapses it, and letting the second
# reading judge it as a pattern would refuse every quoted glob and regex
# anyone types.  It carries no wildcard either, for the same reason — the
# wildcard is a pattern.
_READINGS = (
    "sf=lambda v: list(itertools.accumulate("
    "zip(cc, st, chr(32)+cc, [" + _QUOTE_INIT + "]+st), ds(v), initial=((),1,0,''))); "
    "gf=lambda s: functools.reduce("
    "lambda q,e: (q.setdefault(e[2],[]).append(e[3]), q)[1], s[1:], {}); "
    "jn=lambda q,w: [" + _COLLAPSE + " + w*(i>0)"
    " for i,t in [(z, ''.join(y)) for z,y in q.items()]] or ['']; "
    "sp=sf(0); ut=bool(sp[-1][0]); "
    "rd=jn(gf(sp), '*'); rq=jn(gf(sf(1)), ''); "
)
