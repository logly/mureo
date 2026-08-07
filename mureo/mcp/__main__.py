"""Entry point to start the MCP server via python -m mureo.mcp.

The ``if __name__ == "__main__"`` guard is load-bearing, not decoration:
without it ``import mureo.mcp.__main__`` *starts the stdio server*, which
reads stdin to EOF and closes ``sys.stdout``. ``python -m mureo.mcp`` runs
this file as ``__main__``, so the documented launch path is unaffected.
Mirrors :mod:`mureo.__main__`.
"""

import asyncio

from mureo.mcp.server import main

if __name__ == "__main__":
    asyncio.run(main())
