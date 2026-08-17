"""A conflict the dashboard renders always has a repair that ends it (#636).

The dashboard does not merely report a duplicated ad account: it **withholds
the client's totals** until the duplicate is gone. So "there is a way out of
this" is a claim two independent surfaces make about one document —

- :func:`mureo.web.reports.build_report_summary`, which decides whether the
  card is red and the figures are hidden, and
- :func:`mureo.context.platform_repair.plan_platform_keys`, which decides what
  ``mureo repair platform-key`` can actually remove —

and #636 is what happens when they disagree. Both keys of the reported
duplicate resolved, so the plan proposed nothing while the card stayed red and
the totals stayed hidden. `mureo repair platform-key --all` answered "Nothing
to repair". There was no command, anywhere, that cleared it.

That is the same class of drift as #631 (two answers to "is this key real?"),
so it is pinned the same way: as an **invariant over every shape**, not as a
test for the one document that was reported. Whenever the read side withholds
a client's figures over a duplicate, the repair side must offer either a drop
or a stated next step for it — and the command the dashboard tells the
operator to run must be one the CLI accepts.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mureo.cli import _repair_preview
from mureo.cli._repair_preview import (
    _KEPT_NEXT_STEPS,
    _KEPT_REASONS,
    _drop_reason_line,
)
from mureo.cli.main import app
from mureo.context import platform_guards, platform_repair
from mureo.context.platform_repair import (
    KEEP_CONVERSION_OVERRIDE,
    PlatformEntryFacts,
    PlatformKeyRepair,
    plan_platform_keys,
)
from mureo.context.state import read_state_file
from mureo.core.runtime_context import default_runtime_context, reset_runtime_context
from mureo.web.reports import CONFLICT_DUPLICATE_ACCOUNT, build_report_summary

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

runner = CliRunner()

_WEB = Path(__file__).resolve().parents[1] / "mureo" / "_data" / "web"

# Every reason the plan can hand back, discovered rather than listed: a new
# one added without wording or a next step is exactly the drift this file is
# about, and a hand-written list is what a person forgets to extend.
_KEEP_REASONS = tuple(
    getattr(platform_repair, name)
    for name in platform_repair.__all__
    if name.startswith("KEEP_")
)
_DROP_REASONS = tuple(
    getattr(platform_repair, name)
    for name in platform_repair.__all__
    if name.startswith("DROP_")
)


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture(autouse=True)
def _pin_installed_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reported machine: the LOGLY bridge installed, nothing else."""
    entries = (SimpleNamespace(name="logly_ads_context"),)
    monkeypatch.setattr(platform_guards, "_provider_entry_points", lambda: entries)


def _entry(account_id: str, **extra: Any) -> dict[str, Any]:
    return {"account_id": account_id, "totals": {"spend": 10.0}, **extra}


# One ad account under two keys, in every spelling that reaches the dashboard
# as a ``duplicate_account`` conflict. The shapes differ in which keys resolve
# — which is precisely what used to decide whether an exit existed.
_DUPLICATE_DOCUMENTS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "both keys resolve",  # #636 itself
        {
            "plugin:mureo-logly-bridge": _entry("1234567890"),
            "logly_ads_context": _entry("1234567890"),
        },
    ),
    (
        "one key resolves, one does not",  # #610
        {
            "logly_ads": _entry("1234567890"),
            "logly_ads_context": _entry("1234567890"),
        },
    ),
    (
        "neither key resolves",
        {
            "logly_ads": _entry("1234567890"),
            "logly_adz": _entry("1234567890"),
        },
    ),
    (
        "two built-ins on one account",
        {
            "google_ads": _entry("1234567890"),
            "meta_ads": _entry("act_1234567890"),
        },
    ),
    (
        "three keys on one account",
        {
            "google_ads": _entry("1234567890"),
            "logly_ads_context": _entry("1234567890"),
            "logly_ads": _entry("1234567890"),
        },
    ),
    (
        "one of the two carries a conversion override",
        {
            "plugin:mureo-logly-bridge": _entry(
                "1234567890", conversion_action_types=["offsite_conversion.custom.1"]
            ),
            "logly_ads_context": _entry("1234567890"),
        },
    ),
)


def _summary_for(tmp_path: Path, platforms: dict[str, Any]) -> dict[str, Any]:
    """What the dashboard renders for this document, asked of reports.py."""
    (tmp_path / "STATE.json").write_text(
        json.dumps({"version": "2", "platforms": platforms}), encoding="utf-8"
    )
    return build_report_summary()


@pytest.fixture()
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ctx = default_runtime_context(workspace=tmp_path)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    return tmp_path


_DOCUMENT_IDS = [label for label, _ in _DUPLICATE_DOCUMENTS]


@pytest.mark.parametrize(
    ("label", "platforms"), _DUPLICATE_DOCUMENTS, ids=_DOCUMENT_IDS
)
def test_a_withheld_client_always_has_a_key_the_repair_will_drop(
    _workspace: Path, label: str, platforms: dict[str, Any]
) -> None:
    """The invariant. The dashboard hides these totals until the duplicate is
    resolved, so at least one of the keys it names has to be one the repair
    will remove when the operator names it explicitly."""
    summary = _summary_for(_workspace, platforms)
    conflicts = [
        row
        for row in summary["platform_conflicts"]
        if row["kind"] == CONFLICT_DUPLICATE_ACCOUNT
    ]
    assert conflicts, f"{label}: the dashboard reports no duplicate to agree about"

    doc = read_state_file(_workspace / "STATE.json")
    for row in conflicts:
        droppable = [
            key
            for key in row["platform_keys"]
            if plan_platform_keys(doc, keys=(key,), drop_duplicates=(key,)).repairs
        ]
        assert droppable, (
            f"{label}: the dashboard withholds this client's totals over "
            f"{row['platform_keys']} and the repair offers no way to clear it"
        )


@pytest.mark.parametrize(
    ("label", "platforms"), _DUPLICATE_DOCUMENTS, ids=_DOCUMENT_IDS
)
def test_every_named_key_gets_an_answer_rather_than_silence(
    _workspace: Path, label: str, platforms: dict[str, Any]
) -> None:
    """Naming any key of a reported duplicate produces a repair or a finding
    that is worded and carries a next step. "Nothing to repair" about a key
    the dashboard has just flagged is the #636 dead end."""
    summary = _summary_for(_workspace, platforms)
    doc = read_state_file(_workspace / "STATE.json")
    for row in summary["platform_conflicts"]:
        if row["kind"] != CONFLICT_DUPLICATE_ACCOUNT:
            continue
        for key in row["platform_keys"]:
            plan = plan_platform_keys(doc, keys=(key,), drop_duplicates=(key,))
            assert plan.repairs or plan.kept, f"{label}: {key} got no answer at all"
            for finding in plan.kept:
                assert finding.reason in _KEPT_REASONS
                assert finding.reason in _KEPT_NEXT_STEPS


def test_the_one_refusal_with_no_drop_still_states_the_step(_workspace: Path) -> None:
    """The single shape where no key can be dropped: BOTH entries carry a
    ``conversion_action_types`` allow-list, which no sync restores (#617).

    That refusal stands — but the operator is not left where #636 left them.
    The finding names the step that frees the entry, so the deadlock has an
    exit even here; it just is not a one-command one.
    """
    both = {
        "plugin:mureo-logly-bridge": _entry(
            "1234567890", conversion_action_types=["offsite_conversion.custom.1"]
        ),
        "logly_ads_context": _entry(
            "1234567890", conversion_action_types=["offsite_conversion.custom.2"]
        ),
    }
    summary = _summary_for(_workspace, both)
    assert any(
        row["kind"] == CONFLICT_DUPLICATE_ACCOUNT
        for row in summary["platform_conflicts"]
    )

    doc = read_state_file(_workspace / "STATE.json")
    for key in both:
        plan = plan_platform_keys(doc, keys=(key,), drop_duplicates=(key,))
        assert plan.repairs == ()
        (finding,) = plan.kept
        assert finding.reason == KEEP_CONVERSION_OVERRIDE
        assert _KEPT_NEXT_STEPS[KEEP_CONVERSION_OVERRIDE].strip()


def test_the_terminal_prints_a_runnable_command_for_the_conflict(
    tmp_path: Path,
) -> None:
    """What the operator is told to do, they can run. The dry run of a
    document the dashboard flags names the command that resolves it —
    an instruction with no runnable next step is how #636 happened."""
    state = tmp_path / "STATE.json"
    state.write_text(
        json.dumps(
            {
                "version": "2",
                "platforms": {
                    "plugin:mureo-logly-bridge": _entry("1234567890"),
                    "logly_ads_context": _entry("1234567890"),
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["repair", "platform-key", "--state-file", str(state)])

    assert result.exit_code == 0, result.output
    assert "mureo repair platform-key" in result.output
    assert "--drop-duplicate" in result.output


def _repair_command_flags() -> set[str]:
    """Every option ``mureo repair platform-key`` actually declares."""
    import typer.main

    group = typer.main.get_command(app)
    repair = group.get_command(None, "repair")  # type: ignore[attr-defined, arg-type]
    platform_key = repair.get_command(None, "platform-key")  # type: ignore[attr-defined]
    return {opt for param in platform_key.params for opt in param.opts}


def test_the_dashboards_hint_names_flags_the_command_accepts() -> None:
    """The card tells the operator to run something; the CLI has to accept it.

    A renamed flag would otherwise leave the dashboard pointing at a command
    that errors out — the read side and the write side disagreeing about the
    way out, which is the drift this file exists to stop.
    """
    catalog = json.loads((_WEB / "i18n.json").read_text(encoding="utf-8"))
    declared = _repair_command_flags()
    for locale in ("en", "ja"):
        hint = catalog[locale]["dashboard.reports_conflict_duplicate_repair_hint"]
        assert "mureo repair platform-key" in hint
        flags = set(re.findall(r"--[a-z][a-z-]+", hint))
        assert flags, f"{locale}: the hint names no flag at all"
        assert flags <= declared, f"{locale}: {flags - declared} is not an option"


def test_every_reason_the_plan_reports_is_worded_and_answerable() -> None:
    """A reason added to the plan without wording prints nothing an operator
    can act on — and would be discovered by them, not by this suite."""
    for reason in _KEEP_REASONS:
        assert reason in _KEPT_REASONS, f"{reason} has no explanation"
        assert reason in _KEPT_NEXT_STEPS, f"{reason} has no next step"
        assert "Why it stays:" in _KEPT_REASONS[reason]
        assert "Yours to decide:" in _KEPT_NEXT_STEPS[reason]


def test_every_droppable_reason_says_something_different() -> None:
    """``_drop_reason_line`` ends in an ``else``, so a new DROP_* constant
    would silently inherit another reason's sentence — telling the operator
    the entry is an empty stub while it is being removed for something else.
    """
    facts = PlatformEntryFacts(
        key="losing_key",
        resolvable=True,
        account_id="1234567890",
        campaign_count=0,
        has_totals=False,
        metrics_period=None,
        totals_fetched_at=None,
        rollups=(),
    )
    sibling = replace(facts, key="surviving_key")
    lines = {
        reason: _drop_reason_line(PlatformKeyRepair(facts, (sibling,), reason))
        for reason in _DROP_REASONS
    }

    assert len(set(lines.values())) == len(_DROP_REASONS), lines


def test_the_command_the_two_modules_print_is_one_string() -> None:
    """The module that words the dead-end message and the module that runs
    the command share one spelling of it. Two copies drift, and a wrong
    command inside a "here is the way out" message is #636 again."""
    from mureo.cli import repair_cmd

    assert repair_cmd._COMMAND == _repair_preview.REPAIR_COMMAND
    # …and the preview builds its suggestion from that constant rather than
    # re-typing the command, so renaming it moves both.
    source = Path(_repair_preview.__file__).read_text(encoding="utf-8")
    assert source.count('"mureo repair platform-key"') == 1
