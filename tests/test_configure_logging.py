"""Logging setup for the ``mureo configure`` server (#581).

Nothing in mureo used to install a logging handler, so every
``logger.info`` / ``logger.debug`` a configure run emitted was discarded
and ``WARNING`` and above reached stderr only through Python's
``lastResort`` fallback. These tests pin the replacement:

* a rotating file handler on the ``mureo`` package logger — never on the
  root logger, and never at import time, so importing mureo as a library
  still leaves logging entirely to the host application;
* a documented, per-user path (``~/.mureo/logs/configure.log``) that has
  exactly one writer, so rotation cannot fight launchd's stream capture;
* ``INFO`` by default, raisable with ``MUREO_LOG_LEVEL``;
* the credential-tool constraint: raising the level to ``DEBUG`` turns on
  the HTTP access lines of three request handlers, whose request line
  carries the OAuth ``?code=`` callback. Those query strings are redacted
  before they reach the log.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING, Any

import pytest

from mureo import logging_setup

if TYPE_CHECKING:
    from pathlib import Path


def _mureo_logger() -> logging.Logger:
    return logging.getLogger(logging_setup.PACKAGE_LOGGER_NAME)


def _file_handlers() -> list[RotatingFileHandler]:
    return [
        handler
        for handler in _mureo_logger().handlers
        if isinstance(handler, RotatingFileHandler)
    ]


@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.mark.unit
class TestConfigureLogPath:
    """The path is documented, derived, and never created as a side effect."""

    def test_path_is_under_the_mureo_home(self, home_dir: Path) -> None:
        assert logging_setup.configure_log_path(home_dir) == (
            home_dir / ".mureo" / "logs" / "configure.log"
        )

    def test_path_honours_mureo_home_env(
        self, home_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUREO_HOME", str(home_dir))
        assert logging_setup.configure_log_path() == (
            home_dir / ".mureo" / "logs" / "configure.log"
        )

    def test_resolving_the_path_creates_nothing(self, home_dir: Path) -> None:
        logging_setup.configure_log_path(home_dir)
        assert not (home_dir / ".mureo").exists()

    def test_path_is_not_the_launchd_stream_capture_file(self, home_dir: Path) -> None:
        """The rotating handler must not share launchd's redirect target.

        launchd holds an open fd on ``~/.mureo/configure.log``; a rotation
        that renames it out from under launchd would leave the daemon
        appending to the rotated inode forever.
        """
        from mureo.web.service.launchd import _log_paths

        launchd_out, launchd_err = _log_paths(home_dir)
        our_log = logging_setup.configure_log_path(home_dir)
        assert our_log != launchd_out
        assert our_log != launchd_err


@pytest.mark.unit
class TestLogLevelResolution:
    """``INFO`` by default, raisable through one documented env var."""

    def test_default_is_info(self) -> None:
        assert logging_setup.resolve_log_level({}) == logging.INFO

    def test_env_var_raises_the_level(self) -> None:
        assert logging_setup.resolve_log_level({"MUREO_LOG_LEVEL": "DEBUG"}) == (
            logging.DEBUG
        )

    def test_env_var_is_case_and_space_insensitive(self) -> None:
        assert logging_setup.resolve_log_level({"MUREO_LOG_LEVEL": " warning "}) == (
            logging.WARNING
        )

    def test_unknown_value_falls_back_to_the_default(self) -> None:
        assert logging_setup.resolve_log_level({"MUREO_LOG_LEVEL": "chatty"}) == (
            logging.INFO
        )

    def test_notset_falls_back_to_the_default(self) -> None:
        """``NOTSET`` means "inherit", which for a configure run is silence."""
        assert logging_setup.resolve_log_level({"MUREO_LOG_LEVEL": "NOTSET"}) == (
            logging.INFO
        )

    def test_empty_value_falls_back_to_the_default(self) -> None:
        assert logging_setup.resolve_log_level({"MUREO_LOG_LEVEL": ""}) == logging.INFO

    def test_defaults_to_the_process_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUREO_LOG_LEVEL", "ERROR")
        assert logging_setup.resolve_log_level() == logging.ERROR


@pytest.mark.unit
class TestSetupConfigureLogging:
    """Installing the handler: scope, contents, rotation, permissions."""

    def test_creates_the_log_file_and_returns_its_path(self, home_dir: Path) -> None:
        path = logging_setup.setup_configure_logging(home=home_dir)
        assert path == home_dir / ".mureo" / "logs" / "configure.log"
        assert path is not None
        assert path.exists()

    def test_package_logger_records_reach_the_file(self, home_dir: Path) -> None:
        path = logging_setup.setup_configure_logging(home=home_dir)
        assert path is not None
        logging.getLogger("mureo.web.server").info("configure UI ready at %s", "here")
        contents = path.read_text(encoding="utf-8")
        assert "configure UI ready at here" in contents
        assert "mureo.web.server" in contents
        assert "INFO" in contents

    def test_root_logger_is_left_alone(self, home_dir: Path) -> None:
        before = list(logging.getLogger().handlers)
        logging_setup.setup_configure_logging(home=home_dir)
        assert logging.getLogger().handlers == before

    def test_foreign_loggers_do_not_reach_the_file(self, home_dir: Path) -> None:
        """Third-party libraries stay out of it.

        The google-ads SDK logs full request/response payloads at DEBUG —
        developer token included. Scoping the handler to the ``mureo``
        logger means raising mureo's level can never turn that on.
        """
        path = logging_setup.setup_configure_logging(home=home_dir)
        assert path is not None
        logging.getLogger("google.ads.googleads.client").warning("developer_token=abc")
        assert "developer_token" not in path.read_text(encoding="utf-8")

    def test_debug_is_withheld_by_default(self, home_dir: Path) -> None:
        path = logging_setup.setup_configure_logging(home=home_dir, env={})
        assert path is not None
        logging.getLogger("mureo.web.handlers").debug("noisy access line")
        assert "noisy access line" not in path.read_text(encoding="utf-8")

    def test_env_var_raises_the_installed_level(self, home_dir: Path) -> None:
        path = logging_setup.setup_configure_logging(
            home=home_dir, env={"MUREO_LOG_LEVEL": "DEBUG"}
        )
        assert path is not None
        logging.getLogger("mureo.web.handlers").debug("noisy access line")
        assert "noisy access line" in path.read_text(encoding="utf-8")

    def test_warnings_still_reach_stderr(self, home_dir: Path) -> None:
        """The stderr surface the ``lastResort`` fallback provided is kept."""
        logging_setup.setup_configure_logging(home=home_dir)
        stream_handlers = [
            handler
            for handler in _mureo_logger().handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].stream is sys.stderr
        assert stream_handlers[0].level == logging.WARNING

    def test_is_idempotent(self, home_dir: Path) -> None:
        first = logging_setup.setup_configure_logging(home=home_dir)
        handlers_after_first = list(_mureo_logger().handlers)
        second = logging_setup.setup_configure_logging(home=home_dir)
        assert second == first
        assert _mureo_logger().handlers == handlers_after_first

    def test_rotation_is_bounded(self, home_dir: Path) -> None:
        logging_setup.setup_configure_logging(home=home_dir)
        handlers = _file_handlers()
        assert len(handlers) == 1
        assert handlers[0].maxBytes == logging_setup.MAX_LOG_BYTES
        assert handlers[0].maxBytes > 0
        assert handlers[0].backupCount == logging_setup.BACKUP_COUNT
        assert handlers[0].backupCount >= 1

    def test_the_file_rolls_over_instead_of_growing(
        self, home_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(logging_setup, "MAX_LOG_BYTES", 400)
        path = logging_setup.setup_configure_logging(home=home_dir)
        assert path is not None
        for index in range(50):
            logging.getLogger("mureo.web.server").info("line %d padded out", index)
        assert (path.parent / f"{path.name}.1").exists()
        assert path.stat().st_size <= 4000

    @pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
    def test_the_log_file_is_owner_only(self, home_dir: Path) -> None:
        path = logging_setup.setup_configure_logging(home=home_dir)
        assert path is not None
        assert path.stat().st_mode & 0o777 == 0o600

    def test_an_unwritable_destination_never_breaks_configure(
        self, home_dir: Path
    ) -> None:
        """A read-only home must degrade to stderr, not crash the server."""
        (home_dir / ".mureo").mkdir()
        (home_dir / ".mureo" / "logs").write_text("not a directory", encoding="utf-8")
        assert logging_setup.setup_configure_logging(home=home_dir) is None
        assert _file_handlers() == []


@pytest.mark.unit
class TestNoImportTimeSideEffects:
    """Importing mureo must not hijack logging for library consumers."""

    def test_importing_the_module_installs_nothing(self) -> None:
        import importlib

        importlib.reload(logging_setup)
        assert _mureo_logger().handlers == []


@pytest.mark.unit
class TestHttpAccessLogScrubbing:
    """A raised level must not turn an access log into a credential leak."""

    def test_query_string_is_redacted(self) -> None:
        line = logging_setup.safe_http_log_line(
            '"%s" %s %s',
            "GET /oauth/callback?code=SEKRIT&state=abc HTTP/1.1",
            "200",
            "-",
        )
        assert "SEKRIT" not in line
        assert "abc" not in line
        assert "/oauth/callback" in line
        assert "200" in line

    def test_paths_without_a_query_are_untouched(self) -> None:
        line = logging_setup.safe_http_log_line(
            '"%s" %s %s', "GET / HTTP/1.1", "200", "-"
        )
        assert line == '"GET / HTTP/1.1" 200 -'

    def test_malformed_error_lines_are_redacted_too(self) -> None:
        line = logging_setup.safe_http_log_line(
            "code %d, message %s",
            400,
            "Bad request syntax ('GET /?code=SEKRIT HTTP/1.1')",
        )
        assert "SEKRIT" not in line

    def test_mismatched_format_args_do_not_raise(self) -> None:
        assert logging_setup.safe_http_log_line("%s %s", "only-one") == "%s %s"

    @pytest.mark.parametrize(
        "module_path",
        [
            "mureo.web.handlers.ConfigureHandler",
            "mureo.cli.web_auth._WizardHandler",
            "mureo.auth_setup._CallbackHandler",
        ],
    )
    def test_request_handlers_scrub_before_logging(
        self, module_path: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Every ``log_message`` override routes through the scrubber.

        Their request line carries the OAuth callback's ``?code=`` — an
        authorization code is credential material, so it must never be
        written even at DEBUG.
        """
        import importlib

        module_name, _, class_name = module_path.rpartition(".")
        handler_cls: Any = getattr(importlib.import_module(module_name), class_name)
        with caplog.at_level(logging.DEBUG, logger="mureo"):
            handler_cls.log_message(
                object(),
                '"%s" %s %s',
                "GET /callback?code=SEKRIT&state=abc HTTP/1.1",
                "200",
                "-",
            )
        text = caplog.text
        assert "SEKRIT" not in text
        assert "/callback" in text


@pytest.mark.unit
class TestConfigureEntryPointWiring:
    """The configure server installs the handler on every platform.

    ``run_configure_wizard`` is the single funnel: the interactive CLI,
    ``--serve``, and all three service backends (launchd / systemd /
    Scheduled Task) reach the server through it.
    """

    def test_running_the_wizard_installs_the_log(self, home_dir: Path) -> None:
        from unittest.mock import patch

        from mureo.web.server import run_configure_wizard

        with patch("mureo.web.server.webbrowser.open"):
            run_configure_wizard(
                home=home_dir,
                open_browser=False,
                timeout_seconds=0.2,
            )
        log_path = home_dir / ".mureo" / "logs" / "configure.log"
        assert log_path.exists()
        assert "configure UI ready" in log_path.read_text(encoding="utf-8")

    def test_cli_reports_where_the_log_is(self) -> None:
        from unittest.mock import patch

        from typer.testing import CliRunner

        from mureo.cli.main import app

        with patch("mureo.cli.configure_cmd.run_configure_wizard", return_value=False):
            result = CliRunner().invoke(app, ["configure", "--no-browser"])
        assert result.exit_code == 0, result.output
        assert str(logging_setup.configure_log_path()) in result.output
