"""External insight-source configuration.

Owns the on-disk shape of ``~/.mureo/insight_sources.json`` and the
in-memory frozen dataclass model the federation layer consumes.

The config is a thin pass-through over JSON: nothing here connects
to an MCP server — :mod:`mureo.learning.federation` handles that.
The split keeps the config layer free of MCP-SDK imports, so a test
that just exercises parse/validation behaviour does not pull in the
network-capable client modules.

Tolerance philosophy: a misconfigured or missing config file must
NEVER block :data:`mureo.mcp.tools_learning.mureo_learning_insights_get`.
The tool's primary value is the operator-local knowledge base; the
external sources are an optional augmentation. Every error path here
degrades to "return what we have" so a typo in JSON does not stop the
agent from seeing the operator's own ``/learn`` history.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


# Allowed ``transport`` values. ``stdio`` is a local subprocess; ``sse``
# is the MCP server-sent-events transport; ``http`` is the MCP
# streamable-HTTP transport (the SDK's newer non-SSE transport for
# remote servers). The federation layer routes on the value so adding a
# new transport requires touching both this constant and the federation
# dispatcher — a deliberately small surface.
_ALLOWED_TRANSPORTS: frozenset[str] = frozenset({"stdio", "sse", "http"})


Transport = Literal["stdio", "sse", "http"]


@dataclass(frozen=True)
class InsightSource:
    """One configured external MCP server entry.

    Attributes:
        name: Operator-facing label that becomes the section heading
            in the merged output. Must be unique within a config file
            (enforced by :func:`load_insight_sources`).
        transport: ``"stdio"``, ``"sse"``, or ``"http"``. Picks the
            mcp SDK client transport used to talk to the server.
        tool: The remote tool name to call (each external server can
            choose its own naming — ``insights_get`` /
            ``benchmarks_get`` / etc.).
        command: stdio-only. Executable to spawn (PATH-resolved).
        args: stdio-only. Extra CLI args. Defaults to ``()``.
        env: stdio-only. Process env vars merged into the subprocess.
            Defaults to ``{}``.
        url: sse / http only. Remote MCP endpoint.
        headers: sse / http only. Additional HTTP headers (e.g.
            ``Authorization``). Defaults to ``{}``.
        timeout_sec: Per-source call timeout. Defaults to 10s — long
            enough for a slow remote MCP, short enough that a dead
            server does not stall the diagnostic flow.
    """

    name: str
    transport: Transport
    tool: str
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout_sec: float = 10.0

    def __post_init__(self) -> None:
        if self.transport not in _ALLOWED_TRANSPORTS:
            raise ValueError(
                f"unknown transport {self.transport!r}; expected one of "
                f"{sorted(_ALLOWED_TRANSPORTS)}"
            )
        if self.transport == "stdio" and not self.command:
            raise ValueError(
                f"source {self.name!r}: stdio transport requires 'command'"
            )
        if self.transport in {"sse", "http"} and not self.url:
            raise ValueError(
                f"source {self.name!r}: {self.transport} transport requires 'url'"
            )


@dataclass(frozen=True)
class InsightSourceConfig:
    """The parsed contents of ``insight_sources.json``."""

    sources: tuple[InsightSource, ...] = ()


def default_config_path() -> Path:
    """Path the federation layer reads when no override is supplied.

    ``~/.mureo/insight_sources.json``. Resolved lazily via
    :meth:`Path.home` so an alternate ``$HOME`` (test sandbox,
    environment override) routes correctly without a separate
    indirection.
    """
    return Path.home() / ".mureo" / "insight_sources.json"


def load_insight_sources(path: Path | None = None) -> InsightSourceConfig:
    """Parse the config file at ``path`` (or :func:`default_config_path`).

    Tolerance:
    - Missing file → empty config (no warning; that's the common case).
    - Empty / malformed JSON → empty config + WARNING (the operator
      gets a pointer to the path so they can fix it).
    - Top-level shape wrong (no ``sources`` array, wrong types) →
      empty config + WARNING.
    - Individual entry invalid → that entry is skipped + WARNING; the
      remaining valid entries are returned.

    None of those failure modes raise — the federation layer treats
    "no external sources" as a benign state.
    """
    resolved = path if path is not None else default_config_path()
    if not resolved.exists():
        return InsightSourceConfig()

    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("insight_sources config unreadable at %s: %s", resolved, exc)
        return InsightSourceConfig()

    if not isinstance(raw, dict):
        logger.warning("insight_sources config at %s is not a JSON object", resolved)
        return InsightSourceConfig()

    entries = raw.get("sources", [])
    if not isinstance(entries, list):
        logger.warning(
            "insight_sources config at %s: 'sources' is not a list", resolved
        )
        return InsightSourceConfig()

    parsed: list[InsightSource] = []
    seen_names: set[str] = set()
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            logger.warning(
                "insight_sources config at %s entry #%d is not an object",
                resolved,
                idx,
            )
            continue
        try:
            source = _build_source(entry)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "insight_sources config at %s: skipping invalid entry " "#%d (%s): %s",
                resolved,
                idx,
                entry.get("name", "<unnamed>"),
                exc,
            )
            continue
        if source.name in seen_names:
            logger.warning(
                "insight_sources config at %s: duplicate source name %r "
                "(entry #%d) — keeping the first",
                resolved,
                source.name,
                idx,
            )
            continue
        seen_names.add(source.name)
        parsed.append(source)

    return InsightSourceConfig(sources=tuple(parsed))


def _build_source(entry: dict[str, Any]) -> InsightSource:
    """Convert one JSON object to an :class:`InsightSource`.

    Tuple / dict coercion: ``args`` in JSON arrives as ``list[str]``
    but the dataclass field is ``tuple[str, ...]`` for hashability;
    ``env`` and ``headers`` are passed through as-is.
    """
    args_raw = entry.get("args", [])
    if not isinstance(args_raw, list):
        raise ValueError("'args' must be a list of strings")
    return InsightSource(
        name=entry["name"],
        transport=entry["transport"],
        tool=entry["tool"],
        command=entry.get("command"),
        args=tuple(str(a) for a in args_raw),
        env=dict(entry.get("env", {})),
        url=entry.get("url"),
        headers=dict(entry.get("headers", {})),
        timeout_sec=float(entry.get("timeout_sec", 10.0)),
    )


__all__ = [
    "InsightSource",
    "InsightSourceConfig",
    "Transport",
    "default_config_path",
    "load_insight_sources",
]
