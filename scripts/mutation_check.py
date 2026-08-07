#!/usr/bin/env python3
"""Targeted mutation testing for the delivery-collapse detector (#546).

Green tests prove the code passes its tests. They do not prove the tests
would notice if the code were wrong — and for a detector whose failure
mode is *silence on a dead account*, "the tests pass" is exactly the
reassurance that hides the bug. Two CRITICALs in this feature shipped
past a green suite; one of them (`long_collapse_window`) was found by
this harness rather than by review.

Each entry injects one plausible wrong implementation, runs the tests
that should object, and restores the file. A mutation that SURVIVES is a
gap in the tests, not a pass: either the behaviour is untested or a test
name is claiming more than it exercises.

Usage::

    python scripts/mutation_check.py            # run them all
    python scripts/mutation_check.py --list     # names only
    python scripts/mutation_check.py weekday    # substring filter

Exit status is non-zero if any mutation survives. Not wired into the
pytest run: it rewrites source files and re-invokes pytest per mutation,
which is neither safe to parallelise nor cheap enough for every commit.
``tests/test_mutation_harness.py`` keeps it honest by asserting every
anchor below still exists in the source, so a refactor cannot silently
turn this file into a no-op that always "passes".
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Mutation:
    """One wrong implementation, and the tests that must object to it."""

    name: str
    summary: str
    path: str
    original: str
    mutated: str
    tests: tuple[str, ...]


CORE = "mureo/analysis/delivery_collapse.py"
DIAGNOSIS = "mureo/analysis/collapse_diagnosis.py"
CONFIG = "mureo/analysis/delivery_collapse_config.py"
ADAPTERS = "mureo/analytics/builtin/_delivery_clients.py"
GOOGLE = "mureo/google_ads/_analysis_performance.py"
META = "mureo/meta_ads/_insights.py"
BYOD = "mureo/byod/_client_common.py"
HANDLER = "mureo/mcp/_handlers_delivery_collapse.py"

T_CORE = ("tests/test_delivery_collapse.py",)
T_LAG = ("tests/test_delivery_collapse_reporting_lag.py",)
T_CLIENTS = ("tests/test_daily_delivery_report.py",)
T_DIAGNOSIS = ("tests/test_collapse_diagnosis.py",)
T_MODULES = ("tests/analytics/builtin/test_delivery_collapse_modules.py",)
T_MCP = ("tests/test_mcp_tools_delivery_collapse.py",)
T_CONFIG = ("tests/test_delivery_collapse_config.py",)


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="all_day_baseline",
        summary="weekday-aware baseline degraded to a plain all-day median",
        path=CORE,
        original=(
            "    if len(same_weekday) >= thresholds.min_same_weekday_samples:\n"
            "        sample, method = same_weekday, BaselineMethod.SAME_WEEKDAY_MEDIAN"
        ),
        mutated=(
            "    if False:\n"
            "        sample, method = same_weekday, BaselineMethod.SAME_WEEKDAY_MEDIAN"
        ),
        tests=T_CORE,
    ),
    Mutation(
        name="partial_day_evaluated",
        summary="the partial current day takes part in the comparison",
        path=CORE,
        original=(
            "    return tuple(sorted((d for d in daily if d.date < as_of), "
            "key=lambda d: d.date))"
        ),
        mutated=(
            "    return tuple(sorted((d for d in daily if d.date <= as_of), "
            "key=lambda d: d.date))"
        ),
        tests=T_CORE,
    ),
    Mutation(
        name="status_gate_removed",
        summary="paused campaigns are flagged as collapsed",
        path=CORE,
        original=(
            "    if not is_serving_status(series.status):\n"
            "        # Not a fault: somebody meant to stop this campaign.\n"
            "        return None"
        ),
        mutated="    if False:\n        return None",
        tests=T_CORE + T_MCP,
    ),
    Mutation(
        name="long_collapse_window",
        summary="baseline window slides per day, so a long outage poisons it",
        path=CORE,
        original=(
            "            complete[max(0, candidate - thresholds.baseline_days) "
            ": candidate],"
        ),
        mutated=(
            "            complete[max(0, len(complete) - 1 - "
            "thresholds.baseline_days) : len(complete) - 1],"
        ),
        tests=T_CORE,
    ),
    Mutation(
        name="scan_breaks_early",
        summary="the scan stops at the first failing candidate instead of continuing",
        path=CORE,
        original=(
            "        if window.delivering_days < thresholds.min_baseline_days:\n"
            "            continue"
        ),
        mutated=(
            "        if window.delivering_days < thresholds.min_baseline_days:\n"
            "            break"
        ),
        tests=T_CORE,
    ),
    Mutation(
        name="scan_runs_backwards",
        summary="the scan walks back from the most recent day",
        path=CORE,
        original="    for candidate in range(len(complete)):",
        mutated="    for candidate in reversed(range(len(complete))):",
        tests=T_CORE,
    ),
    Mutation(
        name="min_history_counts_window_length",
        summary="min_baseline_days counts window length, not delivering days",
        path=CORE,
        original=(
            "        self.delivering_days = sum(\n"
            "            1\n"
            "            for day in window\n"
            "            if day.impressions >= thresholds.min_baseline_impressions\n"
            "        )"
        ),
        mutated="        self.delivering_days = len(window)",
        tests=T_CORE,
    ),
    Mutation(
        name="flight_end_ignored",
        summary="a campaign past its end date is reported as collapsed",
        path=CORE,
        original="    if series.end_date is not None and cliff > series.end_date:",
        mutated=(
            "    if False and series.end_date is not None and cliff > series.end_date:"
        ),
        tests=T_CORE,
    ),
    Mutation(
        name="no_gap_reconciliation",
        summary="sparse platform rows are grouped 1:1, so zero-days stay absent",
        path=CORE,
        original=(
            "    for row in fill_missing_delivery_days("
            "rows, reported_through=reported_through):"
        ),
        mutated="    for row in rows:",
        tests=T_CLIENTS + T_CORE + T_LAG,
    ),
    Mutation(
        name="fill_past_reported_range",
        summary="gap-fill runs to the REQUESTED end, so reporting lag reads as zero",
        path=CORE,
        original=("        else max(day for _, day in dated)\n" "    )"),
        mutated=(
            "        else max(day for _, day in dated) + timedelta(days=3)\n" "    )"
        ),
        tests=T_LAG,
    ),
    Mutation(
        name="caller_frontier_ignored",
        summary="the caller's reported_through is discarded for the inferred one",
        path=CORE,
        original=(
            "    report_end = (\n"
            "        reported_through\n"
            "        if reported_through is not None\n"
            "        else max(day for _, day in dated)\n"
            "    )"
        ),
        mutated="    report_end = max(day for _, day in dated)",
        tests=T_LAG,
    ),
    Mutation(
        name="byod_anchor_inferred_after_join",
        summary="the BYOD frontier is inferred post-join instead of from the bundle",
        path=BYOD,
        original="    return fill_missing_delivery_days(out, reported_through=anchor)",
        mutated="    return fill_missing_delivery_days(out)",
        tests=T_CLIENTS,
    ),
    Mutation(
        name="fill_invents_prior_days",
        summary="gap-fill invents days before a campaign first appeared",
        path=CORE,
        original="        start = min(seen)",
        mutated=(
            "        start = min(min(seen), report_end - timedelta(days=MAX_FILL_DAYS))"
        ),
        tests=T_CLIENTS,
    ),
    Mutation(
        name="google_client_unreconciled",
        summary="the Google client returns raw sparse rows",
        path=GOOGLE,
        original=(
            "        return fill_missing_delivery_days("
            "[_daily_delivery_row(row) for row in rows])"
        ),
        mutated="        return [_daily_delivery_row(row) for row in rows]",
        tests=T_CLIENTS,
    ),
    Mutation(
        name="meta_client_unreconciled",
        summary="the Meta client returns raw sparse rows",
        path=META,
        original="        return fill_missing_delivery_days(mapped)",
        mutated="        return mapped",
        tests=T_CLIENTS,
    ),
    Mutation(
        name="meta_status_defaulted",
        summary="a row with no status join is defaulted to ENABLED",
        path=META,
        original='            if str(row.get("campaign_id")) in by_id',
        mutated="            if True",
        tests=T_CLIENTS,
    ),
    Mutation(
        name="byod_delivery_stubbed",
        summary="BYOD delivery falls back to the __getattr__ empty-list stub",
        path=BYOD,
        original=(
            "    return fill_missing_delivery_days(out, reported_through=anchor)"
        ),
        mutated="    return []",
        tests=T_CLIENTS,
    ),
    Mutation(
        name="unavailable_reported_as_ok",
        summary="a data_unavailable fetch is rendered as an empty ok report",
        path=ADAPTERS,
        original=(
            "    except DeliveryDataUnavailableError as exc:\n"
            '        return _report("data_unavailable", detail=str(exc))'
        ),
        mutated=(
            "    except DeliveryDataUnavailableError:\n" '        return _report("ok")'
        ),
        tests=T_MODULES,
    ),
    Mutation(
        name="cause_without_evidence",
        summary="a cause is named even when no check implicates one",
        path=DIAGNOSIS,
        original=(
            "        most_likely_cause=implicated[0].name if implicated else None,"
        ),
        mutated=(
            "        most_likely_cause=(\n"
            "            implicated[0].name\n"
            "            if implicated\n"
            "            else (validated[0].name if validated "
            "else ELIMINATION_LADDER[0])\n"
            "        ),"
        ),
        tests=T_DIAGNOSIS,
    ),
    Mutation(
        name="unresolved_steps_dropped",
        summary="ladder steps nobody checked vanish from the report",
        path=DIAGNOSIS,
        original=(
            '            out.append(f"{name}: not checked — no evidence was supplied")'
        ),
        mutated="            pass",
        tests=T_DIAGNOSIS,
    ),
    Mutation(
        name="config_not_fail_open",
        summary="an unreadable STRATEGY.md propagates instead of failing open",
        path=CONFIG,
        original=(
            "    except OSError:\n"
            '        logger.debug("delivery-collapse: STRATEGY.md unreadable", '
            "exc_info=True)\n"
            "        return CollapseThresholds(), SOURCE_DEFAULTS"
        ),
        mutated="    except OSError:\n        raise",
        tests=T_CONFIG,
    ),
    Mutation(
        name="lookback_argument_ignored",
        summary="the caller's change_lookback_days is silently discarded",
        path=HANDLER,
        original=(
            "            change_lookback_days=_coerce_int(\n"
            '                _opt(arguments, "change_lookback_days", '
            "DEFAULT_CHANGE_LOOKBACK_DAYS),\n"
            '                "change_lookback_days",\n'
            "            ),"
        ),
        mutated="            change_lookback_days=DEFAULT_CHANGE_LOOKBACK_DAYS,",
        tests=T_MCP,
    ),
)


def _apply(mutation: Mutation) -> str:
    """Inject ``mutation`` and return the original file contents."""
    path = REPO_ROOT / mutation.path
    original = path.read_text(encoding="utf-8")
    if mutation.original not in original:
        raise SystemExit(
            f"anchor for mutation {mutation.name!r} not found in {mutation.path}. "
            "The code moved — update scripts/mutation_check.py rather than "
            "deleting the mutation."
        )
    path.write_text(original.replace(mutation.original, mutation.mutated, 1))
    return original


def _run(mutation: Mutation) -> bool:
    """``True`` when the tests caught the mutation."""
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:randomly",
            *mutation.tests,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode != 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filter", nargs="?", default="", help="name substring")
    parser.add_argument("--list", action="store_true", help="list and exit")
    args = parser.parse_args()

    selected = [m for m in MUTATIONS if args.filter in m.name]
    if args.list:
        for mutation in selected:
            print(f"{mutation.name:32} {mutation.summary}")
        return 0

    survivors: list[Mutation] = []
    for mutation in selected:
        original = _apply(mutation)
        try:
            caught = _run(mutation)
        finally:
            (REPO_ROOT / mutation.path).write_text(original, encoding="utf-8")
        print(
            f"{'CAUGHT' if caught else '*** SURVIVED ***':18}"
            f"{mutation.name:32} {mutation.summary}"
        )
        if not caught:
            survivors.append(mutation)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} caught")
    if survivors:
        print(
            "\nA survivor is a gap in the TESTS, not a pass. Add the missing "
            "assertion rather than deleting the mutation."
        )
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
