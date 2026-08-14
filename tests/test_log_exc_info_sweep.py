"""No credential-holding module may write the exception itself (#603, #605).

**Why this file exists.** ``exc_info=True`` writes
``traceback.format_exception()``, which includes ``str(exc)``.

For ``mureo/google_ads/`` the exception is ``GoogleAdsException``, which does
not curate its ``__str__``: its ``__init__(self, error, call, failure,
request_id)`` never passes a message to ``super().__init__()``, so
``BaseException`` keeps the raw constructor args and formatting the exception
prints the underlying ``grpc.Call`` repr — which carries
``debug_error_string()``, and with it the request metadata: the developer token
and the ``authorization`` header. The chained ``raise ... from exc`` inside that
package means a ``RuntimeError`` caught one level up prints the same thing,
because a traceback follows ``__cause__``.

Nothing in those packages installed a logging handler, so the lines were
discarded at runtime until #581 installed one. #603 converted the 36 remaining
call sites under ``mureo/google_ads/`` to log the exception *class* — or the
curated server-side ``failure.errors[0].message`` via ``_extract_error_detail``
— instead. This file is what stops the 37th from being written.

**Why the sweep covers more than Google Ads (#605).** The same shape came back
in ``mureo/auth.py``: a failed Meta token refresh raised a ``ValueError``
carrying Graph's whole ``resp.text`` and logged it with ``exc_info=True``, so
an unbounded, platform-authored response body was written to
``~/.mureo/logs/configure.log``. The property being defended is not "gRPC leaks
metadata" but "no module that handles a credential may write an exception it
did not compose", so the roots below are the modules that hold or exchange
credentials — the token refreshers, the OAuth wizard's storage layer, and the
two platform clients that talk to a token endpoint.

``mureo/web/`` is deliberately NOT a root. Its ~68 sites are ``logger
.exception()`` on local setup actions (writing a config file, running ``pip``,
deploying a skill), where the exception text is a stdlib ``OSError`` or a
``subprocess`` result rather than a platform's response body, and where the
traceback is the diagnostic the operator actually needs from a failed wizard
step. Sweeping it would mean 68 conversions in one change and would trade a
real diagnostic for a class name in cases with no credential in reach. The two
credential-adjacent sites there (``handlers.py`` "Meta token validation
failed" / "Meta token save failed") log exceptions already scrubbed by
``mureo/meta_ads/accounts.py``; if that changes, add the root and fix them.

Two properties worth keeping when editing this file:

- **Derived, never enumerated.** The call sites come from the tree, not from a
  list here, so a new module is covered the moment it is added.
- **Extraction is asserted, not assumed.** ``test_the_sweep_still_matches``
  runs the extractor over planted source, so a sweep that quietly stopped
  matching cannot turn this file into a green no-op.

``logger.exception()`` is swept alongside ``exc_info``: it sets
``exc_info=True`` itself, so it leaks the same bytes without naming the
keyword.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_MUREO_ROOT = pathlib.Path(__file__).resolve().parent.parent / "mureo"

#: The credential-holding trees this file guards. A directory sweeps
#: recursively; a file is swept on its own.
_SOURCE_ROOTS = (
    _MUREO_ROOT / "google_ads",
    _MUREO_ROOT / "meta_ads",
    _MUREO_ROOT / "amazon_ads",
    _MUREO_ROOT / "auth.py",
    _MUREO_ROOT / "auth_setup.py",
)

#: Logging methods that accept an ``exc_info`` keyword.
_LOG_METHODS = frozenset(
    {
        "critical",
        "debug",
        "error",
        "fatal",
        "info",
        "log",
        "warn",
        "warning",
    }
)


def _is_logger_receiver(node: ast.expr) -> bool:
    """Whether ``node`` is something spelled like a logger.

    ``exception`` is the one swept method name that is not logging-specific:
    ``concurrent.futures.Future`` and ``asyncio.Task`` both have an
    ``.exception()``, and ``mureo/amazon_ads/batch.py`` calls it twice. Rather
    than exempt those two lines by number — an exemption that goes stale on the
    next edit — the receiver has to be log-shaped. The rule is deliberately
    loose (a substring, case-folded) so ``logger``, ``_logger``, ``LOG``,
    ``self.log`` and ``access_logger`` are all still caught; ``future``,
    ``owner`` and ``task`` are not.

    ``exc_info=`` needs no such gate: nothing but a logging call takes it.
    """
    if isinstance(node, ast.Name):
        return "log" in node.id.lower()
    if isinstance(node, ast.Attribute):
        return "log" in node.attr.lower()
    if isinstance(node, ast.Call):
        return _is_logger_receiver(node.func)
    return False


def _traceback_log_calls(source: str, module: str) -> list[tuple[str, int, str]]:
    """Every logging call in ``source`` that would write the exception.

    Returned as ``(module file name, line number, what was found)``. Matched on
    the method name rather than the receiver, so ``self._logger.warning`` and a
    module-level ``logger.warning`` are both covered.
    """
    found: list[tuple[str, int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        method = node.func.attr
        if method == "exception":
            if _is_logger_receiver(node.func.value):
                found.append((module, node.lineno, "logger.exception()"))
            continue
        if method not in _LOG_METHODS:
            continue
        found.extend(
            (module, node.lineno, "exc_info=")
            for keyword in node.keywords
            if keyword.arg == "exc_info"
        )
    return found


def _swept_paths() -> list[pathlib.Path]:
    """Every ``.py`` file under :data:`_SOURCE_ROOTS`."""
    paths: list[pathlib.Path] = []
    for root in _SOURCE_ROOTS:
        paths.extend(sorted(root.rglob("*.py")) if root.is_dir() else [root])
    return paths


def _sweep() -> list[tuple[str, int, str]]:
    """Every offending logging call under :data:`_SOURCE_ROOTS`."""
    found: list[tuple[str, int, str]] = []
    for path in _swept_paths():
        found.extend(_traceback_log_calls(path.read_text(encoding="utf-8"), path.name))
    return found


@pytest.mark.unit
def test_no_credential_module_log_line_writes_the_exception() -> None:
    """These trees log a class name or a curated detail, never a traceback."""
    offenders = _sweep()
    assert not offenders, (
        "these log calls write the exception itself, which for a "
        "GoogleAdsException prints the grpc.Call repr — and with it the "
        "developer token and authorization header — and for a platform HTTP "
        "failure prints whatever the platform put in the response body:\n"
        + "\n".join(f"  {module}:{line}: {what}" for module, line, what in offenders)
        + "\nLog type(exc).__name__, or a detail your own code composed "
        "(_extract_error_detail, _graph_error_detail) where the server-side "
        "failure message is what you need."
    )


@pytest.mark.unit
def test_every_root_exists_and_is_swept() -> None:
    """A root renamed out from under this file must not silently sweep nothing."""
    missing = [str(root) for root in _SOURCE_ROOTS if not root.exists()]
    assert not missing, f"swept roots that no longer exist: {missing}"
    assert len(_swept_paths()) >= len(_SOURCE_ROOTS)


@pytest.mark.unit
def test_the_sweep_still_matches() -> None:
    """Planted source is caught — an extractor that stopped matching passes nothing."""
    planted = (
        "logger.warning('a', exc_info=True)\n"
        "logger.debug('b', exc_info=exc)\n"
        "self._logger.error('c', 1, exc_info=True)\n"
        "logger.exception('d')\n"
        "self.log.exception('e')\n"
        "LOG.exception('f')\n"
        "logging.getLogger(__name__).exception('g')\n"
    )
    assert [line for _, line, _ in _traceback_log_calls(planted, "planted.py")] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    ]


@pytest.mark.unit
def test_the_sweep_does_not_invent_offenders() -> None:
    """The safe replacements, and prose about the bug, are not matched.

    ``accounts.py`` carries a comment naming ``exc_info=True`` as the thing it
    is avoiding; a text scan would fail on it forever.
    """
    planted = (
        "# exc_info=True would put the developer token in the log.\n"
        "'''exc_info=True is what this docstring warns against.'''\n"
        "logger.warning('a (%s)', type(exc).__name__)\n"
        "logger.error('b: %s', self._extract_error_detail(exc))\n"
        "some.exc_info = True\n"
        "future.exception()\n"
        "exc = owner.exception()\n"
    )
    assert _traceback_log_calls(planted, "planted.py") == []
