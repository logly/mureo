"""``KeywordProvider`` Protocol — keywords and search-term reports.

The runtime-checkable Protocol search-platform adapters (Google Ads,
Microsoft/Bing Ads, Apple Search Ads) must satisfy. Social / display
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
``list_keywords``                 ``READ_KEYWORDS``
``add_keywords`` /                ``WRITE_KEYWORDS``
``set_keyword_status``
``search_terms``                  ``READ_SEARCH_TERMS``
================================  ====================

Delete-via-status convention
----------------------------
There is no ``remove_keyword`` method. The canonical delete signal is
``set_keyword_status(campaign_id, keyword_id, KeywordStatus.REMOVED)``.
"""

# ruff: noqa: TC001, TC003
# Model + stdlib imports must stay at module top-level (NOT under
# ``TYPE_CHECKING``) so ``typing.get_type_hints(Protocol.method)`` can
# resolve them at test/registry introspection time on Python 3.10.
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from mureo.core.providers.base import BaseProvider
from mureo.core.providers.models import (
    Keyword,
    KeywordSpec,
    KeywordStatus,
    SearchTerm,
)


@runtime_checkable
class KeywordProvider(BaseProvider, Protocol):
    """Structural contract for keyword / search-term operations.

    See the module docstring for the capability gate map and the
    delete-via-status convention.
    """

    def list_keywords(self, campaign_id: str) -> tuple[Keyword, ...]:
        """Return all keywords under ``campaign_id``."""
        ...

    def add_keywords(
        self, campaign_id: str, keywords: Sequence[KeywordSpec]
    ) -> tuple[Keyword, ...]:
        """Add the given keywords to ``campaign_id`` and return the
        created entities.

        ``keywords`` is typed ``Sequence[KeywordSpec]`` (covariant,
        read-only view) — adapters must not assume mutability.
        """
        ...

    def set_keyword_status(
        self, campaign_id: str, keyword_id: str, status: KeywordStatus
    ) -> Keyword:
        """Set the status of ``keyword_id``; use ``KeywordStatus.REMOVED`` to
        delete (delete-via-status convention).
        """
        ...

    def search_terms(
        self, campaign_id: str, start_date: date, end_date: date
    ) -> tuple[SearchTerm, ...]:
        """Return actual user-query rows for ``campaign_id`` over the
        inclusive ``[start_date, end_date]`` window.
        """
        ...


__all__ = ["KeywordProvider"]
