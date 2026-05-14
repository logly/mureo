"""Adapter-originated exceptions for ``mureo.adapters.google_ads``.

These exceptions are raised by the adapter itself when it detects an
operation it cannot fulfil — for example, a Protocol method that has no
counterpart on the underlying :class:`GoogleAdsApiClient`. ``RuntimeError``
raised by the underlying client passes through unchanged (Phase 1 CTO
decision: error wrapping is deferred).

Module foundation rule
----------------------
This module imports nothing from ``mureo.*``. The exception types are
deliberately minimal so the AST import-allowlist test can pin them.
"""

from __future__ import annotations


class GoogleAdsAdapterError(RuntimeError):
    """Base class for errors raised inside ``GoogleAdsAdapter``.

    Subclasses ``RuntimeError`` so callers that already catch the broad
    ``RuntimeError`` raised by :class:`GoogleAdsApiClient` continue to
    work. Callers that want to discriminate adapter-origin errors can
    catch this class instead.
    """


class UnsupportedOperation(GoogleAdsAdapterError):  # noqa: N818
    # Naming: the public surface is intentionally ``UnsupportedOperation``
    # (matching the standard-library style, e.g. ``io.UnsupportedOperation``)
    # rather than ``UnsupportedOperationError``; tests and callers pin
    # this name. ``N818`` is suppressed locally.
    """Raised when a Protocol method has no Google Ads counterpart.

    Phase 1 triggers:
        * ``set_keyword_status(..., KeywordStatus.ENABLED)`` — the
          existing client has no ``enable_keyword`` operation.
        * ``set_extension_status(..., ExtensionStatus.ENABLED |
          ExtensionStatus.PAUSED)`` — the existing extension mixins
          expose remove-only mutations.
    """


__all__ = ["GoogleAdsAdapterError", "UnsupportedOperation"]
