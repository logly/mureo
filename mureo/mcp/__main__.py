"""Entry point to start the MCP server via python -m mureo.mcp."""

import asyncio

from mureo.mcp.server import main

asyncio.run(main())
