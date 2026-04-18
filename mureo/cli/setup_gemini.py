"""Install-kit helper for Gemini CLI.

Gemini CLI uses an extension directory structure. mureo registers as a
single extension at ``~/.gemini/extensions/mureo/gemini-extension.json``
with:

- ``mcpServers.mureo`` — the MCP command.
- ``contextFileName: CONTEXT.md`` — so the agent reads project context.

Hooks and custom slash commands are out of scope for this module: Gemini
CLI has no PreToolUse-style guard surface, and its command format is
``.toml`` (different from the ``.md`` files mureo bundles). Those are
tracked as follow-up work.
"""

from __future__ import annotations

import json
import logging
from importlib import metadata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_EXTENSION_NAME = "mureo"
_DESCRIPTION = "Marketing orchestration framework for AI agents"


def _mureo_version() -> str:
    """Return the installed mureo version, falling back to a literal.

    During development in editable mode ``metadata.version`` returns the
    value from pyproject.toml. If metadata is unavailable (e.g. running
    straight from source without install), fall back to a sentinel so
    the extension manifest still validates.
    """
    try:
        return metadata.version("mureo")
    except metadata.PackageNotFoundError:
        return "0.0.0+source"


_MUREO_MANAGED_KEYS = frozenset({"name", "version", "description"})


def install_gemini_extension() -> Path:
    """Write ``~/.gemini/extensions/mureo/gemini-extension.json``.

    Merges mureo's managed fields (``name``, ``version``, ``description``,
    ``contextFileName``, and ``mcpServers.mureo``) into any existing
    manifest, preserving operator-added keys such as ``excludeTools`` or
    extra ``mcpServers`` entries. Other extensions under
    ``~/.gemini/extensions/`` are untouched.

    Returns the manifest path.
    """
    manifest = (
        Path.home()
        / ".gemini"
        / "extensions"
        / _EXTENSION_NAME
        / "gemini-extension.json"
    )
    manifest.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if manifest.exists():
        try:
            parsed = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                existing = parsed
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Could not parse existing %s — rewriting from scratch", manifest
            )

    # Managed top-level fields always reflect the current mureo install.
    existing["name"] = _EXTENSION_NAME
    existing["version"] = _mureo_version()
    existing["description"] = _DESCRIPTION
    # contextFileName is only written when absent so operators can rename it.
    existing.setdefault("contextFileName", "CONTEXT.md")

    mcp_servers_raw = existing.get("mcpServers")
    mcp_servers: dict[str, Any] = (
        mcp_servers_raw if isinstance(mcp_servers_raw, dict) else {}
    )
    mcp_servers["mureo"] = {"command": "python", "args": ["-m", "mureo.mcp"]}
    existing["mcpServers"] = mcp_servers

    manifest.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Gemini extension manifest written: %s", manifest)
    return manifest
