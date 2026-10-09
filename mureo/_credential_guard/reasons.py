"""Deny reasons, and the python expression that prints one.

A reason is what the agent reads, so each refusal says what actually happened
rather than borrowing another refusal's claim (#582).
"""

from __future__ import annotations

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

_BASH_REASON = "mureo credential guard: commands that can reach ~/.mureo are blocked"

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

# A refusal is not a match. The budget answers before rules 1 to 4 and
# independently of them, so it cannot claim anything about what matched:
# told the command "can reach ~/.mureo" when it never mentioned the
# directory, an agent goes looking for a reference that is not there and
# retries — the mistake rule 4's own reason exists to avoid (#582).
_BUDGET_REASON = (
    "mureo credential guard: brace expansion in this command exceeded the "
    "guard budget, so it was refused with its structure unresolved; use "
    "fewer brace groups or run it in pieces"
)

# Same principle, third ground: a bracket or an expansion whose extent the span
# fold could not decide. The budget's reason used to cover this too, and it was
# wrong about it in the way #582 is about — no budget was spent and no brace
# expansion was attempted, so an agent told to "use fewer brace groups" is being
# sent to look at something that is not the problem. What is wrong with such a
# command, as far as this guard can tell, is that something in it does not
# close, so the reason says that and the fix it names is the one that works.
#
# It says "bracket" and not only "expansion" because the fold tracks a plain
# `(` and `{` as well, to know which closer belongs to which opener. An
# unbalanced one of those is sometimes a command a shell runs happily — one
# written inside a quoted string in a here-document body, say — and the
# refusal is then an over-block. Naming the bracket is what keeps the reason
# true about those: the guard really could not pair it up, and saying
# "expansion" would send the reader looking for one that is not there.
_SPAN_REASON = (
    "mureo credential guard: a bracket or a shell expansion in this command is "
    "not closed, or its closer does not match its opener, so the guard could "
    "not decide where it ends and refused rather than guessed; balance it or "
    "run the command in pieces"
)

# Same principle, different ground: a brace group whose contents the guard
# cannot account for is structure it did not resolve, and it says that rather
# than borrowing the budget's claim about a budget it never spent.
_UNRESOLVED_REASON = (
    "mureo credential guard: this command has brace structure the guard could "
    "not resolve, so it was refused rather than guessed at; keep each brace "
    "group inside one word, with no unquoted separator between its braces, or "
    "run the command in pieces"
)

# From a here-document operator on, this guard reads text the way bash reads
# a body, which means it resolves no quoting there. So a reference it finds
# in such a command may be one the shell would never act on, and claiming the
# command "can reach ~/.mureo" would be claiming more than the guard knows —
# the mistake the budget's own reason exists to avoid (#582). This one says
# what was found and why it was not decided.
_HEREDOC_REASON = (
    "mureo credential guard: this command names ~/.mureo or a pattern that "
    "matches it, and it carries a here-document operator, after which this "
    "guard stops resolving quoting as bash does in a body; so it cannot tell "
    "whether the reference is live and refused rather than guessed; read the "
    "file with the Read tool, or send the command without a here-document"
)

# A hook run with nothing on stdin was handed no tool call, so there is nothing
# to judge and nothing to allow: reading the absence as an empty call would let
# a host that failed to deliver the call through unchecked.  It is not a match
# either, so it says what happened instead of borrowing a rule's reason.
_EMPTY_STDIN_REASON = (
    "mureo credential guard: the hook received no tool call on stdin, so it "
    "refused rather than guessed"
)
