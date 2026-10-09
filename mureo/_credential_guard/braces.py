"""Brace expansion over the readings, and the budget that bounds it.

Brace groups are then *expanded*, not approximated: each reading becomes
the list of strings the shell would produce, and every rule runs against
all of them.  ``~/.mure{o,x}`` and ``~/{.,z}mureo`` are caught because
``.mureo`` is literally among the results.

An earlier version folded each group to one placeholder and guessed
which — ``.*`` if the group held a dot anywhere, ``*`` otherwise — and
the guess is what broke.  ``~/.{mureo,x.y}`` has a dot before the group
and a dot inside an alternative that has nothing to do with the
directory; the fold read them as one, produced ``..*``, which requires
two leading dots, and meanwhile the literal ``.mureo`` that rule 1 would
have matched had already been replaced.  Both rules passed and the file
was read.  Expanding removes the guess instead of refining it.

A brace group is part of one word, so what counts as its contents is
decided by the separator placeholders and not by the characters
themselves.  A group whose contents hold a placeholder is not a group:
bash does not expand a brace group across a separator it is allowed to
act on, and neither does this.  A separator the shell may *not* act on is
ordinary text in the middle of the word, so a group holding one is still
a group and is expanded like any other — which is the whole reason the
question is asked of the fold rather than of the finished text.
``{"a": 1, "b": 2}`` is therefore not brace expansion and costs nothing,
while a group whose alternatives are spelled with quoted separators is.

Ignoring such a ``{...}`` is only safe where the guard can see that
nothing was lost by doing so, so the ignoring is conditional and fails
closed.  A ``{...}`` the shell would expand — one with a comma or a
``..`` — whose contents hold either an expansion placeholder or a
separator from the second kind is *refused* as structure that did not
resolve, rather than ignored.  The reasoning is the same as the budget's:
if an expansion form the span fold does not recognise were to slip
through, its insides would read as separators, and ignoring the group on
that basis would be a guess in the fail-open direction.  Spelled this
way, any such slip lands on deny.  The condition is restricted to
expandable groups because a brace span without a comma or a ``..`` is not
brace expansion to any shell, so there is nothing about it to get wrong;
and bash's own separating comma is always at the group's top level, so it
is always visible in the reading when the group is real.

Two groups are not lists of alternatives the first reading set enumerates:
a sequence (``.{l..n}ureo`` covers ``m`` without the letter appearing
anywhere) and one with absurdly many alternatives.  A sequence it
recognises — endpoints that are integers or single letters — takes the one
coarse reading ``*``, because neither an integer nor a letter can be the
leading dot of a dotfile, so ``.*`` would only over-block; a sequence it
does not recognise, and a group with too many alternatives, take *both*
``*`` and ``.*``, which between them cover "supplies a leading dot" and
"does not".  A group with neither a comma nor a ``..`` is not brace
expansion at all; bash leaves ``{eo}`` literal, so the guard does too, and
``~/.mur{eo}`` is allowed because it opens nothing.

Being literal is not the same as being absent, and that distinction is the
whole of the next step.  Nesting resolves by expanding the innermost group
first, so that the one around it becomes innermost in its turn — but an
inert span never goes away, because nothing expands it, and for as long as
it is there the span around it holds a brace and is not a group to this
reading at all.  Bash has no such order to wait on: it expands braces over
the raw text, before every other expansion, so an alternative carrying an
inert ``{...}`` is just an alternative.  The guard agrees with it by
writing an inert span's braces as placeholders of their own, which leaves
the enclosing span readable, and by putting them back before any rule runs,
which keeps the candidate strings the strings the shell produces.  Only
inert spans are mapped: one with a comma or a ``..`` is the expansion
step's, and mapping it would resolve the inside before the outside; one
holding a separator is not kept in a single word by bash either.  The
mapping needs a pass per level of nesting and is bounded like everything
else here, and a text still changing when the bound is reached is refused
with the rest of the structure the budget did not finish.

Expansion has a budget so a pathological command cannot explode the hook,
and **whatever the budget does not resolve is refused**, in both reading
sets.  Anything still holding an expandable group after the passes denies
on that ground alone.  The first set spends eight passes and 100,000 bytes
over all its readings at once, and it deduplicates as it goes, so a group
whose alternatives repeat costs only its distinct members; the same
deduplication runs on the first set's readings too, which only ever removes
repeats and so changes no decision.  The second set has no coarse reading to
fall back on — it does not answer the pattern rule, so a wildcard standing
for a group there would be judged by nothing — so it enumerates, and to
keep that affordable it is spent a word at a time, over the inner shell's
own words: a second reading is a string handed to a program that re-reads it
with a shell of its own, and that shell splits the content this shell left
quoted on the spaces in it, and will not expand a brace group that holds an
unquoted space.  So the spaces the inner shell acts on split the words here
too, a group with such a space in it dissolves exactly as it does for bash,
and a space that is quoted, escaped, or inside a quoted alternative stays in
the word.  Each word gets sixteen passes, at most 1,024 distinct strings in
a pass and 1,000,000 bytes; the words that hold a group share a total of
4,096 strings, over every reading of the command, and a word that holds none
is not counted against it.  The word that carries the total past 4,096 still
expands, so the ceiling is 5,120.  A comma list is enumerated whole up to
1,024 distinct members, a one-character range between two letters as the
thirty-two characters its endpoints could cover in any case-spelling, an
integer sequence as one of its endpoints (no name the rules read there holds
a digit); a group it cannot enumerate that way, or a word that overruns its
budget, is left unresolved and refused with the rest.  That refusal answers
after rules 1 to 3, so a command they already refuse keeps the reason they
give.

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

What that refuses in practice, in the first set, is a command with more
than eight brace groups, or one whose expansion exceeds the byte budget.
In a string a program re-reads, the second set also refuses a group it
cannot enumerate, and — because it enumerates a word at a time — a single
word holding more than ten two-way groups, or more than 1,024 distinct
strings' worth of alternatives (three letter ranges, whose thirty-two
members each make 32,768, are past it), or a command whose group-bearing
words make more than 5,120 strings between them.  A space the inner shell
acts on puts the groups in different words, or dissolves a group that holds
one, and costs almost nothing — which is why formatted JSON, with a space
after each comma, is allowed whatever its length.  The shape that is left is
a run of comma-bearing groups packed into one word with no space anywhere
between them, which a shell re-reading the string would multiply too.
Quoted braces are the only ones that reach the second set at all, and a
group with no comma and no ``..`` is literal to bash and to ``fe``.
"""

from __future__ import annotations

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
# `ga` excludes the two separator placeholders from a group's contents,
# because a brace group is part of one word: bash will not expand a group
# across a separator it is allowed to act on, so neither does this. Asking
# about the placeholders rather than about the characters is what keeps that
# agreement exact — a separator the shell may not act on is ordinary text
# inside the word, and a group holding one is still a group. Taking the
# characters themselves out would also let two unrelated braces on different
# lines of a multi-line command pair up and swallow what lies between them.
#
# `gu` is the same span with the placeholders *allowed*, which is how the
# leftovers are found: a `{...}` that `ga` does not match is one the shell
# would not expand, and ignoring it is only safe when the guard can see that
# nothing was lost by doing so. `nr` is that test, and it fails closed: of
# the leftovers it looks only at the ones a shell would expand — a span
# without a comma or a `..` is not brace expansion to anybody, so there is
# nothing about it to get wrong — and it refuses those holding a separator
# from `op`, or an expansion the span step could not take out of the way.
# Either means the structure around the group was not resolved, and
# resolving nothing is how this guard answers that.
_BRACE_HELPERS = (
    "ga='[{][^{}' + sn + ']*[}]'; gu='[{][^{}]*[}]'; "
    "fe=lambda s: next((w for w in re.finditer(ga, s)"
    " if ',' in w.group() or '..' in w.group()), None); "
    "nr=lambda s: [w for w in re.findall(gu, s)"
    " if (',' in w or '..' in w)"
    " and (so in w or (sw in w and '*/' in w))]; "
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
    "al=lambda g: (lambda v: v if ',' in g and len(v)<=64"
    " else sq(g[1:-1]))(g[1:-1].split(',')); "
    # `aq` is the second reading set's `al`, and it has no coarse reading to
    # fall back on: that set does not answer rule 2, so a `*` there would be
    # judged by nothing.  It enumerates what it can and leaves the rest of the
    # group as written, which `fe` still finds and `uf` refuses.  A comma list
    # is deduplicated and enumerated whole up to 1,024 distinct members, which
    # is the per-word cap: a list with more than that is left unresolved as a
    # group here rather than built out, so `ex` never materialises more than the
    # cap's worth of a single group and the memory stays bounded by the input's
    # size.  Equal members cost nothing, being deduplicated before the count.
    # An integer sequence is read as one endpoint: digits are no part of any
    # name the rules read here.  A one-character sequence is enumerated only
    # between two ASCII letters, in either direction.  Bash expands it by the
    # ords of the endpoints as written, but the command is lowercased before the
    # guard reads it, so `{A..z}` and `{a..z}` arrive the same and a lowercased
    # endpoint cannot say which case it was.  Taking both the upper- and
    # lower-case ord of each endpoint and ranging over their extremes covers
    # every character bash makes of any case-spelling, lowercased and
    # deduplicated: always the 26 letters plus the six punctuation characters
    # ASCII puts between the cases, `_` among them, so thirty-two candidates for
    # any letter range, which only ever adds to what bash makes.  An endpoint
    # that is not an ASCII letter is left as written and refused.
    "aq=lambda g:(lambda e:(lambda d:list(d)if len(d)<=1024 else[g])"
    "(dict.fromkeys(g[1:-1].split(',')))if','in g"
    " else[e[0]]if len(e)==2 and all(x.lstrip(chr(45)).isdigit()for x in e)"
    " else(lambda o:list(dict.fromkeys(chr(i).lower()"
    " for i in range(min(o),max(o)+1)))if all(97<=(c|32)<=122 for c in o)else[g])"
    "([ord(e[0]),ord(e[0])^32,ord(e[1]),ord(e[1])^32])"
    "if list(map(len,e))==[1,1]else[g])(g[1:-1].split('..')); "
    # `mb` takes the braces of a span that is *literal* to bash — one holding
    # neither a comma nor a `..`, and no separator the shell may act on — and
    # writes them as their own placeholders.  That is what lets a group be
    # read when a literal span sits inside it.  `ga` cannot match across a
    # brace, so a group whose alternative carries an inert `{...}` never
    # matched anything: the expansion loop resolves nesting by waiting for the
    # inner span to go away, and an inert one never does, because `fe` only
    # ever picks a span the shell would expand.  The outer group therefore
    # stayed invisible for as long as the inner one was there, while bash —
    # which expands braces over the raw text, before anything else — read the
    # word as the list of alternatives it is.
    #
    # Mapping only the inert spans is what keeps this exact.  A span with a
    # comma or a `..` is `fe`'s to expand, and taking its braces out of the
    # way would expand the inside before the outside and change the result; a
    # span holding a separator is one bash does not keep in a single word at
    # all, so reading it as part of one would answer a different question than
    # the shell's.  The placeholders are undone before any rule runs, so the
    # candidate strings are the strings the shell produces, brace for brace.
    "mb=lambda s: re.sub(gu, lambda w: (lambda u: w.group()"
    " if (',' in u or '..' in u or sw in u or so in u) else bo+u+bc)"
    "(w.group()[1:-1]), s); "
    # One pass of `mb` takes the innermost inert spans; a span nested inside
    # another needs one pass per level, so it runs to a fixed point. The bound
    # is the expansion budget's own, and a text still changing at the end of it
    # is refused with the rest of the unresolved structure rather than read
    # half-mapped.
    "mp=lambda s: functools.reduce(lambda q,_: q if q[1]"
    " else (lambda n: (n, n==q[0]))(mb(q[0])), range(8), (s,False))[0]; "
    "ex=lambda s,a=al: (lambda t: (lambda w:"
    " (t[:w.start()]+b+t[w.end():] for b in a(w.group()))"
    " if w else [t])(fe(t)))(mp(s)); "
)

# Eight passes expand eight groups, innermost first, so nesting resolves as
# the outer group becomes innermost, and a cap stops a pathological command
# from exploding the hook.
#
# Whatever is left when the budget runs out is *refused*, not approximated:
# `un` collects the candidates that still hold an expandable group, and a
# non-empty `un` denies on that ground alone.  `uf` is that test, and the
# second set's candidates `xq` take it too, in bash_guard.py, once rules 1 to
# 3 have had their say.  The budget used to end in a coarse fallback of two
# `re.sub` collapses, which past ten levels of nesting left literal braces in
# the candidates — text `fnmatch` reads as ordinary characters, so neither
# rule fired and
# `~/.{z11,{z10,...{z1,mureo}}}` was allowed while bash read the file. A
# budget that shrugs is a bypass with a length requirement.
#
# The rule is general: when the guard cannot compute what the shell would
# produce, it denies. In the first set what is left is a command with more
# than eight brace groups, or one whose expansion exceeds the byte budget. In
# the second set a `find . -exec {} \\;` has neither a comma nor a `..`, so
# bash leaves it literal and so does `fe`; what is left there is a run of
# comma-bearing groups packed into one word with no space anywhere between
# them to split it — more than ten two-way ones, or alternatives past the
# per-word or the total candidate cap.
#
# The first set spends one allowance over *all* its readings, the expansion
# bodies included: a command does not get a fresh one for every `$(...)` it
# writes.  The second set answers rules 1 and 4, which read a name written
# out, not rule 2, so it cannot fall back on a coarse reading of a group the
# way the first set does — it enumerates or it refuses.  Enumerating a whole
# string at once multiplied the groups of every word together, which refused
# ordinary quoted data (a JSON array, a `python -c` dict) on the budget.  A
# second reading is a string a program re-reads with a shell of its own, and
# that shell splits the content this shell left quoted on the spaces in it
# and will not expand a group holding an unquoted space.  So `iw` promotes
# those spaces to the separator placeholder — but only the ones the inner
# shell acts on, tracking its quotes and its escapes so a space it has quoted
# stays in the word — and `xq` splits each reading on the separators and
# expands the words one at a time: `ga` never spans a separator, so the
# strings a word makes are the same either way, only without the cross-word
# product.  A word that holds no group expands to itself and is not counted:
# it is one candidate, bounded already, and counting it would let a long run
# of plain words (a here-document body) spend the total before a real group
# is reached.  A word that holds one (`g`) is given sixteen passes, at most
# 1,024 distinct strings in a pass (counted as they are generated, with
# `itertools.islice` stopping at the 1,025th so the work is bounded before the
# list is built), and 1,000,000 bytes; the group-bearing words of a command
# share a total of 4,096 strings, over every reading, past which the rest are
# left unresolved — though the word that carries the total past it still
# expands, so the ceiling is 5,120.  A word that overruns any of these is left
# holding a group, which `fe` finds and `uf` refuses — the first set's rule,
# now reached a word at a time.
#
# The mapping's own leftover — a candidate whose inert brace spans were still
# being taken out when the passes ran out, and so was read half-mapped — is the
# second half of `uf`: it is structure the budget did not finish.  `ut` does
# *not* join them any more. It is an expansion whose extent the span fold
# could not decide, which is a different fact about a different step, and a
# refusal that said the brace budget ran out would be stating something that
# did not happen.
#
# `nu` is the same refusal for the other way the structure can fail to
# resolve: a `{...}` the shell would not expand *and* whose contents the
# guard cannot account for, which is what `nr` decides. It is computed after
# expansion rather than before it, because expanding an inner group is what
# brings an outer one into view.
#
# All three are decided on the mapped text, which is the text the structural
# questions were answered on. `rl` then puts the literal braces back, so every
# rule sees the strings the shell would produce and a span the mapping treated
# as literal reads exactly as it was written.
_EXPAND = (
    "xp=lambda r,a=al,p=8,m=100000,k=None: functools.reduce(lambda q,_: q if q[1]"
    " else (lambda n: (q[0],True) if sum(map(len,n))>m or k and len(n)>k"
    " else (n, n==q[0]))((lambda d: list(itertools.islice("
    "(y for x in q[0] for y in ex(x,a) if not(y in d or d.setdefault(y,0))),"
    " k and k+1)))(dict())), range(p), (r,False))[0]; "
    "rl=lambda r: [x.replace(bo,'{').replace(bc,'}') for x in r]; "
    # `iq` is the inner shell's quoting automaton, and `iw` promotes the
    # whitespace that automaton would act on to the separator placeholder. A
    # second reading is a string handed to a program that re-reads it with a
    # shell of its own: that shell splits the content this shell left quoted on
    # the spaces in it, and it will not expand a brace group that holds an
    # unquoted space (``{a, b}`` is literal to bash, ``{a,b}`` a group). So a
    # space is a boundary only where the inner shell is unquoted, and a space
    # the inner shell has quoted, escaped, or that stands in an inner quoted
    # alternative stays in the word. The states are 0 unquoted, 1 single, 2
    # double, 3 escaped from unquoted, 4 escaped in double; a protected name has
    # no space in it, so an unquoted space can never split one apart, and a
    # group reaching a protected name through a quoted-space alternative keeps
    # that space and stays a group.
    "iq=lambda a,c: 0 if a==3 else 2 if a==4 else (0 if c==q1 else 1) if a==1"
    " else (4 if c==bs else 0 if c==q2 else 2) if a==2"
    " else 3 if c==bs else 1 if c==q1 else 2 if c==q2 else 0; "
    "iw=lambda r: ''.join(sw if a==0 and c in ws else c"
    " for c,a in zip(r, itertools.accumulate(r, iq, initial=0))); "
    # `not ... ==` rather than the inequality operator: the payload may not
    # contain `!`, which a shell with history expansion would rewrite.
    #
    # A word that holds no expandable group expands to itself and is not
    # counted against the total: it is one candidate, bounded already by the
    # byte and word limits, and counting it would let a long run of plain words
    # (a here-document body) exhaust the total before any real group is reached.
    # Only a word that holds a group (``g``) is gated on the total and added to
    # it, so the total measures the enumeration work, not the word count.
    "rs=xp(rd); xq=functools.reduce(lambda q,s: (lambda g: (lambda n:"
    " (q[0]+n, q[1]+len(n)*g))(xp([s],aq,16,1000000,1024)"
    " if not g or q[1]<=4096 else [s]))(1 if fe(mp(s)) else 0),"
    " [s for r in rq for s in re.split('['+sn+']+', iw(r))], ([],0))[0]; "
    "uf=lambda r:[x for x in r if fe(x) or not mb(x)==x]; un=uf(rs); "
    "nu=[x for x in rs if nr(x)]; "
    "ls=rl(rs); lq=rl(xq); "
)
