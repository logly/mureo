"""Config model + tolerant parser for ``~/.mureo/insight_sources.json``.

Operators list the external MCP servers mureo should consult when an
agent calls ``mureo_consult_advisor``. Each entry names a single
vector-search tool the server exposes. The parser is intentionally
tolerant: any error path (missing file, bad JSON, invalid entry,
duplicate name) yields the empty config + a WARNING so a misconfigured
file never blocks the diagnostic flow.

Schema::

    {
      "sources": [
        {
          "name":         "<unique identifier>",
          "transport":    "stdio" | "sse" | "http",
          "tool":         "<vector-search tool name>",
          "command":      "<binary>",         # stdio only
          "args":         ["..."],             # stdio only (optional)
          "env":          {"K": "V"},          # stdio only (optional)
          "url":          "https://...",       # sse / http only
          "headers":      {"K": "V"},          # sse / http only (optional)
          "timeout_sec":  10,                  # default 10
          "top_k":        5                    # default 5
        }
      ]
    }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


Transport = Literal["stdio", "sse", "http"]
_TRANSPORTS: frozenset[str] = frozenset({"stdio", "sse", "http"})

# Defence-in-depth caps. Realistic configs sit well below these — they
# exist to keep a typo or hostile config from monopolising resources.
_MAX_TOP_K = 50
_MAX_TIMEOUT_SEC = 120.0


@dataclass(frozen=True)
class InsightSource:
    """Immutable record of a single external advisor server.

    Validation runs in ``__post_init__``; invalid combinations raise
    ``ValueError`` with a field name in the message so the tolerant
    parser can log which field failed without re-implementing the
    check.
    """

    name: str
    transport: Transport
    tool: str
    command: str | None = None
    args: tuple[str, ...] = ()
    # ``env`` / ``headers`` distinguish "omitted" (``None``) from
    # "deliberately empty" (``{}``). Stdio specifically: ``None`` means
    # "inherit the parent process env" and ``{}`` means "run with a
    # sealed empty env" — collapsing them would silently leak the
    # operator's secrets into a third-party advisor binary.
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    timeout_sec: float = 10.0
    top_k: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if self.transport not in _TRANSPORTS:
            raise ValueError(
                f"transport must be one of {sorted(_TRANSPORTS)}, "
                f"got {self.transport!r}"
            )
        if not isinstance(self.tool, str) or not self.tool.strip():
            raise ValueError("tool must be a non-empty string")
        if self.transport == "stdio":
            if not self.command or not self.command.strip():
                raise ValueError("stdio transport requires a 'command'")
        else:  # sse / http
            if not self.url or not self.url.strip():
                raise ValueError(f"{self.transport} transport requires a 'url'")
        # ``top_k`` upper cap protects against accidental megafetches.
        if (
            not isinstance(self.top_k, int)
            or isinstance(self.top_k, bool)
            or self.top_k < 1
            or self.top_k > _MAX_TOP_K
        ):
            raise ValueError(f"top_k must be a positive int <= {_MAX_TOP_K}")
        # ``timeout_sec`` must be > 0 and capped so a typo'd 1e6 cannot
        # tie up a per-call coroutine forever.
        if (
            not isinstance(self.timeout_sec, (int, float))
            or isinstance(self.timeout_sec, bool)
            or self.timeout_sec <= 0
            or self.timeout_sec > _MAX_TIMEOUT_SEC
        ):
            raise ValueError(f"timeout_sec must be > 0 and <= {_MAX_TIMEOUT_SEC}")


@dataclass(frozen=True)
class InsightSourceConfig:
    """Top-level config — currently just the source list."""

    sources: tuple[InsightSource, ...] = ()


_EMPTY = InsightSourceConfig()


def default_config_path() -> Path:
    """Return the canonical config path: ``~/.mureo/insight_sources.json``."""
    return Path.home() / ".mureo" / "insight_sources.json"


def load_insight_sources(path: Path | None = None) -> InsightSourceConfig:
    """Read and parse the insight-sources config.

    Returns the empty config (and logs a WARNING) on any failure.
    The error paths are isolated per-source so a single bad entry
    does not invalidate its siblings.
    """
    cfg_path = path if path is not None else default_config_path()
    if not cfg_path.exists():
        return _EMPTY

    try:
        raw = cfg_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        logger.warning("insight_sources: failed to read %s: %s", cfg_path, exc)
        return _EMPTY

    if not isinstance(data, dict):
        logger.warning(
            "insight_sources: top-level must be an object, got %s",
            type(data).__name__,
        )
        return _EMPTY

    entries = data.get("sources")
    if not isinstance(entries, list):
        return _EMPTY

    sources: list[InsightSource] = []
    seen_names: set[str] = set()
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            logger.warning("insight_sources: entry %d is not an object, skipping", idx)
            continue
        try:
            src = _build_source(entry)
        except ValueError as exc:
            logger.warning("insight_sources: entry %d invalid (%s), skipping", idx, exc)
            continue
        if src.name in seen_names:
            logger.warning(
                "insight_sources: duplicate name %r at entry %d, "
                "keeping first occurrence",
                src.name,
                idx,
            )
            continue
        seen_names.add(src.name)
        sources.append(src)

    return InsightSourceConfig(sources=tuple(sources))


def _build_source(entry: dict[str, Any]) -> InsightSource:
    """Construct an ``InsightSource`` from a JSON dict.

    Coerces tuple fields and forwards everything else verbatim so the
    dataclass's ``__post_init__`` runs the canonical validation.
    """
    args_raw = entry.get("args", [])
    args = tuple(args_raw) if isinstance(args_raw, list) else ()
    # Preserve the "key absent vs. explicit empty object" distinction —
    # see ``InsightSource.env`` docstring for why it matters.
    env_raw = entry.get("env")
    env = dict(env_raw) if isinstance(env_raw, dict) else None
    headers_raw = entry.get("headers")
    headers = dict(headers_raw) if isinstance(headers_raw, dict) else None
    return InsightSource(
        name=entry.get("name", ""),
        transport=entry.get("transport", ""),
        tool=entry.get("tool", ""),
        command=entry.get("command"),
        args=args,
        env=env,
        url=entry.get("url"),
        headers=headers,
        timeout_sec=float(entry.get("timeout_sec", 10.0)),
        top_k=int(entry.get("top_k", 5)),
    )


__all__ = [
    "InsightSource",
    "InsightSourceConfig",
    "Transport",
    "default_config_path",
    "load_insight_sources",
]
