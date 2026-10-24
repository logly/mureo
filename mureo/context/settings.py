"""Workspace settings stored in STATE.json (#848).

One setting today: ``settings.ops_history.enabled``, the switch for ops
history. Off by default — for every existing workspace and every new one —
because turning it on makes ``reason`` and ``expected`` REQUIRED on every
mutating call, which is a behaviour change an operator opts into.

On disk::

    "settings": {"ops_history": {"enabled": true}}

Absent is the default and reads as disabled, so a document written before
this section existed parses unchanged and gains no key on the next write.
The read is tolerant (anything but a literal ``true`` is "off"): a
hand-edited ``"enabled": "yes"`` must never switch on a requirement the
operator cannot see they switched on. The WRITE is strict — only a real
boolean is accepted.

Written only through
:func:`mureo.context.settings_store.set_ops_history_enabled`, which takes
STATE.json's file lock; the MCP tool and the ``mureo configure`` toggle both
reach it through the workspace-guarded path resolution every other STATE.json
writer uses. It lives in its own module because
:mod:`mureo.context.state_codec` reads :func:`parse_settings`, so this module
sits below :mod:`mureo.context.state_io` and does not import it (#879).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mureo.context.models import StateDocument

#: The two key names on disk, written down once.
OPS_HISTORY_KEY = "ops_history"
ENABLED_KEY = "enabled"


@dataclass(frozen=True)
class WorkspaceSettings:
    """The ``settings`` section.

    ops_history_enabled: Ops history (#848). When true, every mutating call
        must carry ``reason`` and ``expected``, and a proposed/adopted
        decision record must declare at least one ``expected`` effect.
    """

    ops_history_enabled: bool = False


#: Fields the codec maps, for :mod:`mureo.context.state_codec`'s
#: import-time coverage check, spliced into its ``_CODEC_COVERAGE`` table.
SETTINGS_COVERAGE: tuple[type, frozenset[str], str] = (
    WorkspaceSettings,
    frozenset({"ops_history_enabled"}),
    "settings.parse_settings / .settings_to_dict",
)


def parse_settings(raw: Any) -> WorkspaceSettings | None:
    """Read the stored section; ``None`` when there is none.

    Tolerant in every mode: a malformed value reads as the default rather
    than refusing the whole document.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return WorkspaceSettings()
    ops = raw.get(OPS_HISTORY_KEY)
    enabled = isinstance(ops, dict) and ops.get(ENABLED_KEY) is True
    return WorkspaceSettings(ops_history_enabled=enabled)


def settings_to_dict(settings: WorkspaceSettings) -> dict[str, Any]:
    """Serialise the section."""
    return {OPS_HISTORY_KEY: {ENABLED_KEY: settings.ops_history_enabled}}


def ops_history_enabled(doc: StateDocument | None) -> bool:
    """Whether ops history is switched on for this document."""
    if doc is None or doc.settings is None:
        return False
    return doc.settings.ops_history_enabled


__all__ = [
    "ENABLED_KEY",
    "OPS_HISTORY_KEY",
    "SETTINGS_COVERAGE",
    "WorkspaceSettings",
    "ops_history_enabled",
    "parse_settings",
    "settings_to_dict",
]
