"""The display contract models moved to their own module; the old path stays.

:mod:`mureo.context.models` re-exports every class from
:mod:`mureo.context.display_models`, so code importing them from the old
path gets the very same classes, not copies.
"""

from __future__ import annotations

import pytest

from mureo.context import display_models, models

pytestmark = pytest.mark.unit

NAMES = (
    "DisplayBreakdown",
    "DisplayBreakdownRow",
    "DisplayContract",
    "DisplayHighlight",
    "DisplayProposal",
    "DisplayStatedValue",
)


@pytest.mark.parametrize("name", NAMES)
def test_the_old_path_is_the_same_class(name: str) -> None:
    assert getattr(models, name) is getattr(display_models, name)


def test_the_new_module_exports_exactly_these() -> None:
    assert sorted(display_models.__all__) == sorted(NAMES)


def test_a_document_still_holds_a_contract() -> None:
    contract = models.DisplayContract(nav_message="Hello", source="test")
    doc = models.StateDocument(version="2", display=contract)
    assert doc.display is contract
