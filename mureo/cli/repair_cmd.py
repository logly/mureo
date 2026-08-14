"""``mureo repair platform-key`` — the supported way out of a bad key (#610).

The person who needs this cannot read JSON and cannot judge which of two
entries holds the right figures, so the command is built around what it can
decide safely and shows its work for everything else:

- **A dry run is the default.** Running the command changes nothing. It names
  the keys, the ad account and what each entry holds (``fetched_at``, which
  windows, whether a ``totals`` rollup is there), then states exactly what
  would change. ``--apply`` is the second, deliberate step, and it still asks.
- **It only ever removes an entry filed under a key mureo cannot resolve.** A
  duplicate whose two keys BOTH name real platforms is reported and handed
  back — that is a question about which figures are true, which only the
  operator can answer.
- **It backs the document up first**, timestamped, and prints the command that
  puts it back.

``--all``: the same repair, once per client
-------------------------------------------
The incident is not one directory's. It was made by an agent running against
every client on the machine, so repairing one document at a time asks a
non-engineer to remember which directories exist — and gives them no way to
notice the one they missed. ``--all`` surveys every client the active
``StateStore`` advertises (:mod:`mureo.cli._repair_clients`), leads with a
summary of how many of how many need work, and confirms **once** with that
list in view. One client failing costs that client, not the run: the failure
is named in the summary and the exit status is non-zero.

**Archived clients are swept too**, and labelled. Archiving means "stop
collecting this client's figures" — a decision about what to fetch next, not
a statement that what is already stored is correct. Skipping them would leave
the bad key in place to reappear the day the client is un-archived, on a
machine whose operator has no reason to run the sweep a second time. The
dashboard takes the same position where a decision is at stake: its Reports
routing counts the whole registry, archived rows included.

Why the CLI and not a dashboard button
--------------------------------------
The finding surfaces on the dashboard's platform card, and the card now points
here (``dashboard.reports_conflict_repair_hint``), but the repair itself is
not offered there. The card cannot tell the two keys apart: the dashboard's
``unrecognized_key`` signal tests whether a key resolves to a display *label*,
and by that test ``logly_ads_context`` — the CORRECT key in the reported
incident — is just as unrecognised as the invented ``logly_ads``. A button
placed on that signal would offer to delete the right entry. Teaching the
dashboard the difference means putting #609's resolvability answer on the wire
and enumerating installed entry points on every dashboard poll, in a module
whose contract is that it never mutates state. The terminal already has the
answer, in-process and current.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TCH003 (used at runtime by typer)
from typing import TYPE_CHECKING

import typer

from mureo.cli._repair_clients import list_repair_targets, survey_clients
from mureo.cli._state_file import STATE_FILE_OPTION, resolve_default_state_file
from mureo.cli._tty import confirm_or_default
from mureo.cli._tty import terminal_safe as _safe
from mureo.context.errors import ContextFileError
from mureo.context.platform_accounts import duplicate_account_entries
from mureo.context.platform_repair import (
    apply_state_file_repairs,
    is_unresolvable_platform_key,
    plan_platform_key_repairs,
)
from mureo.context.state import read_state_file

if TYPE_CHECKING:
    from collections.abc import Callable

    from mureo.cli._repair_clients import ClientSurvey, ClientTarget
    from mureo.context.models import StateDocument
    from mureo.context.platform_accounts import DuplicateAccountEntry
    from mureo.context.platform_repair import PlatformEntryFacts, PlatformKeyRepair

repair_app = typer.Typer(
    name="repair",
    help="Repair STATE.json problems mureo can fix without guessing.",
    no_args_is_help=True,
)

_COMMAND = "mureo repair platform-key"


def _read_document(state_file: Path) -> StateDocument:
    """Read ``state_file`` or exit with a message an operator can act on."""
    if not state_file.exists():
        typer.echo(f"Error: STATE.json not found at {state_file}", err=True)
        raise typer.Exit(1)
    try:
        return read_state_file(state_file)
    except ContextFileError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


def _reject_unusable_key_argument(doc: StateDocument, key: str) -> None:
    """Explain a ``--key`` that names nothing this command will touch."""
    platforms = doc.platforms or {}
    if key not in platforms:
        known = ", ".join(_safe(k) for k in platforms) or "none"
        typer.echo(
            f"Error: STATE.json has no platform entry named {_safe(key)!r}. "
            f"It holds: {known}.",
            err=True,
        )
        raise typer.Exit(1)
    _reject_resolvable_key(key)


def _reject_resolvable_key(key: str) -> None:
    """Refuse a ``--key`` naming a platform mureo CAN resolve.

    Shared with ``--all``, which has no single document to check the key's
    presence against but must give the identical answer to the identical
    mistake.
    """
    if not is_unresolvable_platform_key(key):
        typer.echo(
            f"Error: mureo can resolve {_safe(key)!r}, so this is not the case "
            f"this command repairs. It only removes an entry filed under a key "
            f"that names no platform at all. If this entry duplicates another, "
            f"decide which one holds the right figures and remove the other "
            f"yourself.",
            err=True,
        )
        raise typer.Exit(1)


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


def _echo_repair(repair: PlatformKeyRepair) -> None:
    """Show one finding and exactly what removing it would and would not do."""
    typer.echo("")
    typer.echo(f"  {_safe(repair.entry.key)} — mureo cannot resolve this key.")
    typer.echo(
        "    It is not one of mureo's own platform names, no plugin installed "
        "here\n    registers it, and it is not a plugin:<distribution>:<provider> "
        "key. So no\n    platform's data can belong to it."
    )
    typer.echo("")
    typer.echo("    This entry holds:")
    _echo_entry_facts(repair.entry, "      ")
    survivors = [facts for facts in repair.same_account if facts.resolvable]
    if survivors:
        typer.echo("")
        typer.echo(
            "    The same ad account is also stored under a key mureo CAN "
            "resolve, which\n    holds:"
        )
        for facts in survivors:
            typer.echo(f"      {_safe(facts.key)}")
            _echo_entry_facts(facts, "        ", show_account=False)
    typer.echo("")
    typer.echo(
        f"    Would change: the whole {_safe(repair.entry.key)} entry is removed "
        f"from STATE.json."
    )
    typer.echo(
        "    Would NOT change: no figures are added together, moved or edited, "
        "and every\n    other platform entry is left exactly as it is."
    )
    if survivors:
        typer.echo(
            f"    Afterwards: the next sync refills {_safe(survivors[0].key)} from "
            f"the platform itself."
        )
    else:
        typer.echo(
            "    Afterwards: no key mureo can resolve holds this ad account, so "
            "nothing refills\n    it on its own. The figures stay in the backup; "
            "re-sync the platform under its\n    real key once you know what that is."
        )


def _undecidable_groups(doc: StateDocument | None) -> tuple[DuplicateAccountEntry, ...]:
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


def _echo_undecidable_duplicates(doc: StateDocument | None) -> None:
    """Report a duplicate this command will not touch, and say why.

    Both keys name real platforms, so the question is which set of partial
    figures is true — the one ``mureo/web/reports.py`` refuses to answer, and
    is right to refuse. Saying nothing here would read as "mureo found no
    problem" to an operator who came from a dashboard warning.
    """
    groups = _undecidable_groups(doc)
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


def _echo_apply_result(repairs: tuple[PlatformKeyRepair, ...]) -> None:
    for repair in repairs:
        typer.echo(f"Removed the {_safe(repair.entry.key)} entry from STATE.json.")
    typer.echo("")
    typer.echo(f"Done. Re-run `{_COMMAND}` to confirm nothing is left.")


@repair_app.command("platform-key")  # type: ignore[untyped-decorator, unused-ignore]
def repair_platform_key(
    state_file: Path | None = STATE_FILE_OPTION,
    key: str | None = typer.Option(
        None,
        "--key",
        help=(
            "Repair only this platform key. Without it, every entry filed "
            "under a key mureo cannot resolve is repaired."
        ),
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Make the change. Without this the command only shows what it "
            "would do and leaves STATE.json untouched."
        ),
    ),
    all_clients: bool = typer.Option(
        False,
        "--all",
        help=(
            "Survey every client this machine knows about instead of one "
            "workspace, and report which of them need repairing. Cannot be "
            "combined with --state-file."
        ),
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt for --apply."
    ),
) -> None:
    """Remove a platform entry filed under a key mureo cannot resolve.

    Shows what it would do and changes nothing unless you pass ``--apply``.
    """
    if all_clients:
        _repair_every_client(state_file=state_file, key=key, apply=apply, yes=yes)
        return
    _repair_one_workspace(state_file=state_file, key=key, apply=apply, yes=yes)


def _repair_one_workspace(
    *, state_file: Path | None, key: str | None, apply: bool, yes: bool
) -> None:
    """The single-document run: one STATE.json, shown in full before acting."""
    if state_file is None:
        state_file = resolve_default_state_file()
    doc = _read_document(state_file)
    if key is not None:
        _reject_unusable_key_argument(doc, key)
    keys = (key,) if key is not None else None
    repairs = plan_platform_key_repairs(doc, keys=keys)

    typer.echo(f"=== {_COMMAND} ===")
    typer.echo("")
    typer.echo(f"STATE.json: {state_file}")
    if not repairs:
        typer.echo("")
        typer.echo(
            "Nothing to repair: every platform entry is filed under a key mureo "
            "can resolve."
        )
        _echo_undecidable_duplicates(doc)
        return

    typer.echo("")
    typer.echo(
        f"Found {len(repairs)} platform "
        f"{'entry' if len(repairs) == 1 else 'entries'} filed under a key mureo "
        f"cannot resolve."
    )
    for repair in repairs:
        _echo_repair(repair)
    _echo_undecidable_duplicates(doc)
    typer.echo("")

    if not _confirmed(apply=apply, yes=yes):
        return
    _apply(state_file, keys)


def _confirmed(
    *,
    apply: bool,
    yes: bool,
    command: str = _COMMAND,
    prompt: str = "Apply this repair?",
) -> bool:
    """Has the operator asked for the change AND agreed to it?

    Two separate gates. Without ``--apply`` this is a dry run and says so.
    With it, the prompt defaults to **no** and — with no TTY, which is what an
    AI agent's shell looks like — declines rather than proceeding, so a
    destructive step is never taken by a caller that could not be asked.

    ``--all`` passes its own ``command`` and ``prompt`` and calls this **once**
    for the whole sweep, with every client's finding already on screen. Asking
    per client would train the operator to hold down ``y`` — the opposite of
    what a confirmation is for.
    """
    if not apply:
        typer.echo("Nothing has been changed — this was a dry run.")
        typer.echo("To make the change, run the same command with --apply:")
        typer.echo(f"  {command} --apply")
        return False
    if confirm_or_default(prompt, default=False, override=True if yes else None):
        return True
    typer.echo("Nothing was changed.")
    return False


def _apply(state_file: Path, keys: tuple[str, ...] | None) -> None:
    """Run the repair and report the backup before what it removed."""
    try:
        outcome = apply_state_file_repairs(state_file, keys=keys)
    except (ContextFileError, OSError) as exc:
        typer.echo(f"Error: STATE.json was not changed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if not outcome.changed:
        # The document changed between the preview and the lock being taken.
        typer.echo("Nothing was changed — STATE.json no longer needs this repair.")
        return
    typer.echo("")
    if outcome.backup is not None:
        typer.echo(f"Backed up STATE.json to {outcome.backup}")
        typer.echo("If this turns out wrong, put it back with:")
        typer.echo(f'  cp "{outcome.backup}" "{state_file}"')
        typer.echo("")
    _echo_apply_result(outcome.repairs)


# ---------------------------------------------------------------------------
# --all: every client on the machine, summary first
# ---------------------------------------------------------------------------

_ALL_COMMAND = f"{_COMMAND} --all"


def _repair_every_client(
    *, state_file: Path | None, key: str | None, apply: bool, yes: bool
) -> None:
    """Survey every client, report, and — once confirmed — repair each.

    Exits non-zero when any client could not be surveyed or repaired. A
    *finding* is not a failure: a dry run that reports work to do exits 0.
    """
    _reject_all_conflicts(state_file=state_file, key=key)
    keys = (key,) if key is not None else None
    registry = list_repair_targets()
    surveys = survey_clients(registry.targets, keys=keys)
    failures = sum(1 for survey in surveys if survey.error)

    typer.echo(f"=== {_ALL_COMMAND} ===")
    typer.echo("")
    _echo_survey_summary(surveys, registry.warning)
    _echo_survey_details(surveys)
    typer.echo("")

    needing = [survey for survey in surveys if survey.repairs]
    if not needing:
        typer.echo(
            "Nothing to repair: every client's platform entries are filed under "
            "keys mureo can resolve."
        )
    elif _confirmed(
        apply=apply,
        yes=yes,
        command=_ALL_COMMAND,
        prompt=f"Apply these repairs to {_clients(len(needing))}?",
    ):
        failures += _apply_every_client(needing, keys)
    if failures:
        # Said last as well as in the summary: on a long sweep the summary has
        # scrolled off, and the closing line is the one an operator reads.
        typer.echo("")
        typer.echo(
            f"Finished with errors: {failures} of {len(surveys)} clients could "
            f"not be read or repaired."
        )
    if registry.warning is not None or failures:
        raise typer.Exit(1)


def _reject_all_conflicts(*, state_file: Path | None, key: str | None) -> None:
    """Refuse the flag combinations ``--all`` cannot mean anything with."""
    if state_file is not None:
        typer.echo(
            "Error: --all repairs every client's STATE.json, so it cannot also "
            "be pointed at a single one with --state-file. Use --all to sweep "
            "the machine, or --state-file to repair one workspace.",
            err=True,
        )
        raise typer.Exit(1)
    # ``--key`` still narrows the sweep — the reported incident used the same
    # invented key everywhere — but it cannot be checked for presence here:
    # there are many documents, and a client that simply does not carry the
    # key is a clean client, not an error.
    if key is not None:
        _reject_resolvable_key(key)


def _clients(count: int) -> str:
    return f"{count} client" if count == 1 else f"{count} clients"


def _client_label(target: ClientTarget) -> str:
    """How one client is named everywhere in the ``--all`` output.

    Slug first (it is what every other surface identifies the client by), the
    display name only when it says something the slug does not, and the
    archived flag always — an operator seeing a repair applied to a client
    they had shelved should be told that is what happened.
    """
    label = _safe(target.slug)
    if target.name and target.name != target.slug:
        label = f"{label} ({_safe(target.name)})"
    return f"{label} [archived]" if target.archived else label


def _echo_survey_summary(
    surveys: tuple[ClientSurvey, ...], warning: str | None
) -> None:
    """The whole point of ``--all``: N of M clients need work, at a glance."""
    total = len(surveys)
    typer.echo(f"Surveyed {_clients(total)}.")
    if warning is not None:
        typer.echo(f"Warning: {_safe(warning)}")
    typer.echo("")
    _echo_survey_group(
        "Need repair",
        [s for s in surveys if s.repairs],
        total,
        lambda s: ", ".join(_safe(r.entry.key) for r in s.repairs),
    )
    _echo_survey_group(
        "Clean",
        [s for s in surveys if not s.repairs and not s.error],
        total,
        _clean_note,
    )
    _echo_survey_group(
        "Could not be read",
        [s for s in surveys if s.error],
        total,
        lambda s: s.error or "",
    )


def _echo_survey_group(
    title: str,
    surveys: list[ClientSurvey],
    total: int,
    note: Callable[[ClientSurvey], str],
) -> None:
    """One block of the summary. Silent when it has no members."""
    if not surveys:
        return
    typer.echo(f"  {title} ({len(surveys)} of {total}):")
    for survey in surveys:
        detail = note(survey)
        suffix = f" — {detail}" if detail else ""
        typer.echo(f"    {_client_label(survey.target)}{suffix}")
    typer.echo("")


def _clean_note(survey: ClientSurvey) -> str:
    """Why a client with no repairable entry may still not be finished.

    "Clean" here means only "nothing mureo will remove". A client whose
    account is stored under two keys that BOTH name real platforms is still
    double-counting, and a client with no STATE.json at all is not the one
    holding the figures the operator is looking for — both are said out loud
    rather than folded into a reassuring word.
    """
    if survey.missing:
        return "no STATE.json yet"
    if _undecidable_groups(survey.doc):
        return "one ad account under two real platform keys (see below)"
    return ""


def _echo_survey_details(surveys: tuple[ClientSurvey, ...]) -> None:
    """The single-workspace detail block, per client that has a finding."""
    for survey in surveys:
        if not survey.repairs and not _undecidable_groups(survey.doc):
            continue
        typer.echo("")
        typer.echo(f"--- {_client_label(survey.target)} ---")
        # Scrubbed: unlike the single run's ``--state-file``, this path came
        # from a backend's client registry rather than from the operator.
        typer.echo(f"STATE.json: {_safe(str(survey.target.state_file))}")
        for repair in survey.repairs:
            _echo_repair(repair)
        _echo_undecidable_duplicates(survey.doc)


def _apply_every_client(
    surveys: list[ClientSurvey], keys: tuple[str, ...] | None
) -> int:
    """Repair each client in turn, and return how many failed.

    A client that fails is named and the sweep continues: a lock it cannot
    take or a permission error on one directory is no reason to leave the
    other eleven broken.
    """
    failures = 0
    for survey in surveys:
        typer.echo("")
        typer.echo(f"{_client_label(survey.target)}:")
        failures += _apply_one_client(survey, keys)
    typer.echo("")
    typer.echo(f"Done. Re-run `{_ALL_COMMAND}` to confirm nothing is left.")
    return failures


def _apply_one_client(survey: ClientSurvey, keys: tuple[str, ...] | None) -> int:
    """Repair one client, returning ``1`` if it failed and ``0`` otherwise."""
    state_file = survey.target.state_file
    if state_file is None:  # pragma: no cover — a surveyed client always has one
        typer.echo(f"  Error: {survey.error or 'no STATE.json to repair'}", err=True)
        return 1
    try:
        outcome = apply_state_file_repairs(state_file, keys=keys)
    except Exception as exc:  # noqa: BLE001 — one client's failure is not the sweep's
        typer.echo(f"  Error: STATE.json was not changed: {_safe(str(exc))}", err=True)
        return 1
    if not outcome.changed:
        # The document changed between the survey and the lock being taken.
        typer.echo("  Nothing was changed — STATE.json no longer needs this repair.")
        return 0
    if outcome.backup is not None:
        typer.echo(f"  Backed up STATE.json to {outcome.backup}")
        typer.echo(f'  Put it back with: cp "{outcome.backup}" "{state_file}"')
    for repair in outcome.repairs:
        typer.echo(f"  Removed the {_safe(repair.entry.key)} entry from STATE.json.")
    return 0
