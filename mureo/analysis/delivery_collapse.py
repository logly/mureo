"""Delivery-collapse detection — the inverse of a cost spike (#546).

``cost_increase_investigate`` answers "why did spend jump?". Nothing
answered its opposite: a campaign whose status still says ENABLED while
its impressions have gone to zero. That contradiction — *configured to
serve, serving nothing* — is the most detectable failure mode in ad
operations, and it is what separates a real fault from an intentional
pause.

Why this is not :mod:`mureo.analysis.anomaly_detector`
------------------------------------------------------
The generic anomaly path takes one campaign's current metrics by hand
and baselines them off ``action_log`` history. On an account operated
partly by hand that history is thin or empty, so the baseline is
``None`` and the detector goes quiet exactly where it is needed. This
module baselines off the **platform's own daily delivery series**
(:data:`BASELINE_SOURCE`) and never reads ``action_log`` at all.

Why the baseline is weekday-aware
---------------------------------
Delivery is seasonal within the week. A retail account can run 350k
impressions on a Tuesday and 15k on a Saturday — a 96% swing that a
flat median would report as a collapse every single weekend. A detector
that cries wolf on Saturdays gets muted, and a muted detector is worth
nothing, so the baseline for a given day is the median of the *same
weekday* inside the trailing window whenever there are enough samples
for it (falling back to the all-day median otherwise, which is recorded
on the signal as :class:`BaselineMethod`).

Why only complete days count
----------------------------
Budget pacing spreads a day's impressions unevenly, so a partially
elapsed day always looks like a cliff. Everything at or after
``as_of`` (the host's today, via :func:`mureo.core.clock.server_now`)
is dropped before any comparison happens.

This module is pure: no network, no filesystem, no clock except the
injectable ``as_of``. Detection is deliberately separable from
diagnosis (:mod:`mureo.analysis.collapse_diagnosis`) — knowing that a
campaign died is actionable on its own, hours before anyone knows why.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: Provenance stamped on every signal. Pinned by the test-suite: the
#: whole point of this detector is that its baseline does NOT come from
#: ``action_log``.
BASELINE_SOURCE = "platform_daily_delivery"

DEFAULT_DROP_PCT = 90.0
DEFAULT_MIN_BASELINE_IMPRESSIONS = 1_000
DEFAULT_BASELINE_DAYS = 28
DEFAULT_MIN_BASELINE_DAYS = 14
DEFAULT_CONSECUTIVE_DAYS = 1
DEFAULT_MIN_SAME_WEEKDAY_SAMPLES = 2

#: Status tokens that mean "this campaign is configured to serve", across
#: every platform vocabulary mureo touches: Google Ads (``ENABLED``),
#: Meta (``ACTIVE``), TikTok (``ENABLE``), and the serving-status spellings
#: bridges and plugins report. Compared case-insensitively.
SERVING_STATUSES: frozenset[str] = frozenset(
    {
        "ENABLED",
        "ENABLE",
        "ACTIVE",
        "RUNNING",
        "SERVING",
        "DELIVERING",
        "ELIGIBLE",
    }
)


class CollapseSeverity(str, Enum):
    """Two tiers only — same rationale as the anomaly detector's.

    ``CRITICAL`` is reserved for a total stop (zero impressions on every
    collapsed day); a severe-but-nonzero drop is ``HIGH``.
    """

    CRITICAL = "critical"
    HIGH = "high"


_SEVERITY_ORDER: dict[CollapseSeverity, int] = {
    CollapseSeverity.CRITICAL: 0,
    CollapseSeverity.HIGH: 1,
}


class BaselineMethod(str, Enum):
    """How the day's baseline was computed. Reported on every signal."""

    SAME_WEEKDAY_MEDIAN = "same_weekday_median"
    ALL_DAY_MEDIAN = "all_day_median"


@dataclass(frozen=True)
class DailyDelivery:
    """One complete day of delivery for one campaign."""

    date: date
    impressions: int
    clicks: int = 0
    cost: float = 0.0


@dataclass(frozen=True)
class DeliverySeries:
    """One campaign's day-grain delivery, normalised across platforms.

    ``status`` is the platform's own spelling (see
    :data:`SERVING_STATUSES`). ``end_date`` is the campaign's flight end
    when the platform reports one; a finished flight stops serving while
    its status stays ENABLED, which is not a fault.
    """

    platform: str
    campaign_id: str
    status: str
    daily: tuple[DailyDelivery, ...]
    campaign_name: str = ""
    end_date: date | None = None


@dataclass(frozen=True)
class CollapseThresholds:
    """Operator-tunable detection thresholds.

    Every field is settable from STRATEGY.md's ``## Guardrails`` section
    as ``- delivery_collapse_<field>: <value>`` — see
    :func:`collapse_thresholds_from_strategy_text`. The defaults are
    deliberately conservative: a 90% drop against a campaign's own
    same-weekday baseline is not ad-ops variance, it is a fault.
    """

    #: How far below its own baseline a day must fall to count as collapsed.
    drop_pct: float = DEFAULT_DROP_PCT
    #: Daily impressions below which a campaign is treated as not
    #: delivering at all. Doubles as the floor under a usable baseline —
    #: a campaign averaging 80 impressions/day hits zero routinely.
    min_baseline_impressions: int = DEFAULT_MIN_BASELINE_IMPRESSIONS
    #: Length of the trailing window the baseline median is drawn from.
    baseline_days: int = DEFAULT_BASELINE_DAYS
    #: Minimum number of days **that actually delivered** (at or above
    #: ``min_baseline_impressions``) required inside that window before
    #: the detector will speak. It counts real delivery, not window
    #: length: 13 delivering days plus 3 already-dead ones is 13, not 16,
    #: so a campaign cannot reach the bar on days it was already down.
    min_baseline_days: int = DEFAULT_MIN_BASELINE_DAYS
    #: Complete collapsed days required before a signal is emitted.
    consecutive_days: int = DEFAULT_CONSECUTIVE_DAYS
    #: Below this many same-weekday samples the baseline falls back to
    #: the all-day median (and says so on the signal).
    min_same_weekday_samples: int = DEFAULT_MIN_SAME_WEEKDAY_SAMPLES


@dataclass(frozen=True)
class CollapseSignal:
    """One campaign whose delivery fell off a cliff while set to serve."""

    platform: str
    campaign_id: str
    campaign_name: str
    status: str
    severity: CollapseSeverity
    collapse_start_date: str
    days_at_collapse: int
    current_impressions: int
    baseline_impressions: float
    drop_pct: float
    current_cost: float
    baseline_cost: float
    baseline_method: BaselineMethod
    baseline_days_used: int
    baseline_samples: int
    evaluated_through: str
    message: str
    recommended_action: str
    baseline_source: str = BASELINE_SOURCE


@dataclass(frozen=True)
class _Baseline:
    """Internal: the reference level one day is compared against."""

    impressions: float
    cost: float
    method: BaselineMethod
    days_used: int
    samples: int


def is_serving_status(status: str) -> bool:
    """Return ``True`` when ``status`` says the campaign should serve."""
    return status.strip().upper() in SERVING_STATUSES


def detect_delivery_collapse(
    series: DeliverySeries,
    *,
    thresholds: CollapseThresholds | None = None,
    as_of: date | None = None,
) -> CollapseSignal | None:
    """Return a signal when ``series`` has collapsed, else ``None``.

    Note the signature: a delivery series and thresholds, nothing else.
    There is deliberately no ``action_log`` parameter — reintroducing one
    would reinstate the empty-history blind spot this detector exists to
    close.
    """
    resolved = thresholds or CollapseThresholds()
    if not is_serving_status(series.status):
        # Not a fault: somebody meant to stop this campaign.
        return None

    complete = _complete_days(series.daily, as_of=as_of)
    found = _find_collapse_start(complete, resolved)
    if found is None:
        return None
    start_index, baseline = found

    if len(complete) - start_index < resolved.consecutive_days:
        return None
    cliff = complete[start_index].date
    if series.end_date is not None and cliff > series.end_date:
        # The flight ended; zero delivery afterwards is expected.
        return None
    return _build_signal(series, complete, start_index, baseline)


def last_reported_day(
    all_series: Iterable[DeliverySeries],
) -> date | None:
    """Latest date the platform reported ANY delivery, or ``None``.

    How far the data demonstrably extends. When it trails the day the
    caller expected, the account has gone quiet — a total outage and a
    reporting failure look identical from here, so it is reported as a
    fact rather than guessed at as a collapse.
    """
    days = [day.date for series in all_series for day in series.daily]
    return max(days) if days else None


def detect_delivery_collapses(
    all_series: Iterable[DeliverySeries],
    *,
    thresholds: CollapseThresholds | None = None,
    as_of: date | None = None,
) -> tuple[CollapseSignal, ...]:
    """Run :func:`detect_delivery_collapse` over many campaigns.

    Ordered CRITICAL first, then by campaign id, so the caller can render
    the list verbatim.
    """
    signals = [
        signal
        for series in all_series
        if (
            signal := detect_delivery_collapse(
                series, thresholds=thresholds, as_of=as_of
            )
        )
        is not None
    ]
    signals.sort(key=lambda s: (_SEVERITY_ORDER[s.severity], s.campaign_id))
    return tuple(signals)


def _complete_days(
    daily: Sequence[DailyDelivery], *, as_of: date | None
) -> tuple[DailyDelivery, ...]:
    """Chronological days strictly before ``as_of`` (today by default).

    The current day is always partial — budget pacing makes it look like
    a cliff every morning — so it never takes part in a comparison.
    """
    if as_of is None:
        from mureo.core import clock

        as_of = clock.server_now().date()
    return tuple(sorted((d for d in daily if d.date < as_of), key=lambda d: d.date))


class _WindowBaselines:
    """Baselines drawn from one fixed pre-cliff window, memoised per weekday.

    Not a frozen dataclass (the repo default) precisely because the memo
    is the point: on a healthy account the scan below tests one day per
    candidate and stops, so computing all seven weekday medians eagerly
    would be the dominant cost of a daily check for no benefit.
    """

    __slots__ = ("_window", "_thresholds", "_by_weekday", "delivering_days")

    def __init__(
        self, window: Sequence[DailyDelivery], thresholds: CollapseThresholds
    ) -> None:
        self._window = window
        self._thresholds = thresholds
        self._by_weekday: dict[int, _Baseline] = {}
        #: Days in the window that actually delivered. This — not the
        #: window's LENGTH — is what ``min_baseline_days`` gates, so a
        #: window padded out with days the campaign was already dead
        #: cannot pass for history.
        self.delivering_days = sum(
            1
            for day in window
            if day.impressions >= thresholds.min_baseline_impressions
        )

    def baseline_for(self, day: DailyDelivery) -> _Baseline:
        weekday = day.date.weekday()
        cached = self._by_weekday.get(weekday)
        if cached is None:
            cached = _baseline_for(day, self._window, self._thresholds)
            self._by_weekday[weekday] = cached
        return cached

    def is_collapsed(self, day: DailyDelivery) -> bool:
        """Is ``day`` collapsed against this window's baseline for its weekday?"""
        baseline = self.baseline_for(day)
        if baseline.impressions < self._thresholds.min_baseline_impressions:
            return False
        return (
            _drop_pct(day.impressions, baseline.impressions)
            >= self._thresholds.drop_pct
        )


def _find_collapse_start(
    complete: Sequence[DailyDelivery],
    thresholds: CollapseThresholds,
) -> tuple[int, _Baseline] | None:
    """Earliest day from which delivery has stayed collapsed, or ``None``.

    Two properties do the work, and both were learned the hard way:

    1. **The window sits strictly before the candidate cliff**, and every
       later day is judged against that same pre-cliff window. Judging
       each day against the window immediately preceding *it* lets a long
       outage redefine "normal" — the median falls to zero and nothing
       looks like a drop any more.
    2. **The scan runs forward and never breaks early.** An earlier
       version walked backwards from the most recent day and stopped at
       the first candidate that failed. On a long outage the most recent
       day's window is itself mostly zeros, so it failed on iteration one
       and the clean window further back was never reached: collapses
       past ~3/4 of ``baseline_days`` reported *nothing*, which the
       report layer then rendered as "checked, healthy". A miss on the
       longest outages is the worst possible place to be silent, and it
       is invisible — which is why ``test_collapse_duration_sweep``
       asserts the whole duration range rather than one length.

    Scanning forward and returning the first hit yields the EARLIEST day
    of the current uninterrupted collapse, so ``days_at_collapse``
    measures the real outage rather than however far back we happened to
    look.
    """
    for candidate in range(len(complete)):
        window = _WindowBaselines(
            complete[max(0, candidate - thresholds.baseline_days) : candidate],
            thresholds,
        )
        if window.delivering_days < thresholds.min_baseline_days:
            continue
        if not window.is_collapsed(complete[candidate]):
            continue
        if not all(window.is_collapsed(day) for day in complete[candidate + 1 :]):
            continue
        return candidate, window.baseline_for(complete[candidate])
    return None


def _baseline_for(
    day: DailyDelivery,
    window: Sequence[DailyDelivery],
    thresholds: CollapseThresholds,
) -> _Baseline:
    """Median baseline for ``day``, same-weekday when there is enough of it.

    Median rather than mean: one promotional spike in the window must not
    inflate the bar and turn every ordinary day that follows into an
    alert.
    """
    same_weekday = [d for d in window if d.date.weekday() == day.date.weekday()]
    if len(same_weekday) >= thresholds.min_same_weekday_samples:
        sample, method = same_weekday, BaselineMethod.SAME_WEEKDAY_MEDIAN
    else:
        sample, method = list(window), BaselineMethod.ALL_DAY_MEDIAN
    return _Baseline(
        impressions=float(statistics.median(d.impressions for d in sample)),
        cost=float(statistics.median(d.cost for d in sample)),
        method=method,
        days_used=len(window),
        samples=len(sample),
    )


def _drop_pct(current: float, baseline: float) -> float:
    """Percentage ``current`` sits below ``baseline`` (0 when unusable)."""
    if baseline <= 0:
        return 0.0
    return 100.0 * (1.0 - (current / baseline))


def _build_signal(
    series: DeliverySeries,
    complete: Sequence[DailyDelivery],
    start_index: int,
    baseline: _Baseline,
) -> CollapseSignal:
    """Render the detected run of collapsed days as a signal."""
    collapsed = complete[start_index:]
    latest = collapsed[-1]
    severity = (
        CollapseSeverity.CRITICAL
        if all(d.impressions == 0 for d in collapsed)
        else CollapseSeverity.HIGH
    )
    drop = _drop_pct(latest.impressions, baseline.impressions)
    days = len(collapsed)
    return CollapseSignal(
        platform=series.platform,
        campaign_id=series.campaign_id,
        campaign_name=series.campaign_name,
        status=series.status,
        severity=severity,
        collapse_start_date=collapsed[0].date.isoformat(),
        days_at_collapse=days,
        current_impressions=latest.impressions,
        baseline_impressions=baseline.impressions,
        drop_pct=drop,
        current_cost=latest.cost,
        baseline_cost=baseline.cost,
        baseline_method=baseline.method,
        baseline_days_used=baseline.days_used,
        baseline_samples=baseline.samples,
        evaluated_through=latest.date.isoformat(),
        message=(
            f"Impressions are {drop:.1f}% below this campaign's own "
            f"{baseline.method.value} baseline of {baseline.impressions:,.0f}/day, "
            f"starting {collapsed[0].date.isoformat()} ({days} day(s) so far), "
            f"while its status is still {series.status}."
        ),
        recommended_action=(
            "Run analysis_delivery_collapse_diagnose for this campaign: overlay "
            "the change feed on the daily series and walk the elimination "
            "ladder (ad approval/policy, billing, budget, bid competitiveness, "
            "targeting and exclusions, learning state, flight dates)."
        ),
    )


# ---------------------------------------------------------------------------
# Normalisation — the shared entry point for every platform
# ---------------------------------------------------------------------------


#: Ceiling on how many days a single campaign's gap-fill may materialise.
#: A caller that passes a ``through`` far in the future would otherwise
#: allocate a row per day per campaign forever.
MAX_FILL_DAYS = 400


def fill_missing_delivery_days(
    rows: Iterable[dict[str, Any]],
    *,
    reported_through: date | None = None,
) -> list[dict[str, Any]]:
    """Materialise the days a platform report omits, and only those.

    Google Ads (GAQL over ``segments.date``) and Meta (insights with
    ``time_increment=1``) are both widely reported to **drop** a
    ``(campaign, date)`` row when there was no delivery, rather than
    return ``impressions=0``. If that holds, then on the exact symptom
    this detector exists for — impressions at literal zero — the
    collapsed days are simply ABSENT, each campaign's series ends at its
    last active day, and nothing ever fires.

    The reconciliation deliberately does **not** depend on knowing which
    way either API behaves. A platform that already returns explicit zero
    rows leaves no gaps to fill, so this is a no-op for it; a platform
    that omits them gets them back. Correct either way, and it cannot rot
    when a platform changes its mind.

    Evidence, not assumption
    ------------------------
    A missing day is zero delivery only where the report **proves** the
    platform covered that day. Two kinds of gap, and they are not alike:

    - **Interior** — bracketed by rows, so the platform demonstrably
      reported past it. Certain: fill it with zero.
    - **Trailing** — beyond the last date anything was reported. That is
      a dead campaign *or* a platform that has not caught up yet, and
      nothing here can tell the two apart. Left absent, so the detector
      simply has no opinion on those days.

    The bracket is the **report**, not the single campaign: any campaign
    in the account carrying a row for date D proves D was covered, so a
    campaign silent on D genuinely delivered nothing. That is what keeps
    a dead campaign detectable in a live account while normal reporting
    lag stays silent — filling to the *requested* range end instead
    turned a one-day lag into a CRITICAL 100% drop on every healthy
    campaign, at any hour, and no ``consecutive_days`` setting closed it
    (a two-day lag simply produced ``days_at_collapse=2``).

    Precondition on ``rows``
    ------------------------
    Using the whole report as the bracket assumes **every campaign in
    ``rows`` came from one fetch and finalises at the same time**. mureo's
    own Google and Meta clients issue a single account-wide query per
    call, so they satisfy it by construction — but this function is
    reachable from ``analysis_delivery_collapse_check`` with rows an agent
    assembled itself, and there the assumption can break. Rows stitched
    together from several fetches, or a connector whose campaigns
    finalise at different times, make the FASTEST campaign's latest date
    the evidence: a slower but perfectly healthy campaign is then
    zero-filled up to it and reported as collapsed.

    When that precondition does not hold, pass ``reported_through``
    explicitly — the oldest per-campaign last date you trust, or a
    freshness timestamp the connector supplies. It is **not** the range
    you asked for; passing that is the bug described above.

    Days *before* a campaign's first row are never invented either: there
    is no evidence it existed yet, and fabricating them would fabricate
    the history the baseline is computed from.

    Residual gap, by construction: when EVERY campaign stops on the same
    day there is no later row to bracket anything, so nothing is filled
    and no signal fires. A total account outage and a platform-wide
    reporting failure are indistinguishable from here. Callers surface it
    instead via :func:`last_reported_day` — see
    ``DeliveryCollapseReport.unreported_days``.
    """
    parsed = [(row, _parse_date(row.get("date"))) for row in rows]
    dated = [(row, day) for row, day in parsed if str(row.get("campaign_id") or "")]
    if not dated:
        return [row for row, _ in parsed]

    report_end = (
        reported_through
        if reported_through is not None
        else max(day for _, day in dated)
    )
    filled = [row for row, _ in parsed]
    for campaign_id, (source, seen) in _index_days_by_campaign(dated).items():
        start = min(seen)
        end = min(report_end, start + timedelta(days=MAX_FILL_DAYS))
        filled.extend(_zero_rows(campaign_id, source, start, end, seen))
    return filled


def _index_days_by_campaign(
    dated: Sequence[tuple[dict[str, Any], date]],
) -> dict[str, tuple[dict[str, Any], set[date]]]:
    """``{campaign_id: (first row seen, every date seen)}``."""
    index: dict[str, tuple[dict[str, Any], set[date]]] = {}
    for row, day in dated:
        campaign_id = str(row["campaign_id"])
        existing = index.get(campaign_id)
        if existing is None:
            index[campaign_id] = (row, {day})
        else:
            existing[1].add(day)
    return index


def _zero_rows(
    campaign_id: str,
    source: dict[str, Any],
    start: date,
    end: date,
    seen: set[date],
) -> list[dict[str, Any]]:
    """Zero-delivery rows for every date in ``[start, end]`` not in ``seen``."""
    out: list[dict[str, Any]] = []
    day = start
    while day <= end:
        if day not in seen:
            out.append(
                {
                    "campaign_id": campaign_id,
                    "campaign_name": source.get("campaign_name", ""),
                    "status": source.get("status", ""),
                    "end_date": source.get("end_date", ""),
                    "date": day.isoformat(),
                    "impressions": 0,
                    "clicks": 0,
                    "cost": 0.0,
                }
            )
        day += timedelta(days=1)
    return out


def delivery_series_from_rows(
    rows: Iterable[dict[str, Any]],
    *,
    platform: str,
    reported_through: date | None = None,
) -> tuple[DeliverySeries, ...]:
    """Group day-grain platform rows into per-campaign series.

    This is what makes the detector genuinely cross-platform: a hosted
    connector, an official-MCP bridge, or a plugin only has to produce
    rows of ``{campaign_id, status, date, impressions, clicks, cost}``
    (plus optional ``campaign_name`` / ``end_date``) to get the same
    detection the native platforms get.

    Rows without a usable ``campaign_id`` are dropped — folding them into
    a synthetic ``""`` campaign would silently mix several campaigns'
    delivery. A malformed ``date`` raises :class:`ValueError`: guessing
    at it would misplace the cliff.

    Gaps are reconciled through :func:`fill_missing_delivery_days` before
    grouping, so a platform that omits its zero-delivery rows cannot
    present a dead campaign as a series that merely stops. Pass
    ``reported_through`` only when you genuinely know how far the
    platform has reported; it is NOT the range you requested, and the
    built-in clients deliberately do not pass it (see that function for
    why filling to the requested end turns reporting lag into a
    CRITICAL).
    """
    grouped: dict[str, list[DailyDelivery]] = {}
    attributes: dict[str, tuple[str, str, date | None]] = {}
    for row in fill_missing_delivery_days(rows, reported_through=reported_through):
        campaign_id = str(row.get("campaign_id") or "").strip()
        if not campaign_id:
            continue
        grouped.setdefault(campaign_id, []).append(
            DailyDelivery(
                date=_parse_date(row.get("date")),
                impressions=_to_int(row.get("impressions")),
                clicks=_to_int(row.get("clicks")),
                cost=_to_float(row.get("cost")),
            )
        )
        if campaign_id not in attributes:
            attributes[campaign_id] = (
                str(row.get("campaign_name") or ""),
                str(row.get("status") or ""),
                _parse_optional_date(row.get("end_date")),
            )
    return tuple(
        DeliverySeries(
            platform=platform,
            campaign_id=campaign_id,
            campaign_name=attributes[campaign_id][0],
            status=attributes[campaign_id][1],
            end_date=attributes[campaign_id][2],
            daily=tuple(sorted(days, key=lambda d: d.date)),
        )
        for campaign_id, days in sorted(grouped.items())
    )


def _parse_date(value: Any) -> date:
    """Parse a ``YYYY-MM-DD`` date; raise :class:`ValueError` otherwise."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError as exc:
            raise ValueError(f"unparseable delivery date: {value!r}") from exc
    raise ValueError(f"unparseable delivery date: {value!r}")


def _parse_optional_date(value: Any) -> date | None:
    """Same as :func:`_parse_date` but tolerates an absent value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _parse_date(value)


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Thresholds from STRATEGY.md ## Guardrails
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")

#: ``## Guardrails`` bullet key -> :class:`CollapseThresholds` field.
GUARDRAIL_KEYS: dict[str, str] = {
    "delivery_collapse_drop_pct": "drop_pct",
    "delivery_collapse_min_baseline_impressions": "min_baseline_impressions",
    "delivery_collapse_baseline_days": "baseline_days",
    "delivery_collapse_min_baseline_days": "min_baseline_days",
    "delivery_collapse_consecutive_days": "consecutive_days",
    "delivery_collapse_min_same_weekday_samples": "min_same_weekday_samples",
}

_INTEGER_FIELDS = frozenset(GUARDRAIL_KEYS.values()) - {"drop_pct"}


def collapse_thresholds_from_guardrails_text(content: str) -> CollapseThresholds:
    """Parse a ``## Guardrails`` body into :class:`CollapseThresholds`.

    Mirrors :func:`mureo.policy.strategy_gate.parse_guardrails`: unknown
    keys are ignored (forward compatibility) and a malformed or
    out-of-range value drops that one rule rather than failing the parse
    — a typo in one bullet must not silently disable detection.
    """
    thresholds = CollapseThresholds()
    for line in content.splitlines():
        match = _BULLET_RE.match(line)
        if match is None:
            continue
        field = GUARDRAIL_KEYS.get(match.group(1).lower())
        if field is None:
            continue
        value = _valid_threshold(field, match.group(2))
        if value is not None:
            # ``replace`` is typed per-field; the key is validated against
            # GUARDRAIL_KEYS above, so the dynamic field name is sound.
            thresholds = replace(thresholds, **{field: value})  # type: ignore[arg-type]
    return thresholds


def _valid_threshold(field: str, raw: str) -> float | int | None:
    """Coerce + range-check one bullet value; ``None`` rejects it."""
    try:
        number = float(raw.replace(",", "").replace("_", "").strip())
    except (AttributeError, ValueError):
        return None
    if field == "drop_pct":
        return number if 0.0 < number <= 100.0 else None
    if field in _INTEGER_FIELDS:
        return int(number) if number >= 1 else None
    return None  # pragma: no cover — defensive: every key maps to a branch


def collapse_thresholds_from_strategy_text(text: str) -> CollapseThresholds:
    """Extract thresholds from full STRATEGY.md text (defaults if absent)."""
    # Local imports: this module stays import-light for the pure path, and
    # ``strategy_gate`` owns the canonical heading name so the two cannot
    # drift onto different sections.
    from mureo.context.strategy import parse_strategy
    from mureo.policy.strategy_gate import GUARDRAILS_HEADING

    for entry in parse_strategy(text):
        if entry.title.strip().lower() == GUARDRAILS_HEADING:
            return collapse_thresholds_from_guardrails_text(entry.content)
    return CollapseThresholds()


__all__ = [
    "BASELINE_SOURCE",
    "GUARDRAIL_KEYS",
    "MAX_FILL_DAYS",
    "SERVING_STATUSES",
    "BaselineMethod",
    "CollapseSeverity",
    "CollapseSignal",
    "CollapseThresholds",
    "DailyDelivery",
    "DeliverySeries",
    "collapse_thresholds_from_guardrails_text",
    "collapse_thresholds_from_strategy_text",
    "delivery_series_from_rows",
    "detect_delivery_collapse",
    "fill_missing_delivery_days",
    "detect_delivery_collapses",
    "last_reported_day",
    "is_serving_status",
]
