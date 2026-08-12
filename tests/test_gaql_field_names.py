"""Every field selected in a GAQL query must exist on the Google Ads proto.

**Why this file exists.** `google_ads_change_history_list` shipped selecting
`change_event.changed_resource_name`, a field that does not exist — the proto
field is `change_resource_name`, no "d". The API rejects such a SELECT, and
the mapper reading the same wrong name yields `""` in silence, so the tool was
inert in production and nothing in the suite could tell: every test built row
dicts by hand, and `MagicMock` answers `hasattr` for any name and returns a
truthy mock, so a misspelling passes every assertion written against it.

The general shape of that gap is "`_search` is mocked everywhere, so the query
string is never read by anything". This closes it for the whole tree rather
than for the one query that was caught: the queries are extracted from source
and every dotted field path is resolved against the vendored protobuf
descriptors.

Two properties worth keeping when editing this file:

- **Derived, never enumerated.** Both the query list and the field list come
  from the tree and the SDK. A hardcoded expectation would go stale silently,
  which is the failure mode being fixed.
- **Extraction is asserted, not assumed.** `test_extraction_covers_every_query`
  pins the query count against an independent count of `FROM` clauses, and
  `test_extraction_covers_every_mapper_field_read` does the same one layer
  down for the mapper sweep. An extractor that silently stopped matching would
  otherwise turn this whole file into a green no-op — which it briefly was,
  when implicitly concatenated string literals were being skipped and 27 field
  references went unchecked, and again when the `_safe_str` / `_safe_int` /
  `_safe_float` idiom — the way most mapper fields are read — was invisible to
  the mapper sweep.

The second half of the file applies both properties one layer down, to the
literal attribute reads in `google_ads/mappers.py`: a SELECT sweep cannot see
`hasattr(campaign, "end_date")`, and that is exactly how `map_campaign` came to
read two fields v23 does not have.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import re

import pytest

#: The API version mureo's client code imports. Kept next to the imports it
#: mirrors (``mureo.google_ads.*`` import ``googleads.v23`` directly); if those
#: move, this must move with them or the sweep validates the wrong schema.
_API_VERSION = "v23"

_SOURCE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "mureo"

# ``SELECT <fields> FROM <resource>``. DOTALL because most queries are
# multi-line triple-quoted strings.
_QUERY_RE = re.compile(r"SELECT\s+(.*?)\bFROM\s+([a-z_][a-z0-9_]*)", re.S)
_FROM_RE = re.compile(r"\bFROM\s+[a-z_][a-z0-9_]*")
# A dotted GAQL field path: ``campaign.id``, ``ad_group_ad.ad.final_urls``.
_FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+$")


@pytest.fixture(scope="module")
def protos() -> tuple[object, object]:
    resources = importlib.import_module(
        f"google.ads.googleads.{_API_VERSION}.resources"
    )
    common = importlib.import_module(f"google.ads.googleads.{_API_VERSION}.common")
    return resources, common


def _message_for(prefix: str, protos: tuple[object, object]) -> object | None:
    """Resolve a GAQL prefix to its proto message class, or ``None``.

    ``metrics`` and ``segments`` are common types; everything else is a
    resource, named in PascalCase.
    """
    resources, common = protos
    if prefix == "metrics":
        return common.Metrics  # type: ignore[attr-defined]
    if prefix == "segments":
        return common.Segments  # type: ignore[attr-defined]
    return getattr(resources, "".join(p.title() for p in prefix.split("_")), None)


def _resolve(path: str, protos: tuple[object, object]) -> str | None:
    """Return why ``path`` is not a real field, or ``None`` when it is."""
    parts = path.split(".")
    message = _message_for(parts[0], protos)
    if message is None:
        return f"unknown resource prefix {parts[0]!r}"
    return _walk(message, parts[1:], parts[0])


def _walk(message: object, segments: list[str], walked: str) -> str | None:
    """Follow ``segments`` down ``message``; return the first failure or ``None``."""
    fields = {f.name: f for f in message.pb(message()).DESCRIPTOR.fields}  # type: ignore[attr-defined]
    for segment in segments:
        # proto-plus mangles names that collide with Python builtins/keywords
        # (``type`` -> ``type_``). GAQL uses the UNMANGLED API name, so accept
        # either spelling — rejecting ``asset.type`` here would be a false
        # positive on correct code.
        field = fields.get(segment) or fields.get(segment + "_")
        if field is None:
            return f"{walked!r} has no field {segment!r}"
        fields = (
            {f.name: f for f in field.message_type.fields}
            if field.message_type is not None
            else {}
        )
        walked = f"{walked}.{segment}"
    return None


def _iter_queries() -> list[tuple[pathlib.Path, str, str]]:
    """Every ``(file, select_body, resource)`` GAQL query in the tree."""
    found: list[tuple[pathlib.Path, str, str]] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for select_body, resource in _QUERY_RE.findall(source):
            found.append((path, select_body, resource))
    return found


def _fields_in(select_body: str) -> list[str]:
    """The dotted field paths in one SELECT clause."""
    paths: list[str] = []
    for raw in select_body.split(","):
        # Quotes are stripped because many queries are built from implicitly
        # concatenated string literals, so a token arrives as `"campaign.id`
        # with the opening quote attached. Missing this silently skipped 27
        # field references across two files.
        token = raw.replace('"', " ").replace("'", " ").replace("\\", " ").strip()
        token = token.split()[0].strip("()") if token.split() else ""
        if _FIELD_RE.match(token):
            paths.append(token)
    return paths


@pytest.mark.unit
def test_extraction_covers_every_query() -> None:
    """The extractor must see every GAQL query the tree contains.

    Without this, a regex that quietly stopped matching would make the whole
    sweep pass by checking nothing.
    """
    from_clauses = sum(
        len(_FROM_RE.findall(path.read_text(encoding="utf-8")))
        for path in _SOURCE_ROOT.rglob("*.py")
    )
    assert len(_iter_queries()) == from_clauses, (
        "GAQL query extraction is out of step with the number of FROM clauses "
        "in the tree. Fix the extractor before trusting this file's result."
    )


@pytest.mark.unit
def test_every_query_selects_at_least_one_field() -> None:
    """A query whose fields all failed to parse would be silently unchecked."""
    empty = [
        f"{path.relative_to(_SOURCE_ROOT.parent)} (FROM {resource})"
        for path, body, resource in _iter_queries()
        if not _fields_in(body)
    ]
    assert not empty, (
        "These GAQL queries yielded no parseable field paths, so nothing about "
        "them was verified:\n  " + "\n  ".join(empty)
    )


@pytest.mark.unit
def test_every_selected_gaql_field_exists_on_the_proto(
    protos: tuple[object, object],
) -> None:
    """The sweep itself. A failure here means the API would reject the query."""
    problems: list[str] = []
    for path, body, resource in _iter_queries():
        for field_path in _fields_in(body):
            error = _resolve(field_path, protos)
            if error is not None:
                problems.append(
                    f"{path.relative_to(_SOURCE_ROOT.parent)}: "
                    f"FROM {resource} selects {field_path!r} — {error}"
                )
    assert not problems, (
        f"{len(problems)} GAQL field(s) name nothing on the "
        f"{_API_VERSION} proto. The API rejects such a SELECT, and a mapper "
        f"reading the same name returns an empty value in silence:\n  "
        + "\n  ".join(problems)
    )


# ---------------------------------------------------------------------------
# The same question one layer down: attribute reads in mappers.py
# ---------------------------------------------------------------------------
#
# A SELECT sweep cannot see ``hasattr(campaign, "end_date")``, and that gap is
# not hypothetical: ``map_campaign`` read ``campaign.start_date`` /
# ``campaign.end_date`` — names the v23 Campaign does not have, it spells them
# ``start_date_time`` / ``end_date_time`` — so both keys were never populated
# and the campaign date-range diagnosis was dead. The ``hasattr`` guard made
# the omission look deliberate and ``MagicMock`` made every test agree.

_MAPPERS_PATH = _SOURCE_ROOT / "google_ads" / "mappers.py"

# A ``reader(subject, "field")`` call site, counted straight off the source so
# the AST sweep has something independent to be pinned against. ``_safe_\w+``
# is matched by name shape on purpose: it does not go through the AST helper
# derivation, so a derivation that stopped recognising the helpers shows up as
# a shortfall here instead of passing quietly.
_FIELD_READ_CALL_RE = re.compile(
    r"\b(?:hasattr|getattr|_safe_\w+)\(\s*[^,()]+?\s*,\s*[\"']", re.S
)

#: Subject variable in ``mappers.py`` -> the proto message it holds, as
#: ``(module, class name)``. Explicit on purpose: a guessed binding would
#: invent failures on correct code.
_MAPPER_SUBJECTS: dict[str, tuple[str, str]] = {
    "action": ("resources", "ConversionAction"),
    "ad": ("resources", "AdGroupAd"),
    "ad_group": ("resources", "AdGroup"),
    "callout": ("common", "CalloutAsset"),
    "campaign": ("resources", "Campaign"),
    "event": ("resources", "ChangeEvent"),
    "metrics": ("common", "Metrics"),
    "rec": ("resources", "Recommendation"),
    "row": ("services", "GoogleAdsRow"),
    "search_term_view": ("resources", "SearchTermView"),
    "sitelink": ("common", "SitelinkAsset"),
    "snippet": ("common", "TagSnippet"),
}

#: Subjects deliberately left unchecked, each with the reason it cannot be
#: bound to one message. Kept explicit and asserted below so the sweep can
#: never quietly shrink to nothing by "skipping" everything.
_UNBOUND_MAPPER_SUBJECTS: dict[str, str] = {
    "asset": "a row (asset.asset.*) or a bare asset, depending on the caller",
    "criterion": "AdGroupCriterion at one call site, CampaignCriterion at the other",
    "keyword": "carries deliberate non-proto fallbacks (keyword.id, str(keyword))",
    "member": "an enum member, not a message",
    "qi": "the quality_info of the unbound 'criterion'",
    "value": "an enum value or a plain int, not a message",
}


def _dotted(node: ast.AST) -> str | None:
    """The dotted path of an attribute chain rooted at a name, else ``None``."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _imported_names(tree: ast.Module) -> set[str]:
    """Names bound by an import — modules and classes, never proto subjects."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _field_read_helpers(tree: ast.Module) -> set[str]:
    """Module-level ``(obj, field_name, ...)`` readers, e.g. ``_safe_str``.

    Derived, never enumerated, like everything else here: a helper is any
    module-level function whose body calls ``getattr(<1st param>, <2nd param>,
    ...)``. That is exactly the shape of a field-read helper, and missing them
    is not academic — ``_safe_str`` / ``_safe_int`` / ``_safe_float`` are how
    most fields in ``mappers.py`` are read, so a sweep blind to them let a
    misspelt ``_safe_str(event, "resource_name")`` stay green while
    ``map_change_event`` returned ``""``.
    """
    helpers: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or len(node.args.args) < 2:
            continue
        obj, attr = node.args.args[0].arg, node.args.args[1].arg
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "getattr"
                and len(inner.args) >= 2
                and isinstance(inner.args[0], ast.Name)
                and inner.args[0].id == obj
                and isinstance(inner.args[1], ast.Name)
                and inner.args[1].id == attr
            ):
                helpers.add(node.name)
    return helpers


def _field_read_calls(tree: ast.Module) -> list[tuple[str | None, str]]:
    """Every ``reader(subject, "field")`` call site, as ``(subject, field)``.

    The readers are ``hasattr`` / ``getattr`` plus the module's own field-read
    helpers. ``subject`` is ``None`` when the first argument is not an
    attribute chain rooted at a name, which no call site currently is; the
    entry is still returned so the extraction assertion can see it.
    """
    readers = {"hasattr", "getattr"} | _field_read_helpers(tree)
    calls: list[tuple[str | None, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in readers
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            calls.append((_dotted(node.args[0]), node.args[1].value))
    return calls


def _mapper_attribute_reads() -> dict[str, set[str]]:
    """Every literal attribute read in ``mappers.py``, grouped by subject.

    Covers plain ``x.field`` chains plus the string literal of
    ``hasattr(x, "field")`` / ``getattr(x, "field", ...)`` and of the module's
    own ``_safe_*`` field-read helpers — the spellings a mapper uses to read a
    proto. An attribute that is *called* is a method, not a proto field, so it
    is left out.
    """
    tree = ast.parse(_MAPPERS_PATH.read_text(encoding="utf-8"))
    skip = _imported_names(tree)
    called = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    reads: dict[str, set[str]] = {}

    def record(path: str | None) -> None:
        if path is None:
            return
        root = path.split(".")[0]
        if root in skip:
            return
        reads.setdefault(root, set()).add(path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and id(node) not in called:
            record(_dotted(node))
    for subject, field in _field_read_calls(tree):
        if subject is not None:
            record(f"{subject}.{field}")
    return reads


def _mapper_message(binding: tuple[str, str], protos: tuple[object, object]) -> object:
    module_name, class_name = binding
    resources, common = protos
    module: object = {
        "resources": resources,
        "common": common,
    }.get(
        module_name
    ) or importlib.import_module(f"google.ads.googleads.{_API_VERSION}.{module_name}")
    return getattr(module, class_name)


@pytest.mark.unit
def test_extraction_covers_every_mapper_field_read() -> None:
    """The sweep must see every ``reader(subject, "field")`` site in mappers.py.

    The mapper half's counterpart to ``test_extraction_covers_every_query``,
    and for the same reason: the sweep understood only ``hasattr`` / ``getattr``
    while most reads go through ``_safe_str`` / ``_safe_int`` / ``_safe_float``,
    so a misspelt field name in any of them was checked by nothing.
    """
    source = _MAPPERS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    swept = _field_read_calls(tree)
    in_source = _FIELD_READ_CALL_RE.findall(source)
    assert len(swept) == len(in_source), (
        f"mapper field-read extraction saw {len(swept)} call site(s) but the "
        f"source contains {len(in_source)}. Either a read idiom the sweep does "
        "not understand is going unchecked, or a new helper does not match the "
        "``_safe_*`` name shape this regex counts. Reconcile the two before "
        "trusting this file's result."
    )
    assert all(subject is not None for subject in (s for s, _ in swept)), (
        "A mapper field read has a subject that is not an attribute chain "
        "rooted at a name, so it cannot be resolved against a proto. Teach "
        "_dotted about it or classify it explicitly."
    )


@pytest.mark.unit
def test_every_mapper_subject_is_classified() -> None:
    """Every attribute-read subject is either bound to a proto or skipped.

    Equality, not containment: a new subject in ``mappers.py`` forces a
    decision, and a subject that disappears cannot leave a stale binding
    behind pretending the sweep still covers it.
    """
    subjects = set(_mapper_attribute_reads())
    classified = set(_MAPPER_SUBJECTS) | set(_UNBOUND_MAPPER_SUBJECTS)
    assert subjects == classified, (
        "mappers.py attribute-read subjects are out of step with this file's "
        "classification. Bind the new subject to its proto message, or list it "
        "in _UNBOUND_MAPPER_SUBJECTS with the reason it cannot be bound.\n"
        f"  unclassified: {sorted(subjects - classified)}\n"
        f"  no longer present: {sorted(classified - subjects)}"
    )


@pytest.mark.unit
def test_mapper_sweep_actually_checks_something() -> None:
    """Every bound subject must contribute reads, or the sweep is a no-op."""
    reads = _mapper_attribute_reads()
    silent = sorted(name for name in _MAPPER_SUBJECTS if not reads.get(name))
    assert not silent, (
        "These subjects are bound to a proto message but yielded no attribute "
        f"reads, so binding them verifies nothing: {silent}"
    )


@pytest.mark.unit
def test_every_mapper_attribute_read_exists_on_the_proto(
    protos: tuple[object, object],
) -> None:
    """The sweep itself — the check the GAQL sweep above structurally cannot do."""
    reads = _mapper_attribute_reads()
    problems: list[str] = []
    for subject, binding in sorted(_MAPPER_SUBJECTS.items()):
        message = _mapper_message(binding, protos)
        for path in sorted(reads.get(subject, set())):
            error = _walk(message, path.split(".")[1:], subject)
            if error is not None:
                problems.append(f"{path} — {error} (on {binding[1]})")
    assert not problems, (
        f"{len(problems)} attribute read(s) in mappers.py name nothing on the "
        f"{_API_VERSION} proto. Behind a hasattr/getattr guard such a read is "
        f"silent: the key is simply never emitted:\n  " + "\n  ".join(problems)
    )
