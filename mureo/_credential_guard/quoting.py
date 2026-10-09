"""The quoting automaton, and what each character of the command reads as."""

from __future__ import annotations

# The quoting automaton, as the step function of a left fold.  The state is
# a 5-tuple.  First, where we are: 0 unquoted, 1 single-quoted, 2
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
#
# Third, whether an unquoted `<<` has been seen.  From there on the quoting
# states 1, 2 and 4 are no longer entered: bash does no quote removal in the
# body of a here-document, so neither does this.  Fourth, the previous
# character, which is what lets the `<<` be seen at all — the fold would
# otherwise have no way to know the character before it.
#
# The latch is one-way and runs to the end of the command rather than to a
# matching delimiter, because the delimiter is not what matters.  Erring
# *long* means the guard declines to resolve quoting somewhere bash would
# have, which can only leave more text visible to the rules; erring short
# means resolving quoting bash does not resolve, and a body is exactly where
# an unbalanced quote is ordinary text.  A here-string (`<<<`) or a `<<`
# inside a comment or an arithmetic expansion is therefore matched
# deliberately: each of them only stops quote resolution, and that direction
# is safe.
#
# Within the latch the automaton keeps exactly one transition: a backslash
# still escapes the character after it, so a line continuation is still
# removed as a pair.  Bash removes it in an unquoted body, and in a quoted
# one the pair survives into text that the consuming program may hand to a
# shell of its own, which removes it then — either way the two characters
# are not part of a name, and keeping them would stop the name being
# contiguous.
#
# The fifth component is the same automaton run as if the latch had never
# closed, and it exists for one question: whether the shell is allowed to act
# on a separator.  Dropping quote resolution is the right answer for every
# other question a body raises — where the command's words are, which
# metacharacters are live — because erring there can only leave more text
# visible to the rules.  It is the wrong answer for this one, and in the
# fail-open direction: a body handed to a shell of its own has its quoting
# resolved by that shell, so a separator written inside quotes there is text
# in the middle of a word, and reading it as a word boundary would make a
# brace group around it disappear.  A separator is therefore a separator only
# where *both* readings say unquoted.  Where they disagree the group survives
# and is judged, which is the safe direction; and a body whose quotes do not
# balance — the thing the latch exists for — can only push this component into
# a quoted state, so it can only keep groups alive, never dissolve one.
_QUOTE_NEXT = (
    "qn=lambda k,x: (1 if x==q1 else 2 if x==q2 else 3 if x==bs else 0) if k==0"
    " else (0 if x==q1 else 1) if k==1"
    " else (0 if x==q2 else 4 if x==bs else 2) if k==2"
    " else (0 if k==3 else 2); "
)

_QUOTE_STEP = (
    "lambda kv,x: (lambda hd: ("
    "(0 if kv[0]==3 else 3 if x==bs else 0) if hd else qn(kv[0],x),"
    " 1 if x==pc else (kv[1] if kv[0] else 0), hd, x, qn(kv[4],x)))"
    "(kv[2] or (kv[0]==0 and kv[3]+x=='<<'))"
)

# The fold's seed, named once because two folds consume it: unquoted, no `%`
# in scope, no here-document operator seen, no previous character, and the
# latch-free quoting state also unquoted.
_QUOTE_INIT = "(0,0,0,'',0)"

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
#
# A separator becomes a placeholder when, and only when, the shell is allowed
# to act on it: an unquoted space, tab or newline becomes `sw`, an unquoted
# `;` `|` `&` `(` `)` `<` `>` becomes `so`.  Quoted, escaped, and inside an
# expansion-that-the-span-step-has-already-taken-out, the same characters are
# ordinary text and stay as written, which is what the shell does with them.
# Deciding this here is what lets a later step ask whether a brace group's
# contents are one word without asking a second time about quoting.
#
# `j` is the latch-free quoting state, and the separator question is the only
# one that consults it: both it and `k` have to say unquoted.  See `_QUOTE_NEXT`
# for why the two are not the same question inside a here-document body.
#
# It is written per character rather than as one join because the span step
# in spans.py has to decide, for each character, whether it belongs to the command
# or to the body of an expansion — and the two decisions are made in the same
# pass, so there is still exactly one place that says what a character reads
# as.
#
# `e` is the here-document latch, and it turns the second kind of separator
# off.  A body is not shell text: bash reads no operator in one, so `;` `|`
# `&` `(` `)` `<` `>` there are ordinary characters in the middle of whatever
# language the body is written in, exactly as a quoted one is.  Whitespace is
# left as a separator, because a body is still a run of lines and two braces
# on different lines of one must not pair up.
#
# `v` asks for the *second reading*, the one that leaves a quoted
# metacharacter live instead of collapsing it to the placeholder.  Quoting is
# what keeps the shell off a metacharacter, so the first reading is the right
# one for every question about what this shell will do — but a quoted string
# is also how a command hands text to a program that starts a shell of its
# own, and that shell sees the metacharacter.  The two readings answer the two
# questions; see `rq` in spans.py for which rules the second one may answer.
_NORMALIZE_CHAR = (
    "nz=lambda x,k,m,j,e,v: '' if (k==0 and x in q1+q2+bs) or (k==1 and x==q1)"
    " or (k==2 and x in q2+bs) or (k>2 and x==nl)"
    " else ('*/' if x in dl+tk+pc"
    " else sw if k==0 and j==0 and x in ws"
    " else so if k==0 and j==0 and not e and x in op"
    " else (ho if k and not m and not v and x in mt else x)); "
)

# An expansion swallows the identifier run that names it: `$D` and `%s` are
# one unknown thing, not an unknown thing followed by the letters `d`/`s`.
# Collapsing them is what lets a single reading serve the rules — after
# it, `$D.mureo` reads as `*/.mureo`, whose dot sits at a boundary exactly
# like the one in `~/.mureo`, so the literal rule needs no separate scan of
# the raw text to find it.  This cannot hide a name: it removes only
# identifier characters, and every form the guard looks for contains a dot.
_COLLAPSE = "re.sub('[*]/[a-z0-9_]*', '*/', t)"
