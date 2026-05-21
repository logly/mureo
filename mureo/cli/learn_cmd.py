"""``mureo learn`` CLI — append insights to the diagnostic knowledge base.

This command is the supported entry-point for the ``/learn`` skill (see
``skills/learn/SKILL.md``) to persist insights without writing to the
file system directly. Routing the write through the
:class:`mureo.core.knowledge_store.KnowledgeStore` resolved by
:func:`mureo.core.runtime_context.get_runtime_context` means an
alternate backend (registered via the ``mureo.runtime_context_factory``
entry-point group) can intercept the append — for example to split
operator-wide insights from workspace-scoped ones.

Two scopes are exposed:

- ``operator`` (default): the cross-workspace operator tier read by
  every diagnostic skill (today's
  ``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md`` for the file-backed
  default).
- ``workspace``: a workspace-scoped tier. Errors with a helpful
  message when the resolved store has no workspace tier configured
  (the file-backed default has none unless one is wired in).
"""

from __future__ import annotations

from enum import Enum

import typer

learn_app = typer.Typer(
    name="learn",
    help="Append insights to the diagnostic knowledge base.",
    no_args_is_help=True,
)


class _Scope(str, Enum):
    """``--scope`` choices, mirrored by the KnowledgeStore tiers."""

    OPERATOR = "operator"
    WORKSPACE = "workspace"


_TEXT_ARGUMENT = typer.Argument(
    ...,
    help=(
        "The insight Markdown to append. The /learn skill formats this "
        "with a YAML-frontmatter-style block (### title + Situation / "
        "Wrong assumption / Correct approach / Why); pass that block "
        "verbatim, including leading and trailing newlines."
    ),
)

_SCOPE_OPTION = typer.Option(
    _Scope.OPERATOR,
    "--scope",
    help=(
        "Where to persist the insight. 'operator' (default) writes the "
        "cross-workspace tier read by every diagnostic skill. "
        "'workspace' writes a workspace-scoped tier if the resolved "
        "KnowledgeStore has one configured; otherwise the command "
        "exits with a non-zero status and a hint."
    ),
)


@learn_app.command("add")  # type: ignore[untyped-decorator, unused-ignore]
def learn_add(
    text: str = _TEXT_ARGUMENT,
    scope: _Scope = _SCOPE_OPTION,
) -> None:
    """Append an insight to the diagnostic knowledge base."""
    from mureo.core.runtime_context import get_runtime_context

    store = get_runtime_context().knowledge_store
    if scope is _Scope.OPERATOR:
        store.append_operator_knowledge(text)
        typer.echo("Saved to the operator (cross-workspace) tier.")
        return
    try:
        store.append_workspace_knowledge(text)
    except NotImplementedError:
        typer.echo(
            "Error: the resolved KnowledgeStore has no workspace tier "
            "configured. Use --scope operator to write to the "
            "cross-workspace tier, or configure a workspace-aware "
            "backend via the mureo.runtime_context_factory entry-point "
            "group.",
            err=True,
        )
        raise typer.Exit(1) from None
    typer.echo("Saved to the workspace tier.")
