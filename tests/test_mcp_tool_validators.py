"""Deferring each tool's input-schema compilation must not weaken the guard.

The other half of the #807 startup fix: ``check_schema`` — validating a tool's
``inputSchema`` against the JSON Schema Draft 2020-12 metaschema — cost a median
of 3.1 ms per tool and 0.82 s summed over the 228-tool catalog at import, for
hundreds of tools a session never calls (measured 2026-10-08 on one machine,
CPython 3.10, ``time.process_time``, bytecode warm, min of 5; see
``mureo/mcp/_tool_validation.py``). :class:`mureo.mcp._tool_validation.LazyToolValidators`
moves that to each tool's first call, which is the call it is enforced on.

What that must not change is the guarantee itself, which is a real-spend one:
``inputSchema`` is advisory until something checks it, and the server-side check
is what makes ``minimum: 1`` on a budget or a bid real (#277), for plugin tools
as much as for built-in ones (#114 follow-up). So:

* :class:`TestLazyToolValidators` — a tool's validator is compiled on its first
  call and enforced on that same call; a plugin's is compiled at startup;
  nothing else compiles the catalog by accident.
* :class:`TestValidatorCompileFaults` — a schema that cannot be compiled is
  reported exactly once, on both channels for a plugin's, and never takes the
  rest of the catalog with it.

What an unusable schema does to the *call* (refused, or for a ``SchemaError``
served unvalidated) is in tests/test_mcp_tool_schema_refusal.py; the
import-cost guards are in tests/test_mcp_startup_budget.py.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import warnings
from contextlib import AbstractContextManager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from mureo.mcp import _tool_validation
from mureo.mcp._tool_validation import LazyToolValidators
from mureo.plugin_warnings import PluginToolWarning
from tests._measurement_child import install_fake_dist, run_in_fresh_interpreter

_UNKNOWN_NAME_PROBES = 5000

SERVER_MODULE = "mureo.mcp.server"

#: ``caplog`` sits on the root logger and sees every logger's records, so the
#: assertions below count this module's only.
_LOGGER_NAME = _tool_validation.logger.name

#: How long a test waits for a thread that should finish immediately. Generous,
#: because the point is to FAIL on a deadlock rather than hang the suite; the
#: threads are daemons and their liveness is asserted, so a regression is red
#: within this window instead of blocking the run. (A daemon left deadlocked can
#: still hang the interpreter's exit through a lock that ``atexit`` needs; see
#: ``test_reporting_does_not_hold_the_lock`` for the one place that applies.)
_THREAD_TIMEOUT_SECONDS = 30

# A plugin with one uncompilable ``inputSchema``, installed the way a real one
# is: an importable module plus a ``*.dist-info`` directory declaring the entry
# point. Nothing here is skipped or stubbed, so the strict-mode check below runs
# the sequence an operator would run.
_BAD_SCHEMA_PLUGIN = "plug_badschema"
_BAD_SCHEMA_TOOLS = ("plug_badschema_echo", "plug_badschema_ping")
_BAD_SCHEMA_PLUGIN_SOURCE = '''"""Throwaway provider with two uncompilable inputSchemas."""

from typing import Any

from mureo.core.providers.capabilities import Capability


class Provider:
    name = "plug_badschema"
    display_name = "plug_badschema"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})

    def mcp_tools(self):
        from mcp.types import Tool

        return (
            Tool(
                name="plug_badschema_echo",
                description="echo",
                inputSchema={"type": 1},
            ),
            Tool(
                name="plug_badschema_ping",
                description="ping",
                inputSchema={"required": "not-a-list"},
            ),
        )

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        from mcp.types import TextContent

        return [TextContent(type="text", text="")]
'''

# The documented strict mode, in the order an operator writes it: name the
# category, install the filter, import the server.
_STRICT_MODE_CODE = """
import warnings

from mureo.plugin_warnings import PluginToolWarning

{install_filter}
__import__({server!r})
print("started")
"""

_PLUGIN_COMPILE_STATE_CODE = """
import json

from mureo.mcp import server

validators = server._TOOL_VALIDATORS
print(
    json.dumps(
        {
            "compiled": sorted(validators._compiled),
            "plugin_owned": sorted(
                set(server._PLUGIN_NAMES) & set(validators._schemas)
            ),
            "total": len(validators._schemas),
        }
    )
)
"""


def _tool_with_schema(name: str, schema: object) -> SimpleNamespace:
    """A stand-in for ``mcp.types.Tool`` that accepts a deliberately bad schema."""
    return SimpleNamespace(name=name, inputSchema=schema)


def _own_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == _LOGGER_NAME]


def patch_check_schema(replacement: object) -> AbstractContextManager[object]:
    """Replace ``Draft202012Validator.check_schema`` for the duration."""
    return patch.object(Draft202012Validator, "check_schema", replacement)


class _ReentrantHandler(logging.Handler):
    """A log handler that looks a tool up from inside ``emit``.

    If reporting ever happens under the mapping's lock again, the worker thread
    deadlocks inside ``emit``. With a handler lock, it would be holding that
    too (``Handler.handle`` takes it around ``emit``), and ``logging.shutdown``
    at exit acquires every live handler's lock, so the interpreter hung after
    reporting the failure. So this handler has no lock, the way the stdlib's
    ``NullHandler`` has none: ``createLock`` leaves ``lock`` at ``None``, which
    leaves exit nothing to wait on, and ``_at_fork_reinit`` — which ``Handler``
    otherwise calls on ``lock`` unconditionally in a forked child — has nothing
    to reinitialise.
    """

    def __init__(self, validators: LazyToolValidators, seen: list[str]) -> None:
        super().__init__()
        self._validators = validators
        self._seen = seen

    def createLock(self) -> None:  # noqa: N802 - overrides logging.Handler
        self.lock = None

    def _at_fork_reinit(self) -> None:
        pass

    def emit(self, record: logging.LogRecord) -> None:
        self._seen.append(f"log:{self._validators.get('good') is not None}")


@pytest.fixture(scope="session")
def bad_schema_plugin_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    """An installed provider plugin whose two tools have unusable schemas."""
    from mureo.core.providers.registry import PROVIDERS_ENTRY_POINT_GROUP

    return install_fake_dist(
        tmp_path_factory.mktemp("bad_schema_plugin"),
        module=_BAD_SCHEMA_PLUGIN,
        source=_BAD_SCHEMA_PLUGIN_SOURCE,
        group=PROVIDERS_ENTRY_POINT_GROUP,
        target=f"{_BAD_SCHEMA_PLUGIN}:Provider",
    )


@pytest.mark.unit
class TestLazyToolValidators:
    """Compiling the input-schema validators is deferred, not dropped."""

    def test_only_plugin_schemas_are_compiled_at_import(self) -> None:
        """A built-in's validator waits for its first call; a plugin's does not.

        A plugin author never gets a run of mureo's CI, so a schema mureo does
        not own is checked while the server is starting, where the operator can
        still see it. There are normally a handful of those.
        """
        proc = run_in_fresh_interpreter(_PLUGIN_COMPILE_STATE_CODE)
        assert proc.returncode == 0, proc.stderr
        state = json.loads(proc.stdout.strip().splitlines()[-1])
        assert state["total"] > 0, state
        assert state["compiled"] == state["plugin_owned"], state

    def test_first_call_both_compiles_and_enforces(self) -> None:
        """The guard runs on the call that compiles it, not after it.

        Built with a fresh :class:`LazyToolValidators` and probed through
        ``_schemas``, because ``name in validators`` is itself a lookup —
        ``Mapping.__contains__`` goes through ``__getitem__`` — and would
        compile the tool before the assertion got to look.
        """
        from mureo.mcp.server import _ALL_TOOLS

        tool = "google_ads_budget_update"
        validators = LazyToolValidators(_ALL_TOOLS)
        if tool not in validators._schemas:
            pytest.skip("google_ads tools disabled in this environment")
        assert validators._compiled == {}

        with pytest.raises(ValueError):
            validators.validate_tool_input(
                tool,
                {"customer_id": "123", "budget_id": "1", "amount_micros": 0},
            )

        # Compiled BY that call, not before it and not after it.
        assert validators._compiled[tool] is not None

    def test_plugin_schemas_can_be_compiled_up_front(self) -> None:
        tool = _tool_with_schema("plug_echo", {"type": "object"})
        validators = LazyToolValidators([tool], plugin_names={"plug_echo"})
        assert validators._compiled == {}

        validators.compile_eagerly(["plug_echo", "not_a_tool"])

        assert validators._compiled["plug_echo"] is not None
        assert "not_a_tool" not in validators._compiled

    def test_unknown_tool_names_do_not_grow_the_cache(self) -> None:
        """A name the catalog never had leaves no entry behind.

        ``_gated_dispatch`` validates before ``_dispatch_tool`` rejects an
        unknown tool name, so the names reaching here come straight from the MCP
        client. Caching them let a caller add an entry per name for the life of
        the process; the eager ``dict.get`` wrote nothing.
        """
        validators = LazyToolValidators(
            [_tool_with_schema("known", {"type": "object"})]
        )

        for index in range(_UNKNOWN_NAME_PROBES):
            validators.validate_tool_input(f"no_such_tool_{index}", {})

        assert validators._compiled == {}
        assert validators.get("known") is not None

    def test_truthiness_compiles_nothing(self) -> None:
        """``if validators:`` must not compile the catalog.

        ``Mapping`` supplies no ``__bool__``, so Python falls back to
        ``__len__`` -> ``__iter__`` -> compile everything: one truthiness test
        would have paid the whole bill this class defers.
        """
        validators = LazyToolValidators(
            [
                _tool_with_schema("one", {"type": "object"}),
                _tool_with_schema("two", {"type": "object"}),
            ]
        )

        assert bool(validators) is True
        assert validators._compiled == {}
        assert bool(LazyToolValidators([])) is False

    def test_iterating_yields_the_usable_validators_and_compiles_all(self) -> None:
        """``__iter__`` / ``__len__`` are the Mapping half nothing else exercises.

        They are the one place this class deliberately pays the whole bill — a
        caller that iterates has asked for every tool — and they have to agree
        with ``__getitem__`` about which tools have a usable validator. A tool
        whose schema will not compile is absent from both, as it was from the
        eager ``dict``.
        """
        validators = LazyToolValidators(
            [
                _tool_with_schema("bad", {"type": 1}),
                _tool_with_schema("good", {"type": "object"}),
            ]
        )

        listed = set(validators)
        length = len(validators)

        assert listed == {"good"}
        assert length == 1
        # Iterating compiled every tool, including the one it did not yield.
        assert set(validators._compiled) == {"bad", "good"}
        assert validators._compiled["bad"] is None


@pytest.mark.unit
class TestValidatorCompileFaults:
    """An unusable schema costs that one tool its validation, and nothing else."""

    def test_a_malformed_schema_is_reported_once_under_concurrency(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two simultaneous first calls compile once, not twice.

        The eager dict could not report the same bad schema twice; a lazy one
        can, between the cache miss and the cache write, unless the compile is
        serialised. The threads are daemons and their liveness is asserted, so
        that a regression that deadlocks fails here instead of hanging the run.
        """
        validators = LazyToolValidators([_tool_with_schema("bad", {"type": 1})])
        barrier = threading.Barrier(2)
        calls: list[object] = []

        def slow_check(schema: object) -> None:
            calls.append(schema)
            time.sleep(0.05)  # widen the window a lock has to close
            raise SchemaError("1 is not valid under any of the given schemas")

        def worker() -> None:
            barrier.wait()
            validators.get("bad")

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            patch_check_schema(slow_check),
        ):
            threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=_THREAD_TIMEOUT_SECONDS)

        assert [t for t in threads if t.is_alive()] == [], (
            "a compile thread never finished: the lock around the compile " "deadlocked"
        )
        assert len(calls) == 1, f"compiled {len(calls)} times, expected once"
        records = _own_records(caplog)
        assert len(records) == 1, [r.getMessage() for r in records]
        assert "bad" not in validators

    def test_a_schema_that_fails_to_compile_is_not_retried(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-``SchemaError`` failure is cached, not retried on every lookup.

        Cached as "no validator" for the mapping and as a refusal for the
        dispatcher (tests/test_mcp_tool_schema_refusal.py): either way the
        compile runs once, and the fault is reported once.
        """
        validators = LazyToolValidators([_tool_with_schema("deep", {"type": "object"})])
        calls: list[object] = []

        def exploding_check(schema: object) -> None:
            calls.append(schema)
            raise RecursionError("maximum recursion depth exceeded")

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            patch_check_schema(exploding_check),
        ):
            first = validators.get("deep")
            second = validators.get("deep")

        assert (first, second) == (None, None)
        assert len(calls) == 1, f"recompiled {len(calls)} times"
        records = _own_records(caplog)
        assert len(records) == 1
        assert "RecursionError" in records[0].getMessage()

    def test_other_tools_keep_their_validation(self) -> None:
        validators = LazyToolValidators(
            [
                _tool_with_schema("bad", {"type": 1}),
                _tool_with_schema("good", {"type": "object", "required": ["who"]}),
            ]
        )

        assert "bad" not in validators
        with pytest.raises(ValueError, match="'who' is a required property"):
            validators.validate_tool_input("good", {})

    def test_a_plugins_bad_schema_reaches_both_channels(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A plugin's fault is warned AND logged; a built-in's is only logged.

        docs/plugin-authoring.md documents ``warnings`` as the channel for
        plugin faults, and it is the only one a strict deployment can promote to
        an error — but this server's transport is stdio, where nothing captures
        warnings by default, so a warning alone is a guardrail removed in
        silence. The log record is what an operator has. A built-in's goes to
        the log only: no plugin author can act on it, and CI
        (tests/test_mcp_strict_input_schemas.py) is where it is caught.
        """
        plugin_validators = LazyToolValidators(
            [_tool_with_schema("plug_bad", {"type": 1})], plugin_names={"plug_bad"}
        )
        builtin_validators = LazyToolValidators(
            [_tool_with_schema("builtin_bad", {"type": 1})]
        )

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            with pytest.warns(PluginToolWarning, match="plug_bad"):
                plugin_validators.get("plug_bad")
            logged_for_plugin = [r.getMessage() for r in _own_records(caplog)]

            caplog.clear()
            with warnings.catch_warnings(record=True) as recorded:
                warnings.simplefilter("always")
                builtin_validators.get("builtin_bad")
            logged_for_builtin = [r.getMessage() for r in _own_records(caplog)]

        assert len(logged_for_plugin) == 1, logged_for_plugin
        assert "plug_bad" in logged_for_plugin[0]
        assert len(logged_for_builtin) == 1, logged_for_builtin
        assert "builtin_bad" in logged_for_builtin[0]
        assert [w for w in recorded if issubclass(w.category, PluginToolWarning)] == []

    def test_every_bad_plugin_schema_is_reported_in_one_go(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """All of them, named, in one report, in a fixed order.

        Reporting them one at a time meant strict mode raised on the first and
        the operator never learned about the other two — and which one came
        first changed between runs, because ``_PLUGIN_NAMES`` is a frozenset.
        Three rounds of "fix it, start it, find the next one" for a fault that
        was known in full before the first word was printed.
        """
        names = ("plug_c", "plug_a", "plug_b")
        validators = LazyToolValidators(
            [_tool_with_schema(name, {"type": 1}) for name in names],
            plugin_names=set(names),
        )

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            pytest.warns(PluginToolWarning) as recorded,
        ):
            validators.compile_eagerly(set(names))

        assert len(recorded) == 1, [str(w.message) for w in recorded]
        message = str(recorded[0].message)
        assert message.startswith("3 tools have an unusable inputSchema"), message
        assert (
            message.index("plug_a") < message.index("plug_b") < message.index("plug_c")
        ), message
        records = _own_records(caplog)
        assert len(records) == 1, [r.getMessage() for r in records]

    def test_a_failed_compile_is_cached_even_when_the_report_raises(self) -> None:
        """Strict mode must not turn one bad schema into a per-call failure.

        The report is what strict mode raises from, so if it ran before the
        cache write the result was never cached: every call recompiled, failed
        again, and raised past the dispatcher. The cache write happens first.
        """
        validators = LazyToolValidators(
            [_tool_with_schema("plug_bad", {"type": 1})], plugin_names={"plug_bad"}
        )

        with warnings.catch_warnings():
            warnings.simplefilter("error", PluginToolWarning)
            with pytest.raises(PluginToolWarning):
                validators.get("plug_bad")

            assert validators._compiled == {"plug_bad": None}
            # Second call: cached, so nothing is reported and nothing raises.
            assert validators.get("plug_bad") is None

    def test_the_log_record_survives_strict_mode(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Promoting the warning to an error must not cost the operator the record.

        ``warnings.warn`` raises under ``filterwarnings("error")``, so the order
        of the two channels decides whether anything is left behind. The log
        record is emitted first.
        """
        validators = LazyToolValidators(
            [_tool_with_schema("plug_bad", {"type": 1})], plugin_names={"plug_bad"}
        )

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", PluginToolWarning)
            with pytest.raises(PluginToolWarning):
                validators.get("plug_bad")

        records = _own_records(caplog)
        assert len(records) == 1, [r.getMessage() for r in records]
        message = records[0].getMessage()
        assert message.startswith("tool plug_bad: inputSchema is not a valid")

    def test_reporting_does_not_hold_the_lock(self) -> None:
        """A report handler may read the mapping it is reporting about.

        ``logging`` handlers and ``showwarning`` hooks are arbitrary code, and
        reporting from inside the (non-reentrant) lock meant a hook that looked
        up any tool deadlocked the server during startup. Both channels are
        exercised — the log record goes out first, so a handler is the earlier
        chance to deadlock.

        A regression fails here after ``_THREAD_TIMEOUT_SECONDS`` and the run
        still exits: see :class:`_ReentrantHandler` for what used to hang it.
        """
        validators = LazyToolValidators(
            [_tool_with_schema("plug_bad", {"type": 1}), _tool_with_schema("good", {})],
            plugin_names={"plug_bad"},
        )
        reentered: list[str] = []
        finished = threading.Event()

        def hook(message: object, *args: object, **kwargs: object) -> None:
            reentered.append(f"warn:{validators.get('good') is not None}")

        def worker() -> None:
            validators.get("plug_bad")
            finished.set()

        logger = logging.getLogger(_LOGGER_NAME)
        handler = _ReentrantHandler(validators, reentered)
        logger.addHandler(handler)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.showwarning = hook  # type: ignore[assignment]
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                assert finished.wait(timeout=_THREAD_TIMEOUT_SECONDS), (
                    "reporting still holds the mapping's lock: a report handler "
                    "that reads the mapping deadlocked"
                )
                thread.join(timeout=_THREAD_TIMEOUT_SECONDS)
        finally:
            logger.removeHandler(handler)

        assert not thread.is_alive()
        assert reentered == ["log:True", "warn:True"]

    def test_reporting_an_apply_failure_does_not_hold_the_lock(self) -> None:
        """The same, for a schema that compiles and then raises when applied.

        That report has its own path (``_report_apply_failure``, which takes the
        lock to count the failure), so the compile-time test above does not
        cover it.
        """
        unresolvable = {"type": "object", "properties": {"b": {"$ref": "#/nowhere"}}}
        validators = LazyToolValidators(
            [
                _tool_with_schema("plug_reffy", unresolvable),
                _tool_with_schema("good", {}),
            ],
            plugin_names={"plug_reffy"},
        )
        reentered: list[str] = []
        finished = threading.Event()

        def hook(message: object, *args: object, **kwargs: object) -> None:
            reentered.append(f"warn:{validators.get('good') is not None}")

        def worker() -> None:
            with pytest.raises(_tool_validation.ToolSchemaUnusableError):
                validators.validate_tool_input("plug_reffy", {"b": 1})
            finished.set()

        logger = logging.getLogger(_LOGGER_NAME)
        handler = _ReentrantHandler(validators, reentered)
        logger.addHandler(handler)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.showwarning = hook  # type: ignore[assignment]
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                assert finished.wait(timeout=_THREAD_TIMEOUT_SECONDS), (
                    "reporting an apply failure still holds the mapping's lock: "
                    "a report handler that reads the mapping deadlocked"
                )
                thread.join(timeout=_THREAD_TIMEOUT_SECONDS)
        finally:
            logger.removeHandler(handler)

        assert not thread.is_alive()
        assert reentered == ["log:True", "warn:True"]

    @pytest.mark.slow
    @pytest.mark.usefixtures("only_when_asked_for")
    def test_a_plugins_bad_schema_can_be_made_fatal(
        self, bad_schema_plugin_path: str
    ) -> None:
        """The strict mode the docs promise, run the way the docs write it.

        In a child interpreter, because it is a property of the import order:
        name the category, install the filter, import the server. Asserting that
        the warning is *emitted* (which is all this test used to do) says
        nothing about whether a filter could ever see it — it could not, and the
        test passed anyway. In the ``slow`` lane because proving it takes two
        full server imports; what keeps the default lane honest is
        ``TestEagerPlatformImports.test_naming_the_warning_category_does_not_import_the_server``,
        which is the property the recipe depends on.
        """
        strict = run_in_fresh_interpreter(
            _STRICT_MODE_CODE.format(
                server=SERVER_MODULE,
                install_filter=(
                    'warnings.filterwarnings("error", category=PluginToolWarning)'
                ),
            ),
            extra_path=(bad_schema_plugin_path,),
        )
        permissive = run_in_fresh_interpreter(
            _STRICT_MODE_CODE.format(server=SERVER_MODULE, install_filter="pass"),
            extra_path=(bad_schema_plugin_path,),
        )

        assert permissive.returncode == 0, permissive.stderr
        assert "started" in permissive.stdout

        assert strict.returncode != 0, (
            f"strict mode did not fail the startup. stdout={strict.stdout!r} "
            f"stderr={strict.stderr[-2000:]!r}"
        )
        assert "PluginToolWarning" in strict.stderr
        assert "started" not in strict.stdout
        # Both faults in the one report, so the operator fixes both at once.
        for tool in _BAD_SCHEMA_TOOLS:
            assert tool in strict.stderr, strict.stderr[-2000:]
