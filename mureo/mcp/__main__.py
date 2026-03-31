"""python -m mureo.mcp でMCPサーバーを起動するエントリポイント"""

import asyncio

from mureo.mcp.server import main

asyncio.run(main())
