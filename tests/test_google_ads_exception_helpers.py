"""The GoogleAdsException test helpers must not mutate the class.

Four test modules build a fake ``GoogleAdsException`` the same way: allocate
with ``__new__`` (skipping ``__init__``, which wants a live ``grpc.RpcError``)
and then attach a fake ``failure``. They attached it by installing a
**class-level property**::

    exc._failure = failure
    type(exc).failure = property(lambda self: self._failure)

``type(exc)`` is ``GoogleAdsException`` itself, so that edits the class, and
nothing put it back. The real ``__init__`` assigns ``self.failure = failure``
(a plain instance attribute), and a read-only property has no setter — so once
any of those modules had run, **every later module in the same session** got
``AttributeError: can't set attribute`` from constructing a real exception.
Order-dependent, and invisible when the file is run on its own.

``failure`` is an ordinary instance attribute, so the property was never
needed: assigning it on the instance gives the same fake and leaves the class
alone.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from google.ads.googleads.errors import GoogleAdsException

_TESTS_DIR = pathlib.Path(__file__).resolve().parent


def _class_attribute_assignments(source: str) -> list[tuple[int, str]]:
    """Assignments to an attribute of ``type(...)`` — i.e. of a live class.

    Matches the exact idiom that caused this, rather than any monkeypatching:
    a test that reaches through ``type(instance)`` is writing to the class of
    an object it did not define, which is process-wide and outlives the test.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Attribute):
                continue
            value = target.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "type"
            ):
                found.append((node.lineno, target.attr))
    return found


@pytest.mark.unit
class TestNoTestMutatesALiveClass:
    def test_no_test_module_assigns_through_type(self) -> None:
        offenders: list[str] = []
        for path in sorted(_TESTS_DIR.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for lineno, attr in _class_attribute_assignments(source):
                offenders.append(f"{path.relative_to(_TESTS_DIR)}:{lineno} .{attr}")
        assert not offenders, (
            "these tests assign through type(...), which edits a live class for "
            "the rest of the session: " + ", ".join(offenders)
        )

    def test_the_sweep_still_matches(self) -> None:
        """An extractor that silently stopped matching would be a green no-op."""
        planted = "type(exc).failure = property(lambda self: self._failure)\n"
        assert _class_attribute_assignments(planted) == [(1, "failure")]

    def test_the_sweep_does_not_flag_ordinary_attribute_writes(self) -> None:
        assert _class_attribute_assignments("exc.failure = failure\n") == []
        assert _class_attribute_assignments("obj.attr.nested = 1\n") == []


@pytest.mark.unit
class TestTheRealExceptionStaysConstructible:
    def test_google_ads_exception_can_still_be_constructed(self) -> None:
        """The symptom, asserted directly.

        ``__init__`` does ``self.failure = failure``; a read-only class
        property makes that raise. If any module has left one behind, this
        fails — which is the whole point of pinning it.
        """
        from unittest.mock import MagicMock

        exc = GoogleAdsException(MagicMock(), MagicMock(), MagicMock(), "req-1")

        assert exc.request_id == "req-1"

    def test_the_class_owns_no_failure_attribute(self) -> None:
        """``failure`` belongs to the instance; the class must not define it."""
        assert "failure" not in vars(GoogleAdsException)
