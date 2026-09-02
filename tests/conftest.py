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


@pytest.fixture(autouse=True)
def _isolate_credential_writes(monkeypatch, tmp_path_factory):
    """Keep every test's credential writes inside a throwaway home (#739).

    The two ``path``-less credential writers — ``refresh_meta_token_if_needed``
    and ``save_amazon_access_token`` — resolve their destination through
    ``mureo.auth._resolve_write_path`` →
    ``mureo.core.runtime_context.runtime_credentials_path``. That resolver has
    two ways of reaching a real file:

    - the fallback is ``Path.home() / ".mureo" / "credentials.json"``, i.e. the
      contributor's OWN credentials; and
    - when ANY ``mureo.runtime_context_factory`` entry point is installed in
      the interpreter running the suite, the fallback is ignored entirely and
      the write lands wherever that plugin's ``SecretStore`` points — which on
      an operator machine is the shared credentials file. ``pip install -e .``
      of a host distribution alongside mureo is enough to arm this.

    Tests that never meant to write anything real were doing exactly that: a
    mocked Graph 200 makes the refresh succeed, and the save that follows is
    not mocked. Because ``get_runtime_context`` caches the resolved context
    process-wide, a later ``HOME`` patch could not undo it either.

    So: point ``HOME`` (POSIX ``Path.home()``) and ``USERPROFILE`` (Windows
    ``Path.home()``; CI runs test-windows) at a fresh temp dir, make the
    factory group look empty, and drop the cached context on both sides of the
    test. Autouse in the root ``conftest.py`` for the same reason as the
    fixtures above: a per-module opt-in only protects the modules that
    remember, which is the failure mode this replaces.

    Tests that deliberately install a fake factory keep working — they patch
    the same ``entry_points`` attribute later in the stack, so their stub wins
    for the duration of the test and unwinds before this fixture restores the
    original.
    """
    from mureo.core import runtime_context
    from mureo.core.runtime_context import (
        RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
    )

    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    real_entry_points = runtime_context.entry_points

    def _entry_points_without_factories(*args, **kwargs):
        """Hide installed factories; every other group is passed through."""
        if kwargs.get("group") == RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP:
            return []
        return real_entry_points(*args, **kwargs)

    monkeypatch.setattr(
        runtime_context, "entry_points", _entry_points_without_factories
    )

    runtime_context.reset_runtime_context()
    yield
    runtime_context.reset_runtime_context()
