"""Import externally-made changes into ``action_log`` (#545).

mureo's guarantees — a policy gate before dispatch, an ``action_log`` entry
after it, an ``observation_due`` window, an evidence review in
``/daily-check`` — all hang off mureo having *made* the change. An operator
working in a platform's own UI is normal professional behaviour, not misuse,
and none of that machinery ever runs for their work. The consequence is not
merely a thin log: mureo cannot tell the difference between "nothing
happened" and "something happened that I cannot see".

This package closes the second half of that. It polls each platform's change
feed, drops what it has already recorded and what mureo itself did, and
appends the rest to ``action_log`` marked :data:`~mureo.context.models.EXTERNAL_ORIGIN`
— visible to daily-check, carrying an observation window, and permanently
distinguishable from a change mureo performed.

Layout:

- :mod:`~mureo.change_import.models` — the normalised change, the feed
  response, the per-platform outcome.
- :mod:`~mureo.change_import.protocol` — the ABI hook: a NEW Protocol in a
  NEW entry-point group, so no published plugin is affected.
- :mod:`~mureo.change_import.registry` — discovery, fault isolation, lookup.
- :mod:`~mureo.change_import.dedupe` — the two ways a change is already
  accounted for, and why one of them can only be approximate.
- :mod:`~mureo.change_import.importer` — the window, the write, the report.
- :mod:`~mureo.change_import.builtin` — mureo-native feeds (Google Ads).

**Coverage is partial and says so.** Only platforms with a registered feed
are polled; every other configured platform comes back
``change_import_unavailable_for_<platform>``, the same honest-degradation
contract as ``analytics_not_available_for_<platform>``. Read that as "mureo
is blind here", never as "nothing happened here" — the absence of a change
feed is not evidence of innocence. ``docs/change-import.md`` states, per
platform, what the feed is and how far mureo can currently read it.
"""

from __future__ import annotations

from mureo.change_import.dedupe import (
    ATTRIBUTION_WINDOW_MINUTES,
    classify_change,
    external_change_id,
    imported_change_ids,
)
from mureo.change_import.importer import (
    DEFAULT_LOOKBACK_DAYS,
    EXTERNAL_OBSERVATION_DAYS,
    import_external_changes,
    latest_imported_at,
    to_action_log_entry,
)
from mureo.change_import.models import (
    ChangeFeedResult,
    ChangeImportOutcome,
    ChangeImportStatus,
    ExternalChange,
    ImportVerdict,
)
from mureo.change_import.protocol import (
    CHANGE_FEED_ENTRY_POINT_GROUP,
    ChangeFeedProvider,
)
from mureo.change_import.registry import (
    ChangeFeedRegistry,
    ChangeFeedWarning,
    clear_change_feed_registry,
    default_change_feed_registry,
    discover_change_feeds,
    get_change_feed,
    list_change_feed_platforms,
    plugin_source,
    register_change_feed,
)

__all__ = [
    "ATTRIBUTION_WINDOW_MINUTES",
    "CHANGE_FEED_ENTRY_POINT_GROUP",
    "DEFAULT_LOOKBACK_DAYS",
    "EXTERNAL_OBSERVATION_DAYS",
    "ChangeFeedProvider",
    "ChangeFeedRegistry",
    "ChangeFeedResult",
    "ChangeFeedWarning",
    "ChangeImportOutcome",
    "ChangeImportStatus",
    "ExternalChange",
    "ImportVerdict",
    "classify_change",
    "clear_change_feed_registry",
    "default_change_feed_registry",
    "discover_change_feeds",
    "external_change_id",
    "get_change_feed",
    "import_external_changes",
    "imported_change_ids",
    "latest_imported_at",
    "list_change_feed_platforms",
    "plugin_source",
    "register_change_feed",
    "to_action_log_entry",
]
