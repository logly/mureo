"""The ops history switch, toggled from ``mureo configure`` (#848).

``settings.ops_history.enabled`` in STATE.json decides whether every
mutating call must carry ``reason`` and ``expected``. The MCP tool
``mureo_state_settings_set`` writes it from an agent; this module is the
same write from the configure UI's Advanced section: a read, a write, and
the two handler functions ``handlers.py`` calls. It lives here rather than
in ``handlers.py`` because that file is already over the project's
file-size budget.

Both paths go through :func:`~mureo.context.settings.set_ops_history_enabled`,
which takes STATE.json's file lock, so a toggle cannot lose a concurrent
action-log append.

The card writes the ACTIVE workspace's STATE.json, the same scope as the
Guardrails card, and sits inside the same cut markers: a backend with a
client roster is served the page without it (see :mod:`mureo.web.app_html`).
The routes still answer a ``client`` parameter, resolved through the one
multi-account seam the Reports tab uses, for a multi-client layer's own
surface.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.context.settings import ops_history_enabled, set_ops_history_enabled
from mureo.context.state import read_state_file
from mureo.web._helpers import send_error_json, send_failure, send_json
from mureo.web.report_clients import state_store_for_client
from mureo.web.strategy_currency import _payload_client, _query_client

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

__all__ = [
    "OpsHistorySettingError",
    "post_ops_history_setting",
    "read_setting",
    "serve_ops_history_setting",
    "state_path_for_client",
    "write_setting",
]

_STATE_FILENAME = "STATE.json"

#: Refusals the caller can fix (a 400); anything else is a fault on our
#: side (a 500).
_CALLER_FAULTS = frozenset({"no_workspace", "invalid_value"})


class OpsHistorySettingError(Exception):
    """The switch could not be read or written.

    Carries a short, secret-free ``code`` the handler maps to an error
    envelope, like
    :class:`~mureo.web.strategy_currency.StrategyCurrencyError`. The
    underlying exception is logged server-side and never echoed.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def state_path_for_client(client: str | None) -> Path:
    """The STATE.json of ``client``'s workspace (the active one on OSS)."""
    store = state_store_for_client(client)
    state_path = getattr(store, "state_path", None)
    if state_path is not None:
        return Path(state_path)
    workspace = getattr(store, "workspace", None)
    if workspace is not None:
        return Path(workspace) / _STATE_FILENAME
    raise OpsHistorySettingError("no_workspace")


def read_setting(path: Path) -> dict[str, Any]:
    """Whether ops history is on for ``path``, and whether the file exists.

    A missing file reads as off: that is every new workspace.
    """
    try:
        doc = read_state_file(path, strict=False)
    except Exception as exc:  # noqa: BLE001 — every read fault is one code
        logger.exception("STATE.json could not be read for the ops history switch")
        raise OpsHistorySettingError("read_failed") from exc
    return {"enabled": ops_history_enabled(doc), "exists": path.exists()}


def write_setting(path: Path, enabled: bool) -> dict[str, Any]:
    """Switch ops history on or off for ``path``.

    A request that changes nothing writes nothing: switching off a
    workspace that has no STATE.json does not create one, and repeating
    the current value does not rewrite the file.
    """
    if not isinstance(enabled, bool):
        raise OpsHistorySettingError("invalid_value")
    if read_setting(path)["enabled"] == enabled:
        return read_setting(path)
    try:
        set_ops_history_enabled(path, enabled)
    except Exception as exc:  # noqa: BLE001 — every write fault is one code
        logger.exception("STATE.json ops history switch could not be written")
        raise OpsHistorySettingError("write_failed") from exc
    return read_setting(path)


def _envelope(client: str | None, path: Path, state: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "client": client, "path": str(path), **state}


def serve_ops_history_setting(handler: BaseHTTPRequestHandler) -> None:
    """GET ``/api/settings/ops_history`` — the switch's current value."""
    client = _query_client(handler.path)
    try:
        path = state_path_for_client(client)
        state = read_setting(path)
    except OpsHistorySettingError as exc:
        send_failure(handler, exc.code, _CALLER_FAULTS)
        return
    send_json(handler, _envelope(client, path, state))


def post_ops_history_setting(
    handler: BaseHTTPRequestHandler, payload: dict[str, Any]
) -> None:
    """POST ``/api/settings/ops_history`` — ``{"enabled": true|false}``.

    Only a JSON boolean is accepted; ``"true"`` or ``1`` is refused rather
    than coerced, because switching this on makes every later change
    require a reason and an expected effect.
    """
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        send_error_json(handler, 400, "invalid_value")
        return
    client = _payload_client(payload)
    try:
        path = state_path_for_client(client)
        state = write_setting(path, enabled)
    except OpsHistorySettingError as exc:
        send_failure(handler, exc.code, _CALLER_FAULTS)
        return
    send_json(handler, _envelope(client, path, state))
