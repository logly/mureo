"""Single-instance probe + active-port state file for ``mureo configure``.

Two cooperating pieces of the persistent-configure feature (issue #241,
Phase 1):

* :func:`probe_mureo_instance` GETs the unauthenticated ``/api/ping``
  endpoint and decides whether the process answering a port is *our*
  configure server (vs. a foreign process that merely grabbed the port).
  It is total: every error path returns ``False`` and it never raises,
  so a second launch can probe a possibly-dead/foreign port safely.

* :func:`write_state_file` / :func:`read_state_file` persist the
  actually-bound port to ``~/.mureo/configure.json`` so ``mureo open``
  (and a future launcher) can find the live URL after an ephemeral
  fallback changed the port. The file carries only ``port`` / ``pid`` /
  ``url`` — no secrets, no other paths — and is written ``0o600``.

Stdlib only (``urllib.request`` for the probe, ``json`` for the state
file). NO third-party HTTP client.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import TYPE_CHECKING, Any, Final

from mureo.fsutil import secure_chmod

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

#: The value :func:`probe_mureo_instance` matches on. Returned verbatim by
#: ``GET /api/ping`` so a foreign process on the same port is never
#: mistaken for a mureo instance.
PING_APP_NAME: Final[str] = "mureo-configure"

#: Filename under ``~/.mureo`` holding the active-port state.
STATE_FILENAME: Final[str] = "configure.json"

#: Short default probe timeout. The configure server answers ``/api/ping``
#: from memory in well under a millisecond on loopback; half a second is a
#: generous ceiling that keeps a foreign-port probe from stalling launch.
_PROBE_TIMEOUT_SECONDS: Final[float] = 0.5


def probe_mureo_instance(
    host: str, port: int, timeout: float = _PROBE_TIMEOUT_SECONDS
) -> bool:
    """Return ``True`` iff a mureo configure server answers ``host:port``.

    GETs ``http://<host>:<port>/api/ping`` and checks the JSON body for
    ``app == "mureo-configure"``. Any failure — connection refused,
    timeout, non-JSON body, non-object JSON, missing/foreign ``app`` —
    yields ``False``. This function NEVER raises: callers treat a
    ``False`` result as "not our instance / nothing reusable here".
    """
    url = f"http://{host}:{port}/api/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except Exception:  # noqa: BLE001 — a probe must never propagate failure
        logger.debug("probe_mureo_instance: %s unreachable", url, exc_info=True)
        return False
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    return payload.get("app") == PING_APP_NAME


def state_file_path(home: Path) -> Path:
    """Resolve the active-port state file under ``<home>/.mureo``.

    Mirrors :mod:`mureo.web.host_paths`' ``~/.mureo`` convention; the
    caller passes the resolved home so tests can inject ``tmp_path``.
    """
    return home / ".mureo" / STATE_FILENAME


def write_state_file(home: Path, *, port: int, url: str) -> None:
    """Persist ``{"port", "pid", "url"}`` to ``<home>/.mureo/configure.json``.

    Best-effort: a write failure (missing parent, read-only FS) is logged
    and swallowed so persisting the port can never crash ``configure``.
    The file is chmod-ed ``0o600`` — it carries no secrets, but matching
    the rest of ``~/.mureo`` keeps the directory uniformly owner-only.
    """
    path = state_file_path(home)
    payload = {"port": int(port), "pid": os.getpid(), "url": url}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Create the file 0o600 from the start (no world-readable window
        # between create and a later chmod); keep chmod as belt-and-braces
        # for a pre-existing file with looser perms. Mirrors the pattern in
        # ``mureo.mcp.plugin_audit``.
        def _opener(p: str, flags: int) -> int:
            return os.open(p, flags | os.O_CREAT, 0o600)

        with open(path, "w", encoding="utf-8", opener=_opener) as fh:
            fh.write(json.dumps(payload))
        secure_chmod(path)
    except OSError:
        logger.debug("write_state_file best-effort skip", exc_info=True)


def read_state_file(home: Path) -> dict[str, Any] | None:
    """Load the active-port state, or ``None`` if absent/unreadable.

    Returns the parsed object only when it is a JSON object carrying a
    string ``url`` and an int-coercible ``port``; anything else (missing
    file, corrupt JSON, wrong shape) yields ``None`` so ``mureo open``
    can fall back to its "run configure first" guidance. Never raises.
    """
    path = state_file_path(home)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    url = payload.get("url")
    port = payload.get("port")
    if not isinstance(url, str) or not url:
        return None
    try:
        payload["port"] = int(port)
    except (TypeError, ValueError):
        return None
    return payload


__all__ = [
    "PING_APP_NAME",
    "STATE_FILENAME",
    "probe_mureo_instance",
    "read_state_file",
    "state_file_path",
    "write_state_file",
]
