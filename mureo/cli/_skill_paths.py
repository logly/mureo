"""Bundled-data path helpers shared by the skill installers (#879).

``setup_cmd``, ``setup_codex``, ``native_skills`` and ``skill_status`` all
read the skill bundle shipped under ``mureo/_data``. The helpers live here,
below all four, so none of them has to import another installer to reach
them.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path


def get_data_path(subdir: str) -> Path:
    """Resolve the path to bundled data files.

    Works both in development (source tree) and after pip install
    (package data).
    """
    # Try importlib.resources first (pip install)
    try:
        ref = resources.files("mureo") / "_data" / subdir
        # Materialize to a real path
        with resources.as_file(ref) as p:
            if p.exists():
                return Path(p)
    except (TypeError, FileNotFoundError):
        pass

    # Fallback: source tree layout
    pkg_root = Path(__file__).parent.parent
    data_path = pkg_root / "_data" / subdir
    if data_path.exists():
        return data_path

    raise FileNotFoundError(
        f"Bundled data not found: {subdir}. " f"Ensure mureo is installed correctly."
    )


def replace_dest(path: Path) -> None:
    """Remove ``path`` in preparation for ``shutil.copytree``.

    ``shutil.rmtree`` refuses symlinks by design (to avoid nuking the
    link's target). A developer who has symlinked a bundled skill dir
    at their own dev copy would otherwise crash re-running setup with
    ``OSError: Cannot call rmtree on a symbolic link``. Unlink the
    symlink itself and leave the target intact.
    """
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
