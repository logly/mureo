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
    DEFAULT_IDENTIFYING,
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
    """One final URL reduced to destination + tracking scheme.

    ``signature`` covers every recognised parameter; ``identifying``
    covers only the campaign-identifying subset and is what the
    scheme-consistency checks compare. Keeping both means the presence
    checks still see ``utm_content`` while the comparison never trips
    over it.
    """

    url: str
    destination: str
    parameters: tuple[tuple[str, str], ...]
    signature: tuple[tuple[str, str], ...]
    identifying: tuple[tuple[str, str], ...]

    @property
    def tagged(self) -> bool:
        return bool(self.parameters)

    @property
    def identifiable(self) -> bool:
        """Whether this URL says anything about which campaign it is."""
        return bool(self.identifying)


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

    @property
    def identifying_signatures(self) -> frozenset[tuple[tuple[str, str], ...]]:
        """The distinct campaign-identifying signatures this ad carries.

        Usually one; an ad with several final URLs can carry more.
        Empty signatures are dropped — an ad with no identifying
        parameter cannot be said to belong to any campaign's scheme.
        """
        return frozenset(url.identifying for url in self.urls if url.identifying)

    def parameter_names(self) -> frozenset[str]:
        return frozenset(name for url in self.urls for name, _ in url.parameters)

    def values_for(self, name: str) -> tuple[str, ...]:
        """Raw (un-shaped) values this ad carries for parameter ``name``."""
        return tuple(
            value for url in self.urls for key, value in url.parameters if key == name
        )


def _extend(base: tuple[str, ...], extra: Sequence[str]) -> tuple[str, ...]:
    return base + tuple(p for p in extra if p not in base)


def resolve_recognized(convention: TrackingConvention | None) -> tuple[str, ...]:
    """Recognised parameter globs — declared names ADD to the default set.

    Declaring ``recognize: argument`` must not switch off ``utm_*``
    detection for the rest of the account. Anything declared under
    ``identify:`` is recognised too: a parameter cannot be compared
    without first being read.
    """
    if convention is None:
        return DEFAULT_RECOGNIZED
    return _extend(
        _extend(DEFAULT_RECOGNIZED, convention.recognize), convention.identify
    )


def resolve_identifying(convention: TrackingConvention | None) -> tuple[str, ...]:
    """Campaign-identifying globs — the only ones schemes are compared on.

    ``identify:`` adds names, ``differentiate:`` removes them. An
    account that carries its segment in ``utm_content`` declares
    ``identify: utm_content``; one whose ``utm_campaign`` varies per
    creative declares ``differentiate: utm_campaign``.
    """
    if convention is None:
        return DEFAULT_IDENTIFYING
    identifying = _extend(DEFAULT_IDENTIFYING, convention.identify)
    if not convention.differentiate:
        return identifying
    excluded = {name.lower() for name in convention.differentiate}
    return tuple(name for name in identifying if name.lower() not in excluded)


def build_views(
    records: Iterable[AdTrackingRecord],
    recognized: Sequence[str],
    identifying: Sequence[str] = DEFAULT_IDENTIFYING,
) -> tuple[AdView, ...]:
    """Reduce every record to an :class:`AdView`, dropping empty URLs."""
    views: list[AdView] = []
    for record in records:
        urls = tuple(
            _url_view(url, recognized, identifying)
            for url in record.final_urls
            if url and url.strip()
        )
        views.append(AdView(record=record, urls=urls))
    return tuple(views)


def _url_view(
    url: str, recognized: Sequence[str], identifying: Sequence[str]
) -> UrlView:
    parameters = tracking_parameters(url, recognized)
    return UrlView(
        url=url,
        destination=destination(url),
        parameters=parameters,
        signature=scheme_signature(parameters),
        identifying=scheme_signature(parameters, identifying),
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
    "resolve_identifying",
    "resolve_recognized",
    "severity_for",
]
