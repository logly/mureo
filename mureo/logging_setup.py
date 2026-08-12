"""Logging for the ``mureo configure`` server (#581).

mureo used to configure logging nowhere: every module took a
``logging.getLogger(__name__)`` and nothing ever installed a handler, so
Python fell back to ``lastResort`` — ``WARNING`` and above went to stderr
unformatted and every ``info`` / ``debug`` was discarded. Diagnostics the
code deliberately preserves (a swallowed Meta token refresh, an account
listing that failed for an unknowable reason) therefore reached nobody,
and "check the log" was advice no operator could act on.

Three deliberate scoping decisions:

**Where.** The handlers go on the ``mureo`` package logger, never the
root logger, and they are installed by :func:`setup_configure_logging`
from the configure entry point — never at import time. Importing mureo as
a library leaves logging entirely to the host application, which is the
one property a package must not take away. Scoping to ``mureo`` also
excludes third-party loggers by construction: the google-ads SDK logs
whole request/response payloads (developer token included) at DEBUG, and
raising *mureo's* level must never turn that on.

**Where it writes.** ``~/.mureo/logs/configure.log``, rotated. It is
deliberately NOT ``~/.mureo/configure.log``: that file is the macOS
LaunchAgent's stdout redirect (``mureo/web/service/launchd.py``), and
launchd holds an open fd on it. A rotation would rename it out from under
launchd, which would then append to the rotated inode forever — two
writers, one of them unbounded. Keeping the two apart gives the rotating
file exactly one writer. On macOS the launchd files remain as raw stream
capture (tracebacks, ``typer.echo`` lines); the file here is the
application log on all three platforms.

**How loud.** ``INFO`` by default; ``MUREO_LOG_LEVEL`` raises or lowers
it. An environment variable rather than a CLI flag because the daemon is
started by a supervisor with a fixed argv (LaunchAgent plist, systemd
unit, Scheduled Task) — a flag would only ever reach the interactive run.

DEBUG is a credential surface, not just a noisy one: it turns on the HTTP
access lines of the request handlers, whose request line carries the
OAuth callback's ``?code=``. :func:`safe_http_log_line` redacts query
strings before they are handed to the logger, so raising the level cannot
turn an access log into a token store.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

from mureo.fsutil import secure_chmod

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: The logger the configure handlers attach to — mureo's own package
#: logger, so a library consumer's root configuration is never touched.
PACKAGE_LOGGER_NAME = "mureo"

#: Environment variable overriding the ``~/.mureo`` home root (same
#: convention as :mod:`mureo.cli.open_cmd`).
MUREO_HOME_ENV = "MUREO_HOME"

#: Environment variable selecting the log level for a configure run.
LOG_LEVEL_ENV = "MUREO_LOG_LEVEL"

#: Level used when ``MUREO_LOG_LEVEL`` is unset, empty or unrecognised.
DEFAULT_LOG_LEVEL = logging.INFO

_MUREO_DIR_NAME = ".mureo"
_LOG_DIR_NAME = "logs"
_LOG_FILE_NAME = "configure.log"

#: Rotation bounds: the log can never exceed ``MAX_LOG_BYTES *
#: (BACKUP_COUNT + 1)`` (~4 MiB) no matter how long the daemon runs.
MAX_LOG_BYTES = 1_048_576
BACKUP_COUNT = 3

_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_STDERR_FORMAT = "mureo: %(levelname)s %(message)s"

#: Marks the handlers this module installed so a second call is a no-op
#: and so tests can identify them without matching on type alone.
_MUREO_HANDLER_ATTR = "_mureo_configure_handler"

#: Replacement for a redacted query string in an HTTP access line.
_REDACTED_QUERY = "?<redacted>"


class _SecureRotatingFileHandler(RotatingFileHandler):
    """Rotating handler that keeps every generation owner-only.

    ``doRollover`` creates the fresh file with the process umask, which
    would drop the ``0o600`` applied at install time. Re-applying it after
    each roll keeps the whole set at owner-only on POSIX (best-effort
    no-op on Windows, like every other mureo file write).
    """

    def doRollover(self) -> None:  # noqa: N802 — stdlib override
        super().doRollover()
        secure_chmod(self.baseFilename)


def _resolve_home(home: Path | None) -> Path:
    """Resolve the home root, honouring an injected ``home`` and env."""
    if home is not None:
        return home
    override = os.environ.get(MUREO_HOME_ENV)
    if override:
        return Path(override)
    return Path.home()


def configure_log_path(home: Path | None = None) -> Path:
    """Return the configure log path. Creates nothing."""
    return _resolve_home(home) / _MUREO_DIR_NAME / _LOG_DIR_NAME / _LOG_FILE_NAME


def resolve_log_level(env: Mapping[str, str] | None = None) -> int:
    """Resolve the configure log level from ``MUREO_LOG_LEVEL``.

    Unset, empty or unrecognised values resolve to :data:`DEFAULT_LOG_LEVEL`
    — a typo in an env var must not silence the log it was meant to open.
    """
    source = env if env is not None else os.environ
    raw = source.get(LOG_LEVEL_ENV, "").strip().upper()
    if not raw:
        return DEFAULT_LOG_LEVEL
    resolved = logging.getLevelName(raw)
    # ``NOTSET`` (0) resolves to an int but means "inherit from the root
    # logger", which for a configure run is silence — treat it as a typo.
    if isinstance(resolved, int) and resolved > logging.NOTSET:
        return resolved
    return DEFAULT_LOG_LEVEL


def _installed_file_handler() -> RotatingFileHandler | None:
    """Return the rotating handler this module installed, if any."""
    for handler in logging.getLogger(PACKAGE_LOGGER_NAME).handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(
            handler, _MUREO_HANDLER_ATTR, False
        ):
            return handler
    return None


def _already_installed() -> bool:
    """``True`` when this module already installed its handlers."""
    return any(
        getattr(handler, _MUREO_HANDLER_ATTR, False)
        for handler in logging.getLogger(PACKAGE_LOGGER_NAME).handlers
    )


def _mark(handler: logging.Handler) -> logging.Handler:
    """Tag a handler as installed by this module."""
    setattr(handler, _MUREO_HANDLER_ATTR, True)
    return handler


def _add_stderr_handler(package_logger: logging.Logger) -> None:
    """Keep warnings on stderr, the one surface operators already watch.

    Without this the file handler would *remove* today's behaviour:
    ``lastResort`` only fires when a record finds no handler at all.
    """
    handler = logging.StreamHandler()
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(_STDERR_FORMAT))
    package_logger.addHandler(_mark(handler))


def _add_file_handler(package_logger: logging.Logger, path: Path) -> Path | None:
    """Install the rotating file handler, or return ``None`` on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handler = _SecureRotatingFileHandler(
            path,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        # A read-only home or a path collision must not stop the configure
        # server from starting — it degrades to the stderr handler above.
        package_logger.warning(
            "Could not open the mureo configure log at %s; "
            "continuing with stderr output only.",
            path,
            exc_info=True,
        )
        return None
    secure_chmod(path)
    handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    package_logger.addHandler(_mark(handler))
    return path


def setup_configure_logging(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Install the configure server's log handlers. Idempotent.

    Returns the path being written to, or ``None`` when the file could not
    be opened (the stderr handler is still installed in that case).

    Call this from the configure entry point only — never at import time.
    """
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    package_logger.setLevel(resolve_log_level(env))
    if _already_installed():
        existing = _installed_file_handler()
        return Path(existing.baseFilename) if existing is not None else None
    _add_stderr_handler(package_logger)
    return _add_file_handler(package_logger, configure_log_path(home))


def scrub_http_log_line(message: str) -> str:
    """Redact every query string in an HTTP access-log line.

    The OAuth callbacks land as ``GET /callback?code=<authorization code>``
    and an authorization code is exchangeable for a token, so the query is
    credential material. Path, status and size are what triage needs; the
    query never is, so all of it goes rather than a curated deny-list of
    parameter names that the next flow would silently outgrow.
    """
    parts = message.split(" ")
    return " ".join(
        f"{part.split('?', 1)[0]}{_REDACTED_QUERY}" if "?" in part else part
        for part in parts
    )


def safe_http_log_line(fmt: str, *args: object) -> str:
    """Format a ``BaseHTTPRequestHandler.log_message`` call and scrub it.

    Interpolating here (rather than handing ``fmt`` and ``args`` to the
    logger) is what makes the scrub possible at all: the secret lives in
    ``args``, and only the formatted line can be redacted as one string.
    """
    try:
        message = fmt % args if args else fmt
    except (TypeError, ValueError):
        # A malformed call must not raise inside a request handler.
        message = fmt
    return scrub_http_log_line(message)
