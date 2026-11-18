"""The shared fitter for text on the always-on ``instructions`` route.

Both the platform delivery models and the plugin tool notes render a bounded
block of whole lines under a heading. The fitting rules are the part that must
not drift between them: whole lines only, in the caller's order, never over
the budget, and a visible notice when anything was dropped.
"""

from __future__ import annotations

import pytest

from mureo.policy.always_on_block import is_single_line, render_block

_HEADING = "Heading line."


def _note(count: int) -> str:
    return f"NOTE: {count} more did not fit."


def _entries(count: int, width: int) -> list[tuple[str, str]]:
    return [
        (f"l{index:02d}", f"- l{index:02d}: " + "x" * width) for index in range(count)
    ]


@pytest.mark.unit
def test_no_entries_render_nothing() -> None:
    assert render_block(_HEADING, [], 1000, _note) == ("", ())


@pytest.mark.unit
def test_entries_that_fit_render_in_order_without_a_notice() -> None:
    entries = [("b", "- b: second"), ("a", "- a: first")]
    block, dropped = render_block(_HEADING, entries, 1000, _note)
    assert block == "Heading line.\n- b: second\n- a: first"
    assert dropped == ()


@pytest.mark.unit
def test_exact_fit_is_accepted() -> None:
    entries = [("a", "- a: first")]
    budget = len(_HEADING) + 1 + len("- a: first")
    block, dropped = render_block(_HEADING, entries, budget, _note)
    assert len(block) == budget
    assert dropped == ()


@pytest.mark.unit
def test_overflow_drops_whole_lines_and_appends_the_notice() -> None:
    entries = _entries(10, 90)
    budget = 400
    block, dropped = render_block(_HEADING, entries, budget, _note)
    assert len(block) <= budget
    assert dropped
    kept = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(kept) + len(dropped) == len(entries)
    # Whole lines only: every kept line is one of the inputs, verbatim.
    assert set(kept) <= {line for _, line in entries}
    assert block.endswith(_note(len(dropped)))
    assert dropped == tuple(label for label, line in entries if line not in kept)


@pytest.mark.unit
def test_greedy_fit_keeps_a_later_short_line_after_a_long_one_is_dropped() -> None:
    entries = [("a", "- a: " + "x" * 50), ("b", "- b: " + "y" * 500), ("c", "- c: z")]
    budget = 200
    block, dropped = render_block(_HEADING, entries, budget, _note)
    assert dropped == ("b",)
    assert "- a: " in block
    assert "- c: z" in block
    assert len(block) <= budget


@pytest.mark.unit
def test_nothing_fitting_renders_nothing_but_reports_every_label() -> None:
    entries = [("a", "- a: " + "x" * 500)]
    block, dropped = render_block(_HEADING, entries, 100, _note)
    assert block == ""
    assert dropped == ("a",)


@pytest.mark.unit
def test_input_is_not_mutated() -> None:
    entries = _entries(10, 90)
    snapshot = list(entries)
    render_block(_HEADING, entries, 400, _note)
    assert entries == snapshot


def _growing_note(count: int) -> str:
    """A notice whose length depends on the count, to pin which count is reserved."""
    return "n" * (10 * count)


def _boundary_entries(first_len: int) -> list[tuple[str, str]]:
    return [("a", "a" * first_len), ("b", "b" * 1000)]


_BOUNDARY_BUDGET = 200
# Heading + newline + line, then newline + the notice sized for every entry.
_BOUNDARY_RESERVE = 1 + len(_growing_note(2))
_LARGEST_KEPT = _BOUNDARY_BUDGET - len(_HEADING) - 1 - _BOUNDARY_RESERVE


@pytest.mark.unit
def test_the_reserve_is_sized_for_every_entry_and_counts_its_newline() -> None:
    block, dropped = render_block(
        _HEADING, _boundary_entries(_LARGEST_KEPT), _BOUNDARY_BUDGET, _growing_note
    )
    assert dropped == ("b",)
    assert block.endswith("\n" + _growing_note(1))
    assert len(block) <= _BOUNDARY_BUDGET


@pytest.mark.unit
def test_a_line_kept_by_the_first_pass_is_dropped_by_the_second() -> None:
    """One character more fits without a notice, but not with the reserve."""
    entries = _boundary_entries(_LARGEST_KEPT + 1)
    first_pass_fits = len(_HEADING) + 1 + _LARGEST_KEPT + 1 <= _BOUNDARY_BUDGET
    assert first_pass_fits
    block, dropped = render_block(_HEADING, entries, _BOUNDARY_BUDGET, _growing_note)
    assert block == ""
    assert dropped == ("a", "b")


@pytest.mark.unit
def test_plain_text_is_a_single_line() -> None:
    assert is_single_line("Offer this when the review is done.")


@pytest.mark.unit
@pytest.mark.parametrize(
    "boundary",
    [
        "\n",
        "\r",
        "\r\n",
        "\v",
        "\f",
        "\x1c",
        "\x1d",
        "\x1e",
        "\x85",
        "\u2028",
        "\u2029",
    ],
)
def test_any_line_boundary_is_not_a_single_line(boundary: str) -> None:
    assert not is_single_line(f"first{boundary}second")
    assert not is_single_line(f"trailing{boundary}")
