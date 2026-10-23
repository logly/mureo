"""Campaign upserts and the platform-entry helpers every targeted write shares.

Split out of :mod:`mureo.context.state` in #917, verbatim apart from the
long functions being broken into named steps; :mod:`mureo.context.state`
re-exports every name here, so existing imports keep working.

- :func:`upsert_campaign` / :func:`get_campaign` — the campaign half of the
  document;
- :func:`_platform_base` and :func:`_stamp_fetched_at` — the two helpers
  every ``platforms``-touching writer builds on (this module's own upsert,
  :mod:`mureo.context.platform_store` and
  :func:`mureo.context.daily.with_platform_daily`), which is why they sit
  here, below all of them.

Why ``period_end`` is not stamped (#798)
----------------------------------------

**:func:`_stamp_fetched_at` deliberately does NOT stamp ``fetched_at``'s
sibling ``period_end``.** That field is the last calendar DAY the figures
cover, and the server cannot answer it: "yesterday" is yesterday in the ad
account's own timezone, which this process does not reliably know — the
account's timezone is a platform attribute nothing in STATE.json is required
to carry, and the machine's clock is not it. Deriving one anyway would put a
date on the operator's card that is silently off by one whenever the account
is not in the host's timezone, and a date that is wrong by a day is worse
than no date at all, because the read side trusts it and takes the staleness
verdict on it (:func:`mureo.web.report_freshness._platform_freshness`). So it
travels only when a caller supplies it, exactly as it was supplied — which is
the asymmetry with ``fetched_at``: the write time is a fact THIS process
observes, the coverage date is one only the caller that pulled the figures
knows.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import CampaignSnapshot, StateDocument

from mureo.context.models import PlatformState
from mureo.context.platform_accounts import account_ids_match, normalize_account_id
from mureo.context.platform_guards import guard_platform_entry_write
from mureo.context.state_io import _locked_state_mutation, _now_iso


def _merge_ads(
    existing: CampaignSnapshot, incoming: CampaignSnapshot
) -> CampaignSnapshot:
    """Inherit ``ads`` from ``existing`` when ``incoming`` did not supply it.

    An upsert replaces the whole snapshot, but ad-level state has no input on
    most calls: the standard flows fetch ads only for ACTIVE campaigns (an
    API-cost guard), so the first upsert after a campaign is paused — exactly
    when "what were its ads doing?" matters most — would otherwise reset
    ``ads`` from the last known statuses back to ``None`` ("never fetched"),
    silently destroying the audit trail #468 exists to create.

    Only ``None`` ("not supplied") inherits. An empty tuple is a real
    observation ("fetched, this campaign has no ads") and overwrites, as does
    any non-empty list. Each :class:`AdState` carries its own ``as_of``, so an
    inherited entry stays honestly dated rather than passing for fresh.
    """
    if incoming.ads is not None or existing.ads is None:
        return incoming
    return replace(incoming, ads=existing.ads)


def _upsert_into(
    campaigns: tuple[CampaignSnapshot, ...],
    campaign: CampaignSnapshot,
    *,
    inherit_ads: bool = False,
) -> tuple[CampaignSnapshot, ...]:
    """Return ``campaigns`` with ``campaign`` replacing any same-id entry
    (or appended when new), preserving order.

    ``inherit_ads`` enables the :func:`_merge_ads` carry-over and is safe ONLY
    for a platform-scoped list. The legacy v1 flat list matches on
    ``campaign_id`` alone — Google and Meta ids are independent namespaces, so
    a collision there matches two unrelated campaigns — and inheriting across
    that blind match would attach one account's ads to another's campaign.
    The flat list therefore keeps plain full-replace semantics.

    The same flag carries the matched entry's on-disk dict (``raw``, #881)
    onto the replacement, for the same reason and with the same limit: the
    snapshot's own fields still replace the stored ones, while the keys mureo
    does not know — an operator's hand-authored notes on that campaign — are
    written back instead of dropped. That limit is the one stated exception
    to #881's "unknown keys survive every write": a match in the v1 flat list
    is platform-blind, so carrying its ``raw`` could attach one platform's
    hand-written keys to another's campaign, and a matched flat entry's
    unknown keys are dropped instead.
    """
    result: list[CampaignSnapshot] = []
    found = False
    for c in campaigns:
        if c.campaign_id == campaign.campaign_id:
            merged = campaign
            if inherit_ads:
                merged = _merge_ads(c, campaign)
                if merged.raw is None and c.raw is not None:
                    merged = replace(merged, raw=c.raw)
            result.append(merged)
            found = True
        else:
            result.append(c)
    if not found:
        result.append(campaign)
    return tuple(result)


def _platform_base(
    platforms: dict[str, PlatformState], platform: str, account_id: str
) -> PlatformState:
    """The :class:`PlatformState` a targeted write should build on.

    The existing entry when there is one, otherwise a minimal new entry
    carrying only ``account_id`` — whose remaining fields take the dataclass's
    own defaults rather than a hand-written copy of them.

    Every caller then uses ``dataclasses.replace`` to change ONLY the fields it
    actually has input for, which is what makes preservation structural: a
    field added to :class:`PlatformState` later is carried across by every
    mutator without any of them being edited. Enumerating instead is how a
    campaign upsert once wiped the dashboard rollups, and how a metrics write
    once wiped the #342 conversion override — both silent, because a reset
    field is indistinguishable from one that was never set.

    One exception, and it is about identity rather than preservation:
    re-pointing a key at a DIFFERENT ad account (allowed when no other key
    holds it) drops ``not_collected``. That note names a collection failure
    for the account the entry used to describe; carried over, it would be
    rendered as a fact about the account that replaced it. Everything else
    survives the re-point exactly as before — the rollups are figures the
    next sync overwrites, while a note nothing overwrites would simply be
    wrong from here on. An entry with no ``account_id`` claims no account, so
    learning one identifies the entry rather than replacing it and the note
    stays; ``act_`` spellings of one account are one account (the same
    reading :func:`~mureo.context.platform_accounts.account_ids_match` gives
    every other surface).
    """
    existing = platforms.get(platform)
    if existing is None:
        return PlatformState(account_id=account_id)
    if (
        existing.not_collected is not None
        and normalize_account_id(existing.account_id)
        and normalize_account_id(account_id)
        and not account_ids_match(existing.account_id, account_id)
    ):
        return replace(existing, not_collected=None)
    return existing


def _supplies_fetched_at(rollup: dict[str, Any]) -> bool:
    """Whether ``rollup`` already states its own ``fetched_at`` (#637).

    Supplied means **a non-blank string**, not merely the key being present.
    ``None``, ``""`` and whitespace state no time at all — they are the
    absence, spelled out — and the tool's ``totals`` schema is a free-form
    object with no per-property types, so a model filling in an optional
    field explicitly sends exactly those. Honouring the key alone would let
    the writer this whole change is about reproduce the symptom it removes:
    the read side ignores a value that is not a string, so the card would go
    on saying *"update time unknown"*. Nothing is lost either way — a blank
    is not a clue to anything, unlike ``"today"``, which is kept.
    """
    supplied = rollup.get("fetched_at")
    return isinstance(supplied, str) and bool(supplied.strip())


def _stamp_fetched_at(rollup: Any, written_at: str) -> Any:
    """Return ``rollup`` carrying a ``fetched_at``, stamping ``written_at``
    when it has none (#637).

    ``fetched_at`` is what the dashboard's staleness marker reads. It used to
    be a field every writer had to remember, and the writer that reaches it
    most often is an agent following a skill — so "optional" became "usually
    missing" and most cards read *"update time unknown"*, which is worse than
    a stamp accurate to the minute. The server knows when the write happened;
    for the supported path (pull the figures, then write them) that IS when
    they were pulled.

    Two things it deliberately does not do:

    - **A supplied value is relayed verbatim**, including one that is not a
      timestamp at all: a caller writing a historical window is stating
      something the server cannot re-derive, and the read side keeps an
      uninterpretable string on purpose (see
      :func:`mureo.web.report_freshness._platform_freshness`) because it is the only
      clue to the writer that produced it. What counts as supplied is
      :func:`_supplies_fetched_at`.
    - **An empty rollup is left empty.** An advisory bridge keeps an entry
      with no figures; a lone ``fetched_at`` would turn "no synced metrics"
      into a rollup claiming a collection time for numbers that do not exist.

    Anything that is not a dict is passed through untouched — this is a write
    helper, not a validator.

    **Its sibling ``period_end`` is deliberately NOT stamped here (#798)** —
    see the module docstring for why.
    """
    if not isinstance(rollup, dict) or not rollup:
        return rollup
    if _supplies_fetched_at(rollup):
        return rollup
    return {**rollup, "fetched_at": written_at}


def _with_campaign(
    doc: StateDocument,
    campaign: CampaignSnapshot,
    *,
    platform: str,
    account_id: str,
) -> StateDocument:
    """``doc`` with ``campaign`` upserted — :func:`upsert_campaign`'s locked step."""
    # v1 flat list — preserved for backward compatibility.
    flat_campaigns = _upsert_into(doc.campaigns, campaign)

    # v2 per-platform — the shape the dashboard reads. Ensure the platform
    # entry exists, carries the (required) account_id, and holds the
    # campaign.
    platforms = dict(doc.platforms) if doc.platforms else {}
    guard_platform_entry_write(platforms, platform, account_id)
    base = _platform_base(platforms, platform, account_id)
    # Everything a campaign upsert has no input for — the platform-level
    # rollup (totals / metrics_period / periods) and the #342 conversion
    # override — is carried over by ``replace``. Each was a real
    # regression when it was enumerated and forgotten: an upsert wiped the
    # dashboard KPIs, and another wiped the account's conversion setting.
    platforms[platform] = replace(
        base,
        account_id=account_id,
        campaigns=_upsert_into(
            base.campaigns,
            campaign,
            # Platform-scoped: a same-id match here IS the same campaign,
            # so carrying its ad-level state over is safe (#468).
            inherit_ads=True,
        ),
    )

    # ``reports`` and ``action_log`` are likewise untouched by construction;
    # dropping the former used to wipe the stored report summaries the
    # dashboard renders on every upsert that followed a report write.
    return replace(
        doc,
        last_synced_at=_now_iso(),
        campaigns=flat_campaigns,
        platforms=platforms,
    )


def upsert_campaign(
    path: Path,
    campaign: CampaignSnapshot,
    *,
    platform: str,
    account_id: str,
) -> StateDocument:
    """Upsert a campaign into STATE.json under its platform.

    Writes the v2 ``platforms[platform]`` section — the schema the
    dashboard reads — with the **required** ``account_id`` and the
    campaign, and stamps ``last_synced_at`` to now. Without these the
    document is schema-incomplete and the client renders as "not yet
    bootstrapped" / inactive even though campaigns exist.

    The legacy v1 flat ``campaigns`` list is updated in lockstep so
    readers still on the v1 shape keep working (the field is retained
    for backward compatibility — see :class:`StateDocument`). That list
    is platform-blind, so it takes the snapshot as given; ad-level state
    is inherited only in the platform-scoped v2 section (see
    :func:`_upsert_into`).

    Args:
        path: STATE.json location.
        campaign: The campaign snapshot to insert or update.
        platform: Platform key the campaign belongs to (e.g.
            ``"google_ads"``, ``"meta_ads"``) — the ``platforms`` dict key.
        account_id: The platform account id (Google ``customer_id`` /
            Meta ``act_*``). Always written onto the platform entry so a
            per-account override is never silently dropped.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: ``platform`` is not a usable platform key, names no
            platform mureo can resolve (a built-in, an installed plugin's
            platform, or a ``plugin:<dist>:<provider>`` key — checked on
            CREATE only, so an existing entry stays writable), or the write
            would create a SECOND key for an account another key already
            holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """

    def _build(doc: StateDocument) -> StateDocument:
        return _with_campaign(doc, campaign, platform=platform, account_id=account_id)

    return _locked_state_mutation(path, _build)


def get_campaign(doc: StateDocument, campaign_id: str) -> CampaignSnapshot | None:
    """Search for a campaign by campaign_id."""
    for c in doc.campaigns:
        if c.campaign_id == campaign_id:
            return c
    return None


__all__ = [
    # The underscored helpers keep their names (#917 moved them, it did not
    # rename them): :mod:`mureo.context.platform_store` and
    # :mod:`mureo.context.daily` build on them, and :mod:`mureo.context.state`
    # still re-exports each one.
    "_platform_base",
    "_stamp_fetched_at",
    "get_campaign",
    "upsert_campaign",
]
