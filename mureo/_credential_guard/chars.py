"""The names the Bash payload gives its metacharacters and placeholders."""

from __future__ import annotations

# Shell metacharacters, named once.  Most may not appear literally in the
# payload (see the NOTE in credential_guard.py), so each arrives as a
# chr() call: q1 ', q2 ", bs backslash, dl $, tk backtick, nl newline,
# pc %.  `ho` is the placeholder a quoted metacharacter collapses to — it
# must be none of: an identifier character (it has to read as a component
# boundary), a metacharacter, or a dot.
#
# `ws` and `op` are the two kinds of character that separate one word from
# the next when the shell is allowed to act on them, and `sw` and `so` are
# the placeholders each kind becomes in the normalized text.  Whether a
# separator is live is a question about quoting, so it is the fold that has
# to answer it rather than a regex over the result — see `nz` in quoting.py.
#
# The two placeholders carry the only meaning in the normalized text that is
# not the meaning of the character itself, so they must be characters a
# brace group's contents cannot hold: control characters, which no path
# component and no shell word contains, and which `_SANITIZE` removes from
# the input so a command cannot write one and claim it.
_CHARS = (
    "q1=chr(39); q2=chr(34); bs=chr(92); dl=chr(36); tk=chr(96); nl=chr(10); "
    "pc=chr(37); ho='='; mt='*?[]{},'; "
    "sw=chr(1); so=chr(2); sn=sw+so; ws=chr(32)+chr(9)+nl; op=';|&()<>'; "
    "bo=chr(3); bc=chr(4); "
)

# A placeholder arriving in the input would let a command claim a structure
# the shell will not make, so none of them reaches the fold: each is replaced
# by the boundary placeholder on the way in.  Nothing is hidden by the swap —
# a control character reads as a component boundary either way — and after it
# the only placeholders in the text are the ones the guard put there.
_SANITIZE = "cc=cc.replace(sw,ho).replace(so,ho).replace(bo,ho).replace(bc,ho); "
