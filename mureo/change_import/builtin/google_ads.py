"""Built-in change feed for Google Ads (#545).

Wraps :meth:`GoogleAdsApiClient.list_change_history` — the read-only
``change_event`` query mureo already shipped — and normalises its rows onto
:class:`~mureo.change_import.models.ExternalChange`. The read existed; what
did not exist was anything that turned it into a record.

**What this feed cannot see.** Documented on every result rather than in a
comment, because an operator reading an empty import needs it:

- ``change_event`` retains roughly **30 days**. Anything older is gone from
  the API, not merely unfetched.
- It reports changes made by **users**. Changes the platform makes on its own
  — automated bidding moving a bid, a policy disapproval, an automated rule —
  do not appear, so an empty feed does not mean a static account.
- It caps at :data:`~mureo.google_ads._extensions_targeting.CHANGE_HISTORY_ROW_LIMIT`
  rows with no paging. A capped response sets ``truncated``.

Rows name ONE canonical target each — see :func:`_row_identity` for why that
matters to attribution.

The client is opened per call through the shared factory, so credentials may
be configured after registration and BYOD routing is picked up automatically.
BYOD has no change history at all (the export carries performance rows, not
an audit trail), and that is reported as ``unavailable_reason`` rather than
as an empty window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.change_import.models import ChangeFeedResult, ExternalChange

if TYPE_CHECKING:
    from datetime import datetime

#: Retention the Google Ads API documents for ``change_event``.
_RETENTION_DAYS = 30

_COVERAGE_NOTES: tuple[str, ...] = (
    f"Google Ads change history retains about {_RETENTION_DAYS} days; older "
    "changes are gone from the API and cannot be backfilled.",
    "It records changes made by users only — automated bidding, policy "
    "decisions and automated rules do not appear, so an empty feed is not "
    "evidence that the account was static.",
)

_TRUNCATION_NOTE = (
    "The change_event row cap was reached and the resource has no paging, so "
    "older changes inside this window are unreachable. Poll more often; they "
    "cannot be recovered later."
)


def _id_from_resource_name(resource_name: str, segment: str) -> str | None:
    """Extract the trailing id from ``customers/<cid>/<segment>/<id>``.

    Returns ``None`` for anything that does not match that shape, so a
    renamed or unexpected resource path yields "no identity" rather than a
    fabricated one — an id invented here would be matched against
    ``action_log`` and could attribute an operator's change to mureo.
    """
    if not resource_name:
        return None
    parts = resource_name.split("/")
    if len(parts) < 2 or parts[-2] != segment or not parts[-1]:
        return None
    return parts[-1]


#: Resource types whose changed resource IS an ad. For these the ad is the
#: canonical target and the ad group is parent context — see
#: :func:`_row_identity`.
_AD_LEVEL_RESOURCE_TYPES = frozenset({"AD", "AD_GROUP_AD"})


def _ad_id_from_changed_resource(changed_resource_name: str) -> str | None:
    """Pull the ad id out of ``customers/<cid>/adGroupAds/<adGroupId>~<adId>``.

    ``None`` for any other shape. The composite id is the only place the feed
    names the ad itself — ``change_event.ad_group`` names the container.
    """
    if not changed_resource_name:
        return None
    parts = changed_resource_name.split("/")
    if len(parts) < 2 or parts[-2] != "adGroupAds":
        return None
    tail = parts[-1].split("~")
    return tail[-1] if len(tail) == 2 and tail[-1] else None


def _row_identity(row: dict[str, Any], resource_type: str) -> dict[str, Any]:
    """The ONE canonical target of a row, plus its campaign.

    mureo records a single canonical target per action — ``entity_id`` when
    declared, else ``ad_id``, else ``campaign_id`` — and parent context is
    deliberately not promoted alongside it
    (:func:`mureo.mcp.plugin_semantics.extract_mutation_identity` states the
    same rule for plugin mutations). The feed side has to speak that same
    language or the two can never be compared: attribution requires both
    sides to name their target at the SAME specificity
    (:func:`mureo.change_import.dedupe._identities_agree`), so a feed row that
    reported *both* the ad and its ad group would look strictly more specific
    than mureo's own record of the very same change, and mureo's ad-level work
    would re-import as external every single run.

    So an ad-level row names the ad and NOT its ad group; every other row that
    carries an ad group names the ad group.
    """
    identity: dict[str, Any] = {
        "campaign_id": _id_from_resource_name(
            str(row.get("campaign") or ""), "campaigns"
        )
    }
    if resource_type in _AD_LEVEL_RESOURCE_TYPES:
        ad_id = _ad_id_from_changed_resource(
            str(row.get("changed_resource_name") or "")
        )
        if ad_id is not None:
            identity["ad_id"] = ad_id
            return identity
        # An ad-level row mureo cannot resolve to an ad names no sub-campaign
        # target at all. Falling back to the ad group would claim a
        # specificity the row does not have, and the campaign alone would let
        # a one-ad change match a campaign-wide one.
        return identity
    ad_group_id = _id_from_resource_name(str(row.get("ad_group") or ""), "adGroups")
    if ad_group_id is not None:
        identity["entity_type"] = "ad_group"
        identity["entity_id"] = ad_group_id
    return identity


def _row_to_change(row: dict[str, Any]) -> ExternalChange | None:
    """Normalise one ``list_change_history`` row, or ``None`` if unusable.

    A row without a change timestamp is dropped: the observation window and
    the watermark both anchor on it, and a change dated "now" because its own
    date was missing would be reviewed on the wrong schedule and would move
    the watermark past changes never seen.
    """
    occurred_at = str(row.get("change_date_time") or "").strip()
    if not occurred_at:
        return None
    resource_type = str(row.get("change_resource_type") or "UNKNOWN")
    changed_fields = row.get("changed_fields") or []
    return ExternalChange(
        platform="google_ads",
        # Google returns ``YYYY-MM-DD HH:MM:SS`` in the account timezone;
        # normalise the separator so ``datetime.fromisoformat`` parses it.
        occurred_at=occurred_at.replace(" ", "T", 1),
        resource_type=resource_type,
        operation=str(row.get("resource_change_operation") or "UNKNOWN"),
        change_id=str(row.get("resource_name") or ""),
        changed_fields=tuple(str(f) for f in changed_fields),
        actor=str(row.get("user_email") or ""),
        client_type=str(row.get("client_type") or ""),
        **_row_identity(row, resource_type),
    )


class GoogleAdsChangeFeed:
    """:class:`~mureo.change_import.protocol.ChangeFeedProvider` for Google Ads."""

    platform = "google_ads"

    async def fetch_change_events(
        self,
        account_id: str,
        *,
        since: datetime,
        until: datetime,
    ) -> ChangeFeedResult:
        """Fetch the account's change history for ``[since, until]``.

        The window is narrowed to whole days because ``change_event``'s filter
        is day-grained on mureo's side; the extra hours at each edge cost
        nothing, since the deduper drops anything already imported.
        """
        client = self._open_client(account_id)
        if client is None:
            # BYOD. ``unavailable_reason`` — NOT an empty result: nothing was
            # looked at, and an empty ``changes`` tuple would be reported as
            # IMPORTED, putting the platform outside ``blind_spots`` and
            # telling the agent it was checked.
            return ChangeFeedResult(
                unavailable_reason=(
                    "Google Ads change history is a live-API read; the BYOD "
                    "export carries performance rows, not an audit trail, so "
                    "no change import is possible in BYOD mode. Nothing was "
                    "checked — this is not evidence that nothing changed."
                )
            )
        rows = await client.list_change_history(
            start_date=since.date().isoformat(),
            end_date=until.date().isoformat(),
        )
        from mureo.google_ads._extensions_targeting import CHANGE_HISTORY_ROW_LIMIT

        truncated = len(rows) >= CHANGE_HISTORY_ROW_LIMIT
        changes = tuple(
            change for change in (_row_to_change(row) for row in rows) if change
        )
        notes = _COVERAGE_NOTES + ((_TRUNCATION_NOTE,) if truncated else ())
        return ChangeFeedResult(changes=changes, truncated=truncated, notes=notes)

    def _open_client(self, account_id: str) -> Any:
        """Open a live Google Ads client, or ``None`` in BYOD mode.

        Local imports keep registry import cheap and free of auth side
        effects. Missing credentials raise out of here on purpose: the
        importer turns that into an ``ERROR`` outcome, which is the honest
        answer — the window was not checked. Returning an empty result would
        report it as quiet.
        """
        from mureo.auth import load_google_ads_credentials
        from mureo.byod.runtime import byod_has
        from mureo.mcp._client_factory import get_google_ads_client
        from mureo.mcp._handlers_google_ads import _resolve_customer_id

        if byod_has("google_ads"):
            return None
        # Bind the account to the workspace allow-list (#411/#413) before it
        # reaches the client factory, so change import cannot become a way to
        # read an account the workspace is not scoped to.
        resolved = _resolve_customer_id(account_id, None)
        creds = load_google_ads_credentials()
        if creds is None:
            raise RuntimeError("google_ads credentials are not configured")
        return get_google_ads_client(creds, resolved)


__all__ = ["GoogleAdsChangeFeed"]
