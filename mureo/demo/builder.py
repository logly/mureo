"""Build the demo XLSX bundle from a :class:`Scenario` row table.

The Google Ads tabs match the schema produced by
``scripts/sheet-template/google-ads-script.js`` (the same shape
``mureo/byod/adapters/google_ads.py`` consumes). The Meta sheet
matches the verified English-locale Ads Manager export header
``mureo/byod/adapters/meta_ads.py`` recognizes. Sheet content comes
from the scenario, so swapping scenarios swaps what the bundle says.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.demo.scenarios._base import Scenario


def build_bundle(out_path: Path, scenario: Scenario) -> None:
    """Write the demo XLSX bundle to ``out_path``.

    Args:
        out_path: Destination path. Overwrites if it exists. Parent
            directory must already exist.
        scenario: The :class:`Scenario` whose ``sheet_rows`` populate
            the workbook.

    Raises:
        ImportError: if ``openpyxl`` is not installed. mureo declares
            it as a required dependency, so this should never trigger
            in a normal install — surfaced explicitly for editable
            checkouts where the user forgot to ``pip install -e .``.
    """
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise ImportError(
            "openpyxl is required to build the demo bundle. "
            "Install with: pip install 'openpyxl>=3.1,<4'"
        ) from exc

    wb = Workbook()
    default = wb.active
    if default is not None:
        wb.remove(default)

    for name, rows in scenario.sheet_rows.items():
        sheet = wb.create_sheet(name)
        for row in rows:
            sheet.append(list(row))

    wb.save(out_path)
