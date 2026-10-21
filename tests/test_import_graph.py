"""The import graph between ``mureo.core`` and ``mureo.context`` (#863).

``mureo.core`` is the lower layer. It used to import ``mureo.context`` at load
time (``core/__init__`` -> ``runtime_context`` -> ``state_store`` ->
``mureo.context.state``), so any top-level ``from mureo.core.<x> import ...``
inside ``mureo.context`` failed with a partially initialised module whenever a
``context`` module was imported first — and two dozen imports in ``context``
were function-local only to dodge that. The default ``FilesystemStateStore``
now lives in :mod:`mureo.context.state_store`, ``runtime_context`` reaches it
by object reference, and these tests pin the direction:

* importing ``mureo.core`` alone loads nothing from ``mureo.context``;
* either package can be imported first;
* ``rollback`` / ``policy`` / ``amazon_ads`` / ``core`` never import
  ``mureo.mcp``, not even function-locally — the server publishes what they
  need at load;
* ``analytics`` / ``change_import`` / ``mureo.client_factory`` never import
  ``mureo.mcp`` either: the credential source, account scoping and the client
  factory they open live clients with sit below it, and loading them does not
  load ``mureo.auth`` (deferred to the first client build);
* ``mureo.web`` and its leaf modules (``instance``, ``service``) load no
  configure server, so ``cli`` imports them at top level; ``web`` imports no
  ``_``-prefixed ``cli`` name;
* ``pytest -m slow``: every module under ``mureo/`` imports on its own, as the
  first import of a fresh interpreter.

The children are the same ones :mod:`tests.test_platform_submodule_imports`
runs (``tests/_measurement_child.py``, shared through the ``standalone_sweep``
fixture), so nothing the parent has imported can warm a cycle for them.
"""

from __future__ import annotations

import ast
import json
import pathlib
import pkgutil

import pytest

import mureo
import mureo.context
import mureo.core
import mureo.core.credential_source as credential_source
import mureo.core.state_store
import mureo.core.tool_failure as tool_failure
import mureo.mcp._helpers as helpers
import mureo.mcp.credential_source as credential_source_compat
import mureo.web
import mureo.web.instance
import mureo.web.server
from mureo.context.state_store import FilesystemStateStore
from tests._measurement_child import (
    StandaloneSweep,
    assert_imports_alone,
    run_in_fresh_interpreter,
)

#: Child: import ``mureo.core`` and nothing else, then report which
#: ``mureo.context`` modules came with it.
_CORE_ALONE = (
    "import json, sys\n"
    "import mureo.core\n"
    "print(json.dumps(sorted(m for m in sys.modules"
    " if m == 'mureo.context' or m.startswith('mureo.context.'))))\n"
)


def _raise_on_unimportable_package(name: str) -> None:
    """Fail collection instead of silently dropping a package's submodules.

    ``pkgutil.walk_packages`` imports each package to find its children and,
    by default, skips one that raises — which would shrink the sweep without
    anyone noticing.
    """
    raise ImportError(f"cannot walk {name}: importing it failed")


def _all_mureo_modules() -> list[str]:
    return [
        info.name
        for info in pkgutil.walk_packages(
            mureo.__path__, "mureo.", onerror=_raise_on_unimportable_package
        )
    ]


#: The ``slow`` lane: every module under ``mureo/``.
ALL_MUREO_MODULES = tuple(_all_mureo_modules())


@pytest.mark.unit
def test_core_alone_loads_nothing_from_context() -> None:
    """``mureo.core`` sits below ``mureo.context`` and must not import it."""
    proc = run_in_fresh_interpreter(_CORE_ALONE)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("first", "second"),
    [("mureo.context", "mureo.core"), ("mureo.core", "mureo.context")],
)
def test_core_and_context_import_in_either_order(first: str, second: str) -> None:
    proc = run_in_fresh_interpreter(f"import {first}\nimport {second}\n")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.unit
def test_filesystem_state_store_resolves_from_every_published_path() -> None:
    """The class moved to ``mureo.context.state_store``; ``mureo.core`` (an ABI
    re-export) and the old ``mureo.core.state_store`` path still resolve to it.
    """
    assert mureo.core.FilesystemStateStore is FilesystemStateStore
    assert mureo.core.state_store.FilesystemStateStore is FilesystemStateStore
    assert mureo.context.FilesystemStateStore is FilesystemStateStore
    with pytest.raises(AttributeError):
        _ = mureo.core.NoSuchName
    with pytest.raises(AttributeError):
        _ = mureo.core.state_store.NoSuchName


@pytest.mark.slow
@pytest.mark.parametrize("module", ALL_MUREO_MODULES)
@pytest.mark.usefixtures("only_when_asked_for")
def test_every_mureo_module_imports_as_the_first_import(
    module: str, standalone_sweep: StandaloneSweep
) -> None:
    returncode, stderr = standalone_sweep.result(module, ALL_MUREO_MODULES)
    assert_imports_alone(module, returncode, stderr)


# ---------------------------------------------------------------------------
# rollback / policy / amazon_ads / core / analytics / change_import /
# client_factory never import ``mureo.mcp`` (#863)
# ---------------------------------------------------------------------------

#: Packages (and top-level modules) below ``mureo.mcp``. ``mureo/mcp/__init__``
#: loads the whole server, so any ``mureo.mcp.*`` import from here — even a
#: function-local one — reaches back up through every tool module.
_BELOW_MCP = (
    "rollback",
    "policy",
    "amazon_ads",
    "core",
    "analytics",
    "change_import",
    "client_factory.py",
)

#: Child: import the lower layers and nothing else, run the two call paths
#: that used to reach ``mureo.mcp`` at call time (the plugin reversal lookup,
#: the Amazon failure rewrite), then report which ``mureo.mcp`` modules came
#: with them (the third-party ``mcp`` SDK is fine).
_LOWER_LAYERS_ALONE = (
    "import json, sys\n"
    "import mureo.rollback, mureo.policy.learning_reset\n"
    "import mureo.amazon_ads.bridge, mureo.core.tool_failure\n"
    "from mureo.amazon_ads.bridge import _normalize_failure\n"
    "from mureo.rollback.planner import _plugin_reversal_keys\n"
    "_plugin_reversal_keys('some_plugin_tool')\n"
    "_normalize_failure([], is_error=True)\n"
    "print(json.dumps(sorted(m for m in sys.modules"
    " if m == 'mureo.mcp' or m.startswith('mureo.mcp.'))))\n"
)

#: Platform SDKs a live client is built on. Google Ads uses ``google.ads``;
#: Meta has no SDK here — ``mureo.meta_ads.client`` talks to the Graph API over
#: ``httpx`` — so its client module stands in, with ``facebook_business`` (the
#: official Meta SDK) listed so adopting it cannot slip in unseen.
_PLATFORM_SDK_MODULES = ("google.ads", "facebook_business", "mureo.meta_ads.client")

#: Child: import the analytics / change-import live-client openers and the
#: modules they open clients with, then report which ``mureo.mcp`` modules and
#: platform SDK modules came with them and whether ``mureo.auth`` did (it is
#: deferred to the first client build for its startup cost, #809).
_LIVE_CLIENT_OPENERS_ALONE = (
    "import json, sys\n"
    "import mureo.analytics.builtin._live_clients\n"
    "import mureo.change_import.builtin.google_ads\n"
    "import mureo.core.credential_source, mureo.core.account_scope\n"
    "import mureo.client_factory\n"
    f"sdks = {_PLATFORM_SDK_MODULES!r}\n"
    "print(json.dumps({'mcp': sorted(m for m in sys.modules"
    " if m == 'mureo.mcp' or m.startswith('mureo.mcp.')),"
    " 'sdk': sorted(m for m in sys.modules"
    " if any(m == s or m.startswith(s + '.') for s in sdks)),"
    " 'auth': 'mureo.auth' in sys.modules}))\n"
)

#: The failure-envelope reader moved to ``mureo.core.tool_failure``;
#: ``mureo.mcp._helpers`` re-exports the same objects.
_ENVELOPE_READER_NAMES = (
    "FAILURE_STATUSES",
    "API_ERROR_PREFIX",
    "API_ERROR_CODE",
    "is_auth_error_result",
    "Failure",
    "failure_of",
    "is_error_result",
)


#: The credential-source ABI moved to ``mureo.core.credential_source``;
#: ``mureo.mcp.credential_source`` re-exports the same objects.
_CREDENTIAL_SOURCE_NAMES = (
    "CredentialSource",
    "CredentialSourceError",
    "GoogleCredentialSource",
    "MetaCredentialSource",
    "active_source_identity",
    "call_source",
    "current_credential_source",
    "current_google_source",
    "current_meta_source",
    "use_credential_source",
)


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


#: The ``target`` the ``mureo.mcp`` guards hand the walkers below.
_MCP_PACKAGE = "mureo.mcp"


def _is_within(name: str, target: str) -> bool:
    """``name`` is ``target`` or one of its submodules."""
    return name == target or name.startswith(f"{target}.")


def _from_import_targets(node: ast.ImportFrom, package: str, target: str) -> list[str]:
    """The ``target*`` modules one ``from ... import ...`` reaches.

    A relative import is resolved against ``package`` (the importing file's
    package), and ``from mureo import mcp`` names the subpackage through an
    alias, so both are checked as the absolute module they load.
    """
    module = node.module or ""
    if node.level:
        base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
        module = f"{base}.{module}" if module else base
    if _is_within(module, target):
        return [module]
    return [
        f"{module}.{alias.name}"
        for alias in node.names
        if _is_within(f"{module}.{alias.name}", target)
    ]


def _imports_of(tree: ast.AST, package: str, target: str) -> list[tuple[int, str]]:
    """Every ``target*`` import in ``tree``, outside ``if TYPE_CHECKING:``.

    ``package`` is the dotted package of the file ``tree`` was parsed from,
    for resolving relative imports.
    """
    found: list[tuple[int, str]] = []
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            pending.extend(node.orelse)
            continue
        if isinstance(node, ast.ImportFrom):
            names = _from_import_targets(node, package, target)
        elif isinstance(node, ast.Import):
            names = [
                alias.name for alias in node.names if _is_within(alias.name, target)
            ]
        else:
            names = []
        found.extend((node.lineno, name) for name in names)  # type: ignore[attr-defined]
        pending.extend(ast.iter_child_nodes(node))
    return sorted(found)


def _package_of(path: pathlib.Path) -> str:
    """The dotted package a module file belongs to (its directory).

    ``rollback/planner.py`` and ``rollback/__init__.py`` -> ``mureo.rollback``.
    """
    parts = path.relative_to(pathlib.Path(mureo.__file__).parent.parent).parts
    return ".".join(parts[:-1])


@pytest.mark.unit
def test_lower_layers_load_nothing_from_mcp() -> None:
    proc = run_in_fresh_interpreter(_LOWER_LAYERS_ALONE)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


@pytest.mark.unit
def test_live_client_openers_load_neither_mcp_nor_auth() -> None:
    proc = run_in_fresh_interpreter(_LIVE_CLIENT_OPENERS_ALONE)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"mcp": [], "sdk": [], "auth": False}


@pytest.mark.unit
@pytest.mark.parametrize("package", _BELOW_MCP)
def test_lower_layer_source_never_imports_mcp(package: str) -> None:
    """Function-local imports included: one that runs only after the server
    has loaded is still an upward dependency, and the next caller to reach it
    without the server gets the cycle."""
    root = pathlib.Path(mureo.__file__).parent / package
    paths = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    offenders = [
        f"{path.relative_to(root.parent)}:{lineno} imports {name}"
        for path in paths
        for lineno, name in _imports_of(
            ast.parse(path.read_text("utf-8")), _package_of(path), _MCP_PACKAGE
        )
    ]
    assert offenders == []


@pytest.mark.unit
@pytest.mark.parametrize("name", _ENVELOPE_READER_NAMES)
def test_envelope_reader_is_one_object_on_both_paths(name: str) -> None:
    assert getattr(helpers, name) is getattr(tool_failure, name)


@pytest.mark.unit
@pytest.mark.parametrize("name", _CREDENTIAL_SOURCE_NAMES)
def test_credential_source_is_one_object_on_both_paths(name: str) -> None:
    assert getattr(credential_source_compat, name) is getattr(credential_source, name)


@pytest.mark.unit
def test_credential_source_paths_export_the_same_names() -> None:
    assert sorted(credential_source.__all__) == sorted(_CREDENTIAL_SOURCE_NAMES)
    assert credential_source_compat.__all__ == credential_source.__all__


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ("import mureo.mcp.server\n", ["mureo.mcp.server"]),
        ("from mureo.mcp._helpers import failure_of\n", ["mureo.mcp._helpers"]),
        ("from mureo import mcp\n", ["mureo.mcp"]),
        ("from mureo import context, mcp\n", ["mureo.mcp"]),
        ("from .. import mcp\n", ["mureo.mcp"]),
        ("from ..mcp.server import x\n", ["mureo.mcp.server"]),
        ("def f():\n    from ..mcp import _helpers\n", ["mureo.mcp"]),
        ("if TYPE_CHECKING:\n    from mureo.mcp.server import x\n", []),
        ("import mcp.types\nfrom mcp import types\n", []),
        ("from mureo import mcpx\nfrom . import mcp\n", []),
    ],
)
def test_mcp_imports_sees_every_spelling(source: str, flagged: list[str]) -> None:
    """``_imports_of`` as if ``source`` were a module of ``mureo.rollback``."""
    found = _imports_of(ast.parse(source), "mureo.rollback", _MCP_PACKAGE)
    assert [name for _, name in found] == flagged


# ---------------------------------------------------------------------------
# meta_ads below auth, the OAuth wizard under web, one credentials default
# path (#863)
#
# ``mureo.auth_setup`` and ``mureo.meta_ads.accounts`` used to import each
# other's private constants, one side function-locally to dodge the cycle;
# the configure OAuth wizard (``mureo.cli.web_auth``, now
# ``mureo.web.auth_wizard``) was reachable from ``mureo.web.oauth_bridge``
# only through function-local imports; and the legacy credentials location
# was spelled out in six modules. These pin the fixed shape.
# ---------------------------------------------------------------------------

#: Modules ``mureo.meta_ads`` sits below. The Meta OAuth constants they need
#: are public in ``mureo.meta_ads.accounts``; the arrow points one way.
_ABOVE_META_ADS = ("mureo.auth", "mureo.auth_setup")

#: Modules whose ``_``-prefixed names no other mureo module may import.
_PRIVATE_NAMES_STAY_HOME = ("mureo.meta_ads.accounts", "mureo.auth_setup")

#: The two path segments of the legacy credentials location. Built from parts
#: so this file does not itself spell the path.
_CREDENTIALS_DIR, _CREDENTIALS_FILE = ".mureo", "credentials" + ".json"

#: The tail of ``<root> / ".mureo" / "credentials.json"`` as
#: :func:`ast.unparse` renders it, whatever quotes and spacing the source used.
_CREDENTIALS_JOIN_TAIL = f" / '{_CREDENTIALS_DIR}' / '{_CREDENTIALS_FILE}'"

#: Every ``(module, enclosing function, root)`` allowed to join that tail, and
#: why. Only ``default_credentials_path`` roots it at ``Path.home()``.
_CREDENTIALS_JOIN_SITES = {
    ("mureo/core/secret_store.py", "default_credentials_path", "Path.home()"): (
        "the one definition of the legacy default location"
    ),
    ("mureo/web/host_paths.py", "_claude_code_paths", "home"): (
        "rooted at get_host_paths(home=...): an injected home is a sandbox"
    ),
    ("mureo/web/host_paths.py", "_claude_desktop_paths", "home"): (
        "rooted at get_host_paths(home=...): an injected home is a sandbox"
    ),
    ("mureo/web/host_paths.py", "_codex_paths", "home"): (
        "rooted at get_host_paths(home=...): an injected home is a sandbox"
    ),
}


def _mureo_sources() -> list[pathlib.Path]:
    return sorted(pathlib.Path(mureo.__file__).parent.rglob("*.py"))


def _credentials_join_sites(tree: ast.AST) -> list[tuple[int, str, str]]:
    """``(line, enclosing function, root)`` of every ``<root> / ".mureo" /
    "credentials.json"`` in ``tree``; the function is ``""`` at module scope.
    """
    found: list[tuple[int, str, str]] = []
    pending: list[tuple[ast.AST, str]] = [(tree, "")]
    while pending:
        node, scope = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.left, ast.BinOp)
            and ast.unparse(node).endswith(_CREDENTIALS_JOIN_TAIL)
        ):
            found.append((node.lineno, scope, ast.unparse(node.left.left)))
        pending.extend((child, scope) for child in ast.iter_child_nodes(node))
    return sorted(found)


def _function_local_imports_of(
    tree: ast.AST, package: str, target: str
) -> set[tuple[int, str]]:
    """``target*`` imports inside any function body of ``tree``."""
    return {
        found
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for found in _imports_of(node, package, target=target)
    }


def _private_names_imported(
    tree: ast.AST, package: str, target: str
) -> list[tuple[int, str]]:
    """``from <target> import _name`` in ``tree``, any position, any spelling."""
    return [
        (node.lineno, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and _from_import_targets(node, package, target)
        for alias in node.names
        if alias.name.startswith("_")
    ]


@pytest.mark.unit
@pytest.mark.parametrize("target", _ABOVE_META_ADS)
def test_meta_ads_source_never_imports_auth(target: str) -> None:
    """Function-local imports included — that is how the cycle used to hide."""
    root = pathlib.Path(mureo.__file__).parent / "meta_ads"
    offenders = [
        f"{path.relative_to(root.parent)}:{lineno} imports {name}"
        for path in sorted(root.rglob("*.py"))
        for lineno, name in _imports_of(
            ast.parse(path.read_text("utf-8")), _package_of(path), target=target
        )
    ]
    assert offenders == []


@pytest.mark.unit
def test_oauth_bridge_has_no_function_local_mureo_import() -> None:
    path = pathlib.Path(mureo.__file__).parent / "web" / "oauth_bridge.py"
    found = _function_local_imports_of(
        ast.parse(path.read_text("utf-8")), _package_of(path), target="mureo"
    )
    assert sorted(found) == []


@pytest.mark.unit
@pytest.mark.parametrize("target", _PRIVATE_NAMES_STAY_HOME)
def test_no_module_imports_private_names_of(target: str) -> None:
    root = pathlib.Path(mureo.__file__).parent
    offenders = [
        f"{path.relative_to(root.parent)}:{lineno} imports {target}.{name}"
        for path in _mureo_sources()
        for lineno, name in _private_names_imported(
            ast.parse(path.read_text("utf-8")), _package_of(path), target
        )
    ]
    assert offenders == []


@pytest.mark.unit
def test_default_credentials_path_is_spelled_once() -> None:
    """Only ``mureo.core.secret_store.default_credentials_path`` builds it from
    ``Path.home()``; every other join of the same segments is allow-listed."""
    root = pathlib.Path(mureo.__file__).parent
    found = [
        (path.relative_to(root.parent).as_posix(), lineno, scope, home)
        for path in _mureo_sources()
        for lineno, scope, home in _credentials_join_sites(
            ast.parse(path.read_text("utf-8"))
        )
    ]
    sites = sorted((module, scope, home) for module, _, scope, home in found)
    assert sites == sorted(_CREDENTIALS_JOIN_SITES), found


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "target", "flagged"),
    [
        ("from mureo.auth import x\n", "mureo.auth", ["mureo.auth"]),
        ("from mureo import auth\n", "mureo.auth", ["mureo.auth"]),
        ("from .. import auth\n", "mureo.auth", ["mureo.auth"]),
        ("def f():\n    import mureo.auth\n", "mureo.auth", ["mureo.auth"]),
        ("from mureo import auth_setup\n", "mureo.auth", []),
        ("from mureo.auth_setup import x\n", "mureo.auth_setup", ["mureo.auth_setup"]),
        ("from ..auth_setup import x\n", "mureo.auth_setup", ["mureo.auth_setup"]),
        ("if TYPE_CHECKING:\n    from mureo.auth import x\n", "mureo.auth", []),
    ],
)
def test_import_walker_sees_every_spelling_of_another_target(
    source: str, target: str, flagged: list[str]
) -> None:
    """``_imports_of`` with ``target`` as if ``source`` were in ``mureo.meta_ads``."""
    found = _imports_of(ast.parse(source), "mureo.meta_ads", target=target)
    assert [name for _, name in found] == flagged


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ("from mureo.auth_setup import _x, y\n", [(1, "_x")]),
        ("def f():\n    from ..auth_setup import _x\n", [(2, "_x")]),
        ("from mureo.auth_setup import y\n", []),
        ("from mureo.auth import _x\n", []),
    ],
)
def test_private_name_walker_sees_every_spelling(
    source: str, flagged: list[tuple[int, str]]
) -> None:
    found = _private_names_imported(ast.parse(source), "mureo.web", "mureo.auth_setup")
    assert found == flagged


@pytest.mark.unit
def test_function_local_walker_ignores_module_scope() -> None:
    source = (
        "import mureo.web\n"
        "def f():\n    from mureo.web import auth_wizard\n"
        "async def g():\n    import json\n"
    )
    found = _function_local_imports_of(ast.parse(source), "mureo.web", "mureo")
    assert sorted(found) == [(3, "mureo.web")]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ('X = Path.home() / "{d}" / "{f}"\n', [(1, "", "Path.home()")]),
        ("def f(home):\n    return home/'{d}'/'{f}'\n", [(2, "f", "home")]),
        (
            'async def g(base):\n    return (\n        base  /  "{d}"\n'
            '        / "{f}"\n    )\n',
            [(3, "g", "base")],
        ),
        (
            "def f():\n    def inner(h):\n        return h / '{d}' / '{f}'\n",
            [(3, "inner", "h")],
        ),
        ("p = Path.home() / '{d}' / 'other.json'\n", []),
        ("p = Path.home() / '{d}'\nq = p / '{f}'\n", []),
    ],
)
def test_credentials_join_walker_sees_every_spelling(
    source: str, flagged: list[tuple[int, str, str]]
) -> None:
    tree = ast.parse(source.format(d=_CREDENTIALS_DIR, f=_CREDENTIALS_FILE))
    assert _credentials_join_sites(tree) == flagged


# ---------------------------------------------------------------------------
# web <-> cli (#863)
#
# ``mureo/web/__init__`` used to import the configure server, and
# ``mureo.web.service`` imported it for one port constant — so every
# ``mureo.web.*`` import loaded the server, the server imports ``cli`` helper
# modules, and ``cli`` could reach ``web`` only function-locally. The layer
# rule now: ``web`` imports ``cli`` helper modules by public names; ``cli``
# imports only ``web`` leaf modules (plus the ``configure`` entry command);
# importing a ``web`` submodule loads the server only when it needs it.
# ---------------------------------------------------------------------------

#: The configure server and its request handler: what a leaf import must not
#: drag in.
_WEB_SERVER_MODULES = ("mureo.web.server", "mureo.web.handlers")

#: Child: import the ``web`` leaves and the ``cli`` modules that use them, then
#: report which of the server modules came with them.
_WEB_LEAVES_ALONE = (
    "import json, sys\n"
    "import mureo.web.service, mureo.web.instance, mureo.installed_packages\n"
    "import mureo.cli.skill_status, mureo.cli.upgrade_cmd\n"
    f"print(json.dumps(sorted(m for m in {_WEB_SERVER_MODULES!r}"
    " if m in sys.modules)))\n"
)

#: Modules that may not import a function-local ``mureo.web*``: each one's
#: former lazy imports existed only to dodge the server cycle.
_NO_LAZY_WEB_IMPORT = ("mureo/web/handlers.py", "mureo/cli/upgrade_cmd.py")

_WEB_PACKAGE = "mureo.web"
_CLI_PACKAGE = "mureo.cli"

#: The ``web`` modules any ``cli`` module may import (each with its
#: submodules): leaves that do not load the configure server.
_WEB_LEAVES_FOR_CLI = (
    "mureo.web.instance",
    "mureo.web.service",
    "mureo.web.report_clients",
)

#: ``(cli module, web module)`` pairs allowed beyond the leaves: the
#: ``configure`` entry command imports ``run_configure_wizard`` from the
#: package, which loads the server on access.
_CLI_WEB_ENTRY_IMPORTS = {("mureo/cli/configure_cmd.py", "mureo.web")}


@pytest.mark.unit
def test_web_leaves_and_their_cli_users_load_no_server() -> None:
    proc = run_in_fresh_interpreter(_WEB_LEAVES_ALONE)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("first", "second"),
    [("mureo.web", "mureo.cli.upgrade_cmd"), ("mureo.cli.upgrade_cmd", "mureo.web")],
)
def test_web_and_upgrade_cmd_import_in_either_order(first: str, second: str) -> None:
    proc = run_in_fresh_interpreter(f"import {first}\nimport {second}\n")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.unit
def test_web_imports_no_private_cli_name() -> None:
    root = pathlib.Path(mureo.__file__).parent
    offenders = [
        f"{path.relative_to(root.parent)}:{lineno} imports {name} from {_CLI_PACKAGE}"
        for path in sorted((root / "web").rglob("*.py"))
        for lineno, name in _private_names_imported(
            ast.parse(path.read_text("utf-8")), _package_of(path), _CLI_PACKAGE
        )
    ]
    assert offenders == []


@pytest.mark.unit
@pytest.mark.parametrize("module", _NO_LAZY_WEB_IMPORT)
def test_no_function_local_web_import_in(module: str) -> None:
    path = pathlib.Path(mureo.__file__).parent.parent / module
    found = _function_local_imports_of(
        ast.parse(path.read_text("utf-8")), _package_of(path), _WEB_PACKAGE
    )
    assert sorted(found) == []


@pytest.mark.unit
def test_cli_imports_only_web_leaves() -> None:
    """Function-local imports included; ``if TYPE_CHECKING:`` ones are not."""
    root = pathlib.Path(mureo.__file__).parent
    offenders = [
        f"{rel}:{lineno} imports {name}"
        for path in sorted((root / "cli").rglob("*.py"))
        for rel in [path.relative_to(root.parent).as_posix()]
        for lineno, name in _imports_of(
            ast.parse(path.read_text("utf-8")), _package_of(path), _WEB_PACKAGE
        )
        if not any(_is_within(name, leaf) for leaf in _WEB_LEAVES_FOR_CLI)
        and (rel, name) not in _CLI_WEB_ENTRY_IMPORTS
    ]
    assert offenders == []


@pytest.mark.unit
def test_web_reexports_resolve_to_the_server_objects() -> None:
    assert mureo.web.ConfigureWizard is mureo.web.server.ConfigureWizard
    assert mureo.web.run_configure_wizard is mureo.web.server.run_configure_wizard
    assert (
        mureo.web.server.DEFAULT_CONFIGURE_PORT
        is mureo.web.instance.DEFAULT_CONFIGURE_PORT
    )
    with pytest.raises(AttributeError):
        _ = mureo.web.NoSuchName
