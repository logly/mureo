"""The path guard's payload (Read, Edit, Write, Grep, Glob, NotebookEdit)."""

from __future__ import annotations

from mureo._credential_guard.reasons import _PATH_REASON, _deny_expr

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
