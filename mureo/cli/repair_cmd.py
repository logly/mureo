"""``mureo repair platform-key`` — the supported way out of a bad key (#610).

The person who needs this cannot read JSON and cannot judge which of two
entries holds the right figures, so the command is built around what it can
decide safely and shows its work for everything else:

- **A dry run is the default.** Running the command changes nothing. It names
  the keys, the ad account and what each entry holds (``fetched_at``, which
  windows, whether a ``totals`` rollup is there), then states exactly what
  would change. ``--apply`` is the second, deliberate step, and it still asks.
- **It removes an entry only when the DOCUMENT shows it is wrong** — a
  duplicate of a key mureo can resolve holding the same ad account, or an
  empty stub (#616). "No plugin here registers this key" is a fact about the
  machine running the repair, not about the entry, so it selects nothing on
  its own. Everything else it finds is reported and handed back: a duplicate
  whose two keys BOTH name real platforms (which figures are true is the
  operator's question), an unresolvable entry that duplicates nothing and
  carries figures, and any entry holding ``conversion_action_types``, which no
  sync restores (#617).
- **…unless the operator names the loser themselves** (``--key <k>
  --drop-duplicate``, #636). Which of two real platform keys holds the true
  figures stays the operator's question; this is where they answer it. The
  answer is honoured only against the document — the key must be one another
  entry's ad account is also stored under — and it buys nothing past #617.
  The flag is required because ``--key`` alone must keep meaning "narrow the
  sweep": an operator scoping a run should never find they deleted the entry
  they were protecting.
- **It backs the document up first**, timestamped, and prints the command that
  puts it back.

What is printed lives in :mod:`mureo.cli._repair_preview` — this module
decides what to do, that one words what it would mean. Every claim it makes
has to survive the run it precedes; the three that did not are #618.

A document mureo cannot read is an ``Error:`` line, never a traceback, on
both paths — see :func:`_echo_unreadable`.

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

``--drop-duplicate`` is deliberately NOT part of it. That flag records one
decision about one pair of entries, made by reading one document; a sweep
would carry it into every other client's STATE.json, including the ones the
operator has never opened. The sweep still reports those duplicates and names
the command to run per client.

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
not offered there.

The card's ``unrecognized_key`` signal does now agree with #609's answer:
since #631 the label path resolves a bare provider name from the same
installed-plugin enumeration the guard reads, so ``logly_ads_context`` — the
CORRECT key in the reported incident — no longer fires it while the invented
``logly_ads`` still does.

Agreeing about the key is not deciding the repair, though, and the second
half is what keeps the button off that card. "Unresolvable" is the FILTER,
not the criterion (#616): removal needs the DOCUMENT to show the entry wrong
— a resolvable sibling holding the same ad account, or an entry storing
nothing at all — and is refused outright for an entry carrying
``conversion_action_types`` (#617). None of that evidence is on the wire, by
design: a conflict row carries keys and a presence bit, never an ad account
id. So an action hung off the signal alone would still offer a deletion this
command refuses — in a module whose contract is that it never mutates state.
The terminal has the whole answer, in-process and current.

``--drop-duplicate`` does not change that. It removes a real entry on the
operator's word, which is the last thing to hang off a one-click control in a
read-only view. What the card owes them is the exact command, and since #636
that is what it prints (``dashboard.reports_conflict_duplicate_repair_hint``)
— with the key left as a placeholder, because mureo does not know which half
is wrong and neither does the wire.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TCH003 (used at runtime by typer)
from typing import TYPE_CHECKING

import typer

from mureo.cli._repair_clients import (
    list_repair_targets,
    survey_clients,
    unreadable_reason,
)
from mureo.cli._repair_preview import (
    REPAIR_COMMAND,
    echo_kept_findings,
    echo_repair,
    echo_undecidable_duplicates,
    undecidable_groups,
)
from mureo.cli._state_file import STATE_FILE_OPTION, resolve_default_state_file
from mureo.cli._tty import confirm_or_default
from mureo.cli._tty import terminal_safe as _safe
from mureo.context.errors import ContextFileError
from mureo.context.platform_repair import (
    DROP_CHOSEN_DUPLICATE,
    apply_state_file_repairs,
    is_unresolvable_platform_key,
    plan_platform_keys,
)
from mureo.context.state import read_state_file

if TYPE_CHECKING:
    from collections.abc import Callable

    from mureo.cli._repair_clients import ClientSurvey, ClientTarget
    from mureo.context.models import StateDocument
    from mureo.context.platform_repair import PlatformKeyRepair

repair_app = typer.Typer(
    name="repair",
    help="Repair STATE.json problems mureo can fix without guessing.",
    no_args_is_help=True,
)

# One spelling, shared with the module that prints "run this to fix it".
_COMMAND = REPAIR_COMMAND


def _read_document(state_file: Path) -> StateDocument:
    """Read ``state_file`` or exit with a message an operator can act on."""
    if not state_file.exists():
        typer.echo(f"Error: STATE.json not found at {state_file}", err=True)
        raise typer.Exit(1)
    try:
        return read_state_file(state_file)
    except (ContextFileError, ValueError) as exc:
        _echo_unreadable(state_file, exc)
        raise typer.Exit(1) from exc


def _echo_unreadable(state_file: Path, exc: Exception) -> None:
    """Report a STATE.json this command cannot read, and stop.

    ``read_state_file`` wraps ``json.JSONDecodeError`` as ``ContextFileError``
    and nothing else, but strict parsing also raises a bare ``ValueError`` for
    a document that is valid JSON and invalid against the schema — a campaign
    missing ``campaign_name``, say. Catching only ``ContextFileError`` left
    that document ending in a Python traceback here while ``--all`` reported
    the same file under "Could not be read": one document, two answers, and
    the person this command exists for cannot read the second one (#618).

    Caught at the CLI rather than by widening ``read_state_file``'s contract:
    that function has fifteen-odd other callers, some of which may well be
    relying on a ``ValueError`` passing through, and this is not the place to
    find out.

    The reason text is ``--all``'s own, so the two paths cannot drift into
    describing one file differently again. It is scrubbed — the failing
    fragment comes out of an agent-writable STATE.json.
    """
    typer.echo(f"Error: mureo cannot read STATE.json: {state_file}", err=True)
    typer.echo(f"       {unreadable_reason(exc)}", err=True)
    typer.echo(
        "       Nothing was changed. This command will not repair a document it "
        "cannot\n       read in full: writing it back would drop whatever the "
        "read skipped.",
        err=True,
    )


def _reject_unusable_key_argument(
    doc: StateDocument, key: str, *, drop_duplicate: bool
) -> None:
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
    if not drop_duplicate:
        _reject_resolvable_key(key)


def _reject_resolvable_key(key: str) -> None:
    """Refuse a ``--key`` naming a platform mureo CAN resolve.

    Shared with ``--all``, which has no single document to check the key's
    presence against but must give the identical answer to the identical
    mistake.

    Not called at all when ``--drop-duplicate`` is passed: that flag is the
    operator saying they know mureo can resolve this key and want it removed
    anyway. The refusal therefore has to NAME it — the previous "remove the
    other yourself" ended in an operator with a red dashboard card, a hidden
    total and no command to run (#636).
    """
    if not is_unresolvable_platform_key(key):
        typer.echo(
            f"Error: mureo can resolve {_safe(key)!r}, so it is not repaired on "
            f"mureo's own judgement. It removes an entry filed under a key that "
            f"names no platform at all.",
            err=True,
        )
        typer.echo(
            f"       If this entry duplicates another key holding the same ad "
            f"account and\n       you have decided THIS is the one to remove, "
            f"say so explicitly:\n"
            f"         {_COMMAND} --key {_safe(key)} --drop-duplicate",
            err=True,
        )
        raise typer.Exit(1)


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
    drop_duplicate: bool = typer.Option(
        False,
        "--drop-duplicate",
        help=(
            "Remove the entry named by --key even though mureo can resolve "
            "its key, because you have decided it is the duplicate half. "
            "Only honoured when another entry holds the same ad account."
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
        _repair_every_client(
            state_file=state_file,
            key=key,
            drop_duplicate=drop_duplicate,
            apply=apply,
            yes=yes,
        )
        return
    _repair_one_workspace(
        state_file=state_file,
        key=key,
        drop_duplicate=drop_duplicate,
        apply=apply,
        yes=yes,
    )


def _reject_choice_without_a_key(*, key: str | None, drop_duplicate: bool) -> None:
    """``--drop-duplicate`` is an answer; it needs the question named.

    Applying it to "every duplicate mureo finds" would be mureo choosing,
    which is the one thing this path exists NOT to do.
    """
    if drop_duplicate and key is None:
        typer.echo(
            "Error: --drop-duplicate says which entry of a duplicate to remove, "
            "so it needs\n       the key: "
            f"{_COMMAND} --key <the key to remove> --drop-duplicate",
            err=True,
        )
        raise typer.Exit(1)


def _repair_one_workspace(
    *,
    state_file: Path | None,
    key: str | None,
    drop_duplicate: bool,
    apply: bool,
    yes: bool,
) -> None:
    """The single-document run: one STATE.json, shown in full before acting."""
    _reject_choice_without_a_key(key=key, drop_duplicate=drop_duplicate)
    invocation = _invocation(
        state_file=state_file, key=key, drop_duplicate=drop_duplicate
    )
    if state_file is None:
        state_file = resolve_default_state_file()
    doc = _read_document(state_file)
    if key is not None:
        _reject_unusable_key_argument(doc, key, drop_duplicate=drop_duplicate)
    keys = (key,) if key is not None else None
    chosen = keys if drop_duplicate else None
    plan = plan_platform_keys(doc, keys=keys, drop_duplicates=chosen)
    repairs = plan.repairs

    typer.echo(f"=== {_COMMAND} ===")
    typer.echo("")
    typer.echo(f"STATE.json: {state_file}")
    if not repairs and not plan.kept:
        # A document whose only finding is a duplicate mureo will not decide
        # is NOT clean, and saying so first is how #636 read as "mureo says
        # there is nothing wrong". The block below states it and names the
        # command that ends it.
        if not undecidable_groups(doc):
            typer.echo("")
            typer.echo(
                "Nothing to repair: every platform entry is filed under a key "
                "mureo can resolve."
            )
        echo_undecidable_duplicates(doc)
        _exit_on_an_unmet_choice(drop_duplicate=drop_duplicate, repairs=repairs)
        return

    removing = frozenset(repair.entry.key for repair in repairs)
    if repairs:
        typer.echo("")
        typer.echo(_found_line(repairs))
        for repair in repairs:
            echo_repair(repair, removing=removing)
    echo_kept_findings(plan.kept)
    echo_undecidable_duplicates(doc, removing=removing)
    typer.echo("")

    if not repairs:
        # Everything found is the operator's call, so there is nothing
        # ``--apply`` could do and no confirmation worth asking for.
        typer.echo("Nothing to repair automatically: mureo will not remove the")
        typer.echo("entries above, for the reason given under each one.")
        _exit_on_an_unmet_choice(drop_duplicate=drop_duplicate, repairs=repairs)
        return
    if not _confirmed(apply=apply, yes=yes, command=invocation):
        return
    _apply(state_file, keys, chosen)


def _invocation(
    *, state_file: Path | None, key: str | None, drop_duplicate: bool
) -> str:
    """This run, spelled so the operator can re-run it with ``--apply``.

    The dry run ends with "run the same command with --apply", and it has to
    BE the same command: a scoped run that echoed the bare command would send
    an operator to a whole-document repair they never asked for — and one that
    dropped ``--drop-duplicate`` would send them to a command that does
    nothing, which is the dead end #636 is about.
    """
    parts = [_COMMAND]
    if state_file is not None:
        parts += ["--state-file", f'"{state_file}"']
    if key is not None:
        parts += ["--key", _safe(key)]
    if drop_duplicate:
        parts.append("--drop-duplicate")
    return " ".join(parts)


def _found_line(repairs: tuple[PlatformKeyRepair, ...]) -> str:
    """How the run introduces what it found.

    "Filed under a key mureo cannot resolve" is false of an entry the operator
    named themselves (#636), and it is the sentence they read before
    confirming.
    """
    noun = "entry" if len(repairs) == 1 else "entries"
    if any(repair.reason == DROP_CHOSEN_DUPLICATE for repair in repairs):
        return f"Found {len(repairs)} platform {noun} you named for removal."
    return (
        f"Found {len(repairs)} platform {noun} filed under a key mureo "
        f"cannot resolve."
    )


def _exit_on_an_unmet_choice(
    *, drop_duplicate: bool, repairs: tuple[PlatformKeyRepair, ...]
) -> None:
    """Fail when an explicit ``--drop-duplicate`` removed nothing.

    A sweep that finds nothing is a clean result; a named entry that mureo
    declined to remove is a request that was refused, and the reason is
    printed above. Exiting 0 there would tell a script — and the operator
    reading only the last line — that the duplicate is gone.
    """
    if drop_duplicate and not repairs:
        raise typer.Exit(1)


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


def _apply(
    state_file: Path,
    keys: tuple[str, ...] | None,
    drop_duplicates: tuple[str, ...] | None = None,
) -> None:
    """Run the repair and report the backup before what it removed."""
    try:
        outcome = apply_state_file_repairs(
            state_file, keys=keys, drop_duplicates=drop_duplicates
        )
    except (ContextFileError, ValueError) as exc:
        # Between the preview and the lock, the document became one mureo
        # cannot parse strictly — a concurrent writer, or a file swapped under
        # it. Reported exactly as the read path reports it, and for the same
        # reason: a bare ``ValueError`` out of strict parsing is not a
        # traceback this command's operator should ever see (#618).
        _echo_unreadable(state_file, exc)
        raise typer.Exit(1) from exc
    except OSError as exc:
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
    *,
    state_file: Path | None,
    key: str | None,
    drop_duplicate: bool,
    apply: bool,
    yes: bool,
) -> None:
    """Survey every client, report, and — once confirmed — repair each.

    Exits non-zero when any client could not be surveyed or repaired. A
    *finding* is not a failure: a dry run that reports work to do exits 0.
    """
    _reject_all_conflicts(state_file=state_file, key=key, drop_duplicate=drop_duplicate)
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
    if not needing and any(_needs_a_decision(survey) for survey in surveys):
        # Findings were made; the sweep just will not act on them on its own.
        # Saying "every key resolves" here would be plainly false (#616) —
        # and saying "nothing to repair" over a duplicate whose two keys both
        # resolve is what #636 was reported as, since the dashboard was at the
        # same time withholding that client's totals. Each block above says
        # what to run.
        typer.echo(
            "Nothing to repair automatically: mureo will not remove the entries "
            "above on\nits own, for the reason given under each one."
        )
    elif not needing and failures:
        # "Every client's entries resolve" is false when a client's entries
        # could not be read at all — the same false reassurance #616/#618 are
        # about, one line further down.
        typer.echo(
            "Nothing to repair in the clients that could be read. The ones "
            "listed under\n'Could not be read' were not surveyed at all."
        )
    elif not needing:
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


def _reject_all_conflicts(
    *, state_file: Path | None, key: str | None, drop_duplicate: bool
) -> None:
    """Refuse the flag combinations ``--all`` cannot mean anything with."""
    if drop_duplicate:
        # One decision, made by reading ONE document, applied to every client
        # on the machine — including the ones the operator has never opened.
        typer.echo(
            "Error: --all sweeps every client, and --drop-duplicate records your "
            "decision\n       about one client's two entries — so they cannot be "
            "combined. Repair\n       those clients one at a time:\n"
            f"         {_COMMAND} --state-file <client>/STATE.json --key "
            f"<the key to remove> --drop-duplicate",
            err=True,
        )
        raise typer.Exit(1)
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
    # A client mureo will not touch is not therefore finished. An account
    # stored under two keys that BOTH name real platforms is still
    # double-counting, and mureo deliberately will not choose between them —
    # so it gets its own group rather than a note hung off "Clean". The
    # operator this command is for reads "Clean (3 of 6)" as "three are
    # fine"; a qualifier after an em dash is exactly what they skim past.
    # Since #616 the same applies to an unresolvable entry mureo declines to
    # remove: it is neither a repair the sweep makes nor a clean client.
    _echo_survey_group(
        "Need your decision",
        [s for s in surveys if _needs_a_decision(s)],
        total,
        _decision_note,
    )
    _echo_survey_group(
        "Clean",
        [
            s
            for s in surveys
            if not s.repairs
            and not s.error
            and not s.kept
            and not undecidable_groups(s.doc)
        ],
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


def _needs_a_decision(survey: ClientSurvey) -> bool:
    """Has this client a finding mureo reports but will not act on?

    Only asked of clients with no repair of their own: a client that needs
    both is counted under "Need repair", where the sweep will visit it anyway,
    and its other findings still print in the detail below.
    """
    if survey.repairs or survey.error:
        return False
    return bool(survey.kept) or bool(undecidable_groups(survey.doc))


def _decision_note(survey: ClientSurvey) -> str:
    """Which of the two undecidable findings this client has — or both."""
    notes = []
    if undecidable_groups(survey.doc):
        notes.append("one ad account under two real platform keys")
    if survey.kept:
        keys = ", ".join(_safe(finding.entry.key) for finding in survey.kept)
        notes.append(f"mureo cannot resolve {keys}, and will not remove it")
    return f"{'; '.join(notes)} (see below)"


def _clean_note(survey: ClientSurvey) -> str:
    """Why a "clean" client may still not be the one holding the figures.

    A client that has never synced has nothing to repair and nothing to
    double-count, but it also has none of the numbers the operator came
    looking for — so it is said out loud rather than folded into a
    reassuring word. The other not-really-clean case, an account stored
    under two keys that both name real platforms, is not here: it has its
    own summary group.
    """
    return "no STATE.json yet" if survey.missing else ""


def _echo_survey_details(surveys: tuple[ClientSurvey, ...]) -> None:
    """The single-workspace detail block, per client that has a finding."""
    for survey in surveys:
        if not (survey.repairs or survey.kept or undecidable_groups(survey.doc)):
            continue
        typer.echo("")
        typer.echo(f"--- {_client_label(survey.target)} ---")
        # Scrubbed: unlike the single run's ``--state-file``, this path came
        # from a backend's client registry rather than from the operator.
        typer.echo(f"STATE.json: {_safe(str(survey.target.state_file))}")
        # Scoped per client: a sweep removes each client's entries from that
        # client's document, so one client's plan says nothing about another's.
        removing = frozenset(repair.entry.key for repair in survey.repairs)
        for repair in survey.repairs:
            echo_repair(repair, removing=removing)
        echo_kept_findings(survey.kept)
        echo_undecidable_duplicates(survey.doc)


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
