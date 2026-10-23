"""Discover the ``mureo`` / ``mureo-*`` distributions installed in this venv.

Shared by ``mureo upgrade`` (:mod:`mureo.cli.upgrade_cmd`) and the configure
UI's About tab, update check and one-click upgrade (:mod:`mureo.web.about`,
:mod:`mureo.web.version_check`, :mod:`mureo.web.upgrade_action`). Names are
matched after PEP 503 canonicalisation: ``mureo`` exactly or ``mureo-<rest>``,
which excludes prefix squatters such as ``mureology`` or ``mureoextras``.

Stdlib only, so either layer imports it without loading the other (#863).
"""

from __future__ import annotations

import logging
import re
from importlib import metadata

logger = logging.getLogger(__name__)

# PEP 503: lowercase, separators normalised to '-'.
_NORMALIZE_RE = re.compile(r"[-_.]+")


def canonicalise(name: str) -> str:
    """Return the PEP 503 canonical form of ``name``."""

    return _NORMALIZE_RE.sub("-", name).lower()


def is_mureo_package(name: str) -> bool:
    """Return True iff ``name`` is ``mureo`` or ``mureo-<rest>``."""

    canonical = canonicalise(name)
    return canonical == "mureo" or canonical.startswith("mureo-")


def discover_all_mureo_packages() -> list[str]:
    """Return canonical names of every ``mureo`` / ``mureo-*`` dist found.

    Walks ``importlib.metadata.distributions()`` and dedupes after PEP 503
    canonicalisation. The result is deterministic: ``mureo`` first (if
    present), then the rest sorted alphabetically.
    """

    seen: set[str] = set()
    for dist in metadata.distributions():
        try:
            # ``Distribution.name`` (3.10+) routes through ``metadata`` but
            # tolerates a few of the more common dist-info quirks. We still
            # wrap it because a single broken dist-info in the venv must
            # not crash ``mureo upgrade --all``.
            name = dist.name
        except Exception as exc:  # noqa: BLE001 — skip a broken dist-info
            logger.warning(
                "Skipped an unreadable distribution (%s)", type(exc).__name__
            )
            continue
        if not name or not is_mureo_package(name):
            continue
        seen.add(canonicalise(name))
    ordered: list[str] = []
    if "mureo" in seen:
        ordered.append("mureo")
        seen.discard("mureo")
    ordered.extend(sorted(seen))
    return ordered
