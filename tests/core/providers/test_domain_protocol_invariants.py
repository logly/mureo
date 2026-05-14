"""Cross-Protocol invariant tests for the four Phase 1 domain Protocols.

RED phase tests for Issue #89 Phase 1 subtasks P1-03..P1-06.

These tests parametrize over the four domain Protocols
(``CampaignProvider``, ``KeywordProvider``, ``AudienceProvider``,
``ExtensionProvider``) and verify invariants that must hold for ALL of
them. Anything specific to a single Protocol lives in the dedicated
``test_<protocol>.py`` file.

Marks: all tests are ``@pytest.mark.unit`` — pure logic, no I/O, no
mocks needed.
"""

from __future__ import annotations

import ast
import inspect
import typing

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# leaf modules do not exist yet. The implementer (GREEN phase) will
# create them.
from mureo.core.providers.audience import AudienceProvider
from mureo.core.providers.base import BaseProvider
from mureo.core.providers.campaign import CampaignProvider
from mureo.core.providers.extension import ExtensionProvider
from mureo.core.providers.keyword import KeywordProvider

_DOMAIN_PROTOCOLS: tuple[type, ...] = (
    CampaignProvider,
    KeywordProvider,
    AudienceProvider,
    ExtensionProvider,
)

_PROTOCOL_NAMES: tuple[str, ...] = (
    "CampaignProvider",
    "KeywordProvider",
    "AudienceProvider",
    "ExtensionProvider",
)

# Internal mureo.* imports each domain Protocol leaf module is allowed
# to make (per HANDOFF AC). The own module is always implicitly allowed.
_ALLOWED_INTERNAL_IMPORTS: frozenset[str] = frozenset(
    {
        "mureo.core.providers.base",
        "mureo.core.providers.capabilities",
        "mureo.core.providers.models",
    }
)


# ---------------------------------------------------------------------------
# Case 1 — All four domain Protocols are runtime-checkable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "protocol_cls",
    _DOMAIN_PROTOCOLS,
    ids=lambda c: c.__name__,
)
def test_all_domain_protocols_are_runtime_checkable(
    protocol_cls: type,
) -> None:
    """Every Phase 1 domain Protocol is decorated with
    ``@runtime_checkable``.
    """
    assert (
        getattr(protocol_cls, "_is_runtime_protocol", False) is True
    ), f"{protocol_cls.__name__} must be decorated with @runtime_checkable"


# ---------------------------------------------------------------------------
# Case 2 — All four inherit the BaseProvider attribute set
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "protocol_cls",
    _DOMAIN_PROTOCOLS,
    ids=lambda c: c.__name__,
)
def test_all_domain_protocols_inherit_base_provider_attributes(
    protocol_cls: type,
) -> None:
    """Every Phase 1 domain Protocol structurally extends
    ``BaseProvider`` — the three attributes ``name``, ``display_name``,
    and ``capabilities`` must all appear in its resolved type hints, and
    ``BaseProvider`` must be in the MRO.
    """
    assert BaseProvider in protocol_cls.__mro__, (
        f"{protocol_cls.__name__} must declare ``class {protocol_cls.__name__}"
        "(BaseProvider, Protocol): ...``"
    )
    hints = typing.get_type_hints(protocol_cls)
    for attr in ("name", "display_name", "capabilities"):
        assert attr in hints, (
            f"{protocol_cls.__name__} must inherit attribute {attr!r} "
            f"from BaseProvider; got hints keys: {sorted(hints.keys())}"
        )


# ---------------------------------------------------------------------------
# Case 3 — All four leaf modules have allowed-imports only (AST scan)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "module_dotted",
    [
        "mureo.core.providers.campaign",
        "mureo.core.providers.keyword",
        "mureo.core.providers.audience",
        "mureo.core.providers.extension",
    ],
)
def test_all_domain_protocol_modules_have_allowed_imports_only(
    module_dotted: str,
) -> None:
    """Each domain Protocol leaf module may only import from
    ``{base, capabilities, models}`` among internal ``mureo.*`` paths.

    Uses ``ast.parse`` on the module's source. ``TYPE_CHECKING``-guarded
    imports are intentionally treated identically to runtime imports —
    the import allow-list is total.
    """
    module = __import__(module_dotted, fromlist=["_dummy"])
    source_path = inspect.getsourcefile(module)
    assert source_path is not None, f"Could not locate {module_dotted} on disk"

    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)

    own_module = module.__name__
    offending: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (
                    alias.name.startswith("mureo.")
                    and alias.name != own_module
                    and alias.name not in _ALLOWED_INTERNAL_IMPORTS
                ):
                    offending.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level > 0:
                offending.append(f"from {'.' * node.level}{mod} import ... (relative)")
            elif (
                mod.startswith("mureo.")
                and mod != own_module
                and mod not in _ALLOWED_INTERNAL_IMPORTS
            ):
                offending.append(f"from {mod} import ...")
            elif mod == "mureo":
                offending.append("from mureo import ...")

    assert offending == [], (
        f"{module_dotted} may only import from "
        f"{sorted(_ALLOWED_INTERNAL_IMPORTS)} among internal mureo.* "
        f"modules. Found: {offending}"
    )


# ---------------------------------------------------------------------------
# Case 4 — All four Protocols are re-exported from the package init
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("protocol_name", _PROTOCOL_NAMES)
def test_all_domain_protocols_are_reexported_from_package(
    protocol_name: str,
) -> None:
    """Each domain Protocol is re-exported from
    ``mureo.core.providers`` and is the **same object identity** as the
    one defined in the leaf module (no wrapping / aliasing).
    """
    import mureo.core.providers as pkg

    assert hasattr(
        pkg, protocol_name
    ), f"mureo.core.providers must re-export {protocol_name!r}"

    # Map name -> leaf-module symbol for identity comparison.
    leaf_symbols: dict[str, type] = {
        "CampaignProvider": CampaignProvider,
        "KeywordProvider": KeywordProvider,
        "AudienceProvider": AudienceProvider,
        "ExtensionProvider": ExtensionProvider,
    }
    expected = leaf_symbols[protocol_name]
    actual = getattr(pkg, protocol_name)

    assert actual is expected, (
        f"mureo.core.providers.{protocol_name} must be the same object "
        f"as the leaf-module symbol (identity check failed)"
    )
