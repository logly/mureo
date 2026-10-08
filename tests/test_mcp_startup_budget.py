"""The MCP server's import cost is a product contract, not an implementation
detail (#807).

An MCP client gives the server a fixed window to answer ``initialize``; Claude
Code's default is 30,000 ms and it is not negotiable from inside the server.
Every second of mureo's startup was ``import mureo.mcp.server`` — the server's
construction path is already free — so the only thing worth pinning is what that
import drags in.

Four guards, in increasing order of how early they catch a regression:

* :class:`TestEagerPlatformImports` — no platform SDK may be imported at module
  scope. This is the sharp test: it fails deterministically the moment someone
  re-adds an eager ``from google.ads...`` on the schema path, regardless of how
  fast the machine is. Scoped to an environment with no provider plugins
  installed — see :func:`_installed_provider_plugins`.
* :class:`TestLazyToolValidators` — the per-tool input-schema validators are
  compiled on first call, and still enforced on that call.
* :class:`TestImportBudget` — a wall-clock ceiling, as a backstop for growth the
  module-name check cannot see (a new heavy dependency nobody listed).
* :class:`TestLazyPublicNames` — making the import lazy must not make a public
  name disappear, and must not push the failure from import time to call time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SERVER_MODULE = "mureo.mcp.server"

# Ceiling for ``import mureo.mcp.server`` in a fresh interpreter, in seconds.
#
# This is a REGRESSION detector, not the target. Measured on the development
# machine (CPython 3.10, macOS): ~23.5 s before #807, ~1 s after. CI runners are
# slower and start cold (no ``__pycache__``, cold page cache), so a value near
# the achieved figure would flake. 10 s sits an order of magnitude above the
# achieved cost, still less than half of the pre-#807 cost, and comfortably
# inside the client's 30 s connect budget — so it fails on a real regression and
# not on a bad day. Override with MUREO_MCP_IMPORT_BUDGET_SECONDS.
DEFAULT_IMPORT_BUDGET_SECONDS = 10.0
IMPORT_BUDGET_ENV = "MUREO_MCP_IMPORT_BUDGET_SECONDS"

# Module prefixes that must NOT be in sys.modules after importing the server.
# Each one is a platform SDK, a generated API surface, or one of mureo's own API
# clients — things only a handler actually serving a call can need, never the
# tool schemas.
FORBIDDEN_EAGER_PREFIXES = (
    "google.ads.googleads",
    "google.oauth2",
    "googleapiclient",
    "mureo.google_ads.client",
    "mureo.meta_ads.client",
)

# Package -> submodule the package must not import just because it was imported.
LAZY_PACKAGES = {
    "mureo.google_ads": "mureo.google_ads.client",
    "mureo.meta_ads": "mureo.meta_ads.client",
}


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


def _run_in_fresh_interpreter(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a child interpreter sharing this one's sys.path."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )


def _installed_provider_plugins() -> list[str]:
    """Names of third-party provider plugins installed in this environment.

    ``collect_plugin_tools`` loads every one of them while the server module is
    executing, and what a plugin imports is the plugin's business — a provider
    that reaches for an ad SDK at module scope puts that SDK in ``sys.modules``
    through no fault of mureo's. So the no-eager-SDK assertion below is scoped to
    an environment with no provider plugins installed, which is what CI and a
    clean dev venv are.
    """
    from importlib.metadata import entry_points

    from mureo.core.providers.registry import PROVIDERS_ENTRY_POINT_GROUP

    return sorted(ep.name for ep in entry_points(group=PROVIDERS_ENTRY_POINT_GROUP))


@pytest.mark.unit
class TestEagerPlatformImports:
    """No platform SDK is imported just to describe the tools."""

    def test_server_import_pulls_no_platform_sdk(self) -> None:
        plugins = _installed_provider_plugins()
        if plugins:
            pytest.skip(
                f"provider plugins installed, their imports are theirs: {plugins}"
            )
        proc = _run_in_fresh_interpreter(
            "import sys\n"
            f"__import__({SERVER_MODULE!r})\n"
            "print('\\n'.join(sorted(sys.modules)))\n"
        )
        assert proc.returncode == 0, proc.stderr
        loaded = proc.stdout.split()
        offenders = sorted(
            name
            for name in loaded
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in FORBIDDEN_EAGER_PREFIXES
            )
        )
        assert offenders == [], (
            f"importing {SERVER_MODULE} eagerly loaded platform SDK modules: "
            f"{offenders}. Move the import into the function that uses it."
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
    """Wall-clock backstop on the server's import cost."""

    def test_server_imports_within_budget(self) -> None:
        budget = _import_budget_seconds()
        started = time.monotonic()
        proc = _run_in_fresh_interpreter(f"__import__({SERVER_MODULE!r})")
        elapsed = time.monotonic() - started
        assert proc.returncode == 0, proc.stderr
        assert elapsed < budget, (
            f"import {SERVER_MODULE} took {elapsed:.2f}s, over the "
            f"{budget:.2f}s budget. Run "
            f"`python -X importtime -c 'import {SERVER_MODULE}'` and look at "
            f"what was added. Raise {IMPORT_BUDGET_ENV} only for a slow "
            f"machine, never to accept a regression."
        )


@pytest.mark.unit
class TestLazyToolValidators:
    """Compiling the input-schema validators is deferred, not dropped."""

    def test_nothing_is_compiled_at_import(self) -> None:
        proc = _run_in_fresh_interpreter(
            "from mureo.mcp import server\n"
            "print(len(server._TOOL_VALIDATORS._compiled))\n"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "0", proc.stdout

    def test_validation_still_rejects_an_out_of_bounds_budget(self) -> None:
        """The guard runs on the call that compiles it, not after it."""
        from mureo.mcp.server import _TOOL_VALIDATORS, _validate_tool_input

        tool = "google_ads_budget_update"
        if tool not in _TOOL_VALIDATORS:
            pytest.skip("google_ads tools disabled in this environment")
        with pytest.raises(ValueError):
            _validate_tool_input(
                tool,
                {"customer_id": "123", "budget_id": "1", "amount_micros": 0},
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
    def test_unknown_attribute_still_raises_attribute_error(self, package: str) -> None:
        module = __import__(package, fromlist=["__all__"])
        unknown = "no_such_name"

        with pytest.raises(AttributeError):
            getattr(module, unknown)

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
