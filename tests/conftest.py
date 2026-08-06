"""Session-wide fixtures for the whole test suite."""

from __future__ import annotations

import pytest


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
