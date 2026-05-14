"""RED-phase tests: AST-scan the adapter modules for forbidden imports.

Encapsulation rule (P1-10 acceptance criterion, parity with P1-09):

- ``mureo/adapters/meta_ads/adapter.py`` may import from:
    - stdlib (any)
    - ``mureo.core.providers.{base, capabilities, models, registry}``
    - ``mureo.core.providers.{campaign, audience}`` — the Protocols
      themselves; allowed for type hints
    - ``mureo.meta_ads.client`` (the public ``MetaAdsApiClient``)
    - ``mureo.meta_ads.mappers`` (the existing dict-shaping helpers)
    - ``mureo.adapters.meta_ads.{mappers, errors}`` (intra-package)
  …but MUST NOT import any ``mureo.meta_ads._*`` private mixin.

- ``mureo/adapters/meta_ads/mappers.py`` may import only:
    - stdlib
    - ``mureo.core.providers.{models, capabilities}``
    - ``mureo.adapters.meta_ads.errors``
  …and nothing else inside ``mureo``.

- ``mureo/adapters/meta_ads/errors.py`` may import only stdlib.

Marks: every test is ``@pytest.mark.unit``.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

_ADAPTER_MODULE = "mureo.adapters.meta_ads.adapter"
_MAPPERS_MODULE = "mureo.adapters.meta_ads.mappers"
_ERRORS_MODULE = "mureo.adapters.meta_ads.errors"

_ADAPTER_ALLOWED: frozenset[str] = frozenset(
    {
        "mureo.core.providers",
        "mureo.core.providers.base",
        "mureo.core.providers.capabilities",
        "mureo.core.providers.models",
        "mureo.core.providers.registry",
        "mureo.core.providers.campaign",
        "mureo.core.providers.audience",
        "mureo.meta_ads.client",
        "mureo.meta_ads.mappers",
        "mureo.adapters.meta_ads.mappers",
        "mureo.adapters.meta_ads.errors",
        "mureo.adapters.meta_ads",
    }
)

_MAPPERS_ALLOWED: frozenset[str] = frozenset(
    {
        "mureo.core.providers",
        "mureo.core.providers.models",
        "mureo.core.providers.capabilities",
        "mureo.adapters.meta_ads.errors",
        "mureo.adapters.meta_ads",
    }
)


def _source_path(dotted: str) -> Path:
    mod = importlib.import_module(dotted)
    src = inspect.getsourcefile(mod)
    assert src is not None, f"cannot locate {dotted} on disk"
    return Path(src)


def _internal_mureo_imports(path: Path) -> list[str]:
    """Return every ``mureo.*`` import (whether ``import X`` or
    ``from X import …``) inside ``path``.

    Relative imports (``from .x import …``) are normalized to their
    absolute dotted form using the module's package prefix.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("mureo"):
                    out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level > 0:
                out.append(f".{'.' * (node.level - 1)}{mod}")
            elif mod.startswith("mureo"):
                out.append(mod)
    return out


@pytest.mark.unit
def test_adapter_imports_within_allowlist() -> None:
    path = _source_path(_ADAPTER_MODULE)
    imports = _internal_mureo_imports(path)
    offending: list[str] = []
    for imp in imports:
        # Reject any private-mixin import explicitly.
        if imp.startswith("mureo.meta_ads._"):
            offending.append(imp)
            continue
        # Relative imports must resolve to an allowed name.
        if imp.startswith("."):
            relative_root = "mureo.adapters.meta_ads"
            base = imp.lstrip(".")
            resolved = f"{relative_root}.{base}" if base else relative_root
            if resolved not in _ADAPTER_ALLOWED:
                offending.append(f"(relative) {imp} -> {resolved}")
            continue
        if imp not in _ADAPTER_ALLOWED:
            offending.append(imp)
    assert offending == [], (
        f"{_ADAPTER_MODULE} has forbidden imports: {offending}. "
        f"Allowed: {sorted(_ADAPTER_ALLOWED)}"
    )


@pytest.mark.unit
def test_adapter_does_not_import_private_mixins() -> None:
    """Explicit check (defense-in-depth alongside the allowlist):
    NO import of ``mureo.meta_ads._*`` private mixins is permitted."""
    path = _source_path(_ADAPTER_MODULE)
    imports = _internal_mureo_imports(path)
    bad = [imp for imp in imports if imp.startswith("mureo.meta_ads._")]
    assert bad == [], f"{_ADAPTER_MODULE} must not import private mixins; found: {bad}"


@pytest.mark.unit
def test_mappers_imports_within_allowlist() -> None:
    path = _source_path(_MAPPERS_MODULE)
    imports = _internal_mureo_imports(path)
    offending: list[str] = []
    for imp in imports:
        if imp.startswith("."):
            relative_root = "mureo.adapters.meta_ads"
            base = imp.lstrip(".")
            resolved = f"{relative_root}.{base}" if base else relative_root
            if resolved not in _MAPPERS_ALLOWED:
                offending.append(f"(relative) {imp} -> {resolved}")
            continue
        if imp not in _MAPPERS_ALLOWED:
            offending.append(imp)
    assert offending == [], (
        f"{_MAPPERS_MODULE} has forbidden imports: {offending}. "
        f"Allowed: {sorted(_MAPPERS_ALLOWED)}"
    )


@pytest.mark.unit
def test_mappers_does_not_import_meta_ads_client_or_mixins() -> None:
    """The adapter's mapper module is pure dict-to-dataclass; it must
    NOT pull in the heavyweight ``mureo.meta_ads.client`` (which
    transitively imports httpx + every Meta mixin) or any private
    mixin."""
    path = _source_path(_MAPPERS_MODULE)
    imports = _internal_mureo_imports(path)
    bad = [imp for imp in imports if imp.startswith("mureo.meta_ads.")]
    assert (
        bad == []
    ), f"{_MAPPERS_MODULE} must not depend on mureo.meta_ads.*; found: {bad}"


@pytest.mark.unit
def test_errors_module_imports_no_mureo_internals() -> None:
    """The errors module is exception types only — no internal imports."""
    path = _source_path(_ERRORS_MODULE)
    imports = _internal_mureo_imports(path)
    assert imports == [], (
        f"{_ERRORS_MODULE} must not import any internal mureo modules; "
        f"found: {imports}"
    )


@pytest.mark.unit
def test_package_init_reexports_adapter_class() -> None:
    """``mureo.adapters.meta_ads`` re-exports ``MetaAdsAdapter``."""
    pkg = importlib.import_module("mureo.adapters.meta_ads")
    assert hasattr(pkg, "MetaAdsAdapter")
