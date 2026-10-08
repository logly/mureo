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
construction really is microseconds — 1.6 ms for the whole 228-tool catalog.
What costs is ``check_schema``, which validates the schema against the Draft
2020-12 metaschema: **a median of 3.1 ms per tool (0.5 ms to 19 ms), 0.82 s for
the catalog.** (One machine, CPython 3.10, no plugins installed,
``time.process_time``, bytecode cache warm, min of 5 runs. Not measured with
``cProfile``: tracing inflates a call this small by about an order of magnitude,
which is where an earlier estimate of "~25 ms per tool" came from.)

Removing the eager platform imports was worth more than this deferral — about
1.4 to 1.6 times as much, not the 2 s an earlier version of this comment
implied by crediting both changes to one of them. Splitting the two on the same
clock, by importing the pre-#807 server with ``check_schema`` replaced by a
no-op (min of 5, same method, no plugins installed; two sittings on the same
machine, hours apart, because the absolute figures move a few percent with the
machine's state and a single column would read as more exact than it is):

    pre-#807 import, as shipped              3.07 s   2.97 s
    pre-#807 import, check_schema no-op      2.26 s   2.11 s  -> check_schema
                                                                 0.8-0.9 s
    this branch (both changes)               0.95 s   0.90 s  -> SDK imports
                                                                 1.2-1.3 s

(``jsonschema`` is imported before the clock starts in all three, so the rows
differ only in the work being measured.) ``check_schema`` is the one remaining
term that grows with the catalog while the MCP client's connect budget (30 s in
Claude Code, not negotiable from inside the server) stays fixed. So a tool's
validator is compiled on that tool's first call, which is the call it is
enforced on, and a session pays only for the tools it uses. A tool is therefore
never dispatched with its declared bounds unchecked — unless its schema cannot
be compiled, or cannot be applied to the arguments at all, which is reported and
costs that one tool its validation (see :meth:`LazyToolValidators._report` and
:func:`validate_tool_input`).

Split out of ``server.py`` to keep that module's size down; the ``_ALL_TOOLS``
catalog arrives as an argument, so nothing here imports the server.
"""

from __future__ import annotations

import logging
import threading
import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

import jsonschema
from jsonschema import Draft202012Validator

from mureo.plugin_warnings import PluginToolWarning

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Sequence

    from mcp.types import Tool

logger = logging.getLogger(__name__)

__all__ = ["LazyToolValidators", "validate_tool_input"]

#: Longest problem description carried into a report. ``SchemaError`` renders the
#: offending schema and the metaschema branch it failed, which ran past 15 lines
#: in practice; folded to one line that is still over a kilobyte. A report is
#: read by a human looking for which tool to fix, so it is cut here, and the
#: whole schema is in the plugin's own source anyway.
_PROBLEM_CHAR_BUDGET: Final = 240


class _NotCompiled:
    """Type of the "no attempt made yet" sentinel.

    A class of its own rather than ``Any``, so the cache's value type stays
    ``Draft202012Validator | None`` to the type-checker: a cached ``None`` means
    "tried, unusable" and must not be retried, which an ``Optional`` lookup
    alone cannot express.
    """


_NOT_COMPILED: Final = _NotCompiled()


def _one_line(exc: Exception) -> str:
    """Render ``exc`` as a single truncated line fit for a warning."""
    folded = " ".join(str(exc).split())
    if len(folded) <= _PROBLEM_CHAR_BUDGET:
        return folded
    return folded[: _PROBLEM_CHAR_BUDGET - 1] + "…"


def _render(problems: Sequence[tuple[str, str]]) -> str:
    """Render ``(tool, problem)`` pairs as one report line.

    ASCII only: this text reaches a log handler and a ``warnings`` hook, and
    both of those end up on whatever console the operator's MCP client gave the
    server, whose encoding is not ours to assume.
    """
    if len(problems) == 1:
        name, problem = problems[0]
        return f"tool {name}: {problem}; input validation skipped for it"
    listed = "; ".join(f"{name}: {problem}" for name, problem in problems)
    return (
        f"{len(problems)} tools have an unusable inputSchema; input validation "
        f"is skipped for each of them: {listed}"
    )


class LazyToolValidators(Mapping[str, Draft202012Validator]):
    """Per-tool JSON Schema validators, compiled on first lookup.

    A read-only mapping, so ``name in validators`` / ``validators[name]`` /
    ``validators.get(name)`` read exactly as the eager ``dict`` did; each of
    those compiles the one tool asked for. A tool with no dict ``inputSchema``,
    or one whose schema cannot be compiled, is absent from the mapping — again
    as before. A name this catalog never had is absent and leaves no trace: the
    dispatcher validates before it rejects an unknown tool name, and those names
    come from the client, so caching them would let a caller grow this mapping
    without limit.

    ``plugin_names`` marks the tools mureo does not own. Their schemas are
    compiled eagerly by :meth:`compile_eagerly` at server start (there are
    normally a handful, and a plugin author gets no CI run of ours in which to
    find out otherwise), and a bad one among them is reported as a
    :class:`~mureo.plugin_warnings.PluginToolWarning`, so the documented
    ``warnings.filterwarnings("error", ...)`` strict mode can turn it into a
    startup failure. Built-in schemas are metaschema-checked in CI instead
    (``tests/test_mcp_strict_input_schemas.py``) and a bad one is logged.

    Thread safety: one lock for the whole mapping, held only while deciding one
    tool's outcome. Two consequences worth naming. A pathological schema
    serialises the *first* lookup of every other tool for as long as its
    ``check_schema`` runs — acceptable because the alternative, a lock per name,
    buys nothing for a one-off cost. And reporting happens after the lock is
    released, so a ``logging`` handler or ``showwarning`` hook that reads this
    mapping cannot deadlock against it (the lock is not reentrant).
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
        self._lock = threading.Lock()

    def compile_eagerly(self, names: Collection[str]) -> None:
        """Compile the validators for ``names`` now, reporting faults together.

        Every name is compiled before anything is reported, and all the faults
        go out in one report. Reporting as they were found meant strict mode
        (``filterwarnings("error", ...)``) raised on the first bad schema and the
        operator never learned about the rest — and which one that was changed
        between runs, because ``names`` arrives as a ``frozenset``. Sorted here
        for the same reason: the report has to read the same way twice.

        A name this catalog does not have is simply not compiled, and nothing is
        recorded for it.
        """
        problems = []
        for name in sorted(names):
            _, problem = self._compile_once(name)
            if problem is not None:
                problems.append((name, problem))
        if problems:
            self._report(problems)

    def _build(self, name: str) -> tuple[Draft202012Validator | None, str | None]:
        """Compile ``name``'s schema. Returns ``(validator, problem)``.

        Pure and total on purpose — it neither reports nor raises — so the
        caller can hold the lock across it and report afterwards.
        """
        schema = self._schemas[name]
        try:
            Draft202012Validator.check_schema(schema)
            return Draft202012Validator(schema), None
        except jsonschema.exceptions.SchemaError as exc:
            # A malformed schema must not take the whole server offline — skip
            # validation for that one tool and say so.
            return None, f"inputSchema is not a valid JSON Schema ({_one_line(exc)})"
        except Exception as exc:
            # Anything else (a RecursionError from a pathological ``$ref``
            # cycle, a jsonschema bug) is cached as "no validator" for the same
            # reason: one unusable schema must not fail every call to that
            # tool, and retrying the compile on every call would fail every
            # time while escaping the dispatcher's ValueError channel.
            return (
                None,
                f"inputSchema could not be compiled "
                f"({type(exc).__name__}: {_one_line(exc)})",
            )

    def _report(self, problems: Sequence[tuple[str, str]]) -> None:
        """Report unusable schemas, once each, to the log and to ``warnings``.

        A plugin's fault goes out as a warning as well, because that is the
        channel docs/plugin-authoring.md documents for plugin faults and the
        only one a strict deployment can promote to an error. It goes to the log
        **too**: this server's normal transport is stdio, where Python installs
        no handler for warnings that an operator reads, and a schema that cannot
        be compiled has cost a real-spend tool its input validation — too loud a
        fact to leave on a channel that is off by default. The log record is
        emitted first, so strict mode (where ``warnings.warn`` raises) still
        leaves the operator the record.

        ``stacklevel=1`` attributes the warning to this module deliberately. The
        schema arrived as data, so no frame in the stack is the culprit, and the
        depth differs between the startup path and a first tool call — a fixed
        depth would be wrong for one of them and would scatter ``warnings``'
        per-location dedup and ``filterwarnings(module=...)`` across both.
        """
        ours = [pair for pair in problems if pair[0] not in self._plugin_names]
        theirs = [pair for pair in problems if pair[0] in self._plugin_names]
        if ours:
            logger.warning("%s", _render(ours))
        if theirs:
            message = _render(theirs)
            logger.warning("%s", message)
            warnings.warn(message, PluginToolWarning, stacklevel=1)

    def _compile_once(
        self, name: str
    ) -> tuple[Draft202012Validator | None, str | None]:
        """Compile ``name`` if it has not been tried, without reporting.

        Returns ``(validator, problem)``, where ``problem`` is set only on the
        call that did the compiling — so a fault is reported once no matter how
        many callers raced for it, and the caller gets to choose when (see
        :meth:`compile_eagerly`).
        """
        if name not in self._schemas:
            return None, None
        cached = self._compiled.get(name, _NOT_COMPILED)
        if not isinstance(cached, _NotCompiled):
            return cached, None
        with self._lock:
            cached = self._compiled.get(name, _NOT_COMPILED)
            if not isinstance(cached, _NotCompiled):
                return cached, None
            validator, problem = self._build(name)
            self._compiled[name] = validator
        return validator, problem

    def _compile(self, name: str) -> Draft202012Validator | None:
        """Return the validator for ``name``, or ``None`` if it has none."""
        validator, problem = self._compile_once(name)
        if problem is not None:
            self._report([(name, problem)])
        return validator

    def __getitem__(self, name: str) -> Draft202012Validator:
        validator = self._compile(name)
        if validator is None:
            raise KeyError(name)
        return validator

    def __iter__(self) -> Iterator[str]:
        # Compiles the whole catalog — only reached by code that iterates or
        # takes ``len()``, which the dispatch path never does. A generator, so a
        # consumer that stops early (``any()``, ``next()``) pays for what it
        # read and not for the rest.
        for name in self._schemas:
            if self._compile(name) is not None:
                yield name

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __bool__(self) -> bool:
        """Whether any tool declares a schema, without compiling one.

        ``Mapping`` does not supply ``__bool__``, so Python would fall back to
        ``__len__`` — which iterates, which compiles all 228. One ``if
        validators:`` would have paid the whole bill this class exists to defer.
        """
        return bool(self._schemas)


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

    A schema can also fail when it is *applied* rather than when it is compiled:
    ``check_schema`` accepts a ``$ref``, and resolving it is deferred to
    ``iter_errors``, which then raises ``referencing``'s ``Unresolvable`` /
    ``PointerToNowhere`` for a pointer into nothing or a ``$ref`` to a URL.
    Those are not ``ValueError``, so they used to escape this function and leave
    the dispatcher classifying a schema fault as a server error. They get the
    same treatment as a schema that would not compile: the tool loses its
    validation, the fault is reported, the call proceeds. Reported on every such
    call, not once — each one is a call served without its declared bounds.
    """
    validator = validators.get(name)
    if validator is None:
        return
    try:
        errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    except Exception as exc:
        logger.warning(
            "tool %s: inputSchema could not be applied (%s: %s); input "
            "validation skipped for this call",
            name,
            type(exc).__name__,
            _one_line(exc),
        )
        return
    if not errors:
        return
    first = errors[0]
    location = "/".join(str(p) for p in first.path) or "(root)"
    raise ValueError(f"Invalid arguments for {name}: at '{location}': {first.message}")
