"""Generate — and age-check — the Amazon MCP tool manifest.

Credentialed/network in production (one authenticated MCP session to
the region endpoint). The result is written to
``~/.mureo/amazon_tools.json`` so the bridge's ``mcp_tools()`` can be a
pure, credential-free, network-free read at mureo server start.

The MCP client session is dependency-injected (``connect``) so the
core is unit-testable without a real Amazon connection or the mcp SDK
transport.

**Staleness.** The manifest is a *snapshot* of a tool surface mureo does
not own, so it drifts: tools appear, disappear, and change schema
upstream while the local copy says otherwise. ``generated_at`` has always
been written; :func:`manifest_age_days` / :func:`is_manifest_stale` are
what finally read it, with a 30-day default threshold overridable via
``MUREO_AMAZON_MANIFEST_MAX_AGE_DAYS``. Staleness is *reported*, never
enforced — an old manifest still serves its tools (refusing to would
break a working setup over a heuristic); the configure-UI status row,
the CLI refresh command, and a one-shot bridge warning surface it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.amazon_ads.endpoints import endpoint_url, request_headers
from mureo.core import clock
from mureo.core.atomic_json import atomic_write_json

if TYPE_CHECKING:
    from mureo.auth import AmazonAdsCredentials

logger = logging.getLogger(__name__)

# (url, headers) -> async context manager yielding an object with
# ``await initialize()`` and ``await list_tools()`` (mcp ClientSession).
ConnectFactory = Callable[[str, dict[str, str]], AbstractAsyncContextManager[Any]]

#: Manifest file name, in ``~/.mureo``. Named once so the status collector
#: (which resolves it under an injected home) and :func:`manifest_path` cannot
#: drift apart.
MANIFEST_FILENAME = "amazon_tools.json"

#: How old a manifest may be before mureo calls it stale. Amazon's tool
#: surface is not versioned for us, so this is a judgement call, not a fact:
#: long enough that a stable setup is never nagged, short enough that a
#: months-old snapshot is called out.
DEFAULT_MANIFEST_MAX_AGE_DAYS = 30

#: Operator override for :data:`DEFAULT_MANIFEST_MAX_AGE_DAYS`, in days.
MANIFEST_MAX_AGE_ENV = "MUREO_AMAZON_MANIFEST_MAX_AGE_DAYS"


def manifest_path() -> Path:
    """Default manifest location: ``~/.mureo/amazon_tools.json``."""
    return Path.home() / ".mureo" / MANIFEST_FILENAME


def manifest_max_age_days() -> float:
    """The staleness threshold in days, honouring the env override.

    An unusable override (blank, non-numeric, zero or negative) falls back to
    the default rather than raising or disabling the check: this runs on the
    status/CLI display path, where a typo in an env var must not take a
    surface down, and "0 days" would report every manifest as stale.
    """
    raw = os.environ.get(MANIFEST_MAX_AGE_ENV)
    if raw is None:
        return float(DEFAULT_MANIFEST_MAX_AGE_DAYS)
    try:
        value = float(raw.strip())
    except (AttributeError, ValueError):
        return float(DEFAULT_MANIFEST_MAX_AGE_DAYS)
    if value <= 0:
        return float(DEFAULT_MANIFEST_MAX_AGE_DAYS)
    return value


def _parse_generated_at(raw: Any) -> datetime | None:
    """Parse a manifest ``generated_at`` into an aware datetime, or ``None``.

    Accepts what :func:`generate_manifest` writes (ISO 8601 with an explicit
    offset) plus the two shapes a hand-edited or foreign file may carry: a
    ``Z`` suffix (``datetime.fromisoformat`` rejects it before 3.11) and a
    naive timestamp, which is read as host-local — the same assumption
    :func:`mureo.core.clock.server_now` makes.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def document_age_days(doc: Any) -> float | None:
    """Age in days of an already-parsed manifest document, or ``None``.

    ``None`` means "cannot tell" — no document, no ``generated_at``, or an
    unparseable one — and every caller reports that as *unknown*, never as
    stale. A future timestamp (clock skew, or a machine that travelled
    timezones) clamps to ``0.0``: it is not aged, and a negative age would
    render as nonsense.
    """
    if not isinstance(doc, dict):
        return None
    generated = _parse_generated_at(doc.get("generated_at"))
    if generated is None:
        return None
    delta = clock.server_now() - generated
    return max(0.0, delta.total_seconds() / 86_400)


def manifest_age_days(path: Path | None = None) -> float | None:
    """Age in days of the manifest at ``path``, or ``None`` when unknowable.

    Never raises: a missing, unreadable, or malformed manifest is an unknown
    age. This is display/telemetry, not a gate.
    """
    target = path or manifest_path()
    try:
        doc = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return document_age_days(doc)


def is_stale(age_days: float | None) -> bool:
    """Is ``age_days`` past the configured threshold? Unknown ⇒ ``False``."""
    if age_days is None:
        return False
    return age_days > manifest_max_age_days()


def is_manifest_stale(path: Path | None = None) -> bool:
    """Is the manifest at ``path`` older than the configured threshold?"""
    return is_stale(manifest_age_days(path))


def _default_connect(
    url: str, headers: dict[str, str]
) -> AbstractAsyncContextManager[Any]:
    @asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(url, headers=headers) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            yield session

    return _cm()


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    # mcp.types.Tool is pydantic v2; keep only the wire-relevant,
    # secret-free fields the bridge will rebuild a Tool from.
    dumped: dict[str, Any] = tool.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    keep = ("name", "description", "inputSchema", "annotations", "_meta")
    return {k: dumped[k] for k in keep if k in dumped}


async def generate_manifest(
    creds: AmazonAdsCredentials,
    *,
    connect: ConnectFactory | None = None,
    out_path: Path | None = None,
) -> Path:
    """Connect once, list Amazon's tools, write the manifest. Returns path.

    Never writes a partial file: the manifest is only written after a
    successful tool listing (a connection failure propagates and leaves
    no file behind).
    """
    connect = connect or _default_connect
    out = out_path or manifest_path()
    url = endpoint_url(creds.region)
    headers = request_headers(creds)

    async with connect(url, headers) as session:
        await session.initialize()
        result = await session.list_tools()
        tools = list(result.tools)

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": creds.region,
        "endpoint": url,
        "account_mode": creds.account_mode,
        "tools": [_tool_to_dict(t) for t in tools],
    }

    # Atomic + 0600 via the repo's shared writer: an unpredictable temp
    # sibling chmodded BEFORE the data is written, fsynced, then
    # ``os.replace``d, so a reader never sees a half-written manifest,
    # the file is never world-readable, and a failure leaves no debris.
    atomic_write_json(doc, out)
    return out


def generate_manifest_sync(
    creds: AmazonAdsCredentials,
    *,
    connect: ConnectFactory | None = None,
    out_path: Path | None = None,
) -> Path:
    """Blocking wrapper for the CLI command path."""
    return asyncio.run(generate_manifest(creds, connect=connect, out_path=out_path))
