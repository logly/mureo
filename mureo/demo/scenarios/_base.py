"""Shared types and helpers for the demo scenario registry.

A :class:`Scenario` bundles everything ``mureo demo init`` needs for a
single named demo: the XLSX sheet rows, the STATE.json document, and
the STRATEGY.md text. Each registered scenario is a frozen dataclass
instance — adding a new one is "drop a module under
``mureo/demo/scenarios/`` and register it in ``__init__``".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mureo.byod.adapters.google_ads import _synthetic_id as _byod_synthetic_id

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date


@dataclass(frozen=True)
class Scenario:
    """A single named demo dataset.

    Attributes:
        name: CLI key (kebab-case, e.g. ``"seasonality-trap"``).
        title: Human-readable title for ``mureo demo list``.
        blurb: One-line description for ``mureo demo list``.
        days: Length of the data period in days.
        end_date: Last calendar day in the data.
        brand: Synthetic brand name used in copy and identifiers.
        sheet_rows: Mapping of XLSX sheet name -> rows (header first).
            Required keys: ``campaigns``, ``ad_groups``, ``search_terms``,
            ``keywords`` (Google Ads), ``meta_ads`` (Meta Ads export).
        state_doc: Full STATE.json document (must round-trip through
            :func:`mureo.context.state.parse_state`). Use schema v2 with
            per-platform campaigns and an ``action_log`` array.
        strategy_md: STRATEGY.md text — should include numeric goals
            and explicit constraints so workflow skills can detect
            violations.
    """

    name: str
    title: str
    blurb: str
    days: int
    end_date: date
    brand: str
    sheet_rows: Mapping[str, Sequence[Sequence[object]]]
    state_doc: Mapping[str, object]
    strategy_md: str
    # When False, the scenario's diagnostic story relies on a sparse
    # or absent action_log (e.g. strategy-drift demos undocumented
    # changes by a manager — empty action_log around active changes
    # is itself the diagnostic signal). Contract tests skip the >=3
    # entries floor only for these scenarios.
    requires_action_log: bool = True


def campaign_id(name: str) -> str:
    """Synthesize the campaign_id BYOD will assign to ``name``.

    Imports the BYOD adapter's helper directly so any change to the
    formula automatically propagates to the demo's STATE.json. Both
    Google Ads and Meta Ads adapters use the same formula today; if
    they diverge in the future we'd need per-platform branches here.
    """
    return _byod_synthetic_id("camp", name)
