"""Tag-marker ``[mcp_servers.<id>]`` writer/remover for OpenAI Codex.

Codex reads its MCP servers from ``~/.codex/config.toml`` — **TOML**, not
JSON — so the JSON writers (``config_writer`` for Claude Code, ``desktop_mcp``
for Claude Desktop) do not apply. This module gives the configure UI the same
per-host surface for Codex.

Design — tagged regions, not a TOML round-trip
----------------------------------------------
Operators routinely hand-edit ``config.toml`` (comments, ordering, other MCP
servers). A full parse → mutate → serialise round-trip would clobber that, so
— exactly like :mod:`mureo.cli.setup_codex` — each mureo-managed server block
is wrapped in a tagged region::

    # >>> mureo-mcp:mureo >>>
    [mcp_servers.mureo]
    command = "python"
    args = ["-m", "mureo.mcp"]
    # <<< mureo-mcp:mureo <<<

Only the bytes between a region's markers are ever read or rewritten; every
other byte of the file is preserved verbatim. The markers are TOML comments,
so the file stays valid TOML for Codex.

Conflict safety
---------------
Appending ``[mcp_servers.<id>]`` when an **untagged** block of the same name
already exists would create a duplicate TOML key that Codex rejects. The
installer refuses to guess whether that block is stale or hand-authored and
raises :class:`CodexConfigConflictError` (mirrors
``setup_codex.CodexMcpConflictError``).

``~/.mureo/credentials.json`` is never read, written, or deleted here.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from mureo.web.host_paths import get_host_paths

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CodexConfigConflictError",
    "install_codex_mcp_block",
    "install_codex_server_block",
    "installed_codex_server_ids",
    "is_codex_server_installed",
    "read_codex_server_env",
    "remove_codex_mcp_block",
    "remove_codex_server_block",
    "resolve_codex_config_path",
    "set_mureo_disable_env_codex",
    "unset_mureo_disable_env_codex",
]

_MUREO_SERVER_ID = "mureo"


class CodexConfigConflictError(Exception):
    """An untagged ``[mcp_servers.<id>]`` block already exists.

    Adopting it automatically would risk a duplicate-key TOML error at the
    next Codex launch; the operator must reconcile it manually.
    """


def resolve_codex_config_path(home: Path | None = None) -> Path:
    """Resolve ``~/.codex/config.toml`` via ``host_paths`` (home-aware)."""
    return get_host_paths("codex", home=home).mcp_registry_path


# ---------------------------------------------------------------------------
# Tagged-region helpers
# ---------------------------------------------------------------------------


def _begin(server_id: str) -> str:
    return f"# >>> mureo-mcp:{server_id} >>>"


def _end(server_id: str) -> str:
    return f"# <<< mureo-mcp:{server_id} <<<"


def _region_span(text: str, server_id: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` byte offsets of the tagged region, or ``None``.

    The span is inclusive of both marker lines and a trailing newline so a
    removed region leaves no blank gap.
    """
    begin = _begin(server_id)
    end = _end(server_id)
    start = text.find(begin)
    if start == -1:
        return None
    end_idx = text.find(end, start)
    if end_idx == -1:
        return None
    stop = end_idx + len(end)
    # Swallow one trailing newline so repeated install/remove cycles don't
    # accrete blank lines.
    if stop < len(text) and text[stop] == "\n":
        stop += 1
    return start, stop


def _toml_str(value: str) -> str:
    """Render ``value`` as a TOML basic string (quotes + escapes)."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _toml_str_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_str(str(v)) for v in values) + "]"


_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    """Render a TOML table key: bare when safe, else a quoted basic-string.

    Every env key in practice is from a closed allow-list (``GOOGLE_*`` /
    ``META_*`` / ``MUREO_DISABLE_*`` — all bare-safe); quoting an odd key is
    defense-in-depth so a stray name can never break out of the assignment
    and produce invalid TOML.
    """
    return key if _BARE_KEY_RE.match(key) else _toml_str(key)


def _coerce_block(server_config: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a (possibly frozen) catalog block to a plain stdio dict.

    Codex provider blocks are always stdio: ``command`` (str), ``args``
    (list[str]), optional ``env`` (str→str). Hosted_http providers have no
    Codex connector and are handled as ``manual_required`` upstream, so a
    ``url`` shape never reaches here. ``type`` (a Claude add-json artefact)
    is dropped — Codex infers stdio from ``command``.
    """
    command = str(server_config.get("command", ""))
    raw_args = server_config.get("args", [])
    args = [str(a) for a in raw_args] if isinstance(raw_args, (list, tuple)) else []
    raw_env = server_config.get("env", {})
    env = (
        {str(k): str(v) for k, v in raw_env.items()}
        if isinstance(raw_env, Mapping)
        else {}
    )
    return {"command": command, "args": args, "env": env}


def _render_region(server_id: str, block: Mapping[str, Any]) -> str:
    """Render the full tagged region (markers + TOML body) for one server."""
    lines = [
        _begin(server_id),
        f"[mcp_servers.{server_id}]",
        f"command = {_toml_str(str(block.get('command', '')))}",
        f"args = {_toml_str_array(list(block.get('args', [])))}",
    ]
    env = block.get("env") or {}
    if env:
        lines.append("")
        lines.append(f"[mcp_servers.{server_id}.env]")
        for key in sorted(env):
            lines.append(f"{_toml_key(key)} = {_toml_str(str(env[key]))}")
    lines.append(_end(server_id))
    return "\n".join(lines) + "\n"


_ENV_LINE_RE = re.compile(r'^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"(?P<val>.*)"\s*$')
_ARGS_RE = re.compile(r"^args\s*=\s*\[(?P<body>.*)\]\s*$")
_COMMAND_RE = re.compile(r'^command\s*=\s*"(?P<val>.*)"\s*$')
_ITEM_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


_TOML_UNESCAPE = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}


def _unescape_toml(value: str) -> str:
    """Inverse of :func:`_toml_str` — a single left-to-right scan.

    Chained ``str.replace`` calls are NOT a correct inverse: after ``\\\\``
    collapses to one backslash, a following ``n``/``t``/``"`` would be
    mis-read as an escape. A windows ``command`` like ``C:\\nina`` (rendered
    on disk as ``"C:\\\\nina"``) must round-trip back to ``C:\\nina``, not
    ``C:<newline>ina`` — otherwise the env-toggle re-render emits invalid
    TOML and Codex fails to parse the whole file. A scanner consumes the
    backslash and exactly one following char, so it is order-independent.
    """
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        ch = value[i]
        if ch == "\\" and i + 1 < n:
            nxt = value[i + 1]
            out.append(_TOML_UNESCAPE.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_region(region_text: str, server_id: str) -> dict[str, Any]:
    """Parse a region this module rendered back into ``{command, args, env}``.

    Tolerant line parsing of our own canonical format — never the operator's
    surrounding TOML. Missing pieces default empty so a hand-trimmed region
    degrades to a re-render rather than a crash.
    """
    command = ""
    args: list[str] = []
    env: dict[str, str] = {}
    in_env = False
    env_header = f"[mcp_servers.{server_id}.env]"
    block_header = f"[mcp_servers.{server_id}]"
    for raw in region_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == env_header:
            in_env = True
            continue
        if line == block_header:
            in_env = False
            continue
        if in_env:
            m = _ENV_LINE_RE.match(line)
            if m:
                env[m.group("key")] = _unescape_toml(m.group("val"))
            continue
        cmd = _COMMAND_RE.match(line)
        if cmd:
            command = _unescape_toml(cmd.group("val"))
            continue
        arr = _ARGS_RE.match(line)
        if arr:
            args = [_unescape_toml(i) for i in _ITEM_RE.findall(arr.group("body"))]
    return {"command": command, "args": args, "env": env}


def _untagged_block_present(text: str, server_id: str) -> bool:
    """True iff ``[mcp_servers.<id>]`` appears outside our tagged region.

    Guards against producing a duplicate TOML key. The header is matched at a
    line start so ``[mcp_servers.<id>.env]`` (a sub-table) does not count.
    """
    span = _region_span(text, server_id)
    header = f"[mcp_servers.{server_id}]"
    pattern = re.compile(r"^\s*" + re.escape(header) + r"\s*$", re.MULTILINE)
    for m in pattern.finditer(text):
        if span is None or not (span[0] <= m.start() < span[1]):
            return True
    return False


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` atomically (temp file + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _collapse_seam(head: str, tail: str) -> str:
    """Join ``head``+``tail`` after a region removal, tidying ONLY the seam.

    Removing a middle region can leave a 3+ newline run straddling the
    junction (e.g. ``...\\n\\n`` + ``\\n[next]``). Collapse that run to a
    single blank line — but only the run touching the seam, so an
    operator's intentional blank-line spacing elsewhere in the file is
    preserved verbatim (the module's "every other byte" contract).
    """
    joined = head + tail
    seam = len(head)
    start = seam
    while start > 0 and joined[start - 1] == "\n":
        start -= 1
    end = seam
    while end < len(joined) and joined[end] == "\n":
        end += 1
    if end - start >= 3:
        joined = joined[:start] + "\n\n" + joined[end:]
    return joined


def _splice_region(text: str, server_id: str, region: str | None) -> str:
    """Replace/remove the tagged region in ``text``; append when adding new.

    ``region=None`` removes; a string replaces an existing region or appends
    a new one (separated by a blank line from prior content).
    """
    span = _region_span(text, server_id)
    if span is not None:
        head, tail = text[: span[0]], text[span[1] :]
        if region is None:
            return _collapse_seam(head, tail)
        return head + region + tail
    if region is None:
        return text
    if not text:
        return region
    separator = (
        "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    )
    return text + separator + region


# ---------------------------------------------------------------------------
# Public surface (mirrors desktop_mcp.py for parity)
# ---------------------------------------------------------------------------


def install_codex_server_block(
    config_path: Path,
    server_id: str,
    server_config: Mapping[str, Any],
) -> bool:
    """Surgically register ``[mcp_servers.<server_id>]`` in the Codex config.

    Returns ``True`` when the region was written, ``False`` when an identical
    tagged region already exists (idempotent — file byte-identical). Raises
    :class:`CodexConfigConflictError` when an untagged block of the same name
    exists (a duplicate-key hazard). All other file content is preserved.
    """
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if _untagged_block_present(text, server_id):
        raise CodexConfigConflictError(
            f"An untagged [mcp_servers.{server_id}] block already exists in "
            f"{config_path}. Remove it and retry, or wrap it in the mureo tag "
            f"markers ({_begin(server_id)} ... {_end(server_id)}) to adopt it."
        )
    region = _render_region(server_id, _coerce_block(server_config))
    span = _region_span(text, server_id)
    if span is not None and text[span[0] : span[1]] == region:
        return False
    _atomic_write_text(config_path, _splice_region(text, server_id, region))
    return True


def install_codex_mcp_block(
    config_path: Path,
    command: str,
    args: list[str],
) -> bool:
    """Register the ``[mcp_servers.mureo]`` block in the Codex config.

    Presence-based idempotency (mirrors ``install_desktop_mcp_block``):
    returns ``False`` when ANY ``mureo`` region already exists so a
    stale/legacy block is never silently overwritten.
    """
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if _region_span(text, _MUREO_SERVER_ID) is not None:
        return False
    return install_codex_server_block(
        config_path,
        _MUREO_SERVER_ID,
        {"command": command, "args": list(args)},
    )


def remove_codex_server_block(config_path: Path, server_id: str) -> bool:
    """Remove only the ``[mcp_servers.<server_id>]`` region. Idempotent."""
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    if _region_span(text, server_id) is None:
        return False
    _atomic_write_text(config_path, _splice_region(text, server_id, None))
    return True


def remove_codex_mcp_block(config_path: Path) -> bool:
    """Remove only the ``[mcp_servers.mureo]`` region. Idempotent."""
    return remove_codex_server_block(config_path, _MUREO_SERVER_ID)


def set_mureo_disable_env_codex(config_path: Path, env_var: str) -> bool:
    """Set ``[mcp_servers.mureo.env] <env_var> = "1"``. Idempotent ``False``.

    Re-renders the mureo region preserving its command/args and any other
    env keys. No-op (``False``) when there is no mureo region or the var is
    already ``"1"``.
    """
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    span = _region_span(text, _MUREO_SERVER_ID)
    if span is None:
        return False
    block = _parse_region(text[span[0] : span[1]], _MUREO_SERVER_ID)
    if block["env"].get(env_var) == "1":
        return False
    block["env"][env_var] = "1"
    _atomic_write_text(
        config_path,
        _splice_region(text, _MUREO_SERVER_ID, _render_region(_MUREO_SERVER_ID, block)),
    )
    return True


def unset_mureo_disable_env_codex(config_path: Path, env_var: str) -> bool:
    """Pop ``[mcp_servers.mureo.env] <env_var>``. Idempotent ``False`` no-op."""
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    span = _region_span(text, _MUREO_SERVER_ID)
    if span is None:
        return False
    block = _parse_region(text[span[0] : span[1]], _MUREO_SERVER_ID)
    if env_var not in block["env"]:
        return False
    del block["env"][env_var]
    _atomic_write_text(
        config_path,
        _splice_region(text, _MUREO_SERVER_ID, _render_region(_MUREO_SERVER_ID, block)),
    )
    return True


def is_codex_server_installed(config_path: Path, server_id: str) -> bool:
    """True iff a mureo-tagged ``[mcp_servers.<server_id>]`` region exists."""
    if not config_path.exists():
        return False
    return _region_span(config_path.read_text(encoding="utf-8"), server_id) is not None


_REGION_ID_RE = re.compile(
    r"^# >>> mureo-mcp:(?P<id>[A-Za-z0-9._-]+) >>>", re.MULTILINE
)


def installed_codex_server_ids(config_path: Path) -> set[str]:
    """All mureo-managed server ids present in the Codex config (tag scan)."""
    if not config_path.exists():
        return set()
    text = config_path.read_text(encoding="utf-8")
    return {m.group("id") for m in _REGION_ID_RE.finditer(text)}


def read_codex_server_env(config_path: Path, server_id: str) -> dict[str, str]:
    """Return the ``env`` table of a mureo-managed server, ``{}`` if absent.

    Read-only; used by the status snapshot to surface which
    ``MUREO_DISABLE_<platform>`` flags the mureo block currently carries.
    Parses only this module's own tagged region, never the operator's
    surrounding TOML.
    """
    if not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8")
    span = _region_span(text, server_id)
    if span is None:
        return {}
    env = _parse_region(text[span[0] : span[1]], server_id)["env"]
    return dict(env)
