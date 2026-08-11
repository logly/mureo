"""The :class:`ChangeFeedProvider` Protocol and its entry-point group (#545).

A **new** Protocol in a **new** entry-point group, deliberately. The rule in
``docs/ABI-stability.md`` §4 is that adding a required method to an existing
``runtime_checkable`` Protocol is breaking: ``isinstance`` against such a
Protocol requires *every* member, so a new method would have silently
de-registered every already-published plugin. #546 hit the same wall on
:class:`~mureo.analytics.protocol.AnalyticsModule` and split its extension
into a sibling Protocol; this does the same one level out.

Two consequences of it being its own group rather than a fifth
``AnalyticsModule`` method:

- A bridge that only wants to publish a change feed does not have to stub
  four analytics methods it will never implement.
- An installed plugin that has never heard of change import is unaffected in
  every way. It registers nothing here, so it is simply absent, and the
  importer reports ``change_import_unavailable_for_<platform>`` for its
  platform — the same honest-degradation contract as
  ``analytics_not_available_for_<platform>``.

Absence of a change feed is not proof of innocence. A platform with no feed
means mureo cannot see manual work there, not that none happened; the
importer's ``UNAVAILABLE`` status says exactly that and must be surfaced to
the operator rather than collapsed into "no changes".
"""

from __future__ import annotations

# ruff: noqa: TC001, TC003
# Model + stdlib imports stay at module top level (NOT under ``TYPE_CHECKING``)
# so ``typing.get_type_hints(ChangeFeedProvider.fetch_change_events)`` resolves
# at introspection time on Python 3.10 — the same rule the domain Protocols in
# ``mureo.core.providers`` follow. This IS the published signature; a plugin
# author checking it against their implementation must be able to read it.
from datetime import datetime
from typing import Protocol, runtime_checkable

from mureo.change_import.models import ChangeFeedResult

#: Entry-point group third-party bridges and plugins register against.
#: Adding a new group is a non-breaking ABI change (``docs/ABI-stability.md``
#: §6) precisely because nothing existing has to move into it.
CHANGE_FEED_ENTRY_POINT_GROUP = "mureo.change_feeds"


@runtime_checkable
class ChangeFeedProvider(Protocol):
    """A platform's change history, normalised for import into ``action_log``.

    Implementations live in ``mureo.change_import.builtin`` for mureo-native
    platforms (auto-registered) or in a third-party distribution shipping an
    entry point in :data:`CHANGE_FEED_ENTRY_POINT_GROUP` (discovered lazily,
    instantiated with no arguments).

    The Protocol is intentionally one method wide. Everything else — dedup,
    attribution, the observation window, the ``action_log`` write — is
    platform-agnostic and lives in core, so an adapter's whole job is to
    fetch and normalise.
    """

    platform: str
    """The canonical platform key this feed answers for.

    For a built-in this IS the STATE.json ``platforms`` key
    (``"google_ads"``). For a plugin or bridge it is the module's *registry
    name*, which MUST equal the provider's ``name`` in the ``mureo.providers``
    group — it is the ``<provider>`` half of ``plugin:<distribution>:<provider>``
    (#537), which mureo builds itself from the distribution that shipped the
    entry point. Do NOT write a ``plugin:``-prefixed value here; the registry
    refuses one, because a module allowed to name itself after another
    distribution could shadow that distribution's key.
    """

    async def fetch_change_events(
        self,
        account_id: str,
        *,
        since: datetime,
        until: datetime,
    ) -> ChangeFeedResult:
        """Return the changes the platform reports in ``[since, until]``.

        Both bounds are timezone-aware. ``since`` is mureo's watermark — the
        newest change it has already imported for this platform, or a default
        lookback on the first pass — so an implementation should treat the
        window as inclusive and let mureo's deduper handle any overlap rather
        than trying to be exact at the boundary.

        Implementations MUST set :attr:`ChangeFeedResult.truncated` when the
        platform's response was capped, and SHOULD populate whatever identity
        (``campaign_id`` / ``ad_id`` / ``entity_id``) the feed exposes: without
        it mureo cannot tell its own change apart from an operator's and will
        record mureo's own work a second time as external.

        Raising is a valid answer for "cannot fetch" (missing credentials,
        expired token, unsupported account). The importer catches it per
        platform and reports ``ERROR`` — never silence.
        """
        ...


__all__ = [
    "CHANGE_FEED_ENTRY_POINT_GROUP",
    "ChangeFeedProvider",
]
