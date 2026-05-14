"""``ExtensionProvider`` Protocol — ad extensions (sitelinks / callouts /
conversions).

The runtime-checkable Protocol search-platform adapters (Google Ads,
Microsoft/Bing Ads) use for ad-extension management. Social / display
platforms typically do NOT implement this Protocol — for example, the
Meta Ads adapter does not.

Capability gate
---------------
Implementing this Protocol does NOT automatically grant capabilities.
The provider's ``capabilities`` frozenset must explicitly include the
relevant ``Capability`` members for any given method to be callable:

================================  ====================
Method                            Required capability
================================  ====================
``list_extensions``               ``READ_EXTENSIONS``
``add_extension`` /               ``WRITE_EXTENSIONS``
``set_extension_status``
================================  ====================

Delete-via-status convention
----------------------------
There is no ``delete_extension`` method. The canonical delete signal is
``set_extension_status(campaign_id, extension_id, ExtensionStatus.REMOVED)``.

Type-safe dispatch
------------------
The ``kind`` parameter on ``list_extensions`` and ``add_extension`` is
the ``ExtensionKind`` enum (never a bare ``str``) so adapters cannot
accept arbitrary platform-specific category strings.
"""

# ruff: noqa: TC001
# Model imports must stay at module top-level (NOT under
# ``TYPE_CHECKING``) so ``typing.get_type_hints(Protocol.method)`` can
# resolve them at test/registry introspection time on Python 3.10.
from __future__ import annotations

from typing import Protocol, runtime_checkable

from mureo.core.providers.base import BaseProvider
from mureo.core.providers.models import (
    Extension,
    ExtensionKind,
    ExtensionRequest,
    ExtensionStatus,
)


@runtime_checkable
class ExtensionProvider(BaseProvider, Protocol):
    """Structural contract for ad-extension operations.

    See the module docstring for the capability gate map, the
    delete-via-status convention, and the type-safe-dispatch rule for
    ``kind``.
    """

    def list_extensions(
        self, campaign_id: str, kind: ExtensionKind
    ) -> tuple[Extension, ...]:
        """Return all extensions of ``kind`` attached to ``campaign_id``."""
        ...

    def add_extension(
        self,
        campaign_id: str,
        kind: ExtensionKind,
        request: ExtensionRequest,
    ) -> Extension:
        """Attach a new extension of ``kind`` to ``campaign_id`` and
        return the created entity.
        """
        ...

    def set_extension_status(
        self,
        campaign_id: str,
        extension_id: str,
        status: ExtensionStatus,
    ) -> Extension:
        """Set the status of ``extension_id``; use
        ``ExtensionStatus.REMOVED`` to delete (delete-via-status
        convention).
        """
        ...


__all__ = ["ExtensionProvider"]
