"""Install / uninstall the mureo demo dataset.

Copies the static CSV/MD/JSON bundle shipped at ``mureo/_data/demo/`` into
the user's ``~/.mureo/demo/`` directory, resolving each CSV's relative
``day_offset`` column to a today-anchored absolute ``date`` column.

This module is the runtime side of `mureo demo init / reset / uninstall`.
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import date, timedelta
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

_PACKAGE_DATA = "mureo._data.demo"

_USER_DEMO_DIR_NAME = ".mureo"
_DEMO_SUBDIR = "demo"


def demo_data_dir() -> Path:
    """Return ``~/.mureo/demo/`` (does not create it)."""
    return Path.home() / _USER_DEMO_DIR_NAME / _DEMO_SUBDIR


def _resolve_offset(value: str, today: date) -> str:
    """Convert a ``day_offset`` string like ``-7`` to ``YYYY-MM-DD``.

    Empty strings and non-integer values pass through unchanged so non-date
    columns (start_offset==null, etc.) survive the round-trip intact.
    """
    if value == "" or value is None:
        return ""
    try:
        offset = int(value)
    except (TypeError, ValueError):
        return value
    return (today + timedelta(days=offset)).strftime("%Y-%m-%d")


_OFFSET_COLUMNS = {"day_offset", "start_offset", "end_offset"}


def _copy_csv_with_dates(src: Path, dst: Path, today: date) -> None:
    """Copy CSV, replacing offset columns with absolute dates."""
    with src.open("r", encoding="utf-8", newline="") as fin:
        reader = csv.DictReader(fin)
        in_fields = list(reader.fieldnames or [])
        out_fields = [
            f.replace("day_offset", "date")
            .replace("start_offset", "start_date")
            .replace("end_offset", "end_date")
            for f in in_fields
        ]

        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("w", encoding="utf-8", newline="") as fout:
            writer = csv.DictWriter(fout, fieldnames=out_fields)
            writer.writeheader()
            for row in reader:
                out_row = {}
                for in_name, out_name in zip(in_fields, out_fields, strict=True):
                    val = row.get(in_name, "")
                    if in_name in _OFFSET_COLUMNS:
                        out_row[out_name] = _resolve_offset(val, today)
                    else:
                        out_row[out_name] = val
                writer.writerow(out_row)


def _iter_package_files(pkg: str) -> Iterator[tuple[str, Any]]:
    root = resources.files(pkg)
    yield from _walk(root, "")


def _walk(node: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    for child in node.iterdir():
        rel = f"{prefix}{child.name}"
        if child.is_dir():
            yield from _walk(child, f"{rel}/")
        else:
            yield rel, child


def install_demo(*, force: bool = False, today: date | None = None) -> Path:
    """Install (or refresh with --force) the demo dataset.

    Returns the destination path (``~/.mureo/demo/``).
    Raises :class:`FileExistsError` if the directory already exists and
    ``force`` is ``False``.
    """
    today = today or date.today()
    dst_root = demo_data_dir()
    if dst_root.exists() and not force:
        raise FileExistsError(
            f"{dst_root} already exists. Use --force to overwrite, "
            f"or run `mureo demo uninstall` first."
        )
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=False)

    for rel_path, src_node in _iter_package_files(_PACKAGE_DATA):
        if rel_path == "__init__.py" or rel_path.endswith("/__init__.py"):
            continue
        dst_path = dst_root / rel_path
        if rel_path.endswith(".csv"):
            with resources.as_file(src_node) as src_real:
                _copy_csv_with_dates(Path(src_real), dst_path, today)
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            with resources.as_file(src_node) as src_real:
                shutil.copy2(Path(src_real), dst_path)

    (dst_root / "installed.json").write_text(
        json.dumps({"installed_on": today.strftime("%Y-%m-%d")}, indent=2)
    )
    return dst_root


def uninstall_demo() -> bool:
    """Remove ``~/.mureo/demo/`` if it exists. Returns ``True`` if removed."""
    target = demo_data_dir()
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def demo_is_installed() -> bool:
    return demo_data_dir().exists()


def installed_schema_version() -> int | None:
    """Read ``version.json`` from the installed demo, or ``None``."""
    p = demo_data_dir() / "version.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return int(data.get("schema_version"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
