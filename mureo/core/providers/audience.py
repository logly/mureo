"""``AudienceProvider`` Protocol — audience / segment operations.

The runtime-checkable Protocol every adapter that supports audience or
segment management must satisfy.

Capability gate
---------------
Implementing this Protocol does NOT automatically grant capabilities.
The provider's ``capabilities`` frozenset must explicitly include the
relevant ``Capability`` members for any given method to be callable:

================================  ====================
Method                            Required capability
================================  ====================
``list_audiences`` /              ``READ_AUDIENCES``
``get_audience``
``create_audience`` /             ``WRITE_AUDIENCES``
``set_audience_status``
================================  ====================

Delete-via-status convention
----------------------------
There is no ``delete_audience`` method. The canonical delete signal is
``set_audience_status(audience_id, AudienceStatus.REMOVED)``; adapters
translate ``REMOVED`` to a platform-native delete call (e.g., the Meta
Custom Audiences delete endpoint).
"""

# ruff: noqa: TC001
# Model imports must stay at module top-level (NOT under
# ``TYPE_CHECKING``) so ``typing.get_type_hints(Protocol.method)`` can
# resolve them at test/registry introspection time on Python 3.10.
from __future__ import annotations

from typing import Protocol, runtime_checkable

from mureo.core.providers.base import BaseProvider
from mureo.core.providers.models import (
    Audience,
    AudienceStatus,
    CreateAudienceRequest,
)


@runtime_checkable
class AudienceProvider(BaseProvider, Protocol):
    """Structural contract for audience / segment operations.

    See the module docstring for the capability gate map and the
    delete-via-status convention.
    """

    def list_audiences(self) -> tuple[Audience, ...]:
        """Return all audiences scoped to this provider's account."""
        ...

    def get_audience(self, audience_id: str) -> Audience:
        """Return a single audience by id."""
        ...

    def create_audience(self, request: CreateAudienceRequest) -> Audience:
        """Create a new audience from ``request`` and return it."""
        ...

    def set_audience_status(self, audience_id: str, status: AudienceStatus) -> Audience:
        """Set the status of ``audience_id``; use
        ``AudienceStatus.REMOVED`` to delete (delete-via-status
        convention).
        """
        ...


__all__ = ["AudienceProvider"]
