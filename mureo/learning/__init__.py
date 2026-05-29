"""Learning federation subpackage.

Read-side companion to ``/learn``. Three pieces wired together:

- :mod:`mureo.learning.insight_sources` — tolerant config parser for
  ``~/.mureo/insight_sources.json``.
- :mod:`mureo.learning.federation` — MCP client wrappers + per-source
  vector-search forwarder with timeout / error isolation /
  concurrent fan-out.
- :mod:`mureo.learning.context_builder` — turn ``(question,
  campaign_id)`` into a context-rich query string by pulling the
  relevant slice of local state.
"""

from __future__ import annotations
