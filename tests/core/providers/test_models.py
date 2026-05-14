"""Tests for ``mureo.core.providers.models``.

RED phase tests for Issue #89 Phase 1 subtasks P1-03..P1-06.

These tests pin the stable ABI surface for the shared domain models
consumed by the four domain Protocols (``CampaignProvider``,
``KeywordProvider``, ``AudienceProvider``, ``ExtensionProvider``) and by
adapters / third-party plugins.

Marks: all tests are ``@pytest.mark.unit`` — pure logic, no I/O, no
mocks needed.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
import typing
from enum import Enum

import pytest

# NOTE: These imports are expected to FAIL during the RED phase — the
# module does not exist yet. That is correct. The implementer (GREEN
# phase) will create ``mureo/core/providers/models.py``.
from mureo.core.providers.models import (  # noqa: E402
    Ad,
    AdStatus,
    Audience,
    AudienceStatus,
    Campaign,
    CampaignFilters,
    CampaignStatus,
    CreateAdRequest,
    CreateAudienceRequest,
    CreateCampaignRequest,
    DailyReportRow,
    Extension,
    ExtensionKind,
    ExtensionRequest,
    ExtensionStatus,
    Keyword,
    KeywordMatchType,
    KeywordSpec,
    KeywordStatus,
    SearchTerm,
    UpdateAdRequest,
    UpdateCampaignRequest,
)

# ---------------------------------------------------------------------------
# Reference tables (single source of truth used across cases below)
# ---------------------------------------------------------------------------

_ALL_MODELS: tuple[type, ...] = (
    Campaign,
    Ad,
    Keyword,
    KeywordSpec,
    SearchTerm,
    Audience,
    Extension,
    DailyReportRow,
    CampaignFilters,
    CreateCampaignRequest,
    UpdateCampaignRequest,
    CreateAdRequest,
    UpdateAdRequest,
    CreateAudienceRequest,
    ExtensionRequest,
)

_STATUS_ENUMS: tuple[type[Enum], ...] = (
    AdStatus,
    AudienceStatus,
    CampaignStatus,
    ExtensionStatus,
    ExtensionKind,
    KeywordMatchType,
    KeywordStatus,
)

_SNAKE_CASE_RE: re.Pattern[str] = re.compile(r"^[a-z_]+$")


# ---------------------------------------------------------------------------
# Case 1 — All domain models are frozen dataclasses
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda c: c.__name__)
def test_all_models_are_frozen_dataclasses(model_cls: type) -> None:
    """Every domain model is a ``@dataclass(frozen=True)`` with at least
    one field, and attempting to mutate an instance raises
    ``FrozenInstanceError``.
    """
    assert dataclasses.is_dataclass(
        model_cls
    ), f"{model_cls.__name__} must be a dataclass"

    fields = dataclasses.fields(model_cls)
    assert len(fields) > 0, f"{model_cls.__name__} must declare at least one field"

    # Frozen check: every dataclass must reject ``__setattr__`` post-init.
    # We construct a minimal instance by providing the smallest plausible
    # value for each required field. We do this by inspecting field types
    # at the typing-string level — not perfect, but sufficient to build a
    # frozen smoke instance.
    try:
        kwargs: dict[str, object] = {}
        hints = typing.get_type_hints(model_cls)
        for f in fields:
            if f.default is not dataclasses.MISSING:
                continue
            if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                continue
            # Required field — synthesize a value based on the resolved
            # type hint. The exact value does not matter; we only need an
            # instance to attempt mutation on.
            kwargs[f.name] = _synthesize_value(hints.get(f.name, str))
        instance = model_cls(**kwargs)
    except Exception as exc:  # pragma: no cover - synthesis fallback
        pytest.skip(f"Could not synthesize instance for {model_cls.__name__}: {exc}")

    with pytest.raises(dataclasses.FrozenInstanceError):
        # Field name doesn't matter — any attribute assignment must fail.
        instance.__setattr__(fields[0].name, kwargs.get(fields[0].name))


def _synthesize_value(hint: object) -> object:
    """Best-effort minimal value for a type hint, used only to build a
    smoke-test instance for the frozen-check.
    """
    from datetime import date, datetime, timezone

    origin = typing.get_origin(hint)
    args = typing.get_args(hint)

    # Optional[T] / T | None
    if origin is typing.Union or (origin is not None and type(None) in args):
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _synthesize_value(non_none[0])
        return None

    # tuple[T, ...]
    if origin in (tuple,):
        return tuple()

    if hint is str:
        return ""
    if hint is int:
        return 0
    if hint is float:
        return 0.0
    if hint is bool:
        return False
    if hint is date:
        return date(2024, 1, 1)
    if hint is datetime:
        return datetime(2024, 1, 1, tzinfo=timezone.utc)
    if isinstance(hint, type) and issubclass(hint, Enum):
        return next(iter(hint))
    return None


# ---------------------------------------------------------------------------
# Case 2 — Status / kind enums are StrEnum with snake_case values
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("enum_cls", _STATUS_ENUMS, ids=lambda c: c.__name__)
def test_status_enums_are_strenum_snake_case(enum_cls: type[Enum]) -> None:
    """Every status / kind enum mixes ``str`` (StrEnum semantics) and
    every member's ``.value`` matches ``^[a-z_]+$``.
    """
    assert issubclass(
        enum_cls, str
    ), f"{enum_cls.__name__} must subclass str (StrEnum semantics)"
    assert issubclass(enum_cls, Enum), f"{enum_cls.__name__} must be an Enum"

    for member in enum_cls:
        assert isinstance(member, str)
        assert _SNAKE_CASE_RE.fullmatch(member.value), (
            f"{enum_cls.__name__}.{member.name}={member.value!r} " f"is not snake_case"
        )
        # Strict StrEnum: ``str(member)`` must equal the raw value (no
        # ``ClassName.MEMBER`` leak).
        assert str(member) == member.value


# ---------------------------------------------------------------------------
# Case 3 — Required enum members are present
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("enum_cls", "required_members"),
    [
        (AdStatus, {"ENABLED", "PAUSED", "REMOVED"}),
        (AudienceStatus, {"ENABLED", "REMOVED"}),
        (CampaignStatus, {"ENABLED", "PAUSED", "REMOVED"}),
        (ExtensionStatus, {"ENABLED", "PAUSED", "REMOVED"}),
        (ExtensionKind, {"SITELINK", "CALLOUT", "CONVERSION"}),
        (KeywordMatchType, {"EXACT", "PHRASE", "BROAD"}),
        (KeywordStatus, {"ENABLED", "PAUSED", "REMOVED"}),
    ],
    ids=lambda v: v.__name__ if isinstance(v, type) else "members",
)
def test_required_enum_members(
    enum_cls: type[Enum],
    required_members: set[str],
) -> None:
    """Each enum must contain at least the documented required members
    (additional members are allowed; this is a subset check, not equality).
    """
    actual = {m.name for m in enum_cls}
    missing = required_members - actual
    assert not missing, (
        f"{enum_cls.__name__} is missing required members: {sorted(missing)}; "
        f"has: {sorted(actual)}"
    )


# ---------------------------------------------------------------------------
# Case 4 — Date / datetime contract: dates are date-typed, not int epoch
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model_cls", "date_field_names"),
    [
        (DailyReportRow, ("date",)),
        # CreateCampaignRequest has optional start_date / end_date — when
        # present, must be ``date | None``, never ``int`` / ``float``.
        (CreateCampaignRequest, ("start_date", "end_date")),
    ],
    ids=lambda v: v.__name__ if isinstance(v, type) else "fields",
)
def test_dates_are_date_typed_not_int_epoch(
    model_cls: type,
    date_field_names: tuple[str, ...],
) -> None:
    """Date fields must be typed as ``datetime.date`` (or ``datetime``),
    never ``int`` / ``float`` (no epoch ints, no ISO strings).
    """
    from datetime import date, datetime

    hints = typing.get_type_hints(model_cls)

    for field_name in date_field_names:
        assert field_name in hints, (
            f"{model_cls.__name__} must declare field {field_name!r} "
            f"(per Phase 1 ABI)"
        )
        hint = hints[field_name]
        # Resolve Optional[date] / date | None to its non-None member.
        args = typing.get_args(hint)
        if type(None) in args:
            non_none = [a for a in args if a is not type(None)]
            assert len(non_none) == 1, (
                f"{model_cls.__name__}.{field_name} optional must wrap "
                f"a single date-like type; got {hint!r}"
            )
            inner = non_none[0]
        else:
            inner = hint

        assert inner in (date, datetime), (
            f"{model_cls.__name__}.{field_name} must be typed as "
            f"datetime.date or datetime.datetime; got {inner!r}"
        )
        # Explicitly forbid int / float to make the failure mode obvious
        # if a future implementer regresses to epoch seconds.
        assert inner is not int, (
            f"{model_cls.__name__}.{field_name} must NOT be int "
            f"(no epoch seconds at the Protocol boundary)"
        )
        assert inner is not float, (
            f"{model_cls.__name__}.{field_name} must NOT be float "
            f"(no epoch seconds at the Protocol boundary)"
        )


# ---------------------------------------------------------------------------
# Case 5 — Required vs optional field boundaries for DTOs
# ---------------------------------------------------------------------------


# Curated required/optional split from the HANDOFF "Models design decisions"
# table. Additional optional fields are allowed; required fields must have
# no default; named optional fields must have a default.
_REQUIRED_OPTIONAL_TABLE: tuple[tuple[type, frozenset[str], frozenset[str]], ...] = (
    (
        CreateCampaignRequest,
        frozenset({"name", "daily_budget_micros"}),
        frozenset({"start_date", "end_date", "bidding_strategy"}),
    ),
    (
        UpdateCampaignRequest,
        frozenset(),  # all-optional, partial-update semantics
        frozenset({"name", "daily_budget_micros", "status", "bidding_strategy"}),
    ),
    (
        CreateAdRequest,
        frozenset({"ad_group_id", "headlines", "descriptions"}),
        frozenset({"final_urls", "path1", "path2"}),
    ),
    (
        UpdateAdRequest,
        frozenset(),
        frozenset({"headlines", "descriptions", "final_urls", "path1", "path2"}),
    ),
    (
        CreateAudienceRequest,
        frozenset({"name"}),
        frozenset({"description", "seed_audience_id"}),
    ),
    (
        ExtensionRequest,
        frozenset({"kind", "text"}),
        frozenset({"url", "description1", "description2"}),
    ),
    (
        KeywordSpec,
        frozenset({"text", "match_type"}),
        frozenset({"cpc_bid_micros"}),
    ),
    (
        CampaignFilters,
        frozenset(),
        frozenset({"status", "name_contains"}),
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model_cls", "required_fields", "optional_fields"),
    _REQUIRED_OPTIONAL_TABLE,
    ids=lambda v: v.__name__ if isinstance(v, type) else "fields",
)
def test_required_vs_optional_field_boundaries(
    model_cls: type,
    required_fields: frozenset[str],
    optional_fields: frozenset[str],
) -> None:
    """Required fields must have NO default; the named optional fields
    must each carry a default (so partial-update semantics work).
    Additional unrelated optional fields are allowed (forward compat).
    """
    fields_by_name = {f.name: f for f in dataclasses.fields(model_cls)}

    for name in required_fields:
        assert (
            name in fields_by_name
        ), f"{model_cls.__name__} must declare required field {name!r}"
        f = fields_by_name[name]
        no_default = (
            f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING  # type: ignore[misc]
        )
        assert no_default, (
            f"{model_cls.__name__}.{name} is documented as REQUIRED but "
            f"has a default; remove it."
        )

    for name in optional_fields:
        assert (
            name in fields_by_name
        ), f"{model_cls.__name__} must declare optional field {name!r}"
        f = fields_by_name[name]
        has_default = (
            f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        )
        assert has_default, (
            f"{model_cls.__name__}.{name} is documented as OPTIONAL but "
            f"has no default; add one (likely ``= None``)."
        )


# ---------------------------------------------------------------------------
# Case 6 — models.py allows only ``mureo.core.providers.capabilities``
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_models_module_has_no_internal_mureo_imports_other_than_capabilities() -> None:
    """``models.py`` is a foundation-layer module sitting alongside
    ``capabilities.py`` and ``base.py``. The only allowed internal
    ``mureo.*`` import is ``mureo.core.providers.capabilities`` (and only
    if needed — the implementer may not need it).

    Uses ``ast.parse`` on the module's source to scan every ``Import``
    and ``ImportFrom`` node. ``TYPE_CHECKING``-guarded imports are
    intentionally treated identically to runtime imports.
    """
    import mureo.core.providers.models as models_module

    source_path = inspect.getsourcefile(models_module)
    assert source_path is not None, "Could not locate models.py on disk"

    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)

    own_module = models_module.__name__  # "mureo.core.providers.models"
    allowed = {"mureo.core.providers.capabilities"}
    offending: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (
                    alias.name.startswith("mureo.")
                    and alias.name != own_module
                    and alias.name not in allowed
                ):
                    offending.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level > 0:
                offending.append(f"from {'.' * node.level}{mod} import ... (relative)")
            elif mod.startswith("mureo.") and mod != own_module and mod not in allowed:
                offending.append(f"from {mod} import ...")
            elif mod == "mureo":
                offending.append("from mureo import ...")

    assert offending == [], (
        "models.py may only import from mureo.core.providers.capabilities "
        f"among internal mureo.* modules. Found: {offending}"
    )


# ---------------------------------------------------------------------------
# Case 7 — KeywordSpec.text non-empty invariant is documented in docstring
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_keyword_spec_text_non_empty_invariant_documented() -> None:
    """``KeywordSpec`` has no ``__post_init__`` validator in Phase 1
    (the Protocol layer is purely structural), but its docstring MUST
    mention the non-empty-text contract so adapter authors know to
    enforce it.
    """
    doc = inspect.getdoc(KeywordSpec) or ""
    assert "non-empty" in doc.lower(), (
        "KeywordSpec docstring must mention the 'non-empty' text contract "
        "so adapter authors enforce it at the adapter layer. "
        f"Got docstring: {doc!r}"
    )


# ---------------------------------------------------------------------------
# Case 8 — collection fields use tuple[T, ...], never list[T]
# ---------------------------------------------------------------------------


# Field-level "collection of T" annotations across the Phase 1 models.
# When in doubt, the adapter must `tuple(...)`-convert before returning.
_COLLECTION_FIELDS: tuple[tuple[type, str], ...] = (
    (CreateAdRequest, "headlines"),
    (CreateAdRequest, "descriptions"),
    (UpdateAdRequest, "headlines"),
    (UpdateAdRequest, "descriptions"),
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model_cls", "field_name"),
    _COLLECTION_FIELDS,
    ids=lambda v: v.__name__ if isinstance(v, type) else v,
)
def test_dataclass_immutability_via_tuple_for_collections(
    model_cls: type,
    field_name: str,
) -> None:
    """Any model field whose semantic is "a collection of T" must be
    annotated as ``tuple[T, ...]`` (or ``tuple[T, ...] | None`` for
    optional collections), never ``list[T]``. This mirrors the existing
    ``mureo/context/models.py`` immutability convention.
    """
    hints = typing.get_type_hints(model_cls)
    assert (
        field_name in hints
    ), f"{model_cls.__name__} must declare field {field_name!r}"
    hint = hints[field_name]

    # Unwrap Optional[T] / T | None
    args = typing.get_args(hint)
    if type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        assert len(non_none) == 1, (
            f"{model_cls.__name__}.{field_name} optional must wrap a "
            f"single collection type; got {hint!r}"
        )
        inner = non_none[0]
    else:
        inner = hint

    origin = typing.get_origin(inner)
    assert origin is tuple, (
        f"{model_cls.__name__}.{field_name} must be typed as "
        f"tuple[T, ...] (immutable); got {inner!r}. Use tuple, not list."
    )
    # Defensive: explicitly reject list at the origin level.
    assert origin is not list, (
        f"{model_cls.__name__}.{field_name} must NOT be list[...] "
        f"(immutability rule)"
    )
