"""Session-wide fixtures for the whole test suite."""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _restore_mureo_package_logger():
    """Undo any ``mureo`` package-logger configuration a test performed (#581).

    ``mureo configure`` installs a rotating file handler plus a stderr
    handler on the ``mureo`` logger and raises that logger's level. Any
    test that reaches the configure entry point would otherwise leak both
    into every later test: the file handler keeps writing to a deleted
    ``tmp_path`` and the level silently filters records other tests assert
    on. Autouse in the root ``conftest.py`` so no test has to remember.
    """
    package_logger = logging.getLogger("mureo")
    handlers = list(package_logger.handlers)
    level = package_logger.level
    yield
    for handler in list(package_logger.handlers):
        if handler not in handlers:
            package_logger.removeHandler(handler)
            handler.close()
    package_logger.setLevel(level)


@pytest.fixture(autouse=True)
def _reset_duplicate_account_warn_latch():
    """Clear the process-wide duplicate-account warn-once latch (#534).

    ``mureo.context.platform_guards`` suppresses a repeat warning for a
    ``(state file, duplicate group)`` pair it has already reported. That is
    correct in production and a test-isolation hazard here: ANY test that
    writes a duplicated document — several do so incidentally, e.g. while
    proving that an already-duplicated document stays writable — arms the
    latch, and a later test asserting on the warning would then see nothing,
    with the outcome depending on collection order.

    Autouse and defined in the root ``conftest.py`` on purpose: a per-class
    fixture only protects the class that remembers to add one, which is
    exactly the failure mode this replaces.
    """
    from mureo.context import platform_guards

    platform_guards._DUPLICATE_ACCOUNT_WARNED.clear()
    yield
    platform_guards._DUPLICATE_ACCOUNT_WARNED.clear()
