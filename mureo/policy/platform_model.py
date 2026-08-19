"""Per-platform delivery models, on the one route that is always read (#648).

The prose half of :mod:`mureo.policy.learning_rules`. That module answered
"what can mureo *check* about this platform"; this one answers "what must the
agent not *assume* about it", for the cases where there is nothing to check.

The gap this closes
-------------------
The only text a platform plugin could put in front of the model
unconditionally was its MCP tool names and tool descriptions. A skill
contributed through ``mureo.skills`` is description-matched: the body is read
only when the agent decides the description applies, which does not happen on
a daily-check or weekly-report run. So a plugin could ship a correct, complete
statement of how its platform works and have it never be read at the point
where the wrong model does its damage — the report. A closed ad network plugin
hit exactly this: mureo described one of its ad groups as being "on automated
bidding, uncapped", a sentence hard-coded nowhere, assembled by the model out
of Google Ads vocabulary because nothing on the always-on route said the
platform has no bidding at all.

A registered :class:`PlatformModel` is rendered into the MCP server's
``instructions``, which the client receives inside the ``initialize``
response, before any tool call and independently of any skill description.

Evidence, not folklore
----------------------
Every model carries the same :class:`~mureo.policy.learning_rules.Evidence`
record the learning rules use: the first-party source, the date it was read,
and the sentence the statement rests on. A model missing any of the three is
refused at registration, because the failure mode this module exists to
prevent is a *plausible* sentence, and a plausible sentence with no source is
indistinguishable from a correct one until it costs money.

mureo core ships **no** built-in models. That is the same honesty rule the
learning rules apply to a platform with no first-party enumeration: where
mureo cannot quote a source, it says nothing rather than guessing, and it does
not pre-empt a platform's own account of itself. A platform with no registered
model contributes no text at all — silence, not a default.

Bounded by construction
-----------------------
Always-on text is a budget shared by everything else the model has to read, so
neither half of it is open-ended: one statement is capped at
:data:`MAX_STATEMENT_CHARS` (refused at registration, so the plugin author
finds out immediately) and the whole block at :data:`MAX_TOTAL_CHARS` (whole
statements dropped in platform order, with a warning naming what was dropped).

In scope, not installed
-----------------------
A model is rendered only when this server actually serves tools whose names
start with its ``tool_prefix``. An installed-but-disabled platform
(``MUREO_DISABLE_*``) exposes no tools and therefore contributes no prose, and
no operator is charged always-on context for a platform they are not running.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from mureo.policy.learning_rules import Evidence

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

#: Longest one platform's statement may be. The only always-on string mureo
#: ships today — the workspace-routing sentence in
#: ``mureo.mcp.server._workspace_instruction`` — is 328 characters, so a
#: platform gets at most one such sentence's worth to say what it is. Enough
#: for "how delivery is selected and priced, and what therefore does not
#: exist"; not enough for a manual.
MAX_STATEMENT_CHARS = 400

#: Longest the rendered lines may be in total (the block's heading is not
#: counted). Roughly five full statements — more platforms than one mureo
#: server serves in any install we know of — after which whole statements are
#: dropped rather than letting the always-on block grow with the plugin list.
MAX_TOTAL_CHARS = 2000

_HEADING = (
    "Platform delivery models — from each platform's own documentation. When "
    "reporting on a platform listed here, use only what its line says: do not "
    "carry over auction, bidding or pricing concepts from another platform, "
    "and never report a figure the line says does not exist."
)


@dataclass(frozen=True)
class PlatformModel:
    """One platform's own account of how it selects and prices delivery.

    ``statement`` is plain prose, one paragraph, addressed to the agent: how
    delivery is chosen and charged on this platform, and — the half that stops
    a borrowed model — what it therefore does *not* have. ``tool_prefix`` is
    how the platform is recognised as in scope, matching the attribution rule
    :class:`~mureo.policy.learning_rules.PlatformLearningRules` already uses.
    """

    platform: str
    tool_prefix: str
    statement: str
    evidence: Evidence


_MODELS: dict[str, PlatformModel] = {}


def _require_text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"platform model needs a non-empty {what}")
    return value


def _validate(model: PlatformModel) -> None:
    """Refuse anything that would put unsourced or unbounded prose on the
    always-on route."""
    _require_text(model.platform, "platform")
    _require_text(model.tool_prefix, "tool_prefix")
    statement = _require_text(model.statement, "statement")
    if len(statement) > MAX_STATEMENT_CHARS:
        raise ValueError(
            f"platform model statement for {model.platform!r} is "
            f"{len(statement)} characters; the always-on budget is "
            f"{MAX_STATEMENT_CHARS}"
        )
    if any(char in statement for char in "\r\n"):
        raise ValueError(
            f"platform model statement for {model.platform!r} must be one "
            f"paragraph of plain prose (no line breaks)"
        )
    evidence = model.evidence
    if not isinstance(evidence, Evidence):
        raise ValueError(
            f"platform model for {model.platform!r} needs an Evidence record "
            f"naming the first-party source it rests on"
        )
    _require_text(evidence.source, "evidence.source")
    _require_text(evidence.quote, "evidence.quote")
    retrieved = _require_text(evidence.retrieved, "evidence.retrieved")
    try:
        date.fromisoformat(retrieved)
    except ValueError as exc:
        raise ValueError(
            f"platform model for {model.platform!r} needs evidence.retrieved "
            f"as an ISO date (YYYY-MM-DD), got {retrieved!r}"
        ) from exc


def register_platform_model(model: PlatformModel) -> None:
    """Register (or replace) one platform's delivery model.

    The hook a provider, bridge or plugin uses to state how its own platform
    works on a route the agent always reads. It hangs off ordinary module
    import — the same registry pattern as
    :func:`~mureo.policy.learning_rules.register_platform_learning_rules` — so
    no new entry-point group is involved: a provider discovered through
    ``mureo.providers`` calls this at import time and is registered before the
    server builds its ``instructions``.

    Raises :class:`ValueError` for a model that is unsourced, over-long or
    multi-paragraph, so a plugin author sees the boundary at registration
    rather than shipping prose that is silently truncated.
    """
    _validate(model)
    _MODELS[model.platform] = model


def reset_platform_models() -> None:
    """Restore the built-in registry (empty). Intended for tests."""
    _MODELS.clear()


def platform_model(platform: str) -> PlatformModel | None:
    """Return the registered model for ``platform``, or ``None``."""
    return _MODELS.get(platform)


def registered_platform_models() -> tuple[str, ...]:
    """Every platform key with a registered model, sorted."""
    return tuple(sorted(_MODELS))


def models_in_scope(tool_names: Iterable[str]) -> tuple[PlatformModel, ...]:
    """Registered models whose ``tool_prefix`` claims at least one of
    ``tool_names``, in platform order.

    Scope is decided from the tool list this server actually serves, not from
    what is installed: a platform switched off by ``MUREO_DISABLE_*`` exposes
    no tools and so contributes nothing.
    """
    names = tuple(tool_names)
    return tuple(
        model
        for _, model in sorted(_MODELS.items())
        if any(name.startswith(model.tool_prefix) for name in names)
    )


def platform_model_instructions(tool_names: Iterable[str]) -> str:
    """Render the always-on block for the platforms ``tool_names`` puts in
    scope.

    Returns ``""`` when nothing is in scope, which is what keeps a default
    install's ``InitializeResult`` byte-identical.
    """
    models = models_in_scope(tool_names)
    if not models:
        return ""
    lines: list[str] = []
    dropped: list[str] = []
    used = 0
    for model in models:
        line = f"- {model.platform}: {model.statement}"
        if used + len(line) > MAX_TOTAL_CHARS:
            # Whole statements only: half a platform model is worse than none,
            # because a truncated sentence still reads as a complete claim.
            dropped.append(model.platform)
            continue
        used += len(line)
        lines.append(line)
    if dropped:
        logger.warning(
            "platform model block exceeds %d characters; omitted: %s",
            MAX_TOTAL_CHARS,
            ", ".join(dropped),
        )
    if not lines:
        return ""
    return "\n".join([_HEADING, *lines])


__all__ = [
    "MAX_STATEMENT_CHARS",
    "MAX_TOTAL_CHARS",
    "PlatformModel",
    "models_in_scope",
    "platform_model",
    "platform_model_instructions",
    "register_platform_model",
    "registered_platform_models",
    "reset_platform_models",
]
