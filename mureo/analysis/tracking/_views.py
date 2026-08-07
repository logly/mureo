"""Internal per-ad view built once and shared by every check.

Kept separate from :mod:`mureo.analysis.tracking.checks` so each check
reads as a rule over already-normalised data rather than re-parsing
URLs. Nothing here is public API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mureo.analysis.tracking.models import DeliveryState, TrackingSeverity
from mureo.analysis.tracking.scheme import (
    DEFAULT_RECOGNIZED,
    destination,
    scheme_signature,
    tracking_parameters,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mureo.analysis.tracking.models import AdTrackingRecord, TrackingConvention


@dataclass(frozen=True)
class UrlView:
    """One final URL reduced to destination + tracking scheme."""

    url: str
    destination: str
    parameters: tuple[tuple[str, str], ...]
    signature: tuple[tuple[str, str], ...]

    @property
    def tagged(self) -> bool:
        return bool(self.parameters)


@dataclass(frozen=True)
class AdView:
    """One ad record plus every URL view derived from it."""

    record: AdTrackingRecord
    urls: tuple[UrlView, ...]

    @property
    def ad_id(self) -> str:
        return self.record.ad_id

    @property
    def key(self) -> tuple[str, str]:
        """Platform-scoped campaign key — campaign ids collide across platforms."""
        return (self.record.platform, self.record.campaign_id)

    @property
    def has_readable_url(self) -> bool:
        return bool(self.urls)

    @property
    def tagged(self) -> bool:
        return any(url.tagged for url in self.urls)

    def shapes_for(self, name: str) -> frozenset[str]:
        """Value shapes this ad carries for parameter ``name`` (any URL)."""
        return frozenset(
            shape for url in self.urls for key, shape in url.signature if key == name
        )

    def parameter_names(self) -> frozenset[str]:
        return frozenset(name for url in self.urls for name, _ in url.parameters)

    def values_for(self, name: str) -> tuple[str, ...]:
        """Raw (un-shaped) values this ad carries for parameter ``name``."""
        return tuple(
            value for url in self.urls for key, value in url.parameters if key == name
        )


def resolve_recognized(convention: TrackingConvention | None) -> tuple[str, ...]:
    """Recognised parameter globs — declared names ADD to the default set.

    Declaring ``recognize: argument`` must not switch off ``utm_*``
    detection for the rest of the account.
    """
    if convention is None or not convention.recognize:
        return DEFAULT_RECOGNIZED
    extra = tuple(p for p in convention.recognize if p not in DEFAULT_RECOGNIZED)
    return DEFAULT_RECOGNIZED + extra


def build_views(
    records: Iterable[AdTrackingRecord],
    recognized: Sequence[str],
) -> tuple[AdView, ...]:
    """Reduce every record to an :class:`AdView`, dropping empty URLs."""
    views: list[AdView] = []
    for record in records:
        urls = tuple(
            _url_view(url, recognized)
            for url in record.final_urls
            if url and url.strip()
        )
        views.append(AdView(record=record, urls=urls))
    return tuple(views)


def _url_view(url: str, recognized: Sequence[str]) -> UrlView:
    parameters = tracking_parameters(url, recognized)
    return UrlView(
        url=url,
        destination=destination(url),
        parameters=parameters,
        signature=scheme_signature(parameters),
    )


def aggregate_delivery(views: Iterable[AdView]) -> DeliveryState:
    """Worst-case delivery state across the ads a finding covers.

    One served ad makes the whole finding a data-integrity incident;
    an unknown among otherwise-unserved ads keeps the answer honest.
    """
    states = {view.record.delivery_state for view in views}
    if DeliveryState.SERVED in states:
        return DeliveryState.SERVED
    if DeliveryState.UNKNOWN in states:
        return DeliveryState.UNKNOWN
    return DeliveryState.NOT_SERVED


def severity_for(state: DeliveryState) -> TrackingSeverity:
    """Severity implied by delivery state.

    Served = reporting is already wrong = CRITICAL. Not served, or not
    known to have served, = a cheap fix = HIGH.
    """
    return (
        TrackingSeverity.CRITICAL
        if state is DeliveryState.SERVED
        else TrackingSeverity.HIGH
    )


__all__ = [
    "AdView",
    "UrlView",
    "aggregate_delivery",
    "build_views",
    "resolve_recognized",
    "severity_for",
]
