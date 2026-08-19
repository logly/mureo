"""A platform plugin's own account of how its platform works, always on (#648).

The only text a plugin could put in front of the model unconditionally used to
be its MCP tool names and descriptions: a contributed ``SKILL.md`` is
description-matched and read on demand, so a plugin's "this is how my platform
actually works" was never read on routine reporting paths — exactly where a
borrowed mental model does its damage.

These tests pin the replacement channel: a registered
:class:`~mureo.policy.platform_model.PlatformModel` is rendered into the MCP
server's ``instructions``, which the client receives in the ``initialize``
response before any tool call and independently of any skill description.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from mureo.policy.learning_rules import Evidence
from mureo.policy.platform_model import (
    MAX_STATEMENT_CHARS,
    MAX_TOTAL_CHARS,
    PlatformModel,
    platform_model,
    platform_model_instructions,
    register_platform_model,
    registered_platform_models,
    reset_platform_models,
)

_EVIDENCE = Evidence(
    source="https://example.invalid/acme/docs/delivery",
    retrieved="2026-08-19",
    quote="Acme selects delivery by eCPM. Acme does not run an auction.",
)

_STATEMENT = (
    "Acme is a closed network: delivery is selected by eCPM (estimated CTR x "
    "CPC), never by an auction against other bidders. There is no win rate, "
    "no bid floor and no automated bid strategy."
)


def _model(**overrides: object) -> PlatformModel:
    fields: dict[str, object] = {
        "platform": "acme_ads",
        "tool_prefix": "acme_ads_",
        "statement": _STATEMENT,
        "evidence": _EVIDENCE,
    }
    fields.update(overrides)
    return PlatformModel(**fields)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    reset_platform_models()
    yield
    reset_platform_models()


# ---------------------------------------------------------------------------
# The registry itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_core_ships_no_platform_models() -> None:
    """Core asserts nothing about any platform it has no quotable source for.

    The prose half of ``learning_rules``' honesty rule: absence of a
    first-party statement is reported as silence, never as a plausible guess.
    """
    assert registered_platform_models() == ()


@pytest.mark.unit
def test_third_party_can_register_and_look_up() -> None:
    register_platform_model(_model())
    assert registered_platform_models() == ("acme_ads",)
    found = platform_model("acme_ads")
    assert found is not None
    assert found.statement == _STATEMENT


@pytest.mark.unit
def test_re_registration_replaces() -> None:
    register_platform_model(_model())
    register_platform_model(_model(statement="Acme prices delivery per click."))
    assert registered_platform_models() == ("acme_ads",)
    found = platform_model("acme_ads")
    assert found is not None
    assert found.statement == "Acme prices delivery per click."


@pytest.mark.unit
def test_reset_restores_the_builtin_registry() -> None:
    register_platform_model(_model())
    reset_platform_models()
    assert registered_platform_models() == ()


# ---------------------------------------------------------------------------
# No guessing: every entry carries first-party evidence
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("field", ["platform", "tool_prefix", "statement"])
def test_empty_required_field_is_refused(field: str) -> None:
    with pytest.raises(ValueError):
        register_platform_model(_model(**{field: "  "}))


@pytest.mark.unit
@pytest.mark.parametrize("field", ["source", "retrieved", "quote"])
def test_blank_evidence_field_is_refused(field: str) -> None:
    evidence = Evidence(
        **{
            **{"source": "https://x.invalid", "retrieved": "2026-08-19", "quote": "q"},
            field: " ",
        }
    )
    with pytest.raises(ValueError):
        register_platform_model(_model(evidence=evidence))


@pytest.mark.unit
@pytest.mark.parametrize("retrieved", ["yesterday", "2026-8-19", "2026-13-01"])
def test_retrieved_must_be_an_iso_date(retrieved: str) -> None:
    evidence = Evidence(
        source="https://x.invalid", retrieved=retrieved, quote="Acme has no auction."
    )
    with pytest.raises(ValueError):
        register_platform_model(_model(evidence=evidence))


# ---------------------------------------------------------------------------
# Length is capped — always-on text is a budget, not a free surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_statement_over_the_cap_is_refused_at_registration() -> None:
    with pytest.raises(ValueError):
        register_platform_model(_model(statement="x" * (MAX_STATEMENT_CHARS + 1)))
    assert registered_platform_models() == ()


@pytest.mark.unit
def test_statement_at_the_cap_is_accepted() -> None:
    register_platform_model(_model(statement="x" * MAX_STATEMENT_CHARS))
    assert registered_platform_models() == ("acme_ads",)


@pytest.mark.unit
def test_multiline_statement_is_refused() -> None:
    with pytest.raises(ValueError):
        register_platform_model(_model(statement="Acme has no auction.\nAlso this."))


@pytest.mark.unit
def test_total_budget_drops_the_overflow_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Many registered platforms cannot silently grow the always-on block."""
    statement = "x" * MAX_STATEMENT_CHARS
    count = MAX_TOTAL_CHARS // MAX_STATEMENT_CHARS + 2
    for index in range(count):
        register_platform_model(
            _model(
                platform=f"p{index:02d}",
                tool_prefix=f"p{index:02d}_",
                statement=statement,
            )
        )
    tool_names = [f"p{index:02d}_list" for index in range(count)]
    with caplog.at_level(logging.WARNING):
        text = platform_model_instructions(tool_names)
    lines = [line for line in text.splitlines() if line.startswith("- ")]
    # Whole statements only, in platform order, never more than the budget.
    assert 0 < len(lines) < count
    assert sum(len(line) for line in lines) <= MAX_TOTAL_CHARS
    assert all(len(line) > MAX_STATEMENT_CHARS for line in lines)
    assert "- p00:" in text
    assert f"- p{count - 1:02d}:" not in text
    assert any("platform model" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Scope: in the block when the platform's tools are, absent when they are not
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_statement_renders_when_the_platform_is_in_scope() -> None:
    register_platform_model(_model())
    text = platform_model_instructions(["acme_ads_campaigns_list", "mureo_state_get"])
    assert _STATEMENT in text
    assert "acme_ads" in text


@pytest.mark.unit
def test_statement_is_absent_when_the_platform_has_no_tools_here() -> None:
    register_platform_model(_model())
    assert platform_model_instructions(["google_ads_campaigns_list"]) == ""


@pytest.mark.unit
def test_unregistered_platform_contributes_nothing() -> None:
    """No registration, no prose — mureo does not fill the gap with a guess."""
    assert platform_model_instructions(["google_ads_campaigns_list"]) == ""
    assert platform_model_instructions(["meta_ads_campaigns_list"]) == ""


@pytest.mark.unit
def test_no_tools_at_all_renders_nothing() -> None:
    register_platform_model(_model())
    assert platform_model_instructions([]) == ""


# ---------------------------------------------------------------------------
# The MCP server surface
# ---------------------------------------------------------------------------


def _server_module():  # type: ignore[no-untyped-def]
    from mureo.mcp import server as mcp_server_module

    return mcp_server_module


def _patch_default_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from mureo.core.runtime_context import DEFAULT_WORKSPACE_ID

    monkeypatch.setattr(
        "mureo.core.runtime_context.get_runtime_context",
        lambda: SimpleNamespace(workspace_id=DEFAULT_WORKSPACE_ID),
    )


@pytest.mark.unit
def test_default_install_instructions_stay_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backward compatibility: nothing registered ⇒ byte-identical
    ``InitializeResult``."""
    server = _server_module()
    _patch_default_workspace(monkeypatch)
    assert server._server_instructions() is None


@pytest.mark.unit
def test_registered_model_reaches_server_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server_module()
    _patch_default_workspace(monkeypatch)
    # ``google_ads_`` is a prefix the built-in tool list really carries, so
    # this exercises the same scope decision a plugin's prefix would hit.
    register_platform_model(_model(platform="google_ads", tool_prefix="google_ads_"))
    text = server._server_instructions()
    assert text is not None
    assert _STATEMENT in text


@pytest.mark.unit
def test_workspace_text_and_model_text_coexist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    server = _server_module()
    monkeypatch.setattr(
        "mureo.core.runtime_context.get_runtime_context",
        lambda: SimpleNamespace(workspace_id="agency:acme"),
    )
    register_platform_model(_model(platform="google_ads", tool_prefix="google_ads_"))
    text = server._server_instructions()
    assert text is not None
    assert "agency:acme" in text
    assert _STATEMENT in text


@pytest.mark.unit
def test_workspace_only_text_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """A multi-workspace install with no models keeps the exact old string."""
    from types import SimpleNamespace

    server = _server_module()
    monkeypatch.setattr(
        "mureo.core.runtime_context.get_runtime_context",
        lambda: SimpleNamespace(workspace_id="agency:globex"),
    )
    assert server._server_instructions() == (
        "This mureo server is bound to workspace 'agency:globex'. Every tool "
        "here reads and writes ONLY that workspace's data. If the user is "
        "working on a different client/workspace, do NOT use this server — use "
        "the mureo server bound to that workspace instead. Never assume a tool "
        "call here acts on any workspace other than 'agency:globex'."
    )


@pytest.mark.unit
def test_model_text_rides_the_initialize_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Always-on means: it is in ``InitializeResult``, before any tool call."""
    server = _server_module()
    _patch_default_workspace(monkeypatch)
    register_platform_model(_model(platform="google_ads", tool_prefix="google_ads_"))
    created = server._create_server()
    options = created.create_initialization_options()
    assert options.instructions is not None
    assert _STATEMENT in options.instructions


@pytest.mark.unit
def test_always_on_route_does_not_go_through_skill_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression pin for the bug this feature exists to fix (#648).

    The failing route was a description-matched ``SKILL.md``. If this surface
    ever grows a dependency on skill discovery or skill matching, it inherits
    that failure mode — so both are made to explode for the duration.
    """
    server = _server_module()
    _patch_default_workspace(monkeypatch)

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("platform-model instructions must not consult skills")

    monkeypatch.setattr("mureo.core.skills.discovery.discover_skills", _boom)
    monkeypatch.setattr("mureo.core.skills.matcher.match_skills", _boom)

    register_platform_model(_model(platform="google_ads", tool_prefix="google_ads_"))
    created = server._create_server()
    assert _STATEMENT in (created.create_initialization_options().instructions or "")
