"""Adapter-originated exceptions for ``mureo.adapters.meta_ads``.

These exceptions are raised by the adapter itself when it detects an
operation it cannot fulfil — for example, a Protocol method that has no
counterpart on the underlying :class:`MetaAdsApiClient`. ``RuntimeError``
raised by the underlying client passes through unchanged (Phase 1 CTO
decision: error wrapping is deferred).

Module foundation rule
----------------------
This module imports nothing from ``mureo.*``. The exception types are
deliberately minimal so the AST import-allowlist test can pin them.
"""

from __future__ import annotations


class MetaAdsAdapterError(RuntimeError):
    """Base class for errors raised inside ``MetaAdsAdapter``.

    Subclasses ``RuntimeError`` so callers that already catch the broad
    ``RuntimeError`` raised by :class:`MetaAdsApiClient` continue to
    work. Callers that want to discriminate adapter-origin errors can
    catch this class instead.
    """


class UnsupportedOperation(MetaAdsAdapterError):  # noqa: N818
    # Naming: the public surface is intentionally ``UnsupportedOperation``
    # (matching the standard-library style, e.g. ``io.UnsupportedOperation``)
    # rather than ``UnsupportedOperationError``; tests and callers pin
    # this name. ``N818`` is suppressed locally.
    """Raised when a Protocol method has no Meta Ads counterpart in Phase 1.

    Phase 1 triggers:
        * ``create_campaign`` with ``start_date`` / ``end_date`` /
          ``bidding_strategy`` — Meta uses ``start_time`` / ``stop_time``
          and an AdSet-level bid strategy, not yet wired through.
        * ``create_ad`` with ``len(headlines) != 1`` — Phase 1 overloads
          ``headlines[0]`` as the pre-built ``creative_id``.
        * ``update_ad`` with any creative field (``headlines`` /
          ``descriptions`` / ``final_urls`` / ``path1`` / ``path2``) —
          Meta cannot mutate a live ad's creative without recreation.
        * ``set_audience_status(..., AudienceStatus.ENABLED)`` — Meta
          has no re-enable counterpart for deleted audiences.
    """


__all__ = ["MetaAdsAdapterError", "UnsupportedOperation"]
