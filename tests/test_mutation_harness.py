"""``scripts/mutation_check.py`` must stay wired to the real source (#546).

The harness is only worth anything if its anchors still match the code.
A refactor that moves a line would otherwise turn a mutation into a
silent no-op — the harness would still print "CAUGHT" for the ones that
work and never mention the one it can no longer inject, which is exactly
the kind of unauditable green this feature has already been bitten by.

So: every anchor is checked against the file it claims to patch, and
every test path it names is checked to exist. Cheap (file reads only),
and it fails loudly at the moment of the refactor rather than the next
time somebody trusts the harness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._script_loader import load_script

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent


HARNESS = load_script("mutation_check")
MUTATIONS = HARNESS.MUTATIONS  # type: ignore[attr-defined]


def _ids() -> list[str]:
    return [m.name for m in MUTATIONS]


def test_the_harness_covers_a_plausible_surface() -> None:
    """Structural anchor: an emptied table must fail, not vacuously pass."""
    assert len(MUTATIONS) >= 15
    assert len({m.name for m in MUTATIONS}) == len(MUTATIONS)


@pytest.mark.parametrize("mutation", MUTATIONS, ids=_ids())
def test_anchor_still_present_in_the_source(mutation: object) -> None:
    source = (REPO_ROOT / mutation.path).read_text(encoding="utf-8")  # type: ignore[attr-defined]

    assert mutation.original in source, (  # type: ignore[attr-defined]
        f"mutation {mutation.name!r} can no longer be injected into "  # type: ignore[attr-defined]
        f"{mutation.path} — the code moved. Update the anchor rather than "  # type: ignore[attr-defined]
        "dropping the mutation."
    )


@pytest.mark.parametrize("mutation", MUTATIONS, ids=_ids())
def test_mutation_actually_changes_the_source(mutation: object) -> None:
    """A mutation equal to the original would always be 'caught'."""
    assert mutation.original != mutation.mutated  # type: ignore[attr-defined]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=_ids())
def test_named_tests_exist(mutation: object) -> None:
    for test_path in mutation.tests:  # type: ignore[attr-defined]
        assert (REPO_ROOT / test_path).exists(), f"{test_path} is missing"
