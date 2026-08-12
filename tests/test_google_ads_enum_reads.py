"""No Google Ads proto enum field may be read with a bare ``str()``.

**Why this file exists.** mureo builds its Google Ads client with the SDK
default ``use_proto_plus=False``, so the SDK's response interceptor converts
every row to raw protobuf before mureo sees it, and an enum field arrives as a
plain ``int``. ``str()`` on it yields ``"2"``, and the ``.split(".")[-1]`` /
``.rsplit(".", 1)`` that usually follows is a no-op on a digit string. The
result is a tool that returns numbers where its own description promises names,
and comparisons like ``field_type == "HEADLINE"`` that can never be true.

That failure is silent in production and invisible in the suite: the tests hand
in doubles whose ``__str__`` returns ``"FieldType.HEADLINE"``, a shape the
production path never produces, so the split works in the test and nowhere
else. #588 found thirteen such reads; a descriptor sweep of the whole package
then found seven more, two of them in the RSA asset analysis, which had
therefore never returned a single headline or description, plus one read that
worked only because someone had written the digits in beside the names. This
file exists so there is no third sweep: the reads
are extracted from source and resolved against the vendored protobuf
descriptors, and any that lands on a ``TYPE_ENUM`` field fails.

Two properties worth keeping when editing this file, the same two
``test_gaql_field_names.py`` states:

- **Derived, never enumerated.** The reads come from the tree and their types
  from the SDK descriptors. Only the subject-to-message bindings are written by
  hand, because a guessed binding would invent failures on correct code — and
  they are asserted against the sweep in both directions, so a new subject
  forces a decision and a departed one cannot linger.
- **Extraction is asserted, not assumed.**
  ``test_extraction_covers_every_str_call`` pins the AST sweep against an
  independent tokenizer count of ``str(`` call sites. An extractor that quietly
  stopped matching would otherwise turn this whole file into a green no-op.

**Scope, and the two exclusions the #588 review cleared.** The sweep covers
``mureo/google_ads/`` — the only tree that reads Google Ads protos.
``mureo/analysis/tracking/sources.py`` stringifies mureo's own ``AdStatus``
dataclass enum, not a protobuf, and is out of the swept root for that reason.
``client.py`` reads ``.name`` off ``GoogleAdsException.failure``, which the SDK
always hands back as proto-plus regardless of the flag, so ``.name`` is correct
there; it is also not a ``str()`` read, and ``.name`` on raw protobuf raises
rather than lying, which is why this sweep is about ``str()`` alone.
"""

from __future__ import annotations

import ast
import importlib
import io
import pathlib
import tokenize

import pytest
from google.protobuf.descriptor import FieldDescriptor

from tests.test_gaql_field_names import (
    _API_VERSION,
    _MAPPER_SUBJECTS,
    _UNBOUND_MAPPER_SUBJECTS,
    _dotted,
    _imported_names,
)

_SOURCE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "mureo" / "google_ads"

#: The proto packages a subject can be bound to.
_PROTO_PACKAGES = ("resources", "common", "services", "errors")


@pytest.fixture(scope="module")
def proto_packages() -> dict[str, object]:
    return {
        name: importlib.import_module(f"google.ads.googleads.{_API_VERSION}.{name}")
        for name in _PROTO_PACKAGES
    }


#: ``(module file name, subject variable)`` -> the proto message it holds, as
#: ``(package, class name)``. Keyed by file because the same variable name
#: holds different messages in different modules (``asset`` is a bare ``Asset``
#: in ``_media.py`` and a row in ``mappers.py``). ``mappers.py`` is absent on
#: purpose: its subjects are already bound in ``test_gaql_field_names.py`` and
#: are reused from there rather than re-declared.
_STR_READ_SUBJECTS: dict[tuple[str, str], tuple[str, str]] = {
    ("_ads.py", "row"): ("services", "GoogleAdsRow"),
    ("_ads.py", "entry"): ("common", "PolicyTopicEntry"),
    ("_analysis_auction.py", "row"): ("services", "GoogleAdsRow"),
    ("_analysis_keywords.py", "row"): ("services", "GoogleAdsRow"),
    ("_analysis_performance.py", "row"): ("services", "GoogleAdsRow"),
    ("_creative.py", "ad"): ("resources", "Ad"),
    ("_diagnostics.py", "row"): ("services", "GoogleAdsRow"),
    ("_diagnostics.py", "ad"): ("resources", "AdGroupAd"),
    ("_diagnostics.py", "cc"): ("resources", "CampaignCriterion"),
    ("_extensions_conversions.py", "row"): ("services", "GoogleAdsRow"),
    ("_extensions_targeting.py", "row"): ("services", "GoogleAdsRow"),
    ("_extensions_targeting.py", "crit"): ("resources", "AdGroupCriterion"),
    ("_media.py", "asset"): ("resources", "Asset"),
    ("_media.py", "image"): ("common", "ImageAsset"),
    ("_placement_mappers.py", "campaign"): ("resources", "Campaign"),
    ("_placement_mappers.py", "ad_group"): ("resources", "AdGroup"),
    ("accounts.py", "child"): ("resources", "CustomerClient"),
    ("client.py", "row"): ("services", "GoogleAdsRow"),
    ("client.py", "budget"): ("resources", "CampaignBudget"),
    ("client.py", "error"): ("errors", "GoogleAdsError"),
}

#: Subjects deliberately left unchecked, each with the reason it cannot be
#: bound to one message. Asserted below in both directions so the sweep can
#: never quietly shrink to nothing by "skipping" everything.
_UNRESOLVABLE_STR_READ_SUBJECTS: dict[tuple[str, str], str] = {
    (
        "_placement_mappers.py",
        "criterion",
    ): "AdGroupCriterion or CampaignCriterion — the mapper serves both levels",
}


def _field_at(message: object, segments: list[str]) -> FieldDescriptor | None:
    """The descriptor of the field ``segments`` names, or ``None``.

    ``test_gaql_field_names._walk`` answers whether a path exists; this needs
    the field itself to ask what type it is, which is why it descends rather
    than reusing that helper. Both spellings of a mangled name are accepted:
    the descriptor carries the API name (``type``) while the attribute read
    uses proto-plus's mangling (``type_``).
    """
    fields = {f.name: f for f in message.pb(message()).DESCRIPTOR.fields}  # type: ignore[attr-defined]
    field: FieldDescriptor | None = None
    for segment in segments:
        field = (
            fields.get(segment)
            or fields.get(segment.removesuffix("_"))
            or fields.get(segment + "_")
        )
        if field is None:
            return None
        fields = (
            {f.name: f for f in field.message_type.fields}
            if field.message_type is not None
            else {}
        )
    return field


def _str_attribute_reads() -> list[tuple[str, int, str]]:
    """Every ``str(<attribute chain>)`` in the package.

    Returned as ``(module file name, line number, dotted path)``. A bare
    ``str(name)`` is not a field read and a chain rooted at an imported name is
    not an instance, so neither is returned.
    """
    reads: list[tuple[str, int, str]] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = _imported_names(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "str"
                and len(node.args) == 1
            ):
                continue
            dotted = _dotted(node.args[0])
            if dotted is None or "." not in dotted:
                continue
            if dotted.split(".")[0] in imported:
                continue
            reads.append((path.name, node.lineno, dotted))
    return reads


def _str_call_sites(source: str) -> int:
    """``str(`` call sites in ``source``, counted by the tokenizer.

    Independent of the AST sweep on purpose — this is what pins it. A regex
    would count the ``str()`` written in a docstring; the tokenizer classifies
    strings and comments for us, and several of this package's ``str()``
    mentions are prose about this very bug.
    """
    count = 0
    previous: tokenize.TokenInfo | None = None
    ignored = {
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.COMMENT,
        tokenize.INDENT,
        tokenize.DEDENT,
    }
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if (
            token.type == tokenize.OP
            and token.string == "("
            and previous is not None
            and previous.type == tokenize.NAME
            and previous.string == "str"
        ):
            count += 1
        if token.type not in ignored:
            previous = token
    return count


def _binding_for(module: str, subject: str) -> tuple[str, str] | None:
    """The proto message bound to ``subject`` in ``module``, if any."""
    if module == "mappers.py":
        return _MAPPER_SUBJECTS.get(subject)
    return _STR_READ_SUBJECTS.get((module, subject))


def _skip_reason(module: str, subject: str) -> str | None:
    """Why ``subject`` in ``module`` cannot be bound to one message, if so."""
    if module == "mappers.py":
        return _UNBOUND_MAPPER_SUBJECTS.get(subject)
    return _UNRESOLVABLE_STR_READ_SUBJECTS.get((module, subject))


def _message_for(binding: tuple[str, str], packages: dict[str, object]) -> object:
    package, class_name = binding
    return getattr(packages[package], class_name)


@pytest.mark.unit
def test_extraction_covers_every_str_call() -> None:
    """The AST sweep must see every ``str(...)`` call site in the package.

    Not every one is a field read — most take a plain name — but if the sweep
    stopped seeing ``str`` calls at all it would pass by checking nothing, and
    that is the one failure this file cannot afford.
    """
    swept = 0
    tokenized = 0
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        swept += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
        )
        tokenized += _str_call_sites(source)
    assert swept == tokenized, (
        f"the AST sweep saw {swept} str() call site(s) but the tokenizer "
        f"counted {tokenized}. Reconcile the two before trusting this file's "
        "result."
    )


@pytest.mark.unit
def test_every_str_read_subject_is_classified() -> None:
    """Every ``str(x.y)`` subject is either bound to a proto or skipped.

    Both directions: a new subject forces a decision, and a subject that
    disappears cannot leave a stale binding behind pretending the sweep still
    covers it. ``mappers.py`` is checked one-way only, because its bindings are
    owned by ``test_gaql_field_names.py`` and cover more subjects than reach a
    ``str()``.
    """
    subjects = {
        (module, path.split(".")[0]) for module, _, path in _str_attribute_reads()
    }
    unclassified = sorted(
        key
        for key in subjects
        if _binding_for(*key) is None and _skip_reason(*key) is None
    )
    assert not unclassified, (
        "these str() read subjects are bound to nothing. Bind each to its proto "
        "message in _STR_READ_SUBJECTS, or list it in "
        f"_UNRESOLVABLE_STR_READ_SUBJECTS with the reason: {unclassified}"
    )
    declared = set(_STR_READ_SUBJECTS) | set(_UNRESOLVABLE_STR_READ_SUBJECTS)
    assert not sorted(declared - subjects), (
        "these entries name a subject this package no longer reads through "
        f"str(), so they verify nothing: {sorted(declared - subjects)}"
    )


@pytest.mark.unit
def test_every_bound_str_read_resolves_on_the_proto(
    proto_packages: dict[str, object],
) -> None:
    """A binding that resolves nothing would make the enum sweep below inert."""
    problems: list[str] = []
    for module, lineno, path in _str_attribute_reads():
        binding = _binding_for(module, path.split(".")[0])
        if binding is None:
            continue
        message = _message_for(binding, proto_packages)
        if _field_at(message, path.split(".")[1:]) is None:
            problems.append(f"{module}:{lineno}: {path} — not a field of {binding[1]}")
    assert not problems, (
        f"{len(problems)} str() read(s) name nothing on the {_API_VERSION} "
        "proto they are bound to. Either the binding is wrong, or the read is "
        "— and an unresolvable read is one the enum sweep cannot check:\n  "
        + "\n  ".join(problems)
    )


@pytest.mark.unit
def test_every_bound_subject_contributes_a_read() -> None:
    """A binding no read reaches verifies nothing."""
    reached = {
        (module, path.split(".")[0]) for module, _, path in _str_attribute_reads()
    }
    silent = sorted(set(_STR_READ_SUBJECTS) - reached)
    assert not silent, f"these bindings are reached by no str() read: {silent}"


@pytest.mark.unit
def test_no_bare_str_is_taken_on_a_proto_enum_field(
    proto_packages: dict[str, object],
) -> None:
    """The sweep itself. A failure here is #588 happening again."""
    problems: list[str] = []
    for module, lineno, path in _str_attribute_reads():
        binding = _binding_for(module, path.split(".")[0])
        if binding is None:
            continue
        field = _field_at(_message_for(binding, proto_packages), path.split(".")[1:])
        if field is not None and field.type == FieldDescriptor.TYPE_ENUM:
            problems.append(
                f"mureo/google_ads/{module}:{lineno}: str({path}) reads the "
                f"{field.enum_type.name} enum"
            )
    assert not problems, (
        f"{len(problems)} enum field(s) are read with a bare str(). On the "
        "raw-protobuf path this client runs on that yields the number, not the "
        "name, and any .split('.') after it is a no-op. Resolve them through "
        "mureo.google_ads._enum_names.map_enum_name against an SDK-derived "
        "map:\n  " + "\n  ".join(problems)
    )
