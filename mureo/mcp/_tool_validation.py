"""Server-side enforcement of each tool's declared ``inputSchema``.

The MCP framework does not enforce ``inputSchema``, so declared bounds
(``minimum``, ``required``, ``type``, ``enum``) are advisory until something
checks them. :func:`validate_tool_input` is that check — the single guard that
makes them real for every mutation, most importantly the real-spend boundary
values (budget / bid ``minimum: 1``) flagged in #277. Plugin tools are checked
on the same path (guardrail parity, #114 follow-up), instead of trusting the
unverifiable assumption that every provider validates its own inputs; a
permissive plugin schema is simply a check that finds nothing to reject.

Compiling the validators is deferred per tool (#807). ``Draft202012Validator``
construction really is microseconds — 6.6 us per schema, 1.5 ms for the whole
228-tool catalog. What costs is ``check_schema``, which validates the schema
against the Draft 2020-12 metaschema: **median 2.2 ms per tool, 0.73 s for the
catalog.** (Measured with ``time.process_time`` in a fresh child interpreter,
best of three runs, bytecode cache warm. Not with ``cProfile``: tracing inflates
a call this small by about an order of magnitude, which is where an earlier
estimate of "~25 ms per tool" came from.)

That is not the single largest startup cost — removing the eager platform
imports was worth more, 3.38 s of import CPU down to 1.14 s on the same clock.
It is the **dominant term in what remains**, and the only one that grows with
the catalog while the MCP client's connect budget (30 s in Claude Code, not
negotiable from inside the server) stays fixed. So a tool's validator is
compiled on that tool's first call, which is the call it is enforced on: no call
is ever served unvalidated, and a session pays only for the tools it uses.

Split out of ``server.py`` to keep that module's size down; the ``_ALL_TOOLS``
catalog arrives as an argument, so nothing here imports the server.
"""

from __future__ import annotations

import logging
import threading
import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import jsonschema
from jsonschema import Draft202012Validator

from mureo.mcp.tool_provider import PluginToolWarning

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Sequence

    from mcp.types import Tool

logger = logging.getLogger(__name__)

__all__ = ["LazyToolValidators", "validate_tool_input"]

# Sentinel for "not compiled yet", so a cached ``None`` (no usable schema) is
# not retried on every call.
_MISSING: Any = object()


class LazyToolValidators(Mapping[str, Draft202012Validator]):
    """Per-tool JSON Schema validators, compiled on first lookup.

    A read-only mapping, so ``name in validators`` / ``validators[name]`` /
    ``validators.get(name)`` read exactly as the eager ``dict`` did; each of
    those compiles the one tool asked for. A tool with no dict ``inputSchema``,
    or one whose schema cannot be compiled, is absent from the mapping — again
    as before.

    ``plugin_names`` marks the tools mureo does not own. Their schemas are
    compiled eagerly by :meth:`compile_eagerly` at server start (there are
    normally a handful, and a plugin author gets no CI run of ours in which to
    find out otherwise), and a bad one among them is reported through
    :class:`~mureo.mcp.tool_provider.PluginToolWarning` as well as the log, so
    the documented ``warnings.filterwarnings("error", ...)`` strict mode can
    turn it into a startup failure. Built-in schemas are metaschema-checked in
    CI instead (``tests/test_mcp_strict_input_schemas.py``).
    """

    def __init__(
        self, tools: Sequence[Tool], *, plugin_names: Collection[str] = ()
    ) -> None:
        self._schemas: dict[str, dict[str, Any]] = {
            tool.name: schema
            for tool in tools
            if isinstance(schema := getattr(tool, "inputSchema", None), dict)
        }
        self._plugin_names = frozenset(plugin_names)
        self._compiled: dict[str, Draft202012Validator | None] = {}
        # One lock for the whole mapping. Contended only on a tool's very
        # first lookup; without it two concurrent first calls to the same tool
        # both run ``check_schema`` and a malformed schema is reported twice,
        # which the eager dict could not do.
        self._lock = threading.Lock()

    def compile_eagerly(self, names: Collection[str]) -> None:
        """Compile the validators for ``names`` now, skipping unknown names."""
        for name in names:
            self._compile(name)

    def _build(self, name: str) -> Draft202012Validator | None:
        """Compile ``name``'s schema, or return ``None`` if it has none / is bad."""
        schema = self._schemas.get(name)
        if schema is None:
            return None
        try:
            Draft202012Validator.check_schema(schema)
            return Draft202012Validator(schema)
        except jsonschema.exceptions.SchemaError as exc:
            # A malformed schema must not take the whole server offline — skip
            # validation for that one tool and say so.
            self._report(
                name,
                f"inputSchema is not a valid JSON Schema ({exc})",
            )
        except Exception as exc:
            # Anything else (a RecursionError from a pathological ``$ref``
            # cycle, a jsonschema bug) is cached as "no validator" for the same
            # reason: one unusable schema must not fail every call to that
            # tool, and retrying the compile on every call would fail every
            # time while escaping the dispatcher's ValueError channel.
            self._report(
                name,
                f"inputSchema could not be compiled ({type(exc).__name__}: {exc})",
            )
        return None

    def _report(self, name: str, problem: str) -> None:
        """Log ``problem`` for ``name``, and warn as well if it is a plugin's."""
        message = f"tool {name}: {problem}; input validation skipped for it"
        logger.warning("%s", message)
        if name in self._plugin_names:
            warnings.warn(message, PluginToolWarning, stacklevel=4)

    def _compile(self, name: str) -> Draft202012Validator | None:
        """Return the validator for ``name``, or ``None`` if it has none."""
        cached = self._compiled.get(name, _MISSING)
        if cached is not _MISSING:
            return cached
        with self._lock:
            if name in self._compiled:
                return self._compiled[name]
            validator = self._build(name)
            self._compiled[name] = validator
            return validator

    def __getitem__(self, name: str) -> Draft202012Validator:
        validator = self._compile(name)
        if validator is None:
            raise KeyError(name)
        return validator

    def __iter__(self) -> Iterator[str]:
        # Materialises the whole catalog — only reached by code that iterates
        # or takes ``len()``, which the dispatch path never does.
        return iter([n for n in self._schemas if self._compile(n) is not None])

    def __len__(self) -> int:
        return sum(1 for _ in self)


def validate_tool_input(
    validators: Mapping[str, Draft202012Validator],
    name: str,
    arguments: dict[str, Any],
) -> None:
    """Validate ``arguments`` against the tool's declared ``inputSchema``.

    Raises ``ValueError`` (the dispatcher's standard caller-error channel)
    on the first violation, before the tool handler runs — so an invalid
    budget/bid never reaches a real-spend API call. Applies to both built-in
    and plugin tools. No-op for a tool without a usable validator (no schema,
    or a schema that fails to compile when this tool's first call compiles it).
    """
    validator = validators.get(name)
    if validator is None:
        return
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return
    first = errors[0]
    location = "/".join(str(p) for p in first.path) or "(root)"
    raise ValueError(f"Invalid arguments for {name}: at '{location}': {first.message}")
