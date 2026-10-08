"""The MCP server's import cost is a product contract, not an implementation
detail (#807).

An MCP client gives the server a fixed window to answer ``initialize``; Claude
Code's default is 30,000 ms and it is not negotiable from inside the server.
Every second of mureo's startup was ``import mureo.mcp.server`` — the server's
construction path is already free — so the only thing worth pinning is what that
import drags in.

Measured on the development machine (CPython 3.10, macOS) with
``time.process_time`` in a child interpreter, best of three runs, bytecode cache
warm — all load-independent, because this machine's load average is not:

============================================  ========  ========
measurement                                   before    after
============================================  ========  ========
CPU of ``import mureo.mcp.server``              3.48 s    1.11 s
``len(sys.modules)`` after that import           2249       880
the same, with one runtime-context factory       2259       890
``check_schema`` over the whole tool catalog   0.80-1.00  not run
============================================  ========  ========

The guards, in increasing order of how early they catch a regression:

* :class:`TestEagerPlatformImports` — no platform SDK may be imported at module
  scope. This is the sharp test: it fails deterministically the moment someone
  re-adds an eager ``from google.ads...`` on the schema path, regardless of how
  fast the machine is. It is measured as a DIFFERENCE between two child
  interpreters (one that loads only the installed provider plugins, one that
  imports the server), so it keeps working in an environment that has plugins
  installed — which is the environment #807 was reported from — instead of
  skipping there and going quietly silent. One case is set up rather than waited
  for: a ``mureo.runtime_context_factory`` plugin, which is what #807 was
  reported with and what left a second, unfixed route into the Google Ads SDK
  (2258 modules against this branch's 890). CI installs no plugins, so without
  it that route is only red on the machines that have one.
* :class:`TestLazyToolValidators` — a tool's input-schema validator is compiled
  on that tool's first call, and enforced on that same call; a plugin's is
  compiled at startup.
* :class:`TestValidatorCompileFaults` — an unusable schema disables validation
  for that one tool, exactly once, and never for the rest of the catalog.
* :class:`TestImportBudget` — a ceiling on the import's own CPU time, as a
  backstop for growth the module-name check cannot see (a new heavy dependency
  nobody listed).
* :class:`TestLazyPublicNames` — making the import lazy must not change what the
  package looks like from outside, and must not push the failure from import
  time to call time.

:class:`TestImportBudget` stays in the default lane rather than moving to the
``slow`` marker: the deterministic module-name check above is the primary guard
and this is only the backstop, so it is cheap to keep honest here.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import threading
import time
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from mureo.mcp._tool_validation import LazyToolValidators, validate_tool_input
from mureo.plugin_warnings import PluginToolWarning
from tests._measurement_child import measurement_child_env

_UNKNOWN_NAME_PROBES = 5000

SERVER_MODULE = "mureo.mcp.server"

# Ceiling for the CPU time of ``import mureo.mcp.server`` in a fresh
# interpreter, in seconds.
#
# CPU rather than wall clock, because wall clock made this test a load meter.
# On a loaded development machine the same import measured 6.96-9.43 s warm and
# 19.45 s cold against a 10 s wall-clock ceiling — 3 of 3 cold runs reached it —
# while its CPU time sat at 1.11-1.14 s with a spread of hundredths. The
# docstring claim that the ceiling "sits several times above" the cost was true
# of the cost and false of the clock it was compared against.
#
# This is a REGRESSION detector, not the target: the achieved cost is ~1.1 s and
# a CI runner's CPU is slower, so 6 s is five times the achieved figure and
# still well inside the client's 30 s connect budget. What it is for is growth
# the module-name check cannot name — a new dependency that costs more CPU than
# everything the server imports today. It is NOT what catches a return to the
# pre-#807 cost (3.48 s of CPU, which fits under any ceiling a slow runner
# tolerates): :class:`TestEagerPlatformImports` owns that, by name and without a
# clock. Override with MUREO_MCP_IMPORT_BUDGET_SECONDS (documented in
# CONTRIBUTING.md).
DEFAULT_IMPORT_BUDGET_SECONDS = 6.0
IMPORT_BUDGET_ENV = "MUREO_MCP_IMPORT_BUDGET_SECONDS"

# Module prefixes that must NOT be in sys.modules after importing the server.
# Each one is a platform SDK, a generated API surface, a transport/crypto stack
# only an API call needs, or one of mureo's own API clients — things only a
# handler actually serving a call can need, never the tool schemas. Before #807
# every one of these was loaded at import (941 modules for the generated Google
# Ads surface alone, 54 for ``cryptography``, 37 for ``google.protobuf``, 23 for
# ``grpc``); after it, none is. Naming the transitive stacks and not just
# ``google.ads.googleads`` is what catches a regression that arrives by some
# other route.
FORBIDDEN_EAGER_PREFIXES = (
    "cryptography",
    "facebook_business",
    "google.ads.googleads",
    "google.api_core",
    "google.auth",
    "google.oauth2",
    "google.protobuf",
    "googleapiclient",
    "grpc",
    "mureo.google_ads.client",
    "mureo.meta_ads.client",
    "proto",
)

# Package -> submodule the package must not import just because it was imported.
LAZY_PACKAGES = {
    "mureo.google_ads": "mureo.google_ads.client",
    "mureo.meta_ads": "mureo.meta_ads.client",
}

# Public name each lazy package re-exports from its client module, used to prove
# a ``mock.patch`` of that name does not survive the patch.
LAZY_CLIENT_EXPORTS = {
    "mureo.google_ads": "GoogleAdsApiClient",
    "mureo.meta_ads": "MetaAdsApiClient",
}

# What a provider plugin pulls in is the plugin's business, so its footprint is
# measured separately and subtracted. This child does exactly what
# ``collect_plugin_tools`` does to a third-party provider — load the entry
# point, instantiate it, ask for its tools — and nothing else, so anything in
# the server's footprint but not in this one is mureo's own doing.
_PLUGIN_FOOTPRINT_CODE = """
import sys
from importlib.metadata import entry_points

from mureo.core.providers.registry import PROVIDERS_ENTRY_POINT_GROUP

for ep in entry_points(group=PROVIDERS_ENTRY_POINT_GROUP):
    try:
        provider_class = ep.load()
        instance = provider_class()
        instance.mcp_tools()
    except KeyboardInterrupt:
        raise
    except BaseException:
        pass
print("\\n".join(sorted(sys.modules)))
"""

# A plugin with one uncompilable ``inputSchema``, installed the way a real one
# is: an importable module plus a ``*.dist-info`` directory declaring the entry
# point. Nothing here is skipped or stubbed, so the strict-mode check below runs
# the sequence an operator would run.
_BAD_SCHEMA_PLUGIN = "plug_badschema"
_BAD_SCHEMA_TOOL = "plug_badschema_echo"
_BAD_SCHEMA_PLUGIN_SOURCE = '''"""Throwaway provider with an uncompilable inputSchema."""

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
        )

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        from mcp.types import TextContent

        return [TextContent(type="text", text="")]
'''

# The documented strict mode, in the order an operator writes it: name the
# category, install the filter, import the server. The marker proves the first
# step did not already import the server — while the category lived under
# ``mureo.mcp``, importing it ran ``mureo/mcp/__init__.py``, which imports the
# server, and the warnings were over before the filter existed.
_SERVER_NOT_IMPORTED = "server-not-yet-imported"
_STRICT_MODE_CODE = """
import sys
import warnings

from mureo.plugin_warnings import PluginToolWarning

assert {server!r} not in sys.modules, "importing the category imported the server"
print({marker!r})
{install_filter}
__import__({server!r})
print("started")
"""


# A ``mureo.runtime_context_factory`` plugin, which is the configuration #807
# was reported from. Its factory imports the provider adapter packages, as an
# integrator's does; the server's import reaches it through
# ``collect_plugin_tools`` -> the Amazon bridge -> the manifest location ->
# ``get_runtime_context()``. Registered for one child interpreter only.
_FACTORY_MODULE = "startup_budget_probe_factory"
_FACTORY_SOURCE = '''"""Throwaway runtime-context factory for the #807 startup guard."""

from mureo.adapters.google_ads import GoogleAdsAdapter  # noqa: F401
from mureo.adapters.meta_ads import MetaAdsAdapter  # noqa: F401
from mureo.core.runtime_context import default_runtime_context


def make_context():
    return default_runtime_context()
'''


_SERVER_FOOTPRINT_CODE = f"""
import sys
__import__({SERVER_MODULE!r})
print("\\n".join(sorted(sys.modules)))
"""

# The import's own CPU time, measured inside the child so the parent's clock —
# and whatever else the machine is doing — never enters into it.
_IMPORT_CPU_CODE = f"""
import time
started = time.process_time()
__import__({SERVER_MODULE!r})
print(time.process_time() - started)
"""


def _import_budget_seconds() -> float:
    raw = os.environ.get(IMPORT_BUDGET_ENV)
    if raw is None:
        return DEFAULT_IMPORT_BUDGET_SECONDS
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover - operator typo
        raise ValueError(
            f"{IMPORT_BUDGET_ENV} must be a number of seconds, got {raw!r}"
        ) from exc


def _run_in_fresh_interpreter(
    code: str, *args: str, extra_path: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a child interpreter sharing this one's sys.path.

    ``extra_path`` goes in front of it, which is how a throwaway distribution
    gets "installed" for one child and for nothing else.
    """
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        env=measurement_child_env(extra_path),
        timeout=300,
    )


def _install_fake_dist(
    root: pathlib.Path, *, module: str, source: str, group: str, target: str
) -> str:
    """Write a module plus the ``*.dist-info`` that declares its entry point.

    Enough of an installation for ``importlib.metadata.entry_points`` to find
    it, with no pip and no effect on the environment the suite itself runs in:
    the returned directory is only ever put on a child's ``sys.path``.
    """
    (root / f"{module}.py").write_text(source, encoding="utf-8")
    dist = root / f"{module}-0.0.dist-info"
    dist.mkdir(exist_ok=True)
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {module.replace('_', '-')}\nVersion: 0.0\n",
        encoding="utf-8",
    )
    (dist / "entry_points.txt").write_text(
        f"[{group}]\n{module} = {target}\n", encoding="utf-8"
    )
    return str(root)


@pytest.fixture(scope="session")
def bad_schema_plugin_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    """An installed provider plugin whose one tool has an unusable schema."""
    from mureo.core.providers.registry import PROVIDERS_ENTRY_POINT_GROUP

    return _install_fake_dist(
        tmp_path_factory.mktemp("bad_schema_plugin"),
        module=_BAD_SCHEMA_PLUGIN,
        source=_BAD_SCHEMA_PLUGIN_SOURCE,
        group=PROVIDERS_ENTRY_POINT_GROUP,
        target=f"{_BAD_SCHEMA_PLUGIN}:Provider",
    )


def _loaded_modules(code: str, *, extra_path: tuple[str, ...] = ()) -> set[str]:
    proc = _run_in_fresh_interpreter(code, extra_path=extra_path)
    assert proc.returncode == 0, proc.stderr
    return set(proc.stdout.split())


def _forbidden(modules: set[str]) -> list[str]:
    return sorted(
        name
        for name in modules
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in FORBIDDEN_EAGER_PREFIXES
        )
    )


def _warn_if_plugins_excuse_forbidden(plugin_modules: set[str]) -> None:
    """Say out loud which forbidden modules the subtraction is about to excuse.

    The difference against the plugins' own footprint is what keeps this guard
    alive in an environment that has plugins, but it cuts both ways: a plugin
    that imports ``mureo.google_ads`` (plausible — it is how a provider talks to
    Google Ads) puts ``mureo.google_ads.client`` in BOTH footprints, and that
    prefix then cannot fail this test no matter what the server does. Failing
    would be wrong — what a plugin imports is the plugin's business — but going
    quiet would be worse, so the weakening is reported where a reader of the
    test output can see it.
    """
    excused = _forbidden(plugin_modules)
    if excused:
        warnings.warn(
            f"{len(excused)} forbidden modules are credited to installed "
            f"provider plugins and are therefore NOT checked against the "
            f"server's import: {excused[:10]}. Installed provider plugins: "
            f"{_installed_provider_plugins()}.",
            stacklevel=2,
        )


def _installed_provider_plugins() -> list[str]:
    """Names of third-party provider plugins installed in this environment."""
    from importlib.metadata import entry_points

    from mureo.core.providers.registry import PROVIDERS_ENTRY_POINT_GROUP

    return sorted(ep.name for ep in entry_points(group=PROVIDERS_ENTRY_POINT_GROUP))


def _tool_with_schema(name: str, schema: object) -> SimpleNamespace:
    """A stand-in for ``mcp.types.Tool`` that accepts a deliberately bad schema."""
    return SimpleNamespace(name=name, inputSchema=schema)


@pytest.mark.unit
class TestEagerPlatformImports:
    """No platform SDK is imported just to describe the tools."""

    @pytest.fixture(scope="session")
    def runtime_context_factory_path(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> str:
        """An installed ``mureo.runtime_context_factory`` plugin, for one child."""
        from mureo.core.runtime_context import (
            RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
        )

        return _install_fake_dist(
            tmp_path_factory.mktemp("runtime_context_factory"),
            module=_FACTORY_MODULE,
            source=_FACTORY_SOURCE,
            group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
            target=f"{_FACTORY_MODULE}:make_context",
        )

    def _assert_no_platform_sdk(self, extra_path: tuple[str, ...] = ()) -> set[str]:
        """Compare the server's import footprint with the plugins' own.

        Returns the server's share, so a caller can assert something further
        about it.
        """
        plugin_modules = _loaded_modules(_PLUGIN_FOOTPRINT_CODE, extra_path=extra_path)
        server_modules = _loaded_modules(_SERVER_FOOTPRINT_CODE, extra_path=extra_path)
        _warn_if_plugins_excuse_forbidden(plugin_modules)
        mureos_own = server_modules - plugin_modules

        # The subtraction must not be able to empty the measurement out. If a
        # plugin ever imports the server itself, every mureo module becomes
        # "the plugin's" and this guard would pass by saying nothing.
        assert SERVER_MODULE in mureos_own, (
            f"the plugin footprint already contains {SERVER_MODULE}, so "
            f"subtracting it leaves nothing of mureo's to check. Installed "
            f"provider plugins: {_installed_provider_plugins()}"
        )

        offenders = _forbidden(mureos_own)
        assert offenders == [], (
            f"importing {SERVER_MODULE} eagerly loaded platform SDK modules: "
            f"{offenders}. Move the import into the function that uses it. "
            f"(Modules credited to installed provider plugins and therefore "
            f"not counted: {sorted(_forbidden(plugin_modules))})"
        )
        return mureos_own

    def test_server_import_pulls_no_platform_sdk(self) -> None:
        self._assert_no_platform_sdk()

    def test_a_runtime_context_factory_plugin_pulls_no_platform_sdk(
        self, runtime_context_factory_path: str
    ) -> None:
        """The configuration #807 was reported from, set up on purpose.

        One registered factory is enough to make the server's import load every
        platform SDK again, by a route the first round of this fix did not
        touch: the Amazon bridge resolves its manifest location in its
        constructor, which asks for the runtime context, which runs the
        factory, which imports the adapters, which imported their clients. CI
        installs no plugins, so that route was green here and red only for a
        developer who had one.
        """
        mureos_own = self._assert_no_platform_sdk(
            extra_path=(runtime_context_factory_path,)
        )

        # Not a vacuous pass: the factory has to have run for this to mean
        # anything, and it runs during the import, not after it.
        assert _FACTORY_MODULE in mureos_own, (
            f"the registered {_FACTORY_MODULE} factory never ran during the "
            f"server's import, so this test proved nothing"
        )

    @pytest.mark.parametrize(
        "package,client_module",
        sorted(LAZY_PACKAGES.items()),
        ids=sorted(LAZY_PACKAGES),
    )
    def test_platform_package_does_not_import_its_client(
        self, package: str, client_module: str
    ) -> None:
        """Importing the package does not drag in its API client."""
        proc = _run_in_fresh_interpreter(
            f"import sys\n__import__({package!r})\nprint({client_module!r} in sys.modules)\n"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", proc.stdout

    def test_gaql_validator_does_not_import_the_google_ads_client(self) -> None:
        """The stdlib-only helper the tool schemas need stays stdlib-only.

        ``mureo.mcp._period_param`` builds the ``period`` enum from
        ``mureo.google_ads._gaql_validator``; that is the import that used to pay
        for the whole generated protobuf tree.
        """
        proc = _run_in_fresh_interpreter(
            "import sys\n"
            "import mureo.google_ads._gaql_validator  # noqa: F401\n"
            "print('mureo.google_ads.client' in sys.modules)\n"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", proc.stdout


@pytest.mark.unit
class TestImportBudget:
    """CPU backstop on the server's import cost."""

    def test_server_imports_within_cpu_budget(self) -> None:
        """Measured by the child, in CPU seconds, not by the parent's clock.

        The import is CPU-bound, and a busy machine or a shared CI runner can
        multiply the wall time of exactly the same work by five. Timing it from
        here measured the machine; ``time.process_time`` in the child measures
        the import.
        """
        budget = _import_budget_seconds()
        proc = _run_in_fresh_interpreter(_IMPORT_CPU_CODE)
        assert proc.returncode == 0, proc.stderr
        cpu = float(proc.stdout.strip().splitlines()[-1])
        assert cpu < budget, (
            f"import {SERVER_MODULE} spent {cpu:.2f}s of CPU, over the "
            f"{budget:.2f}s budget. Run "
            f"`python -X importtime -c 'import {SERVER_MODULE}'` and look at "
            f"what was added. Raise {IMPORT_BUDGET_ENV} only for a slow "
            f"machine, never to accept a regression."
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
        proc = _run_in_fresh_interpreter(
            "import json\n"
            "from mureo.mcp import server\n"
            "validators = server._TOOL_VALIDATORS\n"
            "print(json.dumps({\n"
            "    'compiled': sorted(validators._compiled),\n"
            "    'plugin_owned': sorted(\n"
            "        set(server._PLUGIN_NAMES) & set(validators._schemas)\n"
            "    ),\n"
            "    'total': len(validators._schemas),\n"
            "}))\n"
        )
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
            validate_tool_input(
                validators,
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
            validate_tool_input(validators, f"no_such_tool_{index}", {})

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


@pytest.mark.unit
class TestValidatorCompileFaults:
    """An unusable schema costs that one tool its validation, and nothing else."""

    def test_a_malformed_schema_is_reported_once_under_concurrency(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two simultaneous first calls compile once, not twice.

        The eager dict could not report the same bad schema twice; a lazy one
        can, between the cache miss and the cache write, unless the compile is
        serialised.
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
            caplog.at_level(logging.WARNING, logger="mureo.mcp._tool_validation"),
            patch.object(Draft202012Validator, "check_schema", slow_check),
        ):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        assert len(calls) == 1, f"compiled {len(calls)} times, expected once"
        assert len(caplog.records) == 1, [r.getMessage() for r in caplog.records]
        assert "bad" not in validators

    def test_a_schema_that_fails_to_compile_is_not_retried(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-``SchemaError`` failure is cached as "no validator", not retried.

        Before, only ``SchemaError`` reached the cache write, so a
        ``RecursionError`` from a pathological schema meant every call to that
        tool recompiled, failed again, and raised something the dispatcher's
        ``ValueError`` channel does not classify.
        """
        validators = LazyToolValidators([_tool_with_schema("deep", {"type": "object"})])
        calls: list[object] = []

        def exploding_check(schema: object) -> None:
            calls.append(schema)
            raise RecursionError("maximum recursion depth exceeded")

        with (
            caplog.at_level(logging.WARNING, logger="mureo.mcp._tool_validation"),
            patch.object(Draft202012Validator, "check_schema", exploding_check),
        ):
            first = validators.get("deep")
            second = validators.get("deep")

        assert (first, second) == (None, None)
        assert len(calls) == 1, f"recompiled {len(calls)} times"
        assert len(caplog.records) == 1
        assert "RecursionError" in caplog.records[0].getMessage()

    def test_other_tools_keep_their_validation(self) -> None:
        validators = LazyToolValidators(
            [
                _tool_with_schema("bad", {"type": 1}),
                _tool_with_schema("good", {"type": "object", "required": ["who"]}),
            ]
        )

        assert "bad" not in validators
        with pytest.raises(ValueError, match="'who' is a required property"):
            validate_tool_input(validators, "good", {})

    def test_a_plugins_bad_schema_warns_and_a_builtins_does_not(self) -> None:
        """A plugin's fault is the plugin author's; a built-in's is ours.

        docs/plugin-authoring.md documents ``warnings`` as the channel for
        plugin faults, so a plugin's uncompilable schema goes there. A
        built-in's goes to the log instead: no plugin author can act on it, it
        is caught by tests/test_mcp_strict_input_schemas.py in CI, and a stdio
        MCP client shows an operator one copy of stderr at best.
        """
        plugin_validators = LazyToolValidators(
            [_tool_with_schema("plug_bad", {"type": 1})], plugin_names={"plug_bad"}
        )
        builtin_validators = LazyToolValidators(
            [_tool_with_schema("builtin_bad", {"type": 1})]
        )

        with pytest.warns(PluginToolWarning, match="plug_bad"):
            plugin_validators.get("plug_bad")

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            builtin_validators.get("builtin_bad")
        assert [w for w in recorded if issubclass(w.category, PluginToolWarning)] == []

    def test_a_failed_compile_is_cached_even_when_the_report_raises(self) -> None:
        """Strict mode must not turn one bad schema into a per-call failure.

        The report is what strict mode raises from, so if it ran before the
        cache write the result was never cached: every call recompiled, failed
        again, and raised past the dispatcher. The class docstring claimed the
        opposite. The cache write now happens first.
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

    def test_reporting_does_not_hold_the_lock(self) -> None:
        """A report handler may read the mapping it is reporting about.

        ``logging`` handlers and ``showwarning`` hooks are arbitrary code, and
        reporting from inside the (non-reentrant) lock meant a hook that looked
        up any tool deadlocked the server during startup. Run on a thread with a
        timeout so a regression fails instead of hanging the suite.
        """
        validators = LazyToolValidators(
            [
                _tool_with_schema("plug_bad", {"type": 1}),
                _tool_with_schema("good", {"type": "object"}),
            ],
            plugin_names={"plug_bad"},
        )
        reentered: list[bool] = []
        finished = threading.Event()

        def hook(message: object, *args: object, **kwargs: object) -> None:
            reentered.append(validators.get("good") is not None)

        def worker() -> None:
            validators.get("plug_bad")
            finished.set()

        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.showwarning = hook  # type: ignore[assignment]
            threading.Thread(target=worker, daemon=True).start()
            assert finished.wait(timeout=30), (
                "reporting still holds the mapping's lock: a showwarning hook "
                "that reads the mapping deadlocked"
            )

        assert reentered == [True]

    def test_a_plugins_bad_schema_can_be_made_fatal(
        self, bad_schema_plugin_path: str
    ) -> None:
        """The strict mode the docs promise, run the way the docs write it.

        In a child interpreter, because it is a property of the import order:
        name the category, install the filter, import the server. Asserting that
        the warning is *emitted* (which is all this test used to do) says
        nothing about whether a filter could ever see it — it could not, and the
        test passed anyway.
        """
        strict = _run_in_fresh_interpreter(
            _STRICT_MODE_CODE.format(
                server=SERVER_MODULE,
                marker=_SERVER_NOT_IMPORTED,
                install_filter=(
                    'warnings.filterwarnings("error", category=PluginToolWarning)'
                ),
            ),
            extra_path=(bad_schema_plugin_path,),
        )
        permissive = _run_in_fresh_interpreter(
            _STRICT_MODE_CODE.format(
                server=SERVER_MODULE,
                marker=_SERVER_NOT_IMPORTED,
                install_filter="pass",
            ),
            extra_path=(bad_schema_plugin_path,),
        )

        assert _SERVER_NOT_IMPORTED in permissive.stdout, permissive.stderr
        assert permissive.returncode == 0, permissive.stderr
        assert "started" in permissive.stdout

        assert strict.returncode != 0, (
            f"strict mode did not fail the startup. stdout={strict.stdout!r} "
            f"stderr={strict.stderr[-2000:]!r}"
        )
        assert "PluginToolWarning" in strict.stderr
        assert _BAD_SCHEMA_TOOL in strict.stderr
        assert "started" not in strict.stdout


@pytest.mark.unit
class TestLazyPublicNames:
    """Laziness is invisible from the outside."""

    def test_google_ads_public_names_import_as_before(self) -> None:
        from mureo.google_ads import (
            GoogleAdsAccountListError,
            GoogleAdsApiClient,
            list_accessible_accounts,
        )

        assert isinstance(GoogleAdsApiClient, type)
        assert issubclass(GoogleAdsAccountListError, Exception)
        assert callable(list_accessible_accounts)

    def test_meta_ads_public_names_import_as_before(self) -> None:
        from mureo.meta_ads import (
            META_GRAPH_API_VERSION,
            MetaAdAccountList,
            MetaAdsApiClient,
            list_meta_ad_accounts,
            map_ad,
            map_ad_set,
            map_campaign,
            map_insights,
        )

        assert isinstance(META_GRAPH_API_VERSION, str)
        assert isinstance(MetaAdsApiClient, type)
        assert isinstance(MetaAdAccountList, type)
        for fn in (map_ad, map_ad_set, map_campaign, map_insights):
            assert callable(fn)
        assert callable(list_meta_ad_accounts)

    @pytest.mark.parametrize(
        "package", sorted(LAZY_PACKAGES), ids=sorted(LAZY_PACKAGES)
    )
    def test_attribute_access_and_dir_cover_all(self, package: str) -> None:
        module = __import__(package, fromlist=["__all__"])

        assert set(module.__all__) <= set(dir(module))
        for name in module.__all__:
            assert getattr(module, name) is not None

    @pytest.mark.parametrize(
        "package", sorted(LAZY_PACKAGES), ids=sorted(LAZY_PACKAGES)
    )
    def test_submodules_are_reachable_as_attributes(self, package: str) -> None:
        """``import pkg`` then ``pkg.submodule`` still resolves, and ``dir`` lists it.

        The eager package got this for free: importing it imported the client,
        which imported everything else, and each import installed the submodule
        as an attribute of the package. A lazy package has to do it on purpose.
        Run in a child interpreter because by now this one has imported those
        submodules for other reasons.
        """
        proc = _run_in_fresh_interpreter(
            "import json, pathlib, sys\n"
            "pkg = __import__(sys.argv[1], fromlist=['__path__'])\n"
            "stems = sorted(\n"
            "    p.stem\n"
            "    for p in pathlib.Path(pkg.__path__[0]).glob('*.py')\n"
            "    if p.name != '__init__.py'\n"
            ")\n"
            "missing = [s for s in stems if not hasattr(pkg, s)]\n"
            "undirred = [s for s in stems if s not in dir(pkg)]\n"
            "print(json.dumps({'stems': len(stems), 'missing': missing,"
            " 'undirred': undirred}))\n",
            package,
        )
        assert proc.returncode == 0, proc.stderr
        state = json.loads(proc.stdout.strip().splitlines()[-1])
        assert state["stems"] > 0, state
        assert state["missing"] == [], state
        assert state["undirred"] == [], state

    @pytest.mark.parametrize(
        "package", sorted(LAZY_PACKAGES), ids=sorted(LAZY_PACKAGES)
    )
    def test_unknown_attribute_still_raises_attribute_error(self, package: str) -> None:
        module = __import__(package, fromlist=["__all__"])
        unknown = "no_such_name"

        with pytest.raises(AttributeError):
            getattr(module, unknown)

    @pytest.mark.parametrize(
        "package", sorted(LAZY_CLIENT_EXPORTS), ids=sorted(LAZY_CLIENT_EXPORTS)
    )
    def test_patching_the_client_leaves_no_dead_mock(self, package: str) -> None:
        """A patch of the defining module is over when the ``with`` block is.

        Caching the resolved name into the package's ``globals()`` would make
        ``package.Name`` keep the mock for the rest of the process, because
        ``patch`` restores the module it patched and knows nothing about the
        package's copy. Order-dependent test pollution, waiting for the first
        test that patches this name.
        """
        name = LAZY_CLIENT_EXPORTS[package]
        pkg = __import__(package, fromlist=[name])
        client_module = __import__(f"{package}.client", fromlist=[name])
        real = getattr(client_module, name)

        with patch.object(client_module, name, new="SENTINEL"):
            assert getattr(pkg, name) == "SENTINEL"

        assert getattr(pkg, name) is real
        assert getattr(client_module, name) is real

    async def test_a_tool_still_runs_with_the_client_mocked(self) -> None:
        """A deferred import must fail at neither import nor call time.

        Exercises the dispatch path end to end — tool name through the lazily
        resolved handler table to a mocked client — so a lazy import that merely
        moved the breakage from startup to the first tool call is caught here.
        """
        from mureo.mcp import _handlers_google_ads as handlers
        from mureo.mcp import tools_google_ads

        client = AsyncMock()
        client.list_campaigns.return_value = [{"id": "1", "name": "Test"}]
        with (
            patch.object(
                handlers, "load_google_ads_credentials", return_value=MagicMock()
            ),
            patch.object(handlers, "create_google_ads_client", return_value=client),
            patch.object(
                handlers, "runtime_google_ads_customer_ids", return_value=None
            ),
        ):
            result = await tools_google_ads.handle_tool(
                "google_ads_campaigns_list", {"customer_id": "123"}
            )

        client.list_campaigns.assert_awaited_once()
        assert json.loads(result[0].text)[0]["id"] == "1"
