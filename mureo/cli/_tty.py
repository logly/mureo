"""TTY-safe helpers for CLI prompts.

When ``mureo setup claude-code`` is invoked by an AI agent (Claude
Code's Bash tool, Codex, etc.) the subprocess does not have a
controlling TTY. ``typer.confirm`` blocks forever in that case, which
is the failure mode non-engineers hit when they tell an agent to
install mureo.

This module adds:

- :func:`is_tty` — single source of truth for whether a TTY is
  available on stdin.
- :func:`confirm_or_default` — a drop-in replacement for
  ``typer.confirm`` that takes ``default`` when no TTY is present and
  honors an explicit ``override`` (for CLI flags) without prompting.
- :func:`terminal_safe` — scrub control bytes out of a string that came
  from an agent-writable file before it is echoed.
"""

from __future__ import annotations

import re
import sys

import click
import typer

#: C0/C1 control bytes — ANSI escape, BEL, CR and newline included.
#:
#: STATE.json and the files beside it are agent-writable, so any string they
#: contribute to terminal output is attacker-influenceable. Left in, an agent
#: could clear the operator's screen, spoof a prompt (including a
#: confirmation prompt), or corrupt a column layout so a repair preview reads
#: as something other than what it says.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f]")


def terminal_safe(value: str) -> str:
    """Return ``value`` with every control character replaced by ``?``."""
    return _CONTROL_CHARS.sub("?", value)


def is_tty() -> bool:
    """Return ``True`` only when *both* stdin and stdout are terminals.

    ``typer.confirm`` reads from stdin and writes to stdout. Either
    being redirected means we can't reliably prompt — e.g.
    ``echo y | mureo setup``, ``mureo setup < /dev/null``, or Claude
    Code's Bash tool (no TTY on either side). Requiring both ends is
    what ``click``/``rich`` do for the same reason.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def confirm_or_default(
    prompt: str,
    *,
    default: bool,
    override: bool | None = None,
) -> bool:
    """Prompt for a yes/no answer with safe fallback paths.

    Resolution order:

    1. ``override`` wins if set (used when a CLI flag like
       ``--google-ads`` / ``--no-google-ads`` makes the decision
       explicit). Neither TTY state nor prompts are consulted.
    2. If stdin/stdout have no TTY, return ``default`` silently so the
       command does not hang under an AI agent or a CI runner.
    3. Otherwise, delegate to :func:`typer.confirm`. If the TTY
       disappears mid-prompt (``EOFError`` / ``click.Abort``), fall
       back to ``default`` so the command still completes rather than
       crashing with a stack trace.
    """
    if override is not None:
        return override
    if not is_tty():
        return default
    try:
        return typer.confirm(prompt, default=default)
    except (EOFError, click.exceptions.Abort):
        return default
