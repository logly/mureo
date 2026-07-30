"""Codex CLI image provider — GPT Image via the local ``codex`` binary.

Unlike the hosted-API providers (OpenAI / Google / fal), this adapter does
NOT call a REST endpoint and holds **no API key anywhere**. It shells out to
the locally installed **Codex CLI** (``codex exec``) and drives the CLI's
built-in GPT Image tool to render the picture. Auth is the user's
``codex login`` (ChatGPT account); there is no secret to store or redact.

The model identifier is the opaque built-in tool name ``gpt-image`` — the CLI
owns the exact underlying version, so it is deliberately version-opaque here.

Design notes:

- :meth:`is_configured` is cheap on purpose — it only checks that the
  ``codex`` binary is on ``PATH`` via :func:`shutil.which`, and NEVER spawns a
  process. Login / auth problems surface at :meth:`generate` time with a clear
  hint to run ``codex login``.
- Each image is produced in its own private temp dir (:func:`tempfile.mkdtemp`)
  via :func:`asyncio.create_subprocess_exec` — an argv array, never a shell
  string, so a prompt full of shell metacharacters cannot inject anything.
  That guarantee only holds for a real executable, so on Windows a resolved
  ``.bat``/``.cmd`` shim is refused outright (launching it would make
  ``CreateProcess`` re-invoke ``cmd.exe``, which re-parses the command line):
  :meth:`is_configured` reports False and :meth:`generate` raises with a hint
  to install ``codex.exe`` or run under WSL.
- The run is bounded by a timeout (default 300s, override with the
  ``MUREO_CODEX_TIMEOUT`` environment variable, in seconds). On timeout the
  process is killed and a clear error raised — the whole process group on
  POSIX, the direct child only on Windows (no ``killpg`` there).
- ``n > 1`` runs **sequentially** — concurrent Codex CLI sessions are not
  proven safe, so the provider does not parallelise them.
- Editing is not supported: a live end-to-end check showed the CLI's edit path
  is not reliable enough to ship, so :meth:`edit` raises
  :class:`NotSupportedError` (the fal precedent) and ``capabilities()`` reports
  ``{"edit": False}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mureo.creative_studio.providers import (
    _FIELD_TO_ENV,
    _GPT_IMAGE_SIZES,
    NotSupportedError,
    _creative_studio_secret,
    _redact,
    _size_capabilities,
)

_BINARY = "codex"
_MODEL = "gpt-image"

#: Deterministic output filename the instruction asks the CLI to write.
_OUTPUT_FILENAME = "output.png"

#: Environment variable overriding the per-image subprocess timeout (seconds).
_TIMEOUT_ENV = "MUREO_CODEX_TIMEOUT"
_DEFAULT_TIMEOUT = 300.0

#: Bound on how much captured stderr is echoed into an error (chars).
_STDERR_TAIL = 2000

#: The 8-byte PNG signature — the output must start with it to be accepted.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# GPT Image's supported output sizes, one per aspect class, derived from the
# shared menu (ordered square, landscape, portrait) that the OpenAI
# ``gpt-image-1`` provider also uses — so the sizes asked of the CLI and the
# ones advertised in ``capabilities()`` cannot drift apart. An arbitrary
# width/height is clamped to the nearest of these by orientation.
_SIZE_SQUARE, _SIZE_LANDSCAPE, _SIZE_PORTRAIT = (
    f"{width}x{height}" for width, height in _GPT_IMAGE_SIZES
)

# stderr substrings (matched case-insensitively) that indicate an auth /
# login problem, so the error can append the `codex login` hint.
_AUTH_HINTS: tuple[str, ...] = (
    "login",
    "log in",
    "logged in",
    "not authenticated",
    "unauthenticated",
    "unauthorized",
    "authenticate",
    "sign in",
    "chatgpt account",
)

_LOGIN_HINT = (
    "this looks like an auth problem — run `codex login` to sign the Codex "
    "CLI into your ChatGPT account (no API key is used)"
)
_INSTALL_HINT = (
    "codex provider is not configured: the Codex CLI ('codex') was not found "
    "on PATH. Install the Codex CLI and run `codex login` (no API key needed)"
)

# Windows batch-file shims are refused, never launched. ``CreateProcess`` with
# a NULL ``lpApplicationName`` and a ``.bat``/``.cmd`` target implicitly
# re-invokes ``cmd.exe /c`` on the command line Python assembled with
# ``list2cmdline`` quoting — but cmd.exe's own parser does not honour those
# rules, so metacharacters (`"` `&` `^` `|` `%`) inside an argument can break
# out of the quoting and start new commands (the "BatBadBut" class,
# CVE-2024-27980). Our final argv element carries untrusted prompt text, so
# there is no safe escaping to apply here: fail closed instead. Do NOT "fix"
# this by passing ``executable=`` or ``shell=True`` — both keep the reparse.
_BATCH_SUFFIXES: tuple[str, ...] = (".bat", ".cmd")
_WINDOWS_SHIM_HINT = (
    "codex provider refuses to run the Codex CLI batch shim on Windows "
    "({path}): cmd.exe re-parses the command line, so prompt text could break "
    "out into separate commands. Install the native Codex CLI executable "
    "(codex.exe) on PATH, or run mureo under WSL."
)

# Child-process environment allow-list. The Codex CLI is spawned with ONLY
# these variables (plus any ``CODEX_`` / ``XDG_`` / ``LC_`` prefixed ones) so no
# image-provider API key or other ambient secret leaks into the sandboxed
# subprocess. Kept generous enough for a real codex run (locale, TLS, proxy,
# and codex's own config/auth dir) while fail-closed on everything else.
_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TERM",
        "LANG",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "all_proxy",
        # Windows system infrastructure (non-secret; needed by cmd.exe and the
        # npm .cmd shim). Same class as PATH / HOME / TMPDIR above: a Windows
        # child breaks networking and crypto without SYSTEMROOT, the real Codex
        # CLI ships as an npm ``.cmd`` shim that needs COMSPEC / PATHEXT to
        # launch, and its login state lives under USERPROFILE / APPDATA /
        # LOCALAPPDATA. Listed unconditionally — they simply do not exist on
        # POSIX, where the filter drops them anyway.
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "SYSTEMDRIVE",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
    }
)
_ENV_ALLOW_PREFIXES: tuple[str, ...] = ("LC_", "XDG_", "CODEX_")

# The creative_studio provider key env fallbacks — denied explicitly so they can
# never reach codex even if the allow-list were widened later.
_SECRET_ENV_NAMES: frozenset[str] = frozenset(_FIELD_TO_ENV.values())


def _timeout_seconds() -> float:
    """Return the subprocess timeout in seconds (env override, else default)."""
    raw = os.environ.get(_TIMEOUT_ENV)
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return _DEFAULT_TIMEOUT
        if value > 0:
            return value
    return _DEFAULT_TIMEOUT


def _is_windows_batch_shim(path: str) -> bool:
    """Return whether ``path`` is a Windows batch shim we must refuse to run.

    Uses :func:`os.path.splitext` rather than :class:`pathlib.Path` so the
    check is a pure string operation on every platform. A ``.exe`` (or an
    extensionless binary) is launched directly by ``CreateProcess`` with no
    ``cmd.exe`` reparse, so it stays allowed.
    """
    if os.name != "nt":
        return False
    return os.path.splitext(path)[1].lower() in _BATCH_SUFFIXES


def _spawn_kwargs() -> dict[str, Any]:
    """Return the platform's process-isolation kwargs for the codex spawn.

    POSIX: ``start_new_session=True`` makes codex its own session/process-group
    leader so a timeout can reap the whole tree.

    Windows: sessions do not exist and ``start_new_session`` is unsupported, so
    the nearest equivalent (a new process group) is requested instead. Note the
    weaker guarantee — see :meth:`CodexCliImageProvider._terminate`.
    """
    if os.name == "nt":
        # ``subprocess.CREATE_NEW_PROCESS_GROUP`` exists (and is declared by
        # typeshed) only on Windows, so resolve it dynamically to keep this
        # module importable and mypy-clean on POSIX. The fallback is
        # unreachable on Windows and means "no special flags" elsewhere.
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _clamp_size(width: int, height: int) -> str:
    """Clamp ``width``/``height`` to the nearest GPT Image size by orientation."""
    if width == height:
        return _SIZE_SQUARE
    return _SIZE_LANDSCAPE if width > height else _SIZE_PORTRAIT


def _tail(text: str) -> str:
    """Return the trailing ``_STDERR_TAIL`` chars of ``text`` (stripped)."""
    text = text.strip()
    if len(text) > _STDERR_TAIL:
        return "…" + text[-_STDERR_TAIL:]
    return text


def _looks_like_auth_error(stderr: str) -> bool:
    low = stderr.lower()
    return any(hint in low for hint in _AUTH_HINTS)


def _child_env() -> dict[str, str]:
    """Build the minimal environment for the codex subprocess.

    Only allow-listed variables (plus ``CODEX_`` / ``XDG_`` / ``LC_`` prefixes)
    are forwarded; the image-provider API-key env vars are never included, so a
    prompt-injected codex session cannot exfiltrate a hosted-provider secret.
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        # Deny-list first, allow-list second: a future name collision (a secret
        # env var that also matches an allow-listed name or prefix) then fails
        # closed instead of leaking. Comparison is case-sensitive by design —
        # Windows normalises ``os.environ`` keys to upper case, which is how the
        # Windows entries in ``_ENV_ALLOWLIST`` are spelled.
        if key in _SECRET_ENV_NAMES:
            continue  # never forward an image-provider API key
        if key in _ENV_ALLOWLIST or key.startswith(_ENV_ALLOW_PREFIXES):
            env[key] = value
    return env


def _redact_secrets(text: str) -> str:
    """Redact every configured creative_studio secret value out of ``text``.

    Codex stderr is echoed into raised errors; if a secret ever surfaces there
    (e.g. a mis-set key printed by a tool), scrub it the same way the hosted
    providers scrub their own errors before it reaches the caller.
    """
    for field in _FIELD_TO_ENV:
        secret = _creative_studio_secret(field)
        if secret:
            text = _redact(text, secret)
    return text


def _generate_instruction(prompt: str, size: str) -> str:
    """Build the English instruction handed to ``codex exec`` for generation."""
    return (
        "Use your built-in GPT Image tool to generate exactly one image and "
        f"save it to a file named '{_OUTPUT_FILENAME}' in the current working "
        f"directory. The image must be a PNG at {size} pixels. Do not write any "
        "other files, do not ask for confirmation, and do not explain your "
        f"steps — just generate the image and save it as '{_OUTPUT_FILENAME}'. "
        f"Image content: {prompt}"
    )


class CodexCliImageProvider:
    """Image provider backed by the local Codex CLI's GPT Image tool."""

    name = "codex"
    models: tuple[str, ...] = (_MODEL,)

    def is_configured(self) -> bool:
        # Cheap discovery: presence of the binary only, never a subprocess.
        # Fail closed on a Windows batch shim — the provider will always refuse
        # to launch it, so it must not be advertised as usable.
        path = shutil.which(_BINARY)
        return path is not None and not _is_windows_batch_shim(path)

    def capabilities(self) -> dict[str, Any]:
        # ``requires_api_key`` / ``auth`` are extra, honest metadata: unlike the
        # hosted providers this one needs no key, only a local `codex login`.
        # ``supported_sizes`` is GPT Image's exact menu; ``max_size`` is the
        # per-axis maximum across it — a 1536x1536 square is NOT generatable.
        return {
            "edit": False,
            **_size_capabilities(_GPT_IMAGE_SIZES),
            "requires_api_key": False,
            "auth": "codex_cli_login",
        }

    def _resolve_binary(self) -> str:
        path = shutil.which(_BINARY)
        if not path:
            raise RuntimeError(_INSTALL_HINT)
        # Refuse a .bat/.cmd shim before anything is spawned — see the
        # _WINDOWS_SHIM_HINT comment for the cmd.exe reparse mechanism.
        if _is_windows_batch_shim(path):
            raise RuntimeError(_WINDOWS_SHIM_HINT.format(path=path))
        return path

    async def _run_codex(self, work_dir: Path, instruction: str) -> bytes:
        """Run one ``codex exec`` in ``work_dir``; return the output PNG bytes.

        Raises a clear :class:`RuntimeError` on launch failure, timeout, or a
        missing / empty / non-PNG output, echoing a bounded stderr tail (and
        the ``codex login`` hint when stderr looks like an auth failure).
        """
        binary = self._resolve_binary()
        argv = [
            binary,
            "exec",
            "--sandbox",
            "workspace-write",
            "--skip-git-repo-check",
            "-C",
            str(work_dir),
            # End-of-options marker: guarantees the instruction (which embeds a
            # user prompt that may start with '-') is always parsed as a
            # positional argument, never as a codex flag.
            "--",
            instruction,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
                # Minimal env — no image-provider API key reaches the sandbox.
                env=_child_env(),
                # Own session/process group so a timeout can reap the whole
                # tree (codex spawns child helper processes of its own).
                # Platform-conditional: POSIX sessions vs. Windows process
                # groups — see :func:`_spawn_kwargs`.
                **_spawn_kwargs(),
            )
        except OSError as exc:
            raise RuntimeError(
                f"codex provider failed to launch the Codex CLI: {exc}"
            ) from exc

        timeout = _timeout_seconds()
        try:
            _stdout, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except (TimeoutError, asyncio.TimeoutError):
            # Reaping the killed tree is best-effort.
            self._terminate(proc)
            with contextlib.suppress(Exception):
                await proc.wait()
            raise RuntimeError(
                f"codex provider timed out after {timeout:.0f}s waiting for the "
                f"Codex CLI. Increase the timeout via the {_TIMEOUT_ENV} "
                "environment variable, or simplify the prompt."
            ) from None

        stderr = (stderr_bytes or b"").decode("utf-8", "replace")
        return self._read_output(work_dir / _OUTPUT_FILENAME, stderr)

    @staticmethod
    def _terminate(proc: asyncio.subprocess.Process) -> None:
        """Kill a timed-out codex run (race-guarded, platform-conditional).

        POSIX: ``start_new_session=True`` makes ``proc`` a group leader, so
        signalling its group reaps codex's child helper processes too.

        Windows: there is no ``killpg`` — only the direct child is killed, on a
        best-effort basis. Helper processes codex spawned may survive the kill;
        that is accepted, since the provider neither waits on nor reads from
        them after the timeout.

        Guards for the process already having exited between the timeout and
        the signal.
        """
        if os.name != "nt":
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        # Fallback on POSIX (the group may be gone), and the only option on
        # Windows: signal the direct process.
        with contextlib.suppress(Exception):
            proc.kill()

    def _read_output(self, output: Path, stderr: str) -> bytes:
        """Validate the output file is a non-empty PNG; return its bytes."""
        # Scrub any configured secret from stderr before it can be surfaced.
        stderr = _redact_secrets(stderr)
        if output.is_symlink():
            # Reject a symlink outright — reading it would follow the link to an
            # attacker-chosen path (content disclosure). Never read its target.
            reason = "produced a symlink instead of a regular image file (rejected)"
        elif not output.is_file():
            reason = "produced no output image"
        else:
            data = output.read_bytes()
            if not data:
                reason = "produced an empty output image"
            elif not data.startswith(_PNG_MAGIC):
                reason = "produced an output file that is not a PNG"
            else:
                return data

        detail = _tail(stderr) or "(no stderr captured)"
        message = f"codex provider {reason}. Codex CLI stderr tail:\n{detail}"
        if _looks_like_auth_error(stderr):
            message += f"\n\n{_LOGIN_HINT}."
        raise RuntimeError(message)

    async def _run_once(self, instruction: str) -> bytes:
        """Run one generation in a private temp dir, cleaned up in ``finally``."""
        work_dir = Path(tempfile.mkdtemp(prefix="mureo-codex-"))
        try:
            return await self._run_codex(work_dir, instruction)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    async def generate(
        self, prompt: str, *, width: int, height: int, n: int = 1
    ) -> list[bytes]:
        # Fail fast with the install hint before creating any temp dir.
        self._resolve_binary()
        size = _clamp_size(width, height)
        instruction = _generate_instruction(prompt, size)
        # Sequential — concurrent Codex CLI sessions are not proven safe.
        return [await self._run_once(instruction) for _ in range(n)]

    async def edit(self, image: bytes, instruction: str) -> bytes:
        # A live end-to-end check found the CLI edit path unreliable, so this
        # provider ships without one (fal precedent) rather than a code path
        # that claims to work but doesn't.
        raise NotSupportedError(
            "codex provider does not support image editing; use an edit-capable "
            "provider (e.g. openai or google) for the art-direction edit loop"
        )


#: Exposed so the shared provider test-suite can instantiate without knowing
#: the concrete class name.
PROVIDER_CLASS = CodexCliImageProvider
