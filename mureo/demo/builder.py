"""Build the demo XLSX bundle from the scenario row tables.

The output file is a single XLSX workbook with five sheets:

  campaigns / ad_groups / search_terms / keywords  (Google Ads)
  meta_ads                                         (Meta Ads export)

The Google Ads tabs match the schema produced by
``scripts/sheet-template/google-ads-script.js`` (the same shape
``mureo/byod/adapters/google_ads.py`` consumes). The Meta sheet
matches the verified English-locale Ads Manager export header
``mureo/byod/adapters/meta_ads.py`` recognizes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.demo import scenario

if TYPE_CHECKING:
    from pathlib import Path


def build_bundle(out_path: Path) -> None:
    """Write the demo XLSX bundle to ``out_path``.

    Overwrites any existing file at the target. Caller is responsible
    for ensuring the parent directory exists.

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

    sheets: list[tuple[str, list[list[object]]]] = [
        ("campaigns", scenario.google_campaigns_rows()),
        ("ad_groups", scenario.google_ad_groups_rows()),
        ("search_terms", scenario.google_search_terms_rows()),
        ("keywords", scenario.google_keywords_rows()),
        ("meta_ads", scenario.meta_ads_rows()),
    ]
    for name, rows in sheets:
        sheet = wb.create_sheet(name)
        for row in rows:
            sheet.append(row)

    wb.save(out_path)
