"""The action_log entry model moved to its own module; the old path stays.

:mod:`mureo.context.models` re-exports :class:`ActionLogEntry` and
:data:`EXTERNAL_ORIGIN` from :mod:`mureo.context.action_log_entry` (#851), so
code importing them from the old path gets the very same objects, not copies.
"""

from __future__ import annotations

import pytest

from mureo.context import action_log_entry, models

pytestmark = pytest.mark.unit

NAMES = ("ActionLogEntry", "EXTERNAL_ORIGIN")


@pytest.mark.parametrize("name", NAMES)
def test_the_old_path_is_the_same_object(name: str) -> None:
    assert getattr(models, name) is getattr(action_log_entry, name)


def test_the_new_module_exports_exactly_these() -> None:
    assert sorted(action_log_entry.__all__) == sorted(NAMES)


def test_a_document_still_holds_an_entry() -> None:
    entry = models.ActionLogEntry(
        timestamp="2026-10-13T10:00:00+00:00", action="a", platform="google_ads"
    )
    doc = models.StateDocument(version="2", action_log=(entry,))
    assert doc.action_log == (entry,)
