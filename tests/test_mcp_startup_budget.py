"""The MCP server's import cost is a product contract, not an implementation
detail (#807).

An MCP client gives the server a fixed window to answer ``initialize``; Claude
Code's default is 30,000 ms and it is not negotiable from inside the server.
Every second of mureo's startup was ``import mureo.mcp.server`` — the server's
construction path is already free — so the only thing worth pinning is what that
import drags in.

Measured on one development machine (CPython 3.10, macOS, 228 built-in tools)
with ``time.process_time`` inside a child interpreter, min of 5 runs, bytecode
cache warm — CPU rather than wall clock, because this machine's load average
swings by an order of magnitude and the import's CPU time does not:

=================================================  ========  =======
configuration (CPU / ``len(sys.modules)``)         before     after
=================================================  ========  =======
no plugins installed                               3.1 s /    1.1 s /
                                                   2249       882
a ``runtime_context_factory`` plugin (#807's)      3.1 s /    1.2 s /
                                                   2259       892
a provider plugin that imports a platform client   3.2 s /    2.4 s /
at module scope                                    2250       2229
=================================================  ========  =======

The third row is not a shortfall in this fix: those 2229 modules are the
plugin's own import, and the server's share of them is zero (see
:class:`TestEagerPlatformImports`). docs/plugin-authoring.md tells a plugin
author how to stop paying it.

The guards, in increasing order of how early they catch a regression:

* :class:`TestEagerPlatformImports` — no platform SDK may be requested by
  mureo's own import path. This is the sharp test: it fails deterministically
  the moment someone re-adds an eager ``from google.ads...`` on the schema path,
  regardless of how fast the machine is, and it is an absolute judgement rather
  than a comparison, so it holds in an environment that has plugins installed —
  which is the environment #807 was reported from.
* :class:`TestImportBudget` — a ceiling on the import's own CPU time, as a
  backstop for growth the module-name check cannot see (a new heavy dependency
  nobody listed).
* :class:`TestLazyPublicNames` — making the import lazy must not change what the
  package looks like from outside, and must not push the failure from import
  time to call time.

Deferring the per-tool JSON Schema compilation is the other half of the fix;
its tests are in tests/test_mcp_tool_validators.py.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests._measurement_child import install_fake_dist, run_in_fresh_interpreter

SERVER_MODULE = "mureo.mcp.server"

# Ceiling for the CPU time of ``import mureo.mcp.server`` in a fresh
# interpreter, in seconds.
#
# CPU rather than wall clock, because wall clock made this test a load meter.
# On a loaded development machine the same import measured 6.96-9.43 s warm and
# 19.45 s cold against a 10 s wall-clock ceiling — 3 of 3 cold runs reached it —
# while its CPU time sat at 1.1-1.2 s with a spread of hundredths.
#
# This is a REGRESSION detector, not the target: the achieved cost is ~1.1 s and
# a CI runner's CPU is slower, so 6 s is five times the achieved figure and
# still well inside the client's 30 s connect budget. What it is for is growth
# the module-name check cannot name — a new dependency that costs more CPU than
# everything the server imports today. It is NOT what catches a return to the
# pre-#807 cost (3.1 s of CPU, which fits under any ceiling a slow runner
# tolerates): :class:`TestEagerPlatformImports` owns that, by name and without a
# clock. Override with MUREO_MCP_IMPORT_BUDGET_SECONDS (documented in
# CONTRIBUTING.md).
DEFAULT_IMPORT_BUDGET_SECONDS = 6.0
IMPORT_BUDGET_ENV = "MUREO_MCP_IMPORT_BUDGET_SECONDS"

# Module prefixes that mureo's own import path must not ask for. Each one is a
# platform SDK, a generated API surface, a transport/crypto stack only an API
# call needs, or one of mureo's own API clients — things only a handler actually
# serving a call can need, never the tool schemas. Before #807 every one of
# these was loaded at import (941 modules for the generated Google Ads surface
# alone, 54 for ``cryptography``, 37 for ``google.protobuf``, 23 for ``grpc``);
# after it, none is. Naming the transitive stacks and not just
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

# Modules that only ever pass a request on. ``mureo.google_ads`` /
# ``mureo.meta_ads`` resolve a name through ``__getattr__`` (PEP 562) and
# ``mureo._lazy_package`` is where that lives, so a frame belonging to one of
# them says nothing about WHO wanted the name — the frame behind it does. Not
# skipping them would blame mureo for a plugin's ``from mureo.google_ads import
# GoogleAdsApiClient``, which is the plugin's to make.
IMPORT_CONDUITS = ("mureo._lazy_package", "mureo.google_ads", "mureo.meta_ads")

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

# Who asked for a forbidden module, and whether that was mureo.
#
# The set-difference this used to be ("in the server's footprint but not in the
# plugins' own") is not a judgement that holds on its own: register one ordinary
# provider plugin that does ``from mureo.google_ads import GoogleAdsApiClient``
# at module scope and the difference is empty for 9 of the 12 prefixes below,
# which silently retires most of this guard in exactly the kind of installation
# #807 was reported from. So the question asked here is absolute instead: a
# ``sys.meta_path`` finder records, for each forbidden module, the stack that
# first asked for it, and NO forbidden module may be charged to mureo.
#
# Reading that stack has two rules, and between them they decide whose import it
# was:
#
# 1. Cut the stack at the OUTERMOST frame that belongs to a forbidden module.
#    Everything inside it is the SDK (or mureo's own client, and the mixins it
#    builds itself from) loading — those modules did not want the SDK, whoever
#    asked for the SDK did. Without this cut, a plugin's own
#    ``from mureo.google_ads import GoogleAdsApiClient`` reads as 928 forbidden
#    modules requested by ``mureo.google_ads.mappers``, i.e. as mureo's.
# 2. Of what is left, take the innermost frame that is not the import machinery
#    (``importlib*``, ``_frozen_importlib*``), not this probe (``__main__``) and
#    not one of the lazy packages' resolution hooks (IMPORT_CONDUITS). That
#    frame is the module that wanted the name. Not "is any frame third-party":
#    an integrator's factory importing ``mureo.adapters.google_ads`` must not
#    excuse the adapter for importing its client eagerly — that import is
#    mureo's, and it is the second of the two routes #807 arrived by.
#
# The one thing it cannot see: a module already in ``sys.modules``. If a plugin
# imports an SDK and mureo then asks for the same module, there is no second
# ``find_spec`` call to record. mureo's own module-scope imports all run before
# ``collect_plugin_tools()`` reaches a plugin, so the order works in the guard's
# favour, but it is not a proof.
_ATTRIBUTION_CODE = (
    (
        f"FORBIDDEN = {FORBIDDEN_EAGER_PREFIXES!r}\n"
        f"CONDUITS = {IMPORT_CONDUITS!r}\n"
        f"SERVER = {SERVER_MODULE!r}\n"
    )
    + """
import json
import sys

requests = {}


def is_forbidden(name):
    return any(
        name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN
    )


def is_passing_through(name):
    return (
        name == "__main__"
        or name == "importlib"
        or name.startswith("importlib.")
        or name.startswith("_frozen_importlib")
        or name in CONDUITS
    )


def stack_modules():
    names = []
    frame = sys._getframe(1)
    while frame is not None:
        names.append(frame.f_globals.get("__name__", "<unknown>"))
        frame = frame.f_back
    return names


def requesting_chain():
    names = stack_modules()
    inside_sdk = [i for i, name in enumerate(names) if is_forbidden(name)]
    if inside_sdk:
        names = names[max(inside_sdk) + 1 :]
    chain = []
    for name in names:
        if not is_passing_through(name) and (not chain or chain[-1] != name):
            chain.append(name)
    return chain


class Recorder:
    def find_spec(self, fullname, path=None, target=None):
        if is_forbidden(fullname) and fullname not in requests:
            requests[fullname] = requesting_chain()
        return None


sys.meta_path.insert(0, Recorder())
__import__(SERVER)
print(json.dumps({"requests": requests, "modules": len(sys.modules)}))
"""
)

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

# An ordinary provider plugin written the ordinary way: the platform client
# imported at module scope, which is what a provider needs to talk to the
# platform. It costs this process the whole SDK, and that cost is the plugin's,
# not the server's — the control below says so in both directions.
_SDK_PROVIDER_MODULE = "startup_budget_probe_provider"
_SDK_PROVIDER_SOURCE = '''"""Throwaway provider that imports its client at module scope."""

from typing import Any

from mureo.core.providers.capabilities import Capability
from mureo.google_ads import GoogleAdsApiClient  # noqa: F401


class Provider:
    name = "startup_budget_probe_provider"
    display_name = "startup_budget_probe_provider"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})

    def mcp_tools(self):
        from mcp.types import Tool

        return (
            Tool(
                name="startup_budget_probe_echo",
                description="echo",
                inputSchema={"type": "object"},
            ),
        )

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        from mcp.types import TextContent

        return [TextContent(type="text", text="")]
'''

# The import's own CPU time, measured inside the child so the parent's clock —
# and whatever else the machine is doing — never enters into it.
_IMPORT_CPU_CODE = f"""
import time
started = time.process_time()
__import__({SERVER_MODULE!r})
print(time.process_time() - started)
"""

# ``mureo.plugin_warnings`` exists so that a strict deployment can name the
# warning category BEFORE the plugin faults happen, which is impossible if
# naming it imports the server (docs/plugin-authoring.md).
_WARNING_CATEGORY_CODE = """
import json
import sys

from mureo.plugin_warnings import PluginToolWarning  # noqa: F401

print(json.dumps(sorted(m for m in sys.modules if m.startswith("mureo"))))
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


def _attribute_forbidden_requests(
    extra_path: tuple[str, ...] = (),
) -> dict[str, list[str]]:
    """Import the server in a child and return ``module -> requesting stack``."""
    proc = run_in_fresh_interpreter(_ATTRIBUTION_CODE, extra_path=extra_path)
    assert proc.returncode == 0, proc.stderr
    state = json.loads(proc.stdout.strip().splitlines()[-1])
    requests: dict[str, list[str]] = state["requests"]
    return requests


def _charged_to_mureo(requests: dict[str, list[str]]) -> dict[str, list[str]]:
    """The requests whose innermost non-pass-through frame is mureo's own."""
    return {
        module: chain
        for module, chain in requests.items()
        if chain and (chain[0] == "mureo" or chain[0].startswith("mureo."))
    }


def _assert_no_forbidden_request_is_mureos(requests: dict[str, list[str]]) -> None:
    offenders = _charged_to_mureo(requests)
    assert offenders == {}, (
        f"importing {SERVER_MODULE} asked for platform SDK modules on mureo's "
        f"own import path: "
        f"{ {module: chain[:4] for module, chain in offenders.items()} }. "
        f"Move the import into the function that uses it, or under "
        f"TYPE_CHECKING. (Charged elsewhere, which is allowed: "
        f"{ {m: c[:2] for m, c in requests.items() if m not in offenders} })"
    )


def _target_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
    return target.id if isinstance(target, ast.Name) else None


def _type_checking_reexports(node: ast.If) -> dict[str, str]:
    """``name -> module`` for the ``X as X`` imports in ``if TYPE_CHECKING:``."""
    if not (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"):
        return {}
    found: dict[str, str] = {}
    for statement in node.body:
        if not isinstance(statement, ast.ImportFrom) or statement.module is None:
            continue
        for alias in statement.names:
            assert alias.asname == alias.name, (
                f"{alias.name} is imported without the ``X as X`` re-export "
                f"form, so it is not part of the package's surface to mypy"
            )
            found[alias.name] = statement.module
    return found


def _lazy_package_source(package: str) -> ast.Module:
    spec = importlib.util.find_spec(package)
    assert spec is not None and spec.origin is not None, package
    path = pathlib.Path(spec.origin)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


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

        return install_fake_dist(
            tmp_path_factory.mktemp("runtime_context_factory"),
            module=_FACTORY_MODULE,
            source=_FACTORY_SOURCE,
            group=RUNTIME_CONTEXT_FACTORY_ENTRY_POINT_GROUP,
            target=f"{_FACTORY_MODULE}:make_context",
        )

    @pytest.fixture(scope="session")
    def sdk_importing_provider_path(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> str:
        """An installed provider plugin that imports a platform client eagerly."""
        from mureo.core.providers.registry import PROVIDERS_ENTRY_POINT_GROUP

        return install_fake_dist(
            tmp_path_factory.mktemp("sdk_importing_provider"),
            module=_SDK_PROVIDER_MODULE,
            source=_SDK_PROVIDER_SOURCE,
            group=PROVIDERS_ENTRY_POINT_GROUP,
            target=f"{_SDK_PROVIDER_MODULE}:Provider",
        )

    def test_server_import_asks_for_no_platform_sdk(self) -> None:
        _assert_no_forbidden_request_is_mureos(_attribute_forbidden_requests())

    def test_a_runtime_context_factory_plugin_pulls_no_platform_sdk(
        self, runtime_context_factory_path: str
    ) -> None:
        """The configuration #807 was reported from, set up on purpose.

        One registered factory was enough to make the server's import load every
        platform SDK again, by a route the first round of this fix did not
        touch: ``collect_plugin_tools`` builds the Amazon bridge, whose
        constructor asks for the runtime context, which runs the factory, which
        imports the adapters, which imported their clients. CI installs no
        plugins, so that route was green here and red only for a developer who
        had one.
        """
        requests = _attribute_forbidden_requests(
            extra_path=(runtime_context_factory_path,)
        )
        _assert_no_forbidden_request_is_mureos(requests)

    def test_the_factory_plugin_really_runs_during_the_import(
        self, runtime_context_factory_path: str
    ) -> None:
        """Not a vacuous pass: the factory has to have run for that to mean anything.

        It runs during the import, not after it, which is the whole reason the
        route above exists.
        """
        proc = run_in_fresh_interpreter(
            f"import sys\n__import__({SERVER_MODULE!r})\n"
            f"print({_FACTORY_MODULE!r} in sys.modules)\n",
            extra_path=(runtime_context_factory_path,),
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "True", proc.stdout

    def test_a_plugins_own_sdk_import_is_charged_to_the_plugin(
        self, sdk_importing_provider_path: str
    ) -> None:
        """The control for the guard above: it is not blind, and it is not unfair.

        With a provider plugin that imports a platform client at module scope,
        this process does load the SDK — 2229 modules against 882, and the
        import costs 2.4 s of CPU against 1.1 s. None of it is charged to mureo,
        because none of it was mureo's to ask for; the plugin's own module frame
        is what the recorder finds behind every one of those requests. That is
        also the half of the #807 fix a plugin author owns, and
        docs/plugin-authoring.md now says so.
        """
        requests = _attribute_forbidden_requests(
            extra_path=(sdk_importing_provider_path,)
        )

        assert requests, (
            "the plugin imports mureo.google_ads at module scope, so the "
            "recorder must have seen forbidden modules being requested; it saw "
            "none, which means it is not recording"
        )
        _assert_no_forbidden_request_is_mureos(requests)
        assert {chain[0] for chain in requests.values()} == {_SDK_PROVIDER_MODULE}, {
            module: chain[:4] for module, chain in requests.items()
        }

    @pytest.mark.parametrize(
        "package,client_module",
        sorted(LAZY_PACKAGES.items()),
        ids=sorted(LAZY_PACKAGES),
    )
    def test_platform_package_does_not_import_its_client(
        self, package: str, client_module: str
    ) -> None:
        """Importing the package does not drag in its API client."""
        proc = run_in_fresh_interpreter(
            f"import sys\n__import__({package!r})\n"
            f"print({client_module!r} in sys.modules)\n"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", proc.stdout

    def test_gaql_validator_does_not_import_the_google_ads_client(self) -> None:
        """The stdlib-only helper the tool schemas need stays stdlib-only.

        ``mureo.mcp._period_param`` builds the ``period`` enum from
        ``mureo.google_ads._gaql_validator``; that is the import that used to pay
        for the whole generated protobuf tree.
        """
        proc = run_in_fresh_interpreter(
            "import sys\n"
            "import mureo.google_ads._gaql_validator  # noqa: F401\n"
            "print('mureo.google_ads.client' in sys.modules)\n"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", proc.stdout

    def test_naming_the_warning_category_does_not_import_the_server(self) -> None:
        """``mureo.plugin_warnings`` has to stay a leaf, or strict mode is inert.

        The recipe in docs/plugin-authoring.md is: name the category, install
        the filter, import the server. While the category lived under
        ``mureo.mcp``, naming it ran ``mureo/mcp/__init__.py``, which imports the
        server, which collects the plugins and reports their faults — so the
        filter was always installed after the warnings it was meant to catch.
        """
        proc = run_in_fresh_interpreter(_WARNING_CATEGORY_CODE)
        assert proc.returncode == 0, proc.stderr
        loaded = json.loads(proc.stdout.strip().splitlines()[-1])
        assert "mureo.mcp" not in loaded and "mureo.plugin_warnings" in loaded, loaded


@pytest.mark.unit
class TestImportBudget:
    """CPU backstop on the server's import cost.

    Kept in the default lane rather than moved to the ``slow`` marker: the
    attribution check above is the primary guard and this is only the backstop,
    so it is cheap to keep honest here (one child, ~2 s).
    """

    def test_server_imports_within_cpu_budget(self) -> None:
        """Measured by the child, in CPU seconds, not by the parent's clock.

        The import is CPU-bound, and a busy machine or a shared CI runner can
        multiply the wall time of exactly the same work by five. Timing it from
        here measured the machine; ``time.process_time`` in the child measures
        the import.
        """
        budget = _import_budget_seconds()
        proc = run_in_fresh_interpreter(_IMPORT_CPU_CODE)
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
    def test_the_three_export_lists_agree(self, package: str) -> None:
        """``__all__``, the ``TYPE_CHECKING`` imports and ``_LAZY_EXPORTS`` must match.

        A lazy package says what it exports three times: once for the runtime
        (``_LAZY_EXPORTS``, name -> defining module), once for ``mypy`` (the
        explicit ``X as X`` imports under ``TYPE_CHECKING``, which is what keeps
        a typo'd import a type error), and once for ``from pkg import *``
        (``__all__``). Adding a name to one and forgetting another is silent in
        every direction: a missing ``_LAZY_EXPORTS`` entry only fails when
        someone imports the name, a missing ``TYPE_CHECKING`` import only loses
        the type, a missing ``__all__`` entry only drops out of ``dir()``. Read
        from the source, because two of the three do not exist at runtime.
        """
        tree = _lazy_package_source(package)
        declared: set[str] = set()
        lazy_exports: dict[str, str] = {}
        type_checked: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and _target_name(node) == "__all__":
                declared = set(ast.literal_eval(node.value))
            elif isinstance(node, ast.AnnAssign) and _target_name(node) == (
                "_LAZY_EXPORTS"
            ):
                lazy_exports = ast.literal_eval(node.value)
            elif isinstance(node, ast.If):
                type_checked = _type_checking_reexports(node)

        assert declared, f"{package} declares no __all__"
        assert set(lazy_exports) == declared, (
            f"{package}: _LAZY_EXPORTS and __all__ disagree: "
            f"{set(lazy_exports) ^ declared}"
        )
        assert set(type_checked) == declared, (
            f"{package}: the TYPE_CHECKING imports and __all__ disagree: "
            f"{set(type_checked) ^ declared}"
        )
        assert type_checked == lazy_exports, (
            f"{package}: a name is imported from one module under "
            f"TYPE_CHECKING and resolved from another at runtime: "
            f"{ {k: v for k, v in type_checked.items() if lazy_exports.get(k) != v} }"
        )

    @pytest.mark.slow
    @pytest.mark.usefixtures("only_when_asked_for")
    @pytest.mark.parametrize(
        "package", sorted(LAZY_PACKAGES), ids=sorted(LAZY_PACKAGES)
    )
    def test_submodules_are_reachable_as_attributes(self, package: str) -> None:
        """``import pkg`` then ``pkg.submodule`` still resolves, and ``dir`` lists it.

        The eager package got this for free: importing it imported the client,
        which imported everything else, and each import installed the submodule
        as an attribute of the package. A lazy package has to do it on purpose.
        Run in a child interpreter because by now this one has imported those
        submodules for other reasons — and in the ``slow`` lane because that
        child imports every submodule of a platform package, which is seconds of
        SDK import for a property the cheap tests above already cover for the
        two names that matter.
        """
        proc = run_in_fresh_interpreter(
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
        "package", sorted(LAZY_PACKAGES), ids=sorted(LAZY_PACKAGES)
    )
    def test_a_dotted_attribute_name_answers_false(self, package: str) -> None:
        """``hasattr`` has to answer, not raise.

        A name with a dot in it sent ``import_module`` after a grandchild. When
        the first component does not exist either, the ``ModuleNotFoundError``
        names the *parent* — ``mureo.google_ads.no_such`` — so the guard that
        turns "no such submodule" into ``AttributeError`` did not match, and the
        error escaped through ``hasattr``, which PEP 562 and ``hasattr``'s own
        contract say cannot happen. Measured before the fix:
        ``ModuleNotFoundError: No module named 'mureo.google_ads.no_such'``.
        """
        module = __import__(package, fromlist=["__all__"])

        assert hasattr(module, "no_such.attribute") is False
        with pytest.raises(AttributeError):
            getattr(module, "not an identifier")

    @pytest.mark.parametrize(
        "package", sorted(LAZY_PACKAGES), ids=sorted(LAZY_PACKAGES)
    )
    def test_dir_does_not_advertise_the_lazy_machinery(self, package: str) -> None:
        """``dir()`` lists the package's surface, not this file's imports.

        Listing ``globals()`` put the imports that make the package lazy —
        ``TYPE_CHECKING``, ``_LAZY_EXPORTS``, the hooks' own helpers, and the
        ``__future__`` flag — into what a reader and a completion engine take
        for the public surface. The eager package listed none of them.
        """
        module = __import__(package, fromlist=["__all__"])
        machinery = {
            "annotations",
            "lazy_dir",
            "lazy_getattr",
            "TYPE_CHECKING",
            "_LAZY_EXPORTS",
        }

        assert machinery.isdisjoint(dir(module)), sorted(
            machinery.intersection(dir(module))
        )

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
