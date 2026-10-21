"""Re-emitting an entry the codec kept with its on-disk dict (#859 / #881).

One rule, shared by every STATE.json entry that carries a ``raw`` field —
:class:`~mureo.context.models.ActionLogEntry` (#859) and
:class:`~mureo.context.models.PlatformState` /
:class:`~mureo.context.models.CampaignSnapshot` /
:class:`~mureo.context.models.AdState` (#881). Two copies of it would be two
answers to "what does a hand-authored entry look like after mureo writes the
document", and they would drift.

Stdlib only, so both codecs import it at module level without a cycle.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping


def preserved_dict(
    raw: Mapping[str, Any],
    canonical: Mapping[str, Any],
    *,
    required: Collection[str],
    known: Collection[str],
    opaque: bool,
) -> dict[str, Any]:
    """Re-emit a preserved entry in its on-disk key order.

    ``canonical`` is the entry as the codec would emit it from its fields
    alone; ``required`` / ``known`` are the codec's required and known keys.

    A known key carries the entry's CURRENT value, so a mutation lands (and
    the model's normalisation applies, as it always has); one whose field is
    now unset is left out, so a cleared field stays cleared — except on an
    ``opaque`` entry (one the model refused), whose other optional fields
    were never read, so an unset one is emitted as found.
    A required key whose current value is empty is emitted exactly as found
    (absent stays absent, null stays null) rather than as an invented ``""``.
    An unknown key is copied through. Known fields set on the entry but not
    on disk (e.g. a stamped ``batch_id``) follow, in the codec's order; one
    whose value is ``None`` is not added, so a codec that emits some unset
    keys as ``null`` does not invent them on an entry that never had them.
    """
    result: dict[str, Any] = {}
    for key, raw_value in raw.items():
        if key in required:
            current = canonical[key]
            result[key] = current if current else copy.deepcopy(raw_value)
        elif key not in known:
            result[key] = copy.deepcopy(raw_value)
        elif key in canonical:
            result[key] = canonical[key]
        elif opaque:
            result[key] = copy.deepcopy(raw_value)
    for key, value in canonical.items():
        if key in raw or value is None or (key in required and not value):
            continue
        result[key] = value
    return result


__all__ = ["preserved_dict"]
