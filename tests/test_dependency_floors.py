"""Security floors in ``pyproject.toml`` dependencies (#910).

certifi 2026.10.19 and grpcio 1.84.1 are the first releases whose trust
stores no longer carry the compromised ``emSign ECC Root CA - G3``. pip
leaves an already-satisfied dependency alone on ``--upgrade``, so only an
explicit floor makes ``mureo upgrade`` pull the fixed releases onto an
existing install. Losing either floor silently reopens that gap.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from packaging.requirements import Requirement

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent


def _requirement(name: str) -> Requirement:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    matches = [
        Requirement(spec)
        for spec in data["project"]["dependencies"]
        if Requirement(spec).name == name
    ]
    assert len(matches) == 1, f"expected exactly one {name} dependency"
    return matches[0]


def test_certifi_floor_excludes_the_compromised_bundle() -> None:
    req = _requirement("certifi")
    assert ">=2026.10.19" in str(req.specifier)
    assert req.specifier.contains("2026.10.19")
    assert not req.specifier.contains("2026.10.5")


def test_grpcio_floor_excludes_the_compromised_roots() -> None:
    req = _requirement("grpcio")
    assert ">=1.84.1" in str(req.specifier)
    assert req.specifier.contains("1.84.1")
    assert not req.specifier.contains("1.84.0")
    # google-ads requires grpcio<2.0.0; the floor must not widen past it.
    assert not req.specifier.contains("2.0.0")
