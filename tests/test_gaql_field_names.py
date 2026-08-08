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
  pins the query count against an independent count of `FROM` clauses. An
  extractor that silently stopped matching would otherwise turn this whole
  file into a green no-op — which it briefly was, when implicitly concatenated
  string literals were being skipped and 27 field references went unchecked.
"""

from __future__ import annotations

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
    fields = {f.name: f for f in message.pb(message()).DESCRIPTOR.fields}  # type: ignore[attr-defined]
    walked = parts[0]
    for segment in parts[1:]:
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
