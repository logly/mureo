"""PEP 562 attribute resolution for the lazy platform packages.

``mureo.google_ads`` and ``mureo.meta_ads`` resolve their re-exported names and
their submodules on first access instead of at package import, so that a
stdlib-only helper from one of them does not pay for the platform API client
(#807). Both need the same two hooks, and both had a byte-identical copy of
them; they live here once instead.

A package keeps only the parts that cannot be shared: its ``__all__``, the
``_LAZY_EXPORTS`` table that says which module defines each of those names, and
the ``if TYPE_CHECKING:`` import list that gives a type-checker the real types
(see :mod:`mureo.google_ads`).

No **re-exported name** resolved here is cached into the asking package's
``globals()``, and that is deliberate: a cached re-export outlives the
``mock.patch`` that produced it, because ``patch`` restores the *defining*
module's attribute and knows nothing about the package's copy — which would
leave a dead mock installed for the rest of the process. The price is real and
is not "cheap": even on a ``sys.modules`` hit, :func:`importlib.import_module`
takes the import lock and re-resolves the name. Measured below, which is why the
in-tree call sites read these names once per operation; code in a loop should
import the defining module instead. (A **submodule** is different, and not by
choice: importing ``pkg.sub`` makes the import system bind ``sub`` on ``pkg``,
so after its first access a submodule *is* in the package's ``globals()`` and
this hook is not consulted for it again — exactly as with an eager package.)

Measured 2026-10-08 on one development machine (CPython 3.10.0, macOS, no
plugins, bytecode cache warm, ``time.process_time`` over 200,000 iterations —
20,000 for the miss — min of 5 runs, no ``cProfile``). Not checked by any test;
re-measure before relying on the absolute figures:

=========================================  ==========  =========
attribute access                           per call    ratio
=========================================  ==========  =========
``pkg.GoogleAdsApiClient`` (through here)    12.3 us     129x
``client.GoogleAdsApiClient`` (direct)       0.095 us      1x
a name the package does not have (miss)        37 us      --
=========================================  ==========  =========

A miss costs more still because it searches ``sys.path`` before failing, and it
is not cached either, so ``hasattr`` in a loop is the wrong shape for these
packages.
"""

from __future__ import annotations

from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["lazy_dir", "lazy_getattr"]


def lazy_getattr(package: str, exports: Mapping[str, str], name: str) -> object:
    """Resolve ``name`` as one of ``exports`` or as a submodule of ``package``.

    Raises ``AttributeError`` for anything ``package`` does not have, as PEP 562
    requires. An ``ImportError`` from inside a submodule is *not* swallowed:
    only a ``ModuleNotFoundError`` naming the attribute asked for becomes an
    ``AttributeError``; anything else propagates unchanged.

    One case this cannot tell apart: an ``AttributeError`` raised while a
    submodule's own body runs propagates unchanged too, and an
    ``AttributeError`` is what "no such attribute" looks like. ``getattr``
    surfaces the inner error, but ``hasattr(package, name)`` answers ``False``
    for a submodule that exists and is broken. Unlike ``ModuleNotFoundError``,
    an ``AttributeError`` does not reliably name what was missing, so there is
    nothing to match on; import the submodule directly to see the fault.
    """
    module_name = exports.get(name)
    if module_name is not None:
        return getattr(import_module(module_name), name)
    if not name.isidentifier():
        # ``hasattr(pkg, "a.b")`` has to answer False, and a dotted name would
        # send ``import_module`` looking for a grandchild and raise
        # ModuleNotFoundError past ``hasattr`` instead (the ``exc.name`` guard
        # below sees "pkg.a", not the name asked for).
        raise AttributeError(f"module {package!r} has no attribute {name!r}")
    try:
        return import_module(f"{package}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"{package}.{name}":
            raise
        raise AttributeError(f"module {package!r} has no attribute {name!r}") from exc


@cache
def _submodule_names(locations: tuple[str, ...]) -> frozenset[str]:
    """Submodule names under ``locations``, read from disk once per location set.

    Cached because ``dir()`` is called by completion engines and in loops, and
    the uncached version walked the directory on every call: on the Google Ads
    package (35 submodule files) ``dir()`` cost 549 us uncached against 11 us
    cached, where the eager package's default ``dir()`` cost 3.1 us (same
    machine and method as the table above, 10,000 iterations). The cost of the
    cache is that a submodule *file added to the tree after* this process first
    called ``dir()`` is not listed by a later call — a developer editing a
    package the running process has already introspected, where a restart is the
    expectation anyway. Attribute access is unaffected; it never reads this.
    """
    from pkgutil import iter_modules

    return frozenset(info.name for info in iter_modules(locations))


def lazy_dir(
    path: Iterable[str], public: Iterable[str], namespace: Mapping[str, object]
) -> list[str]:
    """List a lazy package's dunders, its public names and its submodules.

    ``namespace`` is the package's ``globals()``, and only its dunders are taken
    from it. Listing all of it advertised the machinery that makes the package
    lazy (``TYPE_CHECKING``, ``_LAZY_EXPORTS``, ``lazy_dir``, ``lazy_getattr``)
    as part of the package's surface; ``dir()`` is what a reader and a
    completion engine take for the surface, and the eager package never listed
    them. The filter is by name, so dunders pass as a class — which includes
    the hooks themselves (``__getattr__``, ``__dir__``) and
    ``__annotations__``.
    """
    return sorted(
        {name for name in namespace if name.startswith("__")}
        | set(public)
        | _submodule_names(tuple(path))
    )
