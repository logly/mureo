"""Reference tables in the docs that restate code must match that code.

Three tables copy a definition that lives in code: the STATE.json field
tables in ``docs/strategy-context.md`` (the dataclasses in
``mureo.context``), the workflow commands table in ``docs/mcp-server.md``
(the operational skills ``mureo`` installs, from ``mureo/_data/skills``)
and its default limits table (the throttle configs). Adding a field, a
skill or changing a limit edits the code only; nothing in the code reads
the tables, so only a test that reads the documents notices the drift
(#1043).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping

import pytest

import mureo.throttle
from mureo.chatgpt_ads.handlers import ALL_TOOLS as CHATGPT_ADS_TOOLS
from mureo.context.decisions import DecisionRecord
from mureo.context.display_models import DisplayContract
from mureo.context.models import (
    ActionLogEntry,
    AdState,
    BatchRecord,
    CampaignSnapshot,
    StateDocument,
)
from mureo.mcp.plugin_semantics import derive_semantics
from mureo.throttle import (
    CREATIVE_STUDIO_THROTTLE,
    GOOGLE_ADS_THROTTLE,
    META_ADS_THROTTLE,
    PLUGIN_THROTTLE,
    SEARCH_CONSOLE_THROTTLE,
    ThrottleConfig,
)
from tests._doc_surface import (
    _MCP_SERVER_DOC,
    _REPO_ROOT,
    Table,
    _doc_text,
    code_spans,
    markdown_tables,
)

pytestmark = pytest.mark.unit

_STRATEGY_DOC = "docs/strategy-context.md"

#: The heading of each STATE.json field table and the type it describes.
#: ``Settings`` is not here: its one row is the nested key path
#: ``ops_history.enabled``, which the codec maps to the differently named
#: field ``WorkspaceSettings.ops_history_enabled``.
_FIELD_TABLES: dict[str, type] = {
    "Root": StateDocument,
    "Campaign Snapshot": CampaignSnapshot,
    "Ad State": AdState,
    "Action Log Entry": ActionLogEntry,
    "Display Contract": DisplayContract,
    "Batch Record": BatchRecord,
    "Decision Record": DecisionRecord,
}

#: Dataclass fields that are not keys of STATE.json, so the field tables
#: (which describe the file) do not list them.
_NOT_FILE_KEYS = {
    "raw": "what the codec keeps in memory of the on-disk form (an entry it "
    "cannot represent from its fields, or a document's unreadable sections) "
    "to write it back as found; never written as a key of its own",
}

_WORKFLOW_HEADING = "Workflow Commands"
_LIMITS_HEADING = "Default Limits"


def _chatgpt_ads_throttle() -> ThrottleConfig | None:
    """The one throttle every ChatGPT Ads tool declares, as dispatch reads it."""
    declared = {derive_semantics(tool).throttle for tool in CHATGPT_ADS_TOOLS}
    return declared.pop() if len(declared) == 1 else None


def _limit_configs() -> dict[str, ThrottleConfig | None]:
    """Row label of the default limits table → the config that row restates.

    Built on call rather than at import, so reading the ChatGPT Ads tools'
    throttle is not part of collecting this module.
    """
    return {
        "Google Ads": GOOGLE_ADS_THROTTLE,
        "Meta Ads": META_ADS_THROTTLE,
        "Search Console": SEARCH_CONSOLE_THROTTLE,
        "Creative Studio": CREATIVE_STUDIO_THROTTLE,
        "ChatGPT Ads (per tool)": _chatgpt_ads_throttle(),
        "Plugin tools without a declared throttle (shared default bucket)": (
            PLUGIN_THROTTLE
        ),
    }


def _throttle_presets() -> dict[str, ThrottleConfig]:
    """Every module-level ``ThrottleConfig`` in ``mureo.throttle``."""
    return {
        name: value
        for name, value in vars(mureo.throttle).items()
        if isinstance(value, ThrottleConfig)
    }


def _tables_under(markdown: str, heading: str) -> list[Table]:
    return [table for table in markdown_tables(markdown) if table.heading == heading]


def documented_fields(markdown: str, heading: str) -> set[str]:
    """Field names in the first column of the table under ``heading``."""
    return {
        name
        for table in _tables_under(markdown, heading)[:1]
        for row in table.rows
        for name in code_spans(row[0])
    }


def field_mismatches(markdown: str, types: Mapping[str, type]) -> list[str]:
    """Field tables whose names differ from their dataclass's fields."""
    problems: list[str] = []
    for heading, cls in types.items():
        documented = documented_fields(markdown, heading)
        expected = {f.name for f in dataclasses.fields(cls)} - set(_NOT_FILE_KEYS)
        if documented != expected:
            problems.append(
                f"{heading}: missing {sorted(expected - documented)}, "
                f"not a field {sorted(documented - expected)}"
            )
    return problems


def workflow_commands(markdown: str) -> set[str]:
    """``/name`` entries in the workflow commands table, slash stripped."""
    return {
        span[1:]
        for table in _tables_under(markdown, _WORKFLOW_HEADING)
        for row in table.rows
        for span in code_spans(row[0])
        if span.startswith("/")
    }


def workflow_mismatches(markdown: str, skills: Iterable[str]) -> list[str]:
    """Skills the table omits and table entries that are not skills."""
    listed = workflow_commands(markdown)
    shipped = set(skills)
    return [f"not listed: /{name}" for name in sorted(shipped - listed)] + [
        f"no such skill: /{name}" for name in sorted(listed - shipped)
    ]


def _hourly_cap(cell: str) -> int | None:
    """``--`` (no cap) → ``None``; ``50,000`` → ``50000``."""
    return None if cell == "--" else int(cell.replace(",", ""))


def limit_rows(markdown: str) -> dict[str, tuple[float, float, int | None]]:
    """Row label → (QPS, Burst, Hourly Cap) of the default limits table."""
    rows: dict[str, tuple[float, float, int | None]] = {}
    for table in _tables_under(markdown, _LIMITS_HEADING):
        rate_col = table.header.index("QPS")
        burst_col = table.header.index("Burst")
        cap_col = table.header.index("Hourly Cap")
        for row in table.rows:
            rows[row[0]] = (
                float(row[rate_col]),
                float(row[burst_col]),
                _hourly_cap(row[cap_col]),
            )
    return rows


def limit_mismatches(
    markdown: str, configs: Mapping[str, ThrottleConfig | None]
) -> list[str]:
    """Rows whose QPS, Burst or Hourly Cap differs from their config."""
    problems: list[str] = []
    for label, documented in limit_rows(markdown).items():
        config = configs.get(label)
        if config is None:
            continue
        expected = (config.rate, config.burst, config.hourly_limit)
        if documented != expected:
            problems.append(f"{label}: doc {documented} != code {expected}")
    return problems


def _operational_skills() -> list[str]:
    """The operational skills ``mureo`` installs, read from the tree it ships
    (``mureo.core.skills.discovery``'s built-in directory)."""
    return sorted(
        path.parent.name
        for path in (_REPO_ROOT / "mureo" / "_data" / "skills").glob("*/SKILL.md")
        if not path.parent.name.startswith("_")
    )


# --- docs/strategy-context.md field tables ---------------------------------


def test_every_field_table_is_found() -> None:
    """Coverage guard: each type's table is located by its heading."""
    markdown = _doc_text(_STRATEGY_DOC)
    unfound = [h for h in _FIELD_TABLES if not documented_fields(markdown, h)]
    assert unfound == [], f"{_STRATEGY_DOC} field tables not found: {unfound}"


def test_not_file_keys_are_still_fields() -> None:
    """An excluded name that left every dataclass must leave the exclusion."""
    fields = {f.name for cls in _FIELD_TABLES.values() for f in dataclasses.fields(cls)}
    stale = sorted(set(_NOT_FILE_KEYS) - fields)
    assert stale == [], f"excluded names that are not fields: {stale}"


def test_field_tables_match_the_dataclasses() -> None:
    mismatches = field_mismatches(_doc_text(_STRATEGY_DOC), _FIELD_TABLES)
    assert mismatches == [], f"{_STRATEGY_DOC}: {mismatches}"


def test_field_mismatches_reports_a_missing_field() -> None:
    @dataclasses.dataclass(frozen=True)
    class Snippet:
        campaign_id: str
        status: str

    snippet = (
        "#### Snippet\n\n| Field | Type |\n|---|---|\n| `campaign_id` | `string` |\n"
    )
    assert field_mismatches(snippet, {"Snippet": Snippet}) == [
        "Snippet: missing ['status'], not a field []"
    ]


# --- docs/mcp-server.md workflow commands ----------------------------------


def test_workflow_table_is_found() -> None:
    """Coverage guard: the table under its heading is read."""
    assert workflow_commands(_doc_text(_MCP_SERVER_DOC))
    assert _operational_skills()


def test_workflow_table_lists_exactly_the_operational_skills() -> None:
    mismatches = workflow_mismatches(_doc_text(_MCP_SERVER_DOC), _operational_skills())
    assert mismatches == [], f"{_MCP_SERVER_DOC} workflow commands: {mismatches}"


def test_workflow_mismatches_reports_both_directions() -> None:
    snippet = (
        "## Workflow Commands\n\n| Command | Purpose |\n|---|---|\n"
        "| `/daily-check` | Daily |\n| `/retired` | Gone |\n"
    )
    assert workflow_mismatches(snippet, ["daily-check", "rescue"]) == [
        "not listed: /rescue",
        "no such skill: /retired",
    ]


# --- docs/mcp-server.md default limits -------------------------------------


def test_chatgpt_ads_tools_share_one_throttle() -> None:
    """The per-tool row stands for every ChatGPT Ads tool only if they agree."""
    assert _chatgpt_ads_throttle() is not None


def test_limit_rows_and_mapping_cover_each_other() -> None:
    """Coverage guard: every row has a config and every config found its row."""
    rows = set(limit_rows(_doc_text(_MCP_SERVER_DOC)))
    configs = set(_limit_configs())
    assert sorted(rows - configs) == [], "rows with no config"
    assert sorted(configs - rows) == [], "configs with no row"


def test_every_throttle_preset_has_a_row() -> None:
    """A preset added to ``mureo.throttle`` needs its row in the table.

    Compared by identity: two presets with equal values are still two rows.
    """
    mapped = [config for config in _limit_configs().values() if config is not None]
    unmapped = [
        name
        for name, preset in _throttle_presets().items()
        if not any(preset is config for config in mapped)
    ]
    assert _throttle_presets()
    assert unmapped == [], f"throttle presets with no row: {unmapped}"


def test_limit_rows_match_the_throttle_configs() -> None:
    mismatches = limit_mismatches(_doc_text(_MCP_SERVER_DOC), _limit_configs())
    assert mismatches == [], f"{_MCP_SERVER_DOC} default limits: {mismatches}"


def test_limit_mismatches_reports_a_wrong_rate_and_cap() -> None:
    snippet = (
        "### Default Limits\n\n| Platform | QPS | Burst | Hourly Cap |\n"
        "|---|---|---|---|\n| Google Ads | 8 | 5 | -- |\n"
        "| Meta Ads | 20 | 10 | 40,000 |\n"
    )
    configs = {
        "Google Ads": ThrottleConfig(rate=10.0, burst=5),
        "Meta Ads": ThrottleConfig(rate=20.0, burst=10, hourly_limit=50_000),
    }
    assert limit_mismatches(snippet, configs) == [
        "Google Ads: doc (8.0, 5.0, None) != code (10.0, 5, None)",
        "Meta Ads: doc (20.0, 10.0, 40000) != code (20.0, 10, 50000)",
    ]
