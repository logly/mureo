"""The exceptions that mean "stop", never "this operation failed".

mureo has several deliberately best-effort boundaries — a before-state
capture, a per-module analytics run — that catch ``BaseException`` so a
failure there degrades gracefully instead of taking down the operation behind
it. Every one of them must first let the *control-flow* exceptions through:
they are not a report that the work failed, they are the process being told to
stop, and swallowing one turns a cancelled or shutting-down call into a
caller that keeps working for nobody.

One named tuple rather than a literal repeated at each site: the set has to
stay identical everywhere, and a literal is exactly how the spellings drift
apart (one site catching two of the three, the next reader copying the
shorter one).

Deliberately stdlib-only, so it can be imported at module level from anywhere
— including ``mureo.amazon_ads.bridge``, which must not reach into
``mureo.mcp.*`` at import time (see ``bridge._normalize_failure``).
"""

from __future__ import annotations

import asyncio

#: Re-raise these before any ``except BaseException`` best-effort fallback.
#:
#: - ``KeyboardInterrupt`` / ``SystemExit``: the interpreter is going away.
#: - ``asyncio.CancelledError``: the caller stopped waiting for this result
#:   (mureo's MCP server cancels a tool call's task when the client goes away).
STOP_EXCEPTIONS: tuple[type[BaseException], ...] = (
    KeyboardInterrupt,
    SystemExit,
    asyncio.CancelledError,
)

__all__ = ["STOP_EXCEPTIONS"]
