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
finds out immediately) and the rendered block at :data:`MAX_TOTAL_CHARS`.

Truncation is never silent *to the reader*. A block that lost statements to
the budget carries a line saying so, because the heading otherwise reads as a
complete list and "not listed" would then mean both "has no model" and "had
one, but it did not fit" — and the second of those is the #648 failure mode
returning unannounced.

Who may speak for a platform
----------------------------
Registration runs inside a third-party module import, so this contribution
point is a **trust boundary**: it puts text in front of the agent
unconditionally, which is exactly the power the module exists to grant. Two
controls keep a plugin from using it to speak for someone else, matching the
posture :mod:`mureo.core.providers.registry` already takes for provider names:

1. **First wins.** A second registration for a platform key that is already
   taken is dropped with a :class:`PlatformModelWarning`, never silently
   overwritten — so a plugin installed *after* a legitimate one cannot take
   the slot. ``warnings.filterwarnings("error", PlatformModelWarning)`` turns
   that into a startup failure for operators who want to fail closed.
2. **Only the owner is rendered.** Being registered is not enough. A model is
   rendered only where a tool whose name starts with its ``tool_prefix`` was
   *contributed by the platform the model names*, judged from the server's
   tool-ownership map — not from "some tool somewhere matches the prefix".
   A plugin claiming ``google_ads_`` therefore renders nothing: those tools
   are mureo's own, and mureo registers no models. A plugin can state how its
   own platform works; it cannot state how anyone else's does.

Neither control judges whether a statement is *true* — nothing can. What they
bound is whose name a statement can be published under.

In scope, not installed
-----------------------
Even for the owner, a model is rendered only when this server actually serves
its tools. An installed-but-disabled platform (``MUREO_DISABLE_*``) exposes no
tools and therefore contributes no prose, and no operator is charged always-on
context for a platform they are not running.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from mureo.policy.learning_rules import Evidence

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: Longest one platform's statement may be. The only always-on string mureo
#: ships today — the workspace-routing sentence in
#: ``mureo.mcp.server._workspace_instruction`` — is 328 characters, so a
#: platform gets at most one such sentence's worth to say what it is. Enough
#: for "how delivery is selected and priced, and what therefore does not
#: exist"; not enough for a manual.
MAX_STATEMENT_CHARS = 400

#: Longest the **whole rendered block** may be — heading, statement lines, the
#: newlines joining them and the truncation notice, all counted. Roughly four
#: full statements, more platforms than one mureo server serves in any install
#: we know of, after which whole statements are dropped rather than letting the
#: always-on block grow with the plugin list.
MAX_TOTAL_CHARS = 2000

_HEADING = (
    "Platform delivery models — from each platform's own documentation. When "
    "reporting on a platform listed here, use only what its line says: do not "
    "carry over auction, bidding or pricing concepts from another platform, "
    "and never report a figure the line says does not exist."
)


def _omission_note(count: int) -> str:
    """The line that stops a truncated block reading as a complete one."""
    return (
        f"NOTE: this list is INCOMPLETE — {count} further platform model(s) "
        f"did not fit in this block's length budget. For any platform not "
        f"named above, assume nothing about how it selects or prices delivery; "
        f"ask the operator rather than carrying over another platform's model."
    )


class PlatformModelWarning(UserWarning):
    """Emitted when a registration is dropped because the slot is taken.

    A :class:`UserWarning` subclass so operators can fail closed with
    ``warnings.filterwarnings("error", category=PlatformModelWarning)``, the
    same opt-in :class:`~mureo.core.providers.registry.RegistryWarning`
    offers for a provider name collision.
    """


@dataclass(frozen=True)
class PlatformModel:
    """One platform's own account of how it selects and prices delivery.

    ``statement`` is plain prose, one paragraph, addressed to the agent: how
    delivery is chosen and charged on this platform, and — the half that stops
    a borrowed model — what it therefore does *not* have.

    ``platform`` must be the registering provider's own name: it is both the
    label the statement is published under and the ownership key
    :func:`models_in_scope` checks the tools against. ``tool_prefix`` selects
    which of that provider's tools put it in scope, matching the attribution
    rule :class:`~mureo.policy.learning_rules.PlatformLearningRules` already
    uses — but here a prefix match alone renders nothing, because the prefix
    is a claim and the ownership map is what settles it.
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
    """Register one platform's delivery model. First registration wins.

    The hook a provider, bridge or plugin uses to state how its own platform
    works on a route the agent always reads. It hangs off ordinary module
    import — the same registry pattern as
    :func:`~mureo.policy.learning_rules.register_platform_learning_rules` — so
    no new entry-point group is involved: a provider discovered through
    ``mureo.providers`` calls this at import time and is registered before the
    server builds its ``instructions``.

    **First wins, like provider names.** If ``model.platform`` is already
    registered the new model is dropped with a :class:`PlatformModelWarning`,
    never silently substituted, so a plugin installed after a legitimate one
    cannot take over the slot. This mirrors
    :meth:`mureo.core.providers.registry.Registry.register`; the repository
    must not answer "can a later plugin steal a slot?" two different ways.

    Registration is not permission to speak for the named platform — see
    :func:`models_in_scope`, which renders a model only where that platform
    actually contributed the tools.

    Raises :class:`ValueError` for a model that is unsourced, over-long or
    multi-paragraph, so a plugin author sees the boundary at registration
    rather than shipping prose that is silently truncated.
    """
    _validate(model)
    existing = _MODELS.get(model.platform)
    if existing is not None:
        warnings.warn(
            f"platform model for {model.platform!r} is already registered "
            f"(source {existing.evidence.source!r}); the later registration "
            f"is dropped (first wins)",
            PlatformModelWarning,
            stacklevel=2,
        )
        return
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


def models_in_scope(tool_owners: Mapping[str, str]) -> tuple[PlatformModel, ...]:
    """Registered models this server may render, in platform order.

    ``tool_owners`` maps a tool name to the name of the provider that
    contributed it. A model is in scope only when a tool starting with its
    ``tool_prefix`` is owned by the platform the model *names* — matching the
    prefix is not enough, or any plugin could annotate any other platform's
    tools by choosing a prefix. mureo's own built-in tools are not in the map
    at all, so nothing can be published under their platforms' names; mureo
    core registers no models, and a claim on ``google_ads_`` renders nothing.

    Scope is also decided from what this server actually serves, not from what
    is installed: a platform switched off by ``MUREO_DISABLE_*`` exposes no
    tools and so contributes nothing.
    """
    owned = tuple(tool_owners.items())
    return tuple(
        model
        for _, model in sorted(_MODELS.items())
        if any(
            owner == model.platform and name.startswith(model.tool_prefix)
            for name, owner in owned
        )
    )


def _fit(
    models: tuple[PlatformModel, ...], reserve: int
) -> tuple[list[str], list[str]]:
    """Greedily fit statement lines into the budget, ``reserve`` held back.

    Whole statements only: half a platform model is worse than none, because a
    truncated sentence still reads as a complete claim.
    """
    lines: list[str] = []
    dropped: list[str] = []
    used = len(_HEADING)
    for model in models:
        line = f"- {model.platform}: {model.statement}"
        # +1 for the newline that joins this line to the block.
        if used + 1 + len(line) + reserve > MAX_TOTAL_CHARS:
            dropped.append(model.platform)
            continue
        used += 1 + len(line)
        lines.append(line)
    return lines, dropped


def platform_model_instructions(tool_owners: Mapping[str, str]) -> str:
    """Render the always-on block for the platforms in scope, within budget.

    The returned string never exceeds :data:`MAX_TOTAL_CHARS` characters,
    counting the heading, the statement lines, the newlines joining them and
    the truncation notice. Returns ``""`` when nothing is in scope, which is
    what keeps a default install's ``InitializeResult`` byte-identical.
    """
    models = models_in_scope(tool_owners)
    if not models:
        return ""
    # First pass spends the whole budget on statements; only if something did
    # not fit is a notice needed, and only then does it cost anything. The
    # reserve is computed for the largest count the notice could ever carry,
    # so the second pass cannot overshoot.
    lines, dropped = _fit(models, reserve=0)
    note = ""
    if dropped:
        lines, dropped = _fit(models, reserve=1 + len(_omission_note(len(models))))
        note = _omission_note(len(dropped))
        logger.warning(
            "platform model block exceeds %d characters; omitted: %s",
            MAX_TOTAL_CHARS,
            ", ".join(dropped),
        )
    if not lines:
        return ""
    return "\n".join([_HEADING, *lines, *([note] if note else [])])


__all__ = [
    "MAX_STATEMENT_CHARS",
    "MAX_TOTAL_CHARS",
    "PlatformModel",
    "PlatformModelWarning",
    "models_in_scope",
    "platform_model",
    "platform_model_instructions",
    "register_platform_model",
    "registered_platform_models",
    "reset_platform_models",
]
