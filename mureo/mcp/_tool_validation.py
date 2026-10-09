"""Server-side enforcement of each tool's declared ``inputSchema``.

The MCP framework does not enforce ``inputSchema``, so declared bounds
(``minimum``, ``required``, ``type``, ``enum``) are advisory until something
checks them. :meth:`LazyToolValidators.validate_tool_input` is that check — the
single guard that makes them real for every mutation, most importantly the
real-spend boundary values (budget / bid ``minimum: 1``) flagged in #277. Plugin
tools are checked on the same path (guardrail parity, #114 follow-up), instead
of trusting the unverifiable assumption that every provider validates its own
inputs; a permissive plugin schema is simply a check that finds nothing to
reject.

Compiling the validators is deferred per tool (#807). ``Draft202012Validator``
construction really is microseconds — 1.6 ms for the whole 228-tool catalog.
What costs is ``check_schema``, which validates the schema against the Draft
2020-12 metaschema: **a median of 3.1 ms per tool (0.5 ms to 19 ms), 0.82 s
summed over the catalog.** (Both measured 2026-10-08 on one development machine,
CPython 3.10, no plugins installed: ``check_schema`` called directly on each of
the 228 schemas, ``time.process_time``, bytecode cache warm, min of 5 runs. Not
measured with ``cProfile``: tracing inflates a call this small by about an order
of magnitude, which is where an earlier estimate of "~25 ms per tool" came
from.)

Removing the eager platform imports was worth more than this deferral — about
1.4 to 1.6 times as much, not the 2 s an earlier version of this comment
implied by crediting both changes to one of them. Splitting the two is a
separate measurement from the 0.82 s above, taken on the whole server import
rather than on ``check_schema`` alone: the pre-#807 server imported as shipped
and with ``check_schema`` replaced by a no-op (same machine, min of 5, same
method, no plugins installed; two sittings hours apart on 2026-10-08, because
the absolute figures move a few percent with the machine's state and a single
column would read as more exact than it is):

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
enforced on, and a session pays only for the tools it uses.

A tool whose schema cannot be used is handled one of two ways, and the
difference is deliberate:

* **Not a valid JSON Schema** (``check_schema`` raises ``SchemaError``): the
  tool loses its input validation and is still served. This is pre-#807
  behaviour, unchanged; mureo's own schemas are metaschema-checked in CI, so
  in practice this reaches production only through a plugin. It is reported.
* **Anything else** — compiling raised something other than ``SchemaError`` (a
  ``RecursionError`` from a pathological ``$ref`` cycle, a ``jsonschema`` bug),
  or the schema raised while being *applied* (a ``$ref`` that resolves to
  nothing): every call that cannot be checked is **refused** with
  :class:`ToolSchemaUnusableError`, and the handler never runs. Before #807
  the first made the server fail to start and the second failed the call; a
  call is never served with declared bounds it could not check.

Both are reported to the log, and a plugin's also as a
:class:`~mureo.plugin_warnings.PluginToolWarning` — see
:meth:`LazyToolValidators._report`, which every report goes through.

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

    from jsonschema.exceptions import ValidationError
    from mcp.types import Tool

logger = logging.getLogger(__name__)

__all__ = ["LazyToolValidators", "ToolSchemaUnusableError"]

#: Longest problem description carried into a report. ``SchemaError`` renders the
#: offending schema and the metaschema branch it failed, which ran past 15 lines
#: in practice; folded to one line that is still over a kilobyte. A report is
#: read by a human looking for which tool to fix, so it is cut here, and the
#: whole schema is in the plugin's own source anyway.
_PROBLEM_CHAR_BUDGET: Final = 240

#: What a cut problem description ends with. ASCII, like the rest of a report.
_ELLIPSIS: Final = "..."


class ToolSchemaUnusableError(RuntimeError):
    """A tool's ``inputSchema`` cannot check this call, so the call is refused.

    Raised before the tool's handler runs, for a schema that failed to compile
    with something other than ``SchemaError`` or that failed while being applied
    to the call's arguments. Deliberately not a ``ValueError``: the dispatcher
    reads ``ValueError`` as "the caller sent bad arguments", and nothing a caller
    sends can fix this — the fault is in the schema. The original exception is
    chained as ``__cause__``; its type is not part of this one, so a
    ``jsonschema`` / ``referencing`` exception type does not leak to callers.
    """


class _NotCompiled:
    """Type of the "no attempt made yet" sentinel.

    A class of its own rather than ``Any``, so the cache's value type stays
    ``Draft202012Validator | None`` to the type-checker: a cached ``None`` means
    "tried, unusable" and must not be retried, which an ``Optional`` lookup
    alone cannot express.
    """


_NOT_COMPILED: Final = _NotCompiled()


def _one_line(exc: BaseException) -> str:
    """Render ``exc`` as a single truncated line fit for a report."""
    folded = " ".join(str(exc).split())
    if len(folded) <= _PROBLEM_CHAR_BUDGET:
        return folded
    return folded[: _PROBLEM_CHAR_BUDGET - len(_ELLIPSIS)] + _ELLIPSIS


def _render(problems: Sequence[tuple[str, str]]) -> str:
    """Render ``(tool, problem)`` pairs as one report line.

    ASCII only: this text reaches a log handler and a ``warnings`` hook, and
    both of those end up on whatever console the operator's MCP client gave the
    server, whose encoding is not ours to assume — on an ASCII stream one
    non-ASCII character costs the whole record, not just itself. A problem
    quotes the schema, which can be in any language, so anything outside ASCII
    is escaped rather than trusted to be absent.
    """
    if len(problems) == 1:
        name, problem = problems[0]
        text = f"tool {name}: {problem}"
    else:
        listed = "; ".join(f"{name}: {problem}" for name, problem in problems)
        text = f"{len(problems)} tools have an unusable inputSchema: {listed}"
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _first_error_path(error: ValidationError) -> list[Any]:
    return list(error.path)


class LazyToolValidators(Mapping[str, Draft202012Validator]):
    """Per-tool JSON Schema validators, compiled on first lookup.

    A read-only mapping, so ``name in validators`` / ``validators[name]`` /
    ``validators.get(name)`` read exactly as the eager ``dict`` did; each of
    those compiles the one tool asked for. A tool with no dict ``inputSchema``,
    or one whose schema cannot be compiled, is absent from the mapping — again
    as before. Absent is not the same as unchecked, though: the dispatcher goes
    through :meth:`validate_tool_input`, which refuses a call to a tool whose
    schema failed to compile for any reason other than ``SchemaError``. A name
    this catalog never had is absent and leaves no trace: the dispatcher
    validates before it rejects an unknown tool name, and those names come from
    the client, so caching them would let a caller grow this mapping without
    limit.

    ``plugin_names`` marks the tools mureo does not own. Their schemas are
    compiled eagerly by :meth:`compile_eagerly` at server start (there are
    normally a handful, and a plugin author gets no CI run of ours in which to
    find out otherwise), and a fault in one of them — at compile time or when a
    call applies it — is reported as a
    :class:`~mureo.plugin_warnings.PluginToolWarning` as well as logged, so the
    documented ``warnings.filterwarnings("error", ...)`` strict mode can turn it
    into an error. Built-in schemas are metaschema-checked in CI instead
    (``tests/test_mcp_strict_input_schemas.py``) and a bad one is logged.

    Thread safety: one lock for the whole mapping, held only while deciding one
    tool's outcome or bumping one counter. Two consequences worth naming. A
    pathological schema serialises the *first* lookup of every other tool for
    as long as its ``check_schema`` runs — acceptable because the alternative, a
    lock per name, buys nothing for a one-off cost. And reporting happens after
    the lock is released, so a ``logging`` handler or ``showwarning`` hook that
    reads this mapping cannot deadlock against it (the lock is not reentrant).
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
        # Tools whose schema failed to compile with something other than
        # SchemaError, and the exception it failed with: every call refused.
        self._refusals: dict[str, BaseException] = {}
        # Calls refused because the schema raised when applied, per tool. Keys
        # are catalog names only (an unknown name never reaches the apply step),
        # so this is bounded by the catalog.
        self._apply_failures: dict[str, int] = {}
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

    def _build(
        self, name: str
    ) -> tuple[Draft202012Validator | None, str | None, BaseException | None]:
        """Compile ``name``'s schema. Returns ``(validator, problem, refusal)``.

        Pure and total on purpose — it neither reports nor raises — so the
        caller can hold the lock across it and report afterwards. ``refusal`` is
        the exception that makes every call to this tool refused, if any.
        """
        schema = self._schemas[name]
        try:
            Draft202012Validator.check_schema(schema)
            return Draft202012Validator(schema), None, None
        except jsonschema.exceptions.SchemaError as exc:
            # Not a valid JSON Schema: the tool is served without input
            # validation, as before #807, and the fault is reported.
            problem = (
                f"inputSchema is not a valid JSON Schema, so its input is not "
                f"validated ({_one_line(exc)})"
            )
            return None, problem, None
        except Exception as exc:
            # Anything else (a RecursionError from a pathological ``$ref``
            # cycle, a jsonschema bug) used to stop the server from starting.
            # Compiling is lazy now, so the equivalent is that this one tool
            # cannot be called: cached as a refusal, so the compile is not
            # retried on every call, and every call is refused.
            problem = (
                f"inputSchema could not be compiled, so calls to it are refused "
                f"({type(exc).__name__}: {_one_line(exc)})"
            )
            # Keep the cause for chaining, not the ~1000 frames a
            # RecursionError's traceback would pin for the life of the process.
            return None, problem, exc.with_traceback(None)

    def _report(self, problems: Sequence[tuple[str, str]]) -> None:
        """Report unusable schemas to the log and, for a plugin's, to ``warnings``.

        A plugin's fault goes out as a warning as well, because that is the
        channel docs/plugin-authoring.md documents for plugin faults and the
        only one a strict deployment can promote to an error. It goes to the log
        **too**: this server's normal transport is stdio, where Python installs
        no handler for warnings that an operator reads, and a schema that cannot
        be used has cost a real-spend tool its validation or its availability —
        too loud a fact to leave on a channel that is off by default. The log
        record is emitted first, so strict mode (where ``warnings.warn`` raises)
        still leaves the operator the record.

        ``stacklevel=1`` attributes the warning to this module deliberately. The
        schema arrived as data, so no frame in the stack is the culprit, and the
        depth differs between the startup path and a tool call — a fixed depth
        would be wrong for one of them and would scatter ``warnings``' per-
        location dedup and ``filterwarnings(module=...)`` across both.
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
            validator, problem, refusal = self._build(name)
            # The refusal is written first: a caller that sees the cache entry
            # without taking the lock must also see the refusal.
            if refusal is not None:
                self._refusals[name] = refusal
            self._compiled[name] = validator
        return validator, problem

    def _compile(self, name: str) -> Draft202012Validator | None:
        """Return the validator for ``name``, or ``None`` if it has none."""
        validator, problem = self._compile_once(name)
        if problem is not None:
            # Theoretical gap: for a plugin tool under strict mode this raises
            # PluginToolWarning out of a lookup; compile_eagerly() at startup
            # reports every plugin tool first, so a call never gets here first.
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

    def validate_tool_input(self, name: str, arguments: dict[str, Any]) -> None:
        """Check ``arguments`` against tool ``name``'s declared ``inputSchema``.

        Runs before the tool handler, so an invalid budget/bid never reaches a
        real-spend API call. Applies to built-in and plugin tools alike.

        Raises:
            ValueError: the arguments violate the schema (the dispatcher's
                caller-error channel); the first violation by path is named.
            ToolSchemaUnusableError: the schema cannot check this call — it
                failed to compile with something other than ``SchemaError``,
                or it raised while being applied (``check_schema`` accepts a
                ``$ref``; resolving it is deferred to here, and a pointer into
                nothing raises ``referencing``'s ``Unresolvable``). The call is
                refused rather than served with bounds nobody checked.
            PluginToolWarning: under strict mode, on the first such refusal of
                a plugin's tool — the call is refused either way.

        A tool with no schema, or one that is not a valid JSON Schema
        (``SchemaError`` at compile time), is served unvalidated: see the
        module docstring for why those two cases differ.
        """
        validator = self.get(name)
        if validator is None:
            refusal = self._refusals.get(name)
            if refusal is not None:
                raise ToolSchemaUnusableError(
                    f"tool {name}: inputSchema could not be compiled "
                    f"({type(refusal).__name__}: {_one_line(refusal)}); "
                    f"the call is refused"
                ) from refusal
            return
        try:
            first = min(
                validator.iter_errors(arguments), key=_first_error_path, default=None
            )
        except Exception as exc:
            self._report_apply_failure(name, exc)
            raise ToolSchemaUnusableError(
                f"tool {name}: inputSchema could not be applied "
                f"({type(exc).__name__}: {_one_line(exc)}); the call is refused"
            ) from exc
        if first is None:
            return
        location = "/".join(str(p) for p in first.path) or "(root)"
        raise ValueError(
            f"Invalid arguments for {name}: at '{location}': {first.message}"
        )

    def _report_apply_failure(self, name: str, exc: Exception) -> None:
        """Report a schema that raised when applied: in full once, then quietly.

        The first refusal goes out like any other schema fault (log, and
        ``warnings`` for a plugin's). Later ones are a DEBUG record with a
        running count: the tool name comes from the client, so an agent
        retrying in a loop would otherwise write a full WARNING per attempt.
        Nothing is lost by that — every one of those calls is still refused.
        """
        with self._lock:
            count = self._apply_failures.get(name, 0) + 1
            self._apply_failures[name] = count
        if count == 1:
            problem = (
                f"inputSchema could not be applied, so calls it cannot check "
                f"are refused ({type(exc).__name__}: {_one_line(exc)})"
            )
            self._report([(name, problem)])
            return
        logger.debug(
            "tool %s: inputSchema could not be applied again; %d calls refused "
            "so far",
            name,
            count,
        )
