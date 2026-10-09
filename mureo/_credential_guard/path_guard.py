"""The path guard's payload (Read, Edit, Write, Grep, Glob, NotebookEdit)."""

from __future__ import annotations

from mureo._credential_guard.reasons import (
    _EMPTY_STDIN_REASON,
    _PATH_REASON,
    _deny_expr,
)

# stdin is read as bytes and handed to ``json.loads`` undecoded, which detects
# UTF-8, -16 and -32 by itself.  Read as text it is decoded with the console
# code page on Windows, so a host that sends UTF-8 has every non-ASCII
# character in it turned into something else: a path under a home directory
# with a non-ASCII name stops comparing equal to ``~/.mureo``, and a Bash
# command with non-ASCII text in it is read as different text.  No stdin at
# all is not an empty tool call; ``ib`` is kept so that case can be refused.
_STDIN = "ib=sys.stdin.buffer.read(); d=json.loads(ib or b'{}'); "

_PATH_GUARD_CODE = (
    "import sys,json,os; "
    # Fail closed: exit 1 is a non-blocking hook error in both hosts, so an
    # escaping exception would let the call through. A path that makes
    # realpath raise (an embedded NUL, say) must deny, not proceed.
    "sys.excepthook=lambda *a: (" + _deny_expr(_PATH_REASON) + ", "
    "sys.stdout.flush(), os._exit(0)); " + _STDIN + "i=d.get('tool_input') or {}; "
    "p=str(i.get('file_path') or i.get('path') or i.get('notebook_path') or ''); "
    "e=os.path.expanduser(p); "
    "b=os.path.realpath(os.path.expanduser('~/.mureo')).lower(); "
    "bl=os.path.abspath(os.path.expanduser('~/.mureo')).lower(); "
    "r=os.path.realpath(e).lower() if p else ''; "
    "lp=os.path.abspath(e).lower() if p else ''; "
    + _deny_expr(_EMPTY_STDIN_REASON)
    + " if not ib else ("
    + _deny_expr(_PATH_REASON)
    + " if p and (r==b or r.startswith(b+os.sep)"
    " or lp==bl or lp.startswith(bl+os.sep)) else None)"
)
