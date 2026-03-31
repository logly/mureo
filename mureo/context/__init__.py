"""mureo context -- File-based strategy context (STRATEGY.md / STATE.json)."""

from mureo.context.errors import ContextFileError
from mureo.context.models import CampaignSnapshot, StateDocument, StrategyEntry
from mureo.context.state import (
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
    # models
    "CampaignSnapshot",
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
    "get_campaign",
    "parse_state",
    "read_state_file",
    "render_state",
    "upsert_campaign",
    "write_state_file",
]
