"""Brace expansion over the readings, and the budget that bounds it."""

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
    "al=lambda w: (lambda v: v if ',' in w.group() and len(v)<=64"
    " else sq(w.group()[1:-1]))(w.group()[1:-1].split(',')); "
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
    "ex=lambda s: (lambda t: (lambda w:"
    " [t[:w.start()] + a + t[w.end():] for a in al(w)]"
    " if w else [t])(fe(t)))(mp(s)); "
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
#
# The budget is spent over *all* the readings of one set, the expansion bodies
# included: a command does not get a fresh allowance for every `$(...)` it
# writes.  `xp` runs it twice, once per reading set, and each set gets half of
# the total — the two together cost what one cost before, so the bound on the
# work the hook can be made to do has not moved.
#
# `ms` is the mapping's own leftover: a candidate whose inert brace spans were
# still being taken out when the passes ran out was read half-mapped, so it
# joins `un`, the structure the budget did not finish. `ut` does *not* join
# them any more. It is an expansion whose extent the span fold could not
# decide, which is a different fact about a different step, and a refusal that
# said the brace budget ran out would be stating something that did not happen.
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
    "xp=lambda r: functools.reduce(lambda q,_: q if q[1] else"
    " (lambda n: (q[0],True) if sum(map(len,n))>100000"
    " else (n, n==q[0]))"
    "([y for x in q[0] for y in ex(x)]), range(8), (r,False))[0]; "
    "rl=lambda r: [x.replace(bo,'{').replace(bc,'}') for x in r]; "
    # `not ... ==` rather than the inequality operator: the payload may not
    # contain `!`, which a shell with history expansion would rewrite.
    "rs=xp(rd); ms=[x for x in rs if not mb(x)==x]; "
    "un=[x for x in rs if fe(x)] + ms; "
    "nu=[x for x in rs if nr(x)]; "
    "ls=rl(rs); lq=rl(xp(rq)); "
)
