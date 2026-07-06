"""Policy-gate extension point for mureo's MCP tool dispatch.

Constants exported:
- :data:`POLICY_GATES_ENTRY_POINT_GROUP` — the entry-point group name
  (``"mureo.policy_gates"``). Exposed for symmetry with the existing
  ``PROVIDERS_ENTRY_POINT_GROUP`` etc.



mureo OSS ships ONE built-in gate — :class:`mureo.policy.strategy_gate.StrategyPolicyGate`,
which enforces the operator's STRATEGY.md ``## Guardrails`` hard rules
(strategy enforcement is core mureo value). It is fail-open: with no
``## Guardrails`` section it abstains, so the default behaviour stays
byte-identical to "no enforcement". The dispatcher runs the built-in
gate(s) first (see :func:`mureo.mcp.server._builtin_policy_gates`), then
any gates registered by third-party packages via the ``mureo.policy_gates``
entry-point group.

This entry-point contract lets third-party packages (for example
``mureo-agency``, which builds a read-only mode for ad-platform
mutations) plug additional policy logic into mureo without forking the
dispatcher, on equal footing with the built-in gate. ``_load_policy_gates``
returns only the entry-point gates; the built-in gate is added separately
at evaluation time.

Stable ABI (1.x):
- :class:`PolicyGate` Protocol — the contract a third-party gate
  must satisfy.
- :class:`PolicyDecision` frozen dataclass — the return shape.
- ``mureo.policy_gates`` entry-point group — registration mechanism.

mureo MAY add fields to :class:`PolicyDecision` over time but MUST
NOT remove or rename existing ones. Third-party gates SHOULD
construct ``PolicyDecision`` with keyword arguments only.

Per-gate evaluation rules enforced by the dispatcher (in
:func:`mureo.mcp.server.handle_call_tool`):

- Every registered gate is evaluated on every tool call, in
  entry-point discovery order.
- If any gate returns ``allowed=False``, the tool call is refused
  and the gate's ``reason`` surfaces verbatim to the agent as a
  TextContent error.
- If a gate raises any ``Exception``, the dispatcher treats the
  gate as **abstain** (i.e. allow this gate; consult the next one)
  and logs a WARNING. A broken third-party gate MUST NOT take
  mureo offline. Subsequent gates are still consulted, so a deny
  from a later gate still blocks the call.

Implementations MUST be pure and fast — ``evaluate`` runs on every
tool call. Cache any expensive lookup (file reads, network calls)
behind a TTL inside the implementation itself; the dispatcher does
no caching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

#: The entry-point group name third-party packages register against.
#: Renaming this string is a breaking change — every plugin's
#: ``pyproject.toml`` would have to change. See
#: ``docs/ABI-stability.md`` §6.
POLICY_GATES_ENTRY_POINT_GROUP = "mureo.policy_gates"


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of a single :meth:`PolicyGate.evaluate` call.

    Attributes:
        allowed: ``True`` to let the call proceed (this gate
            abstains from blocking it); ``False`` to refuse.
        reason: Human-readable explanation surfaced to the agent
            verbatim when ``allowed`` is ``False``. Required to be
            meaningful when denying — an empty reason makes the
            refusal opaque to the operator-side LLM.
    """

    allowed: bool
    reason: str = ""


@runtime_checkable
class PolicyGate(Protocol):
    """Pre-dispatch policy hook for mureo's MCP tool surface.

    A third-party package registers an implementation via the
    ``mureo.policy_gates`` entry-point group::

        [project.entry-points."mureo.policy_gates"]
        read_only = "mureo_agency.policy:ReadOnlyGate"

    mureo's dispatcher consults all registered gates before
    dispatching each tool call. See the module docstring for the
    evaluation rules.

    **Lifecycle**: the dispatcher instantiates the gate class fresh
    on every dispatch (one ``cls()`` call per tool call). Instance
    attributes therefore do NOT persist across calls. If you need
    cross-call caching (e.g. a TTL'd re-read of
    ``~/.mureo/config.json``), put the cache on a class attribute
    or a module-level singleton — instance state is ephemeral.

    **Async**: the v1 contract is synchronous by design. A future
    Protocol for asynchronous gates may be added under a separate
    name; gates that need to await network I/O are out of scope for
    ``mureo.policy_gates`` in 0.9.x.

    **Evaluation order**: the order in which gates are consulted is
    *unspecified* — gates MUST NOT depend on each other or on a
    particular ordering. Any single deny blocks the call regardless
    of position.
    """

    def evaluate(self, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
        """Decide whether ``tool_name`` (called with ``arguments``)
        should be allowed.

        MUST return a :class:`PolicyDecision` instance. Returning any
        other type (``None``, ``True``, a tuple, etc.) is treated by
        the dispatcher as a buggy gate and the gate is **abstained
        with a WARNING** — the call proceeds as if the gate had
        returned ``PolicyDecision(allowed=True)``.

        MUST NOT have side effects beyond local caching. MUST NOT
        raise — if the gate cannot decide, return
        ``PolicyDecision(allowed=True)`` to abstain rather than
        raising, so the dispatcher does not log it as a broken gate.

        ``reason`` (when denying) is surfaced to the operator-side
        agent verbatim. Do NOT include credentials, account IDs, or
        anything else sensitive in ``reason``; the dispatcher itself
        deliberately does NOT echo the ``arguments`` dict in the
        refusal payload to avoid the same leak.
        """
        ...


__all__ = [
    "POLICY_GATES_ENTRY_POINT_GROUP",
    "PolicyDecision",
    "PolicyGate",
]
