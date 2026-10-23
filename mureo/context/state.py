"""Read, mutate and durably write STATE.json — the single import surface.

``mureo.context.state`` has always been the single import site for the whole
STATE.json surface, and callers inside and outside this tree import it from
here. Since #917 it holds no logic of its own: every name below is
re-exported from the module that defines it, lowest layer first.

- :mod:`mureo.context.state_io` — the document layer: the atomic write (temp
  file -> fsync -> rename), the cross-process lock that makes a read ->
  modify -> write cycle one critical section, and the server clock;
- :mod:`mureo.context.campaign_store` — campaign upserts, and the
  platform-entry helpers every targeted write builds on;
- :mod:`mureo.context.action_log_store` — :func:`append_action_log`, the
  single recording choke point;
- :mod:`mureo.context.batch_store` — opening and closing a batch;
- :mod:`mureo.context.platform_store` — a platform entry's rollups,
  ``daily`` history, ``not_collected`` notes and conversion override;
- :mod:`mureo.context.report_store` — ``reports`` summaries and the
  ``display`` contract.

The targeted mutators own STATE.json's merge semantics — what a partial write
inherits rather than resets.

Three halves were split out earlier, and are re-exported here too:

- the JSON codec (:func:`parse_state` / :func:`render_state` and their
  per-field helpers) is :mod:`mureo.context.state_codec` (#538);
- the account conversion-override lookup
  (:func:`load_conversion_action_types`) is
  :mod:`mureo.context.conversion_overrides` (#538);
- the day-grain merge, the retention trim and the completeness guard are
  :mod:`mureo.context.daily` (#710), because a writer that lands ``daily``
  inside its OWN atomic document write needs them without a path — see that
  module.
"""

from __future__ import annotations

from mureo.context.action_log_store import append_action_log
from mureo.context.batch_store import begin_batch, end_batch
from mureo.context.campaign_store import _platform_base as _platform_base
from mureo.context.campaign_store import _stamp_fetched_at as _stamp_fetched_at
from mureo.context.campaign_store import get_campaign, upsert_campaign
from mureo.context.conversion_overrides import load_conversion_action_types
from mureo.context.daily import (
    DAILY_RETENTION_DAYS,
    capped_platform_daily,
    with_platform_daily,
)
from mureo.context.platform_store import (
    set_conversion_action_types,
    set_platform_metrics,
    set_platform_not_collected,
    set_workspace_not_collected,
)
from mureo.context.platform_store import set_platform_daily as set_platform_daily
from mureo.context.report_store import set_display, set_report
from mureo.context.state_codec import parse_state, render_state
from mureo.context.state_io import _atomic_write as _atomic_write
from mureo.context.state_io import (
    _locked_state_mutation,
    read_state_file,
    write_state_file,
)
from mureo.context.state_io import _now_iso as _now_iso
from mureo.context.state_io import _state_lock_path as _state_lock_path

#: The retention trim's old private name, kept as an alias (#710).
#:
#: A downstream writer that merges ``daily`` inside its own atomic document
#: write imports it to apply the retention rule, which is exactly the coupling
#: :func:`~mureo.context.daily.capped_platform_daily` exists to retire — but
#: dropping the name would break that writer on upgrade. New code uses the
#: public one.
_capped_daily = capped_platform_daily

# The names imported above in the ``import X as X`` form
# (``set_platform_daily`` and the private ``_atomic_write``, ``_now_iso``,
# ``_platform_base``, ``_stamp_fetched_at``, ``_state_lock_path``) were defined
# here before #917 without being listed in ``__all__``, and are imported from
# here by name. That form is the re-export mypy's ``no_implicit_reexport``
# reads as deliberate, so ``__all__`` stays exactly what it was.

__all__ = [
    # Re-exported from mureo.context.state_codec / .conversion_overrides /
    # .daily so every existing ``from mureo.context.state import ...`` keeps
    # working (#538, #710). Listed here, not merely imported, so the re-export
    # is explicit under mypy's ``no_implicit_reexport``.
    "DAILY_RETENTION_DAYS",
    "capped_platform_daily",
    "load_conversion_action_types",
    "parse_state",
    "render_state",
    "with_platform_daily",
    # Defined in the store modules since #917, and before that here.
    # ``_locked_state_mutation`` keeps its underscore — it is not for callers
    # outside this package, it is the read-modify-write primitive every
    # section's writer is built on — but it IS imported from here, so it is
    # declared rather than reached for through a name mypy's
    # ``no_implicit_reexport`` treats as an accident.
    "_locked_state_mutation",
    "append_action_log",
    "begin_batch",
    "end_batch",
    "get_campaign",
    "read_state_file",
    "set_conversion_action_types",
    "set_display",
    "set_platform_metrics",
    "set_platform_not_collected",
    "set_report",
    "set_workspace_not_collected",
    "upsert_campaign",
    "write_state_file",
]
