"""Demo bootstrap for ``mureo demo init``.

Materializes a self-contained directory containing a synthetic XLSX
bundle, a STRATEGY.md seed, a ``.mcp.json`` for Claude Code, and a
README. The bundle round-trips through the existing BYOD pipeline so
the demo experience is identical to a real BYOD import minus the data
download step.
"""

from mureo.demo.installer import DemoInitError, materialize

__all__ = ["DemoInitError", "materialize"]
