"""Shared mutate-error decorator for the Google Ads client and its mixins.

A leaf module on purpose. ``_wrap_mutate_error`` used to live in
:mod:`mureo.google_ads.client`, which every mixin then imported it from — while
``client`` imports the mixins to build the class. That cycle only resolved
because the package ``__init__`` imported ``client`` first, so ``client`` was
always the module that started executing. Once the package stopped importing
``client`` eagerly (#807), importing a mixin *first* — which is what a
single-file ``pytest`` run or a ``-k`` filter does — entered the cycle from the
other side and failed. Keeping the decorator here, with no ``mureo.google_ads``
imports of its own, removes the mixin-to-client edge entirely, so no module's
import order matters.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


def _wrap_mutate_error(label: str) -> Callable[[_F], _F]:
    """Decorator that logs GoogleAdsException details and re-raises a
    RuntimeError whose message includes the specific API error detail.

    Including the API detail (e.g. "bid below minimum", "invalid asset
    format", etc.) lets agents see the actual reason their request was
    rejected rather than a generic "An error occurred..." message.
    """

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(self, *args, **kwargs)
            except GoogleAdsException as exc:
                detail = self._extract_error_detail(exc)
                logger.error(
                    "%s failed: %s (campaign=%s)",
                    label,
                    detail,
                    args[0] if args else kwargs,
                )
                # Return a specific hint for RESOURCE_NOT_FOUND, but
                # still append the API detail so the resource name or
                # other context surfaces in the error message.
                if self._has_error_code(exc, "mutate_error", "RESOURCE_NOT_FOUND"):
                    raise RuntimeError(
                        f"{label} failed: The specified resource was not found. "
                        "Please verify the ID is correct. "
                        "Retrieve the latest ID using a list tool "
                        f"(e.g., ads.list) and try again. Details: {detail}"
                    ) from exc
                raise RuntimeError(
                    f"An error occurred while processing {label}: {detail}"
                ) from exc

        return wrapper  # type: ignore[return-value]

    return decorator
