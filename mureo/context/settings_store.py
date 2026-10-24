"""Switch workspace settings in STATE.json — the path half of :mod:`mureo.context.settings`.

Split out of :mod:`mureo.context.settings` in #879, verbatim. That module
holds the section's model, its tolerant parse and its serialisation; this
one holds the locked write that changes it. The split is what lets the
writer take STATE.json's lock at top level: :mod:`mureo.context.state_codec`
reads :func:`mureo.context.settings.parse_settings`, so
:mod:`mureo.context.settings` sits BELOW :mod:`mureo.context.state_io` and
cannot import it, while this module sits above both.

:mod:`mureo.context.state` does not re-export :func:`set_ops_history_enabled`;
import it from here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import StateDocument

from mureo.context.settings import WorkspaceSettings, ops_history_enabled
from mureo.context.state_io import _locked_state_mutation, read_state_file


def set_ops_history_enabled(path: Path, enabled: Any) -> StateDocument:
    """Switch ops history on or off for the workspace at ``path``.

    A value that is already in force writes nothing — in particular, "off"
    for a workspace with no STATE.json does not create one.

    Raises:
        ValueError: ``enabled`` is not a boolean. Refused before the file
            is opened, so a bad call never creates or touches STATE.json.
    """
    if not isinstance(enabled, bool):
        raise ValueError(f"enabled must be a boolean; got {enabled!r}")

    current_doc = read_state_file(path)
    if ops_history_enabled(current_doc) == enabled:
        return current_doc

    def _build(doc: StateDocument) -> StateDocument:
        current = doc.settings or WorkspaceSettings()
        return replace(doc, settings=replace(current, ops_history_enabled=enabled))

    return _locked_state_mutation(path, _build)


__all__ = ["set_ops_history_enabled"]
