"""No Google Ads log line may write the exception itself (#603).

**Why this file exists.** ``exc_info=True`` writes
``traceback.format_exception()``, which includes ``str(exc)``.
``GoogleAdsException`` does not curate its ``__str__``: its
``__init__(self, error, call, failure, request_id)`` never passes a message to
``super().__init__()``, so ``BaseException`` keeps the raw constructor args and
formatting the exception prints the underlying ``grpc.Call`` repr — which
carries ``debug_error_string()``, and with it the request metadata: the
developer token and the ``authorization`` header. The chained ``raise ... from
exc`` inside this package means a ``RuntimeError`` caught one level up prints
the same thing, because a traceback follows ``__cause__``.

Nothing in the package installed a logging handler, so those lines were
discarded at runtime until #581 installed one. #603 converted the 36 remaining
call sites under ``mureo/google_ads/`` to log the exception *class* — or the
curated server-side ``failure.errors[0].message`` via ``_extract_error_detail``
— instead. This file is what stops the 37th from being written.

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

_SOURCE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "mureo" / "google_ads"

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


def _sweep() -> list[tuple[str, int, str]]:
    """Every offending logging call under ``mureo/google_ads/``."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        found.extend(_traceback_log_calls(path.read_text(encoding="utf-8"), path.name))
    return found


@pytest.mark.unit
def test_no_google_ads_log_line_writes_the_exception() -> None:
    """The whole package logs a class name or a curated detail, never a traceback."""
    offenders = _sweep()
    assert not offenders, (
        "these Google Ads log calls write the exception itself, which for a "
        "GoogleAdsException prints the grpc.Call repr and with it the "
        "developer token and authorization header:\n"
        + "\n".join(f"  {module}:{line}: {what}" for module, line, what in offenders)
        + "\nLog type(exc).__name__, or _extract_error_detail(exc) where the "
        "server-side failure message is what you need."
    )


@pytest.mark.unit
def test_the_sweep_still_matches() -> None:
    """Planted source is caught — an extractor that stopped matching passes nothing."""
    planted = (
        "logger.warning('a', exc_info=True)\n"
        "logger.debug('b', exc_info=exc)\n"
        "self._logger.error('c', 1, exc_info=True)\n"
        "logger.exception('d')\n"
    )
    assert [line for _, line, _ in _traceback_log_calls(planted, "planted.py")] == [
        1,
        2,
        3,
        4,
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
    )
    assert _traceback_log_calls(planted, "planted.py") == []
