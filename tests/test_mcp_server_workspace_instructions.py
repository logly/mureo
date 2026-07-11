"""MCP server ``instructions`` name the bound workspace.

When several mureo servers are configured (one per workspace) in a host that
exposes all of them to every conversation, each server must tell the model which
workspace it is bound to. The default single-workspace install must stay
byte-identical (no instructions).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mureo.core.runtime_context import DEFAULT_WORKSPACE_ID, RuntimeContextFactoryError


def _import_server_module():
    from mureo.mcp import server as mcp_server_module

    return mcp_server_module


def _patch_workspace(monkeypatch: pytest.MonkeyPatch, workspace_id: str) -> None:
    # ``_server_instructions`` re-imports ``get_runtime_context`` from the module
    # on every call, so patching the module attribute is picked up at call time.
    monkeypatch.setattr(
        "mureo.core.runtime_context.get_runtime_context",
        lambda: SimpleNamespace(workspace_id=workspace_id),
    )


@pytest.mark.unit
def test_default_workspace_has_no_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _import_server_module()
    _patch_workspace(monkeypatch, DEFAULT_WORKSPACE_ID)
    assert server._server_instructions() is None


@pytest.mark.unit
def test_bound_workspace_is_named_and_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _import_server_module()
    _patch_workspace(monkeypatch, "agency:acme")
    text = server._server_instructions()
    assert text is not None
    # Names the exact workspace so the model can disambiguate sibling servers …
    assert "agency:acme" in text
    # … and states the hard scoping guarantee that prevents cross-client reads.
    assert "ONLY" in text


@pytest.mark.unit
def test_factory_error_omits_instructions_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _import_server_module()

    def _boom() -> None:
        raise RuntimeContextFactoryError("two factories registered")

    monkeypatch.setattr("mureo.core.runtime_context.get_runtime_context", _boom)
    # A broken factory must not stop the server from being created; the error
    # surfaces on the first tool call as before, not at startup.
    assert server._server_instructions() is None


@pytest.mark.unit
def test_create_server_propagates_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _import_server_module()
    _patch_workspace(monkeypatch, "agency:globex")
    created = server._create_server()
    assert created.instructions is not None
    assert "agency:globex" in created.instructions


@pytest.mark.unit
def test_create_server_default_has_no_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _import_server_module()
    _patch_workspace(monkeypatch, DEFAULT_WORKSPACE_ID)
    created = server._create_server()
    assert created.instructions is None
