"""What ``mureo repair platform-key`` prints before it is allowed to act.

Split out of :mod:`mureo.cli.repair_cmd` when the preview grew the three
things #616/#617/#618 found missing, and worth keeping apart: this module is
where every claim made to the operator is worded, and it is the half that has
to be true. The command module decides what to do; this one says what that
would mean.

The claims it is responsible for
--------------------------------
- **Why an entry can go.** Not "mureo cannot resolve this key" — that is a
  fact about the machine running the repair, and an operator cannot tell it
  apart from a bridge that is simply not installed here (#616). Each block
  names the evidence in the document instead: the resolvable key holding the
  same account, or the entry being an empty stub.
- **What is NOT changed.** Scoped to the entries outside the plan. Printed
  unconditionally, one block per repair, it contradicted the block below it
  the moment a run removed two entries (#618).
- **What else holds this ad account.** Every sibling, resolvable or not.
  Filtering to the resolvable ones hid precisely the siblings that were also
  being removed, so a run that left an account with no entry at all said
  nothing about it (#618).
- **What no sync brings back.** ``conversion_action_types`` is printed
  whenever an entry carries one (#617). A preview can only show what
  ``PlatformEntryFacts`` carries, and the field's absence there is what made
  the loss silent.

Every string that came out of STATE.json goes through ``terminal_safe``:
the file is agent-writable, so its keys, account ids and timestamps are
attacker-influenceable text on its way to a terminal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from mureo.cli._tty import terminal_safe as _safe
from mureo.context.platform_accounts import duplicate_account_entries
from mureo.context.platform_repair import (
    DROP_DUPLICATE,
    KEEP_CARRIES_FIGURES,
    KEEP_CONVERSION_OVERRIDE,
    is_unresolvable_platform_key,
)

if TYPE_CHECKING:
    from mureo.context.models import StateDocument
    from mureo.context.platform_accounts import DuplicateAccountEntry
    from mureo.context.platform_repair import (
        PlatformEntryFacts,
        PlatformKeyFinding,
        PlatformKeyRepair,
    )


def _echo_entry_facts(
    facts: PlatformEntryFacts, indent: str, *, show_account: bool = True
) -> None:
    """Print one entry's contents — never its figures, only what it holds.

    The key is the caller's to print: it is already the subject of the
    sentence introducing each block. ``show_account`` drops the ad account on
    a block the surrounding sentence has already said shares one, so the
    operator reads facts rather than repetition.
    """
    if show_account:
        typer.echo(
            f"{indent}ad account:  {_safe(facts.account_id) or '(none recorded)'}"
        )
    typer.echo(f"{indent}campaigns:   {facts.campaign_count}")
    typer.echo(f"{indent}totals:      {_totals_line(facts)}")
    typer.echo(f"{indent}periods:     {_periods_line(facts)}")
    _echo_conversion_override(facts, indent)


def _echo_conversion_override(facts: PlatformEntryFacts, indent: str) -> None:
    """Name ``conversion_action_types`` whenever an entry carries one (#617).

    Printed only when set, so an entry without one reads exactly as before.
    The action types themselves are listed, not just counted: they are the
    one thing in the entry no sync brings back, so an operator who has to
    re-declare them needs to be able to read them off the screen.
    """
    types = facts.conversion_action_types
    if not types:
        return
    noun = "conversion_action_type" if len(types) == 1 else "conversion_action_types"
    typer.echo(
        f"{indent}conversions: {len(types)} {noun} you declared — "
        f"no sync restores this"
    )
    typer.echo(f"{indent}             {', '.join(_safe(t) for t in types)}")


def _totals_line(facts: PlatformEntryFacts) -> str:
    if not facts.has_totals:
        return "none stored"
    window = (
        _safe(facts.metrics_period) if facts.metrics_period else "an unnamed window"
    )
    when = (
        f"fetched {_safe(facts.totals_fetched_at)}"
        if facts.totals_fetched_at
        else "no fetch time recorded"
    )
    return f"stored, covering {window}, {when}"


def _periods_line(facts: PlatformEntryFacts) -> str:
    if not facts.rollups:
        return "none stored"
    return "; ".join(
        f"{_safe(rollup.period)} "
        + (
            f"(fetched {_safe(rollup.fetched_at)})"
            if rollup.fetched_at
            else "(no fetch time recorded)"
        )
        for rollup in facts.rollups
    )


_UNRESOLVABLE_EXPLANATION = (
    "    It is not one of mureo's own platform names, no plugin installed "
    "here\n    registers it, and it is not a plugin:<distribution>:<provider> "
    "key."
)


def echo_repair(repair: PlatformKeyRepair, *, removing: frozenset[str]) -> None:
    """Show one finding and exactly what removing it would and would not do.

    ``removing`` is every key THIS run drops, not just this one. Without it
    each block reassured the operator that every other entry was left alone
    while the block below removed one, and a sibling holding the same ad
    account disappeared without either block saying so (#618).
    """
    typer.echo("")
    typer.echo(f"  {_safe(repair.entry.key)} — mureo cannot resolve this key.")
    typer.echo(_UNRESOLVABLE_EXPLANATION)
    typer.echo("")
    typer.echo(f"    Why it can go: {_drop_reason_line(repair)}")
    typer.echo("")
    typer.echo("    This entry holds:")
    _echo_entry_facts(repair.entry, "      ")
    _echo_same_account(repair.same_account, removing=removing)
    typer.echo("")
    typer.echo(
        f"    Would change: the whole {_safe(repair.entry.key)} entry is removed "
        f"from STATE.json."
    )
    _echo_unchanged_claim(removing)
    _echo_afterwards(repair, removing=removing)


def _drop_reason_line(repair: PlatformKeyRepair) -> str:
    """Why the DOCUMENT — not this machine's plugin list — condemns the entry.

    An operator told only "mureo cannot resolve this key" cannot tell a real
    mistake from a bridge that is not installed here, which is the confusion
    #616 was filed for. So the block names the evidence.
    """
    if repair.reason == DROP_DUPLICATE:
        duplicated = ", ".join(
            _safe(facts.key) for facts in repair.same_account if facts.resolvable
        )
        return (
            f"the same ad account is stored under {duplicated}, which\n    mureo CAN "
            f"resolve — so this entry duplicates a record that survives, and\n    "
            f"holds nothing a sync cannot refill."
        )
    return (
        "the entry is an empty stub — no campaigns, no totals, no\n    stored periods "
        "and no settings of your own. Removing it loses nothing."
    )


def _sibling_note(facts: PlatformEntryFacts, *, removing: frozenset[str]) -> str:
    """How one same-account sibling is labelled in a repair block."""
    if facts.key in removing:
        return "this run removes this entry too"
    if facts.resolvable:
        return "mureo CAN resolve this key; it stays"
    return "mureo cannot resolve this key either; it stays"


def _echo_same_account(
    siblings: tuple[PlatformEntryFacts, ...], *, removing: frozenset[str]
) -> None:
    """Every other entry for this ad account — resolvable or not.

    Filtering to the resolvable ones hid exactly the siblings that were also
    being dropped, so the operator was never shown that an account was about
    to lose its last record (#618).
    """
    if not siblings:
        return
    typer.echo("")
    typer.echo("    The same ad account is also stored under:")
    for facts in siblings:
        typer.echo(
            f"      {_safe(facts.key)} — {_sibling_note(facts, removing=removing)}."
        )
        _echo_entry_facts(facts, "        ", show_account=False)


def _echo_unchanged_claim(removing: frozenset[str]) -> None:
    """Scope the reassurance to the entries outside this run's plan (#618)."""
    if len(removing) < 2:
        typer.echo(
            "    Would NOT change: no figures are added together, moved or edited, "
            "and every\n    other platform entry is left exactly as it is."
        )
        return
    typer.echo(
        f"    Would NOT change: no figures are added together, moved or edited. "
        f"Every\n    platform entry other than the {len(removing)} this run removes "
        f"is left exactly as it is."
    )
    typer.echo(
        f"    This run removes: {', '.join(_safe(k) for k in sorted(removing))}."
    )


def _echo_afterwards(repair: PlatformKeyRepair, *, removing: frozenset[str]) -> None:
    """What is left holding this ad account once the run finishes."""
    staying = [facts for facts in repair.same_account if facts.key not in removing]
    refilled = [facts for facts in staying if facts.resolvable]
    if refilled:
        typer.echo(
            f"    Afterwards: the next sync refills {_safe(refilled[0].key)} from "
            f"the platform itself."
        )
    elif staying:
        keys = ", ".join(_safe(facts.key) for facts in staying)
        typer.echo(
            f"    Afterwards: this ad account is still stored under {keys}, which "
            f"mureo\n    cannot resolve either — so nothing refills it on its own. "
            f"The figures stay\n    in the backup."
        )
    elif repair.same_account:
        gone = ", ".join(
            _safe(key)
            for key in [repair.entry.key, *(f.key for f in repair.same_account)]
        )
        typer.echo(
            f"    Afterwards: this run removes every entry for ad account "
            f"{_safe(repair.entry.account_id)}"
        )
        typer.echo(
            f"    ({gone}), so STATE.json will hold NO record of that account at all."
        )
        typer.echo(
            "    The figures stay in the backup; re-sync the platform under its real"
            "\n    key once you know what that is."
        )
    else:
        typer.echo(
            "    Afterwards: no key mureo can resolve holds this ad account, so "
            "nothing refills\n    it on its own. The figures stay in the backup; "
            "re-sync the platform under its\n    real key once you know what that is."
        )


def echo_kept_findings(kept: tuple[PlatformKeyFinding, ...]) -> None:
    """Report the unresolvable entries mureo refuses to remove, and why."""
    if not kept:
        return
    typer.echo("")
    typer.echo(
        f"Found {len(kept)} platform {'entry' if len(kept) == 1 else 'entries'} "
        f"mureo cannot resolve but will NOT remove."
    )
    for finding in kept:
        _echo_kept_finding(finding)


def _echo_kept_finding(finding: PlatformKeyFinding) -> None:
    """One entry handed back, in the same shape as a repair block."""
    typer.echo("")
    typer.echo(
        f"  {_safe(finding.entry.key)} — mureo cannot resolve this key, and will "
        f"NOT remove it."
    )
    typer.echo(_UNRESOLVABLE_EXPLANATION)
    typer.echo("")
    typer.echo(_KEPT_REASONS[finding.reason])
    typer.echo("")
    typer.echo("    This entry holds:")
    _echo_entry_facts(finding.entry, "      ")
    typer.echo("")
    typer.echo("    Would change: nothing.")
    typer.echo(_KEPT_NEXT_STEPS[finding.reason])


_KEPT_REASONS = {
    KEEP_CARRIES_FIGURES: (
        "    Why it stays: that is a fact about THIS machine, not about the "
        "entry — the\n    plugin that owns the key may simply not be installed "
        "here. Nothing in\n    STATE.json says the entry is wrong: no key mureo "
        "can resolve holds its ad\n    account, and it is not empty. So this "
        "entry may be the only record of the\n    figures below, and mureo will "
        "not delete it on a guess."
    ),
    KEEP_CONVERSION_OVERRIDE: (
        "    Why it stays: it carries conversion_action_types — a conversion "
        "allow-list\n    you declared by hand. Every figure here can be "
        "re-fetched from the platform;\n    that setting cannot, because nothing "
        "on the platform side knows it. Removing\n    the entry would take it "
        "with it, so mureo refuses rather than asking you to\n    confirm a loss "
        "it can avoid."
    ),
}

_KEPT_NEXT_STEPS = {
    KEEP_CARRIES_FIGURES: (
        "    Yours to decide: install the plugin that owns this key, or check the "
        "figures\n    and remove the entry yourself."
    ),
    KEEP_CONVERSION_OVERRIDE: (
        "    Yours to decide: declare those action types on the entry you are "
        "keeping,\n    clear them here, then run this command again."
    ),
}


def undecidable_groups(doc: StateDocument | None) -> tuple[DuplicateAccountEntry, ...]:
    """Duplicates whose keys ALL name real platforms — mureo's to report only.

    Split out of the echo so the ``--all`` summary can flag a client whose
    only finding is one of these without printing the whole block twice.
    """
    if doc is None:
        return ()
    return tuple(
        group
        for group in duplicate_account_entries(doc.platforms or {})
        if not any(is_unresolvable_platform_key(key) for key in group.platform_keys)
    )


def echo_undecidable_duplicates(doc: StateDocument | None) -> None:
    """Report a duplicate this command will not touch, and say why.

    Both keys name real platforms, so the question is which set of partial
    figures is true — the one ``mureo/web/reports.py`` refuses to answer, and
    is right to refuse. Saying nothing here would read as "mureo found no
    problem" to an operator who came from a dashboard warning.
    """
    groups = undecidable_groups(doc)
    if not groups:
        return
    typer.echo("")
    for group in groups:
        keys = ", ".join(_safe(key) for key in group.platform_keys)
        typer.echo(
            f"One ad account ({_safe(group.account_id)}) is stored under platform "
            f"keys that\nBOTH name real platforms ({keys}), so its spend, "
            f"conversions and CPA are\ncounted twice."
        )
    typer.echo(
        "mureo does not choose between them: the two entries usually hold "
        "different\npartial figures, so dropping either under-counts as much as "
        "adding them\ntogether over-counts. Check which entry holds the right "
        "figures and remove\nthe other yourself."
    )


__all__ = [
    "echo_kept_findings",
    "echo_repair",
    "echo_undecidable_duplicates",
    "undecidable_groups",
]
