"""Locale-aware numeric parsing for BYOD Meta Ads Excel exports."""

from __future__ import annotations

import pytest

from mureo.byod.adapters.meta_ads import _to_float


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        # US / JP grouping
        ("1,234.56", 1234.56),
        ("1,234", 1234.0),
        ("$1,234.56", 1234.56),
        ("¥1,234", 1234.0),
        ("1234.56", 1234.56),
        # EU (comma decimal) with a thousands dot — previously mis-parsed.
        ("1.234,56", 1234.56),
        ("1.234,56 €", 1234.56),
        ("€1.234,56", 1234.56),
        # Degenerate / corrupt
        ("", 0.0),
        ("abc123", 0.0),
    ],
)
def test_to_float_locales(cell: str, expected: float) -> None:
    assert _to_float(cell) == expected
