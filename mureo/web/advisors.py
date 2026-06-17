"""Configure-UI actions for the External advisor MCP card (#advanced).

The dashboard's Advanced → "External advisor MCP" card lists / adds /
deletes entries in ``~/.mureo/insight_sources.json`` — the external MCP
servers ``mureo_consult_advisor`` fans out to. This module is the thin
wrapper the ``/api/advisors`` endpoints call: it builds an
:class:`~mureo.learning.insight_sources.InsightSource` from the request
body (whose ``__post_init__`` runs the canonical validation), persists it
through the #276-hardened writer, and returns JSON-friendly envelopes.

Scope is strictly list / add / delete — there is NO connection test and
NO enable/disable toggle.

Security boundary: an advisor entry can name an arbitrary local command
(stdio) and pass env secrets to a third-party binary, so the card carries
an explicit warning and only trusted advisors should be added. The values
here are operator-supplied config, not credentials, but the writer still
uses the atomic + backup + fail-closed stack so a corrupt file is never
clobbered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.learning.insight_sources import (
    InsightSource,
    add_insight_source,
    load_insight_sources,
    remove_insight_source,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "AdvisorActionError",
    "add_advisor",
    "list_advisors",
    "remove_advisor",
]


class AdvisorActionError(Exception):
    """Raised for a client-correctable advisor action failure (400-class).

    Carries a short, secret-free ``code`` the handler maps to an error
    envelope. The message is safe to surface — it never echoes a command,
    env value, or header.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def list_advisors(*, path: Path | None = None) -> list[dict[str, str]]:
    """Return the configured advisors as display rows.

    Tolerant read (a malformed file simply lists nothing) — listing must
    never 500. Each row carries ``name``, ``transport`` and a ``target``
    (the command for stdio, the url for sse/http) for display only; no
    args / env / headers are surfaced (a header could be a bearer token).
    """
    config = load_insight_sources(path)
    rows: list[dict[str, str]] = []
    for source in config.sources:
        target = source.command if source.transport == "stdio" else source.url
        rows.append(
            {
                "name": source.name,
                "transport": source.transport,
                "target": target or "",
            }
        )
    return rows


def _coerce_str_map(raw: Any) -> dict[str, str] | None:
    """Coerce a JSON object of str→str (env / headers) or ``None``.

    A non-dict (absent / wrong type) yields ``None`` so the
    inherit-vs-sealed distinction is preserved: an explicit ``{}`` in the
    body stays ``{}`` (sealed empty env), an omitted key stays ``None``
    (inherit). Values are stringified defensively.
    """
    if not isinstance(raw, dict):
        return None
    return {str(k): str(v) for k, v in raw.items()}


def add_advisor(payload: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Build an ``InsightSource`` from ``payload`` and persist it.

    Returns ``{"status": "ok", "advisors": [...]}`` with the updated list
    on success. Raises :class:`AdvisorActionError` (mapped to a 400-class
    envelope) when the body is invalid (``InsightSource`` validation /
    duplicate name); the message never leaks a secret.
    """
    name = str(payload.get("name", "")).strip()
    transport = str(payload.get("transport", "")).strip()
    tool = str(payload.get("tool", "")).strip()
    command_raw = payload.get("command")
    command = str(command_raw).strip() if command_raw not in (None, "") else None
    args_raw = payload.get("args")
    args = tuple(str(a) for a in args_raw) if isinstance(args_raw, list) else ()
    env = _coerce_str_map(payload.get("env"))
    url_raw = payload.get("url")
    url = str(url_raw).strip() if url_raw not in (None, "") else None
    headers = _coerce_str_map(payload.get("headers"))

    try:
        source = InsightSource(
            name=name,
            transport=transport,  # type: ignore[arg-type]
            tool=tool,
            command=command,
            args=args,
            env=env,
            url=url,
            headers=headers,
        )
    except ValueError as exc:
        # ``InsightSource.__post_init__`` raises ValueError with a field
        # name in the message; surface a generic, secret-free code.
        raise AdvisorActionError("invalid_advisor") from exc

    try:
        config = add_insight_source(source, path=path)
    except ValueError as exc:  # duplicate name
        raise AdvisorActionError("duplicate_name") from exc

    rows = [
        {
            "name": s.name,
            "transport": s.transport,
            "target": (s.command if s.transport == "stdio" else s.url) or "",
        }
        for s in config.sources
    ]
    return {"status": "ok", "advisors": rows}


def remove_advisor(
    payload: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Remove the advisor named in ``payload`` and return the updated list.

    Idempotent: removing an absent name is not an error — the response
    just reports the unchanged list. Raises :class:`AdvisorActionError`
    when ``name`` is missing/blank.
    """
    name = str(payload.get("name", "")).strip()
    if not name:
        raise AdvisorActionError("name_required")
    remove_insight_source(name, path=path)
    return {"status": "ok", "advisors": list_advisors(path=path)}
