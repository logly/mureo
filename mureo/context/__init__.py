"""mureo context -- File-based strategy context (STRATEGY.md / STATE.json)."""

from mureo.context.batch import (
    BatchError,
    active_batch,
    batch_members,
    batch_platforms,
    find_batch,
)
from mureo.context.errors import ContextFileError
from mureo.context.models import (
    ActionLogEntry,
    AdState,
    BatchRecord,
    CampaignSnapshot,
    PlatformState,
    StateDocument,
    StrategyEntry,
)
from mureo.context.state import (
    append_action_log,
    begin_batch,
    end_batch,
    get_campaign,
    parse_state,
    read_state_file,
    render_state,
    upsert_campaign,
    write_state_file,
)
from mureo.context.strategy import (
    add_strategy_entry,
    parse_strategy,
    read_strategy_file,
    remove_strategy_entry,
    render_strategy,
    write_strategy_file,
)

__all__ = [
    # errors
    "ContextFileError",
    # batch (#549)
    "BatchError",
    "active_batch",
    "batch_members",
    "batch_platforms",
    "find_batch",
    # models
    "ActionLogEntry",
    "AdState",
    "BatchRecord",
    "CampaignSnapshot",
    "PlatformState",
    "StateDocument",
    "StrategyEntry",
    # strategy
    "add_strategy_entry",
    "parse_strategy",
    "read_strategy_file",
    "remove_strategy_entry",
    "render_strategy",
    "write_strategy_file",
    # state
    "append_action_log",
    "begin_batch",
    "end_batch",
    "get_campaign",
    "parse_state",
    "read_state_file",
    "render_state",
    "upsert_campaign",
    "write_state_file",
]
